"""
Selection management for dataset curation.
Tracks which movies and individual images are selected for dataset export.

Selection model:
- A movie can be "selected" (all its images included by default)
- Individual images within a selected movie can be "excluded"
- Individual images from non-selected movies can be "included"
"""

import json
from datetime import datetime
from contextlib import contextmanager
from database import get_db


def init_selection_tables():
    """Create selection tables if they don't exist"""
    with get_db() as conn:
        conn.executescript("""
            -- Movies selected for dataset
            CREATE TABLE IF NOT EXISTS selected_movies (
                movie_id INTEGER PRIMARY KEY,
                selected_at TEXT NOT NULL,
                FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE
            );

            -- Per-image overrides
            -- included=1: force-include (even if movie not selected)
            -- included=0: force-exclude (even if movie is selected)
            CREATE TABLE IF NOT EXISTS image_overrides (
                image_id INTEGER PRIMARY KEY,
                included INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE
            );
        """)


def select_movie(movie_id: int) -> dict:
    """Select a movie (all its images)"""
    now = datetime.now().isoformat()
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO selected_movies (movie_id, selected_at) VALUES (?, ?)",
            (movie_id, now)
        )
        # Clear any per-image overrides for this movie since it's now fully selected
        conn.execute("""
            DELETE FROM image_overrides WHERE image_id IN (
                SELECT id FROM images WHERE movie_id = ?
            )
        """, (movie_id,))
    return get_selection_summary()


def deselect_movie(movie_id: int) -> dict:
    """Deselect a movie"""
    with get_db() as conn:
        conn.execute("DELETE FROM selected_movies WHERE movie_id = ?", (movie_id,))
        # Clear any per-image overrides for this movie
        conn.execute("""
            DELETE FROM image_overrides WHERE image_id IN (
                SELECT id FROM images WHERE movie_id = ?
            )
        """, (movie_id,))
    return get_selection_summary()


def toggle_movie(movie_id: int) -> dict:
    """Toggle movie selection, return new state"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT movie_id FROM selected_movies WHERE movie_id = ?", (movie_id,)
        ).fetchone()
    if row:
        return {"selected": False, **deselect_movie(movie_id)}
    else:
        return {"selected": True, **select_movie(movie_id)}


def select_movies_bulk(movie_ids: list) -> dict:
    """Select multiple movies at once"""
    now = datetime.now().isoformat()
    with get_db() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO selected_movies (movie_id, selected_at) VALUES (?, ?)",
            [(mid, now) for mid in movie_ids]
        )
        # Clear overrides
        if movie_ids:
            placeholders = ','.join(['?'] * len(movie_ids))
            conn.execute(f"""
                DELETE FROM image_overrides WHERE image_id IN (
                    SELECT id FROM images WHERE movie_id IN ({placeholders})
                )
            """, movie_ids)
    return get_selection_summary()


def deselect_movies_bulk(movie_ids: list) -> dict:
    """Deselect multiple movies at once"""
    with get_db() as conn:
        if movie_ids:
            placeholders = ','.join(['?'] * len(movie_ids))
            conn.execute(
                f"DELETE FROM selected_movies WHERE movie_id IN ({placeholders})", movie_ids
            )
            conn.execute(f"""
                DELETE FROM image_overrides WHERE image_id IN (
                    SELECT id FROM images WHERE movie_id IN ({placeholders})
                )
            """, movie_ids)
    return get_selection_summary()


def toggle_image(image_id: int) -> dict:
    """Toggle an individual image's selection state"""
    now = datetime.now().isoformat()
    with get_db() as conn:
        # Get the image's movie
        img = conn.execute(
            "SELECT movie_id FROM images WHERE id = ?", (image_id,)
        ).fetchone()
        if not img:
            return {"error": "Image not found"}

        movie_id = img['movie_id']
        movie_selected = conn.execute(
            "SELECT 1 FROM selected_movies WHERE movie_id = ?", (movie_id,)
        ).fetchone() is not None

        # Check current override
        override = conn.execute(
            "SELECT included FROM image_overrides WHERE image_id = ?", (image_id,)
        ).fetchone()

        if override is not None:
            # Remove override (revert to movie-level state)
            conn.execute("DELETE FROM image_overrides WHERE image_id = ?", (image_id,))
            new_state = movie_selected  # reverts to movie default
        else:
            # Add override (opposite of movie state)
            new_included = 0 if movie_selected else 1
            conn.execute(
                "INSERT OR REPLACE INTO image_overrides (image_id, included, updated_at) VALUES (?, ?, ?)",
                (image_id, new_included, now)
            )
            new_state = not movie_selected

    return {"image_id": image_id, "included": new_state}


def exclude_image(image_id: int) -> dict:
    """Exclude a specific image (even if its movie is selected)"""
    now = datetime.now().isoformat()
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO image_overrides (image_id, included, updated_at) VALUES (?, 0, ?)",
            (image_id, now)
        )
    return {"image_id": image_id, "included": False}


def include_image(image_id: int) -> dict:
    """Include a specific image (even if its movie is not selected)"""
    now = datetime.now().isoformat()
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO image_overrides (image_id, included, updated_at) VALUES (?, 1, ?)",
            (image_id, now)
        )
    return {"image_id": image_id, "included": True}


def clear_image_override(image_id: int) -> dict:
    """Remove per-image override, reverting to movie-level selection"""
    with get_db() as conn:
        conn.execute("DELETE FROM image_overrides WHERE image_id = ?", (image_id,))
    return {"image_id": image_id, "override_cleared": True}


def clear_all_selections() -> dict:
    """Clear all selections"""
    with get_db() as conn:
        conn.execute("DELETE FROM selected_movies")
        conn.execute("DELETE FROM image_overrides")
    return get_selection_summary()


def get_selected_movie_ids() -> list:
    """Get list of selected movie IDs"""
    with get_db() as conn:
        rows = conn.execute("SELECT movie_id FROM selected_movies").fetchall()
        return [r['movie_id'] for r in rows]


def is_movie_selected(movie_id: int) -> bool:
    """Check if a movie is selected"""
    with get_db() as conn:
        return conn.execute(
            "SELECT 1 FROM selected_movies WHERE movie_id = ?", (movie_id,)
        ).fetchone() is not None


def get_movie_image_states(movie_id: int) -> dict:
    """Get selection states for all images in a movie"""
    with get_db() as conn:
        movie_selected = conn.execute(
            "SELECT 1 FROM selected_movies WHERE movie_id = ?", (movie_id,)
        ).fetchone() is not None

        overrides = {}
        rows = conn.execute("""
            SELECT io.image_id, io.included
            FROM image_overrides io
            JOIN images i ON io.image_id = i.id
            WHERE i.movie_id = ?
        """, (movie_id,)).fetchall()

        for r in rows:
            overrides[r['image_id']] = bool(r['included'])

        return {
            "movie_selected": movie_selected,
            "overrides": overrides
        }


def get_selection_summary() -> dict:
    """Get summary of current selection state"""
    with get_db() as conn:
        # Count selected movies
        movie_count = conn.execute(
            "SELECT COUNT(*) as c FROM selected_movies"
        ).fetchone()['c']

        # Count total images from selected movies
        base_image_count = conn.execute("""
            SELECT COUNT(*) as c FROM images
            WHERE movie_id IN (SELECT movie_id FROM selected_movies)
        """).fetchone()['c']

        # Count excluded images (overrides with included=0 in selected movies)
        excluded_count = conn.execute("""
            SELECT COUNT(*) as c FROM image_overrides io
            JOIN images i ON io.image_id = i.id
            WHERE io.included = 0
            AND i.movie_id IN (SELECT movie_id FROM selected_movies)
        """).fetchone()['c']

        # Count force-included images (from non-selected movies)
        force_included_count = conn.execute("""
            SELECT COUNT(*) as c FROM image_overrides io
            JOIN images i ON io.image_id = i.id
            WHERE io.included = 1
            AND i.movie_id NOT IN (SELECT movie_id FROM selected_movies)
        """).fetchone()['c']

        total_images = base_image_count - excluded_count + force_included_count

        return {
            "selected_movies": movie_count,
            "total_images": total_images,
            "base_images": base_image_count,
            "excluded_images": excluded_count,
            "force_included_images": force_included_count,
        }


def get_all_selected_image_ids() -> list:
    """Get all image IDs that would be in the final dataset"""
    with get_db() as conn:
        # Images from selected movies minus exclusions
        base_ids = conn.execute("""
            SELECT i.id FROM images i
            WHERE i.movie_id IN (SELECT movie_id FROM selected_movies)
            AND i.id NOT IN (
                SELECT image_id FROM image_overrides WHERE included = 0
            )
        """).fetchall()

        # Plus force-included images
        force_ids = conn.execute("""
            SELECT io.image_id as id FROM image_overrides io
            JOIN images i ON io.image_id = i.id
            WHERE io.included = 1
            AND i.movie_id NOT IN (SELECT movie_id FROM selected_movies)
        """).fetchall()

        return [r['id'] for r in base_ids] + [r['id'] for r in force_ids]


def get_movies_with_selection_state(movie_ids: list = None) -> list:
    """Get movies with their selection state and override counts"""
    with get_db() as conn:
        if movie_ids:
            placeholders = ','.join(['?'] * len(movie_ids))
            where_clause = f"WHERE m.id IN ({placeholders})"
            params = movie_ids
        else:
            where_clause = ""
            params = []

        rows = conn.execute(f"""
            SELECT m.id, m.title, m.year, m.image_count, m.aspect_ratio_group,
                   m.original_language, m.genres, m.countries,
                   CASE WHEN sm.movie_id IS NOT NULL THEN 1 ELSE 0 END as selected,
                   (SELECT COUNT(*) FROM image_overrides io
                    JOIN images i ON io.image_id = i.id
                    WHERE i.movie_id = m.id AND io.included = 0) as excluded_count,
                   (SELECT COUNT(*) FROM image_overrides io
                    JOIN images i ON io.image_id = i.id
                    WHERE i.movie_id = m.id AND io.included = 1) as force_included_count
            FROM movies m
            LEFT JOIN selected_movies sm ON m.id = sm.movie_id
            {where_clause}
            ORDER BY m.title
        """, params).fetchall()

        return [dict(r) for r in rows]
