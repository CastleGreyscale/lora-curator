"""
Tag-based image queries for the Tags panel.

Matching is exact (`tag = ?`) rather than `LIKE '%tag%'`: tags are picked from
the counted list the UI already shows, so an exact match makes the result count
line up with the count printed beside the tag — and it can use
idx_image_tags_tag instead of scanning the whole (multi-million row) table once
per tag per page.

Include tags are ANDed (an image must carry all of them); exclude tags remove
any image carrying one.
"""

from database import get_db

MAX_PER_PAGE = 200


def _conditions(include_tags, exclude_tags):
    """Build the shared WHERE fragment over `images i`."""
    conditions, params = [], []

    for tag in include_tags or []:
        conditions.append("i.id IN (SELECT image_id FROM image_tags WHERE tag = ?)")
        params.append(tag)

    for tag in exclude_tags or []:
        conditions.append("i.id NOT IN (SELECT image_id FROM image_tags WHERE tag = ?)")
        params.append(tag)

    if not conditions:
        raise ValueError("Provide at least one include or exclude tag")

    return " AND ".join(conditions), params


def page_images(include_tags, exclude_tags, page=1, per_page=100):
    """One page of matching images, each with its current selection state.

    Ordered by movie then filename so paging is stable and frames from the same
    film stay together.
    """
    where, params = _conditions(include_tags, exclude_tags)
    per_page = max(1, min(int(per_page), MAX_PER_PAGE))
    page = max(1, int(page))

    with get_db() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM images i WHERE {where}", params
        ).fetchone()["c"]

        rows = conn.execute(
            f"""
            SELECT i.id, i.filename, i.filepath, i.width, i.height, i.movie_id,
                   m.title AS movie_title, m.year AS movie_year,
                   m.aspect_ratio_group,
                   io.included AS override_included,
                   CASE WHEN sm.movie_id IS NOT NULL THEN 1 ELSE 0 END AS movie_selected
            FROM images i
            JOIN movies m ON i.movie_id = m.id
            LEFT JOIN image_overrides io ON io.image_id = i.id
            LEFT JOIN selected_movies sm ON sm.movie_id = i.movie_id
            WHERE {where}
            ORDER BY m.title, i.filename, i.id
            LIMIT ? OFFSET ?
            """,
            params + [per_page, (page - 1) * per_page],
        ).fetchall()

    images = []
    for r in rows:
        img = dict(r)
        override = img.pop("override_included")
        img["movie_selected"] = bool(img["movie_selected"])
        img["has_override"] = override is not None
        img["included"] = bool(override) if override is not None else img["movie_selected"]
        images.append(img)

    return {
        "images": images,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page,
    }


def matched_image_ids(include_tags, exclude_tags):
    """Every image id matching the filter — used for select/deselect all."""
    where, params = _conditions(include_tags, exclude_tags)
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT i.id FROM images i WHERE {where} ORDER BY i.id", params
        ).fetchall()
    return [r["id"] for r in rows]
