"""
Browse & Selection API routes.
Add to your main.py:
    from browse_routes import router as browse_router
    app.include_router(browse_router)
"""

from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from typing import List, Optional
import json
from database import get_db
import selections

router = APIRouter(prefix="/api", tags=["browse"])


# ── Pydantic models ──────────────────────────

class ToggleMovieRequest(BaseModel):
    movie_id: int

class BulkMovieRequest(BaseModel):
    movie_ids: List[int]

class ToggleImageRequest(BaseModel):
    image_id: int

class BulkImageRequest(BaseModel):
    image_ids: List[int]
    included: bool = True


# ── Movie browsing with thumbnails ───────────

@router.get("/browse/movies")
async def browse_movies(
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    languages: Optional[str] = None,
    genres: Optional[str] = None,
    countries: Optional[str] = None,
    aspects: Optional[str] = None,
    keywords: Optional[str] = None,
    keywords_exclude: Optional[str] = None,
    search: Optional[str] = None,
    sort: Optional[str] = "title",
    page: int = 1,
    per_page: int = 60,
):
    """
    Get movies with a single representative thumbnail each.
    Returns paginated results respecting all filters.
    """
    with get_db() as conn:
        conditions = []
        params = []

        if year_min is not None:
            conditions.append("m.year >= ?")
            params.append(year_min)
        if year_max is not None:
            conditions.append("m.year <= ?")
            params.append(year_max)

        if languages:
            lang_list = [l.strip() for l in languages.split(",")]
            placeholders = ",".join(["?"] * len(lang_list))
            conditions.append(f"m.original_language IN ({placeholders})")
            params.extend(lang_list)

        if genres:
            genre_list = [g.strip() for g in genres.split(",")]
            genre_conditions = []
            for g in genre_list:
                genre_conditions.append("m.genres LIKE ?")
                params.append(f"%{g}%")
            conditions.append(f"({' OR '.join(genre_conditions)})")

        if countries:
            country_list = [c.strip() for c in countries.split(",")]
            country_conditions = []
            for c in country_list:
                country_conditions.append("m.countries LIKE ?")
                params.append(f"%{c}%")
            conditions.append(f"({' OR '.join(country_conditions)})")

        if aspects:
            aspect_list = [a.strip() for a in aspects.split(",")]
            placeholders = ",".join(["?"] * len(aspect_list))
            conditions.append(f"m.aspect_ratio_group IN ({placeholders})")
            params.extend(aspect_list)

        if keywords:
            kw_list = [k.strip() for k in keywords.split(",")]
            kw_conditions = []
            for kw in kw_list:
                kw_conditions.append("m.keywords LIKE ?")
                params.append(f"%{kw}%")
            conditions.append(f"({' OR '.join(kw_conditions)})")

        if keywords_exclude:
            kw_list = [k.strip() for k in keywords_exclude.split(",")]
            for kw in kw_list:
                conditions.append("(m.keywords NOT LIKE ? OR m.keywords IS NULL)")
                params.append(f"%{kw}%")

        if search:
            conditions.append("(m.title LIKE ? OR m.original_title LIKE ? OR m.folder_name LIKE ?)")
            params.extend([f"%{search}%"] * 3)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # Sort
        sort_map = {
            "title": "m.title ASC",
            "year": "m.year DESC",
            "year_asc": "m.year ASC",
            "images": "m.image_count DESC",
            "recent": "m.indexed_at DESC",
        }
        order = sort_map.get(sort, "m.title ASC")

        # Count total
        count_row = conn.execute(
            f"SELECT COUNT(*) as total FROM movies m {where}", params
        ).fetchone()
        total = count_row["total"]

        # Get page of movies with their middle image as thumbnail
        offset = (page - 1) * per_page
        rows = conn.execute(f"""
            SELECT m.id, m.title, m.original_title, m.year, m.image_count,
                   m.aspect_ratio_group, m.original_language, m.genres, m.countries,
                   m.overview, m.folder_name,
                   CASE WHEN sm.movie_id IS NOT NULL THEN 1 ELSE 0 END as selected,
                   (SELECT COUNT(*) FROM image_overrides io
                    JOIN images i ON io.image_id = i.id
                    WHERE i.movie_id = m.id AND io.included = 0) as excluded_count
            FROM movies m
            LEFT JOIN selected_movies sm ON m.id = sm.movie_id
            {where}
            ORDER BY {order}
            LIMIT ? OFFSET ?
        """, params + [per_page, offset]).fetchall()

        movies = []
        for r in rows:
            movie = dict(r)
            # Parse JSON fields
            for field in ('genres', 'countries'):
                if movie[field]:
                    try:
                        movie[field] = json.loads(movie[field])
                    except:
                        movie[field] = []
                else:
                    movie[field] = []

            # Get middle image as thumbnail
            thumb = conn.execute("""
                SELECT id, filename FROM images
                WHERE movie_id = ?
                ORDER BY filename
                LIMIT 1 OFFSET (
                    SELECT COUNT(*) / 2 FROM images WHERE movie_id = ?
                )
            """, (movie['id'], movie['id'])).fetchone()

            movie['thumbnail_id'] = thumb['id'] if thumb else None
            movies.append(movie)

        return {
            "movies": movies,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": (total + per_page - 1) // per_page,
        }


@router.get("/browse/movies/{movie_id}/images")
async def browse_movie_images(
    movie_id: int,
    page: int = 1,
    per_page: int = 100,
):
    """
    Get all images for a specific movie with their selection state.
    """
    with get_db() as conn:
        # Get movie info
        movie = conn.execute("""
            SELECT m.*,
                   CASE WHEN sm.movie_id IS NOT NULL THEN 1 ELSE 0 END as selected
            FROM movies m
            LEFT JOIN selected_movies sm ON m.id = sm.movie_id
            WHERE m.id = ?
        """, (movie_id,)).fetchone()

        if not movie:
            raise HTTPException(status_code=404, detail="Movie not found")

        movie_dict = dict(movie)
        for field in ('genres', 'countries', 'keywords'):
            if movie_dict.get(field):
                try:
                    movie_dict[field] = json.loads(movie_dict[field])
                except:
                    movie_dict[field] = []
            else:
                movie_dict[field] = []

        # Get total image count
        total = conn.execute(
            "SELECT COUNT(*) as c FROM images WHERE movie_id = ?", (movie_id,)
        ).fetchone()['c']

        # Get images with override state
        offset = (page - 1) * per_page
        rows = conn.execute("""
            SELECT i.id, i.filename, i.filepath, i.width, i.height,
                   io.included as override_included
            FROM images i
            LEFT JOIN image_overrides io ON i.id = io.image_id
            WHERE i.movie_id = ?
            ORDER BY i.filename
            LIMIT ? OFFSET ?
        """, (movie_id, per_page, offset)).fetchall()

        movie_selected = bool(movie_dict['selected'])
        images = []
        for r in rows:
            img = dict(r)
            # Determine effective selection state
            if img['override_included'] is not None:
                img['included'] = bool(img['override_included'])
                img['has_override'] = True
            else:
                img['included'] = movie_selected
                img['has_override'] = False
            del img['override_included']
            images.append(img)

        return {
            "movie": movie_dict,
            "images": images,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": (total + per_page - 1) // per_page,
        }


# ── Selection endpoints ──────────────────────

@router.post("/selection/toggle-movie")
async def toggle_movie(req: ToggleMovieRequest):
    """Toggle a movie's selection state"""
    return selections.toggle_movie(req.movie_id)


@router.post("/selection/select-movies")
async def select_movies(req: BulkMovieRequest):
    """Select multiple movies"""
    return selections.select_movies_bulk(req.movie_ids)


@router.post("/selection/deselect-movies")
async def deselect_movies(req: BulkMovieRequest):
    """Deselect multiple movies"""
    return selections.deselect_movies_bulk(req.movie_ids)


@router.post("/selection/toggle-image")
async def toggle_image(req: ToggleImageRequest):
    """Toggle an individual image"""
    return selections.toggle_image(req.image_id)


@router.post("/selection/images")
async def set_images_selection(req: BulkImageRequest):
    """Include or drop a batch of images (the Tags panel's per-page select all)."""
    if req.included:
        return selections.include_images_bulk(req.image_ids)
    return selections.deselect_images_bulk(req.image_ids)


@router.get("/selection/summary")
async def selection_summary():
    """Get selection summary"""
    return selections.get_selection_summary()


@router.get("/selection/movie-ids")
async def selected_movie_ids():
    """Get list of selected movie IDs"""
    return {"movie_ids": selections.get_selected_movie_ids()}


@router.post("/selection/clear")
async def clear_selections():
    """Clear all selections"""
    return selections.clear_all_selections()


@router.post("/selection/select-all-filtered")
async def select_all_filtered(
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    languages: Optional[str] = None,
    genres: Optional[str] = None,
    countries: Optional[str] = None,
    aspects: Optional[str] = None,
    keywords: Optional[str] = None,
    keywords_exclude: Optional[str] = None,
    search: Optional[str] = None,
):
    """Select all movies matching current filters"""
    with get_db() as conn:
        conditions = []
        params = []

        if year_min is not None:
            conditions.append("year >= ?")
            params.append(year_min)
        if year_max is not None:
            conditions.append("year <= ?")
            params.append(year_max)
        if languages:
            lang_list = [l.strip() for l in languages.split(",")]
            placeholders = ",".join(["?"] * len(lang_list))
            conditions.append(f"original_language IN ({placeholders})")
            params.extend(lang_list)
        if genres:
            genre_list = [g.strip() for g in genres.split(",")]
            genre_conditions = []
            for g in genre_list:
                genre_conditions.append("genres LIKE ?")
                params.append(f"%{g}%")
            conditions.append(f"({' OR '.join(genre_conditions)})")
        if countries:
            country_list = [c.strip() for c in countries.split(",")]
            country_conditions = []
            for c in country_list:
                country_conditions.append("countries LIKE ?")
                params.append(f"%{c}%")
            conditions.append(f"({' OR '.join(country_conditions)})")
        if aspects:
            aspect_list = [a.strip() for a in aspects.split(",")]
            placeholders = ",".join(["?"] * len(aspect_list))
            conditions.append(f"aspect_ratio_group IN ({placeholders})")
            params.extend(aspect_list)
        if keywords:
            kw_list = [k.strip() for k in keywords.split(",")]
            kw_conditions = []
            for kw in kw_list:
                kw_conditions.append("keywords LIKE ?")
                params.append(f"%{kw}%")
            conditions.append(f"({' OR '.join(kw_conditions)})")
        if keywords_exclude:
            kw_list = [k.strip() for k in keywords_exclude.split(",")]
            for kw in kw_list:
                conditions.append("(keywords NOT LIKE ? OR keywords IS NULL)")
                params.append(f"%{kw}%")
        if search:
            conditions.append("(title LIKE ? OR original_title LIKE ?)")
            params.extend([f"%{search}%"] * 2)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        rows = conn.execute(
            f"SELECT id FROM movies {where}", params
        ).fetchall()

        movie_ids = [r['id'] for r in rows]

    return selections.select_movies_bulk(movie_ids)


@router.post("/selection/deselect-all-filtered")
async def deselect_all_filtered(
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    languages: Optional[str] = None,
    genres: Optional[str] = None,
    countries: Optional[str] = None,
    aspects: Optional[str] = None,
    keywords: Optional[str] = None,
    keywords_exclude: Optional[str] = None,
    search: Optional[str] = None,
):
    """Deselect all movies matching current filters"""
    with get_db() as conn:
        conditions = []
        params = []

        if year_min is not None:
            conditions.append("year >= ?")
            params.append(year_min)
        if year_max is not None:
            conditions.append("year <= ?")
            params.append(year_max)
        if languages:
            lang_list = [l.strip() for l in languages.split(",")]
            placeholders = ",".join(["?"] * len(lang_list))
            conditions.append(f"original_language IN ({placeholders})")
            params.extend(lang_list)
        if genres:
            genre_list = [g.strip() for g in genres.split(",")]
            genre_conditions = []
            for g in genre_list:
                genre_conditions.append("genres LIKE ?")
                params.append(f"%{g}%")
            conditions.append(f"({' OR '.join(genre_conditions)})")
        if aspects:
            aspect_list = [a.strip() for a in aspects.split(",")]
            placeholders = ",".join(["?"] * len(aspect_list))
            conditions.append(f"aspect_ratio_group IN ({placeholders})")
            params.extend(aspect_list)
        if keywords:
            kw_list = [k.strip() for k in keywords.split(",")]
            kw_conditions = []
            for kw in kw_list:
                kw_conditions.append("keywords LIKE ?")
                params.append(f"%{kw}%")
            conditions.append(f"({' OR '.join(kw_conditions)})")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = conn.execute(f"SELECT id FROM movies {where}", params).fetchall()
        movie_ids = [r['id'] for r in rows]

    return selections.deselect_movies_bulk(movie_ids)
