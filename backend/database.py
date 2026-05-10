"""
Database schema and operations for the LoRA Dataset Curator
Uses SQLite for zero-config local storage
"""

import sqlite3
import json
import os
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager
from typing import Optional

DB_PATH = os.environ.get("CURATOR_DB_PATH", "curator.db")


def get_db_path():
    return DB_PATH


@contextmanager
def get_db():
    """Context manager for database connections"""
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Initialize database schema"""
    with get_db() as conn:
        conn.executescript("""
            -- Movies table: one row per movie folder
            CREATE TABLE IF NOT EXISTS movies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                folder_name TEXT NOT NULL,
                folder_path TEXT NOT NULL UNIQUE,
                aspect_ratio_group TEXT,  -- e.g. "2.35_scope", "other_1.47"
                title TEXT,
                original_title TEXT,
                year INTEGER,
                release_date TEXT,
                overview TEXT,
                tmdb_id INTEGER,
                imdb_id TEXT,
                original_language TEXT,
                countries TEXT,          -- JSON array
                genres TEXT,             -- JSON array
                keywords TEXT,           -- JSON array
                image_count INTEGER DEFAULT 0,
                fetched_at TEXT,
                indexed_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            -- Images table: one row per image file
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                movie_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                filepath TEXT NOT NULL UNIQUE,
                width INTEGER,
                height INTEGER,
                aspect_ratio REAL,
                file_size INTEGER,       -- bytes
                indexed_at TEXT NOT NULL,
                FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE
            );

            -- Tags from LLaVA or other vision models
            CREATE TABLE IF NOT EXISTS image_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_id INTEGER NOT NULL,
                tag TEXT NOT NULL,
                confidence REAL DEFAULT 1.0,
                model TEXT,              -- which model generated this tag
                tagged_at TEXT NOT NULL,
                FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE
            );

            -- Full captions from vision models
            CREATE TABLE IF NOT EXISTS image_captions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_id INTEGER NOT NULL,
                caption TEXT NOT NULL,
                model TEXT,
                tagged_at TEXT NOT NULL,
                FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE
            );

            -- Projects: curated datasets for training
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                config_json TEXT,         -- full project.toml as JSON
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            -- Project images: which images are in which project
            CREATE TABLE IF NOT EXISTS project_images (
                project_id INTEGER NOT NULL,
                image_id INTEGER NOT NULL,
                added_at TEXT NOT NULL,
                PRIMARY KEY (project_id, image_id),
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE
            );

            -- Indexes for fast filtering
            CREATE INDEX IF NOT EXISTS idx_movies_year ON movies(year);
            CREATE INDEX IF NOT EXISTS idx_movies_language ON movies(original_language);
            CREATE INDEX IF NOT EXISTS idx_movies_aspect ON movies(aspect_ratio_group);
            CREATE INDEX IF NOT EXISTS idx_images_movie ON images(movie_id);
            CREATE INDEX IF NOT EXISTS idx_images_aspect ON images(aspect_ratio);
            CREATE INDEX IF NOT EXISTS idx_images_dimensions ON images(width, height);
            CREATE INDEX IF NOT EXISTS idx_image_tags_tag ON image_tags(tag);
            CREATE INDEX IF NOT EXISTS idx_image_tags_image ON image_tags(image_id);
            CREATE INDEX IF NOT EXISTS idx_image_tags_model_image ON image_tags(model, image_id);
        """)


def scan_dataset_root(root_path: str, progress_callback=None) -> dict:
    """
    Scan the main_datasets directory and index everything into the database.
    
    Expected structure:
        root/aspect_ratios/1.00_square/Movie Name/.movie_metadata.json + images
        root/aspect_ratios/2.35_scope/Movie Name/.movie_metadata.json + images
        root/other_1.47/Movie Name/.movie_metadata.json + images
    
    Returns scan statistics.
    """
    root = Path(root_path)
    if not root.exists():
        raise FileNotFoundError(f"Root path does not exist: {root_path}")
    
    IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff'}
    now = datetime.now().isoformat()
    
    stats = {
        'movies_found': 0,
        'movies_new': 0,
        'movies_updated': 0,
        'images_found': 0,
        'images_new': 0,
        'errors': []
    }
    
    # Collect all movie folders
    movie_folders = []
    
    # Check for aspect_ratios subdirectory
    aspect_ratios_dir = root / "aspect_ratios"
    
    if aspect_ratios_dir.exists():
        # Standard structure: aspect_ratios/group/movie
        for group_dir in sorted(aspect_ratios_dir.iterdir()):
            if group_dir.is_dir():
                for movie_dir in sorted(group_dir.iterdir()):
                    if movie_dir.is_dir():
                        movie_folders.append((group_dir.name, movie_dir))
    
    # Also check for other_X.XX folders directly under root
    for item in sorted(root.iterdir()):
        if item.is_dir() and item.name.startswith("other_"):
            for movie_dir in sorted(item.iterdir()):
                if movie_dir.is_dir():
                    movie_folders.append((item.name, movie_dir))
    
    total_folders = len(movie_folders)
    
    with get_db() as conn:
        for idx, (aspect_group, movie_dir) in enumerate(movie_folders):
            stats['movies_found'] += 1
            
            if progress_callback:
                progress_callback(idx, total_folders, movie_dir.name)
            
            # Load metadata
            metadata_file = movie_dir / '.movie_metadata.json'
            metadata = {}
            if metadata_file.exists():
                try:
                    with open(metadata_file, 'r') as f:
                        metadata = json.load(f)
                except Exception as e:
                    stats['errors'].append(f"Error reading metadata for {movie_dir.name}: {e}")
            
            # Count/list images
            image_files = []
            for f in movie_dir.iterdir():
                if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS:
                    image_files.append(f)
            
            image_count = len(image_files)
            stats['images_found'] += image_count
            
            # Upsert movie record
            folder_path = str(movie_dir)
            existing = conn.execute(
                "SELECT id FROM movies WHERE folder_path = ?", (folder_path,)
            ).fetchone()
            
            movie_data = {
                'folder_name': movie_dir.name,
                'folder_path': folder_path,
                'aspect_ratio_group': aspect_group,
                'title': metadata.get('title', movie_dir.name),
                'original_title': metadata.get('original_title'),
                'year': metadata.get('year'),
                'release_date': metadata.get('release_date'),
                'overview': metadata.get('overview'),
                'tmdb_id': metadata.get('tmdb_id'),
                'imdb_id': metadata.get('imdb_id'),
                'original_language': metadata.get('original_language'),
                'countries': json.dumps(metadata.get('countries', [])),
                'genres': json.dumps(metadata.get('genres', [])),
                'keywords': json.dumps(metadata.get('keywords', [])),
                'image_count': image_count,
                'fetched_at': metadata.get('fetched_at'),
                'updated_at': now,
            }
            
            if existing:
                movie_id = existing['id']
                stats['movies_updated'] += 1
                cols = ', '.join(f"{k} = ?" for k in movie_data.keys())
                vals = list(movie_data.values()) + [movie_id]
                conn.execute(f"UPDATE movies SET {cols} WHERE id = ?", vals)
            else:
                movie_data['indexed_at'] = now
                stats['movies_new'] += 1
                cols = ', '.join(movie_data.keys())
                placeholders = ', '.join(['?'] * len(movie_data))
                cursor = conn.execute(
                    f"INSERT INTO movies ({cols}) VALUES ({placeholders})",
                    list(movie_data.values())
                )
                movie_id = cursor.lastrowid
            
            # Index images (skip already-indexed ones)
            existing_images = set(
                row['filepath'] for row in
                conn.execute("SELECT filepath FROM images WHERE movie_id = ?", (movie_id,)).fetchall()
            )
            
            for img_file in image_files:
                filepath = str(img_file)
                if filepath in existing_images:
                    continue
                
                stats['images_new'] += 1
                
                # Get basic file info (dimensions deferred for speed)
                file_size = img_file.stat().st_size
                
                conn.execute(
                    """INSERT OR IGNORE INTO images 
                       (movie_id, filename, filepath, file_size, indexed_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (movie_id, img_file.name, filepath, file_size, now)
                )
    
    return stats


def get_filter_options():
    """Get all available filter values for the UI"""
    with get_db() as conn:
        # Year range
        year_range = conn.execute(
            "SELECT MIN(year) as min_year, MAX(year) as max_year FROM movies WHERE year IS NOT NULL"
        ).fetchone()
        
        # Aspect ratio groups
        aspect_groups = [
            row['aspect_ratio_group'] for row in
            conn.execute(
                "SELECT DISTINCT aspect_ratio_group FROM movies ORDER BY aspect_ratio_group"
            ).fetchall()
        ]
        
        # Languages
        languages = [
            row['original_language'] for row in
            conn.execute(
                "SELECT DISTINCT original_language FROM movies WHERE original_language IS NOT NULL ORDER BY original_language"
            ).fetchall()
        ]
        
        # Genres (need to parse JSON arrays)
        all_genres = set()
        for row in conn.execute("SELECT genres FROM movies WHERE genres IS NOT NULL").fetchall():
            try:
                genres = json.loads(row['genres'])
                all_genres.update(genres)
            except (json.JSONDecodeError, TypeError):
                pass
        
        # Countries
        all_countries = set()
        for row in conn.execute("SELECT countries FROM movies WHERE countries IS NOT NULL").fetchall():
            try:
                countries = json.loads(row['countries'])
                all_countries.update(countries)
            except (json.JSONDecodeError, TypeError):
                pass
        
        # Keywords (ALL, sorted by frequency - frontend handles search/filter)
        keyword_counts = {}
        for row in conn.execute("SELECT keywords FROM movies WHERE keywords IS NOT NULL").fetchall():
            try:
                keywords = json.loads(row['keywords'])
                for kw in keywords:
                    keyword_counts[kw] = keyword_counts.get(kw, 0) + 1
            except (json.JSONDecodeError, TypeError):
                pass
        all_keywords = sorted(keyword_counts.items(), key=lambda x: -x[1])
        
        # Stats
        total_movies = conn.execute("SELECT COUNT(*) as c FROM movies").fetchone()['c']
        total_images = conn.execute("SELECT COUNT(*) as c FROM images").fetchone()['c']
        
        return {
            'year_range': {
                'min': year_range['min_year'] if year_range else None,
                'max': year_range['max_year'] if year_range else None,
            },
            'aspect_groups': aspect_groups,
            'languages': sorted(languages),
            'genres': sorted(all_genres),
            'countries': sorted(all_countries),
            'keywords': [{'keyword': kw, 'count': count} for kw, count in all_keywords],
            'total_movies': total_movies,
            'total_images': total_images,
        }


def filter_movies(
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    genres: Optional[list] = None,
    countries: Optional[list] = None,
    languages: Optional[list] = None,
    keywords_include: Optional[list] = None,
    keywords_exclude: Optional[list] = None,
    aspect_groups: Optional[list] = None,
    search: Optional[str] = None,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    """Filter movies with pagination, returns matching movies and aggregated stats"""
    
    conditions = []
    params = []
    
    if year_min is not None:
        conditions.append("year >= ?")
        params.append(year_min)
    if year_max is not None:
        conditions.append("year <= ?")
        params.append(year_max)
    if languages:
        placeholders = ','.join(['?'] * len(languages))
        conditions.append(f"original_language IN ({placeholders})")
        params.extend(languages)
    if aspect_groups:
        placeholders = ','.join(['?'] * len(aspect_groups))
        conditions.append(f"aspect_ratio_group IN ({placeholders})")
        params.extend(aspect_groups)
    if search:
        conditions.append("(title LIKE ? OR original_title LIKE ? OR overview LIKE ?)")
        search_term = f"%{search}%"
        params.extend([search_term, search_term, search_term])
    
    where_clause = " AND ".join(conditions) if conditions else "1=1"
    
    with get_db() as conn:
        # Get all matching movies (we need to do JSON filtering in Python)
        query = f"""
            SELECT * FROM movies 
            WHERE {where_clause}
            ORDER BY year DESC, title ASC
        """
        all_rows = conn.execute(query, params).fetchall()
        
        # JSON array filtering (genres, countries, keywords)
        filtered_rows = []
        for row in all_rows:
            row_dict = dict(row)
            
            # Genre filter
            if genres:
                movie_genres = json.loads(row_dict.get('genres') or '[]')
                if not any(g in genres for g in movie_genres):
                    continue
            
            # Country filter
            if countries:
                movie_countries = json.loads(row_dict.get('countries') or '[]')
                if not any(c in countries for c in movie_countries):
                    continue
            
            # Keywords include
            if keywords_include:
                movie_keywords = [k.lower() for k in json.loads(row_dict.get('keywords') or '[]')]
                if not any(k.lower() in movie_keywords for k in keywords_include):
                    continue
            
            # Keywords exclude
            if keywords_exclude:
                movie_keywords = [k.lower() for k in json.loads(row_dict.get('keywords') or '[]')]
                if any(k.lower() in movie_keywords for k in keywords_exclude):
                    continue
            
            # Parse JSON fields for response
            row_dict['countries'] = json.loads(row_dict.get('countries') or '[]')
            row_dict['genres'] = json.loads(row_dict.get('genres') or '[]')
            row_dict['keywords'] = json.loads(row_dict.get('keywords') or '[]')
            filtered_rows.append(row_dict)
        
        total_count = len(filtered_rows)
        total_images = sum(r.get('image_count', 0) for r in filtered_rows)
        
        # Paginate
        start = (page - 1) * per_page
        end = start + per_page
        page_rows = filtered_rows[start:end]
        
        # Aggregate stats for the filtered set
        genre_counts = {}
        country_counts = {}
        year_counts = {}
        aspect_counts = {}
        
        for row in filtered_rows:
            for g in row.get('genres', []):
                genre_counts[g] = genre_counts.get(g, 0) + 1
            for c in row.get('countries', []):
                country_counts[c] = country_counts.get(c, 0) + 1
            y = row.get('year')
            if y:
                decade = (y // 10) * 10
                year_counts[decade] = year_counts.get(decade, 0) + 1
            ag = row.get('aspect_ratio_group')
            if ag:
                aspect_counts[ag] = aspect_counts.get(ag, 0) + 1
        
        return {
            'movies': page_rows,
            'total_movies': total_count,
            'total_images': total_images,
            'page': page,
            'per_page': per_page,
            'total_pages': (total_count + per_page - 1) // per_page,
            'aggregations': {
                'genres': sorted(genre_counts.items(), key=lambda x: -x[1]),
                'countries': sorted(country_counts.items(), key=lambda x: -x[1]),
                'decades': sorted(year_counts.items()),
                'aspect_groups': sorted(aspect_counts.items()),
            }
        }


def get_random_images(movie_ids: Optional[list] = None, count: int = 20) -> list:
    """
    Get random sample of images with stratified sampling.
    Picks random movies first, then 1-2 images per movie to ensure variety.
    """
    import random
    
    with get_db() as conn:
        # Step 1: Get available movies (with image counts)
        if movie_ids:
            placeholders = ','.join(['?'] * len(movie_ids))
            available_movies = conn.execute(
                f"""SELECT id, title, year, aspect_ratio_group, image_count
                    FROM movies WHERE id IN ({placeholders}) AND image_count > 0""",
                movie_ids
            ).fetchall()
        else:
            available_movies = conn.execute(
                "SELECT id, title, year, aspect_ratio_group, image_count FROM movies WHERE image_count > 0"
            ).fetchall()
        
        if not available_movies:
            return []
        
        available_movies = [dict(m) for m in available_movies]
        
        # Step 2: Determine images per movie
        # With many movies, take 1 per movie. With few, allow more.
        num_movies = len(available_movies)
        if num_movies >= count:
            # More movies than requested images: 1 image per movie, sample movies
            selected_movies = random.sample(available_movies, count)
            images_per_movie = 1
        elif num_movies >= count // 2:
            # Enough movies for decent variety at 1-2 per movie
            selected_movies = random.sample(available_movies, min(num_movies, count))
            images_per_movie = max(1, count // len(selected_movies))
        else:
            # Few movies — allow more images per movie but cap it
            selected_movies = available_movies
            images_per_movie = max(1, min(3, count // max(1, len(selected_movies))))
        
        # Step 3: Pull random images from each selected movie
        results = []
        remaining = count
        
        # Shuffle to avoid always filling from same movies
        random.shuffle(selected_movies)
        
        for movie in selected_movies:
            if remaining <= 0:
                break
            
            take = min(images_per_movie, remaining)
            rows = conn.execute(
                """SELECT i.*, m.title as movie_title, m.year as movie_year,
                          m.aspect_ratio_group
                   FROM images i
                   JOIN movies m ON i.movie_id = m.id
                   WHERE i.movie_id = ?
                   ORDER BY RANDOM()
                   LIMIT ?""",
                (movie['id'], take)
            ).fetchall()
            
            results.extend([dict(r) for r in rows])
            remaining -= len(rows)
        
        # Step 4: If we still need more (rare edge case), backfill
        if remaining > 0 and available_movies:
            backfill_ids = [m['id'] for m in available_movies]
            already_have = {r['id'] for r in results}
            placeholders = ','.join(['?'] * len(backfill_ids))
            extra = conn.execute(
                f"""SELECT i.*, m.title as movie_title, m.year as movie_year,
                           m.aspect_ratio_group
                    FROM images i
                    JOIN movies m ON i.movie_id = m.id
                    WHERE i.movie_id IN ({placeholders}) AND i.id NOT IN ({','.join('?' * len(already_have)) if already_have else '0'})
                    ORDER BY RANDOM()
                    LIMIT ?""",
                backfill_ids + list(already_have) + [remaining]
            ).fetchall()
            results.extend([dict(r) for r in extra])
        
        # Shuffle final results so they're not grouped by movie
        random.shuffle(results)
        return results


def get_db_stats():
    """Get overall database statistics"""
    with get_db() as conn:
        movies = conn.execute("SELECT COUNT(*) as c FROM movies").fetchone()['c']
        images = conn.execute("SELECT COUNT(*) as c FROM images").fetchone()['c']
        tagged = conn.execute("SELECT COUNT(DISTINCT image_id) as c FROM image_tags").fetchone()['c']
        captioned = conn.execute("SELECT COUNT(DISTINCT image_id) as c FROM image_captions").fetchone()['c']
        projects = conn.execute("SELECT COUNT(*) as c FROM projects").fetchone()['c']
        
        # Size on disk
        db_size = os.path.getsize(get_db_path()) if os.path.exists(get_db_path()) else 0
        
        return {
            'total_movies': movies,
            'total_images': images,
            'tagged_images': tagged,
            'captioned_images': captioned,
            'projects': projects,
            'db_size_mb': round(db_size / (1024 * 1024), 2),
        }
