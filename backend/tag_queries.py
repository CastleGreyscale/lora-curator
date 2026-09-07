"""
Tag-based image queries for the Tags panel.

Matching is exact (`tag = ?`) rather than `LIKE '%tag%'`: tags are picked from
the counted list the UI already shows, so an exact match makes the result count
line up with the count printed beside the tag — and it can use
idx_image_tags_tag instead of scanning the whole (multi-million row) table once
per tag per page.

Include tags are ANDed (an image must carry all of them); exclude tags remove
any image carrying one. Aspect-ratio groups narrow the set to images from
movies in those groups, the same field Browse & Select filters on.

Hand reclassification (`edit_tags`) lives here too: the tagger can't reliably
tell a close-up from an extreme close-up, so the UI lets you pick the images it
got wrong and swap the tag yourself.
"""

from datetime import datetime

from database import get_db

MAX_PER_PAGE = 200

# Tags written by hand carry this in image_tags.model, so they stay
# distinguishable from model output. The tagger's "already tagged?" check keys
# on its own model name, so these rows never make an image look tagged.
MANUAL_MODEL = "manual"

# SQLite's default host-parameter limit is 999; stay well under it.
_CHUNK = 400


def _chunked(items, size=_CHUNK):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _conditions(include_tags, exclude_tags, aspect_groups=None):
    """Build the shared WHERE fragment over `images i`."""
    conditions, params = [], []

    for tag in include_tags or []:
        conditions.append("i.id IN (SELECT image_id FROM image_tags WHERE tag = ?)")
        params.append(tag)

    for tag in exclude_tags or []:
        conditions.append("i.id NOT IN (SELECT image_id FROM image_tags WHERE tag = ?)")
        params.append(tag)

    if aspect_groups:
        # Subquery rather than a join so this fragment also works in
        # matched_image_ids(), which doesn't touch the movies table.
        placeholders = ",".join(["?"] * len(aspect_groups))
        conditions.append(
            f"i.movie_id IN (SELECT id FROM movies WHERE aspect_ratio_group IN ({placeholders}))"
        )
        params.extend(aspect_groups)

    if not conditions:
        raise ValueError("Provide at least one tag or aspect ratio filter")

    return " AND ".join(conditions), params


def _tags_by_image(conn, image_ids):
    """{image_id: [tag, ...]} for the images on one page."""
    tags = {image_id: [] for image_id in image_ids}
    for chunk in _chunked(image_ids):
        placeholders = ",".join(["?"] * len(chunk))
        rows = conn.execute(
            f"""SELECT image_id, tag FROM image_tags
                WHERE image_id IN ({placeholders})
                ORDER BY image_id, id""",
            chunk,
        ).fetchall()
        for r in rows:
            tags[r["image_id"]].append(r["tag"])
    return tags


def page_images(include_tags, exclude_tags, page=1, per_page=100, aspect_groups=None):
    """One page of matching images, each with its tags and selection state.

    Ordered by movie then filename so paging is stable and frames from the same
    film stay together.
    """
    where, params = _conditions(include_tags, exclude_tags, aspect_groups)
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

        tags = _tags_by_image(conn, [r["id"] for r in rows])

    images = []
    for r in rows:
        img = dict(r)
        override = img.pop("override_included")
        img["movie_selected"] = bool(img["movie_selected"])
        img["has_override"] = override is not None
        img["included"] = bool(override) if override is not None else img["movie_selected"]
        img["tags"] = tags.get(img["id"], [])
        images.append(img)

    return {
        "images": images,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page,
    }


def matched_image_ids(include_tags, exclude_tags, aspect_groups=None):
    """Every image id matching the filter — used for select/deselect all."""
    where, params = _conditions(include_tags, exclude_tags, aspect_groups)
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT i.id FROM images i WHERE {where} ORDER BY i.id", params
        ).fetchall()
    return [r["id"] for r in rows]


def normalize_tag(tag):
    """Same shape the tagger stores: trimmed, lowercase, sanely sized."""
    tag = (tag or "").strip().lower()
    return tag if 0 < len(tag) < 100 else None


def edit_tags(image_ids, add_tags=None, remove_tags=None):
    """Add and/or remove tags on a set of images.

    A reclassification is just a remove + an add in one call (drop "close-up",
    apply "extreme close-up"), so both happen in a single transaction and the
    images are never left carrying neither tag.

    Removal drops the tag whatever wrote it; adds are skipped where the image
    already carries the tag, so re-applying is harmless.
    """
    image_ids = [int(i) for i in image_ids or []]
    if not image_ids:
        raise ValueError("No images given")

    add = [t for t in (normalize_tag(t) for t in add_tags or []) if t]
    remove = [t for t in (normalize_tag(t) for t in remove_tags or []) if t]
    if not add and not remove:
        raise ValueError("Provide at least one tag to add or remove")

    now = datetime.now().isoformat()
    added = removed = 0

    with get_db() as conn:
        for tag in remove:
            for chunk in _chunked(image_ids):
                placeholders = ",".join(["?"] * len(chunk))
                cur = conn.execute(
                    f"DELETE FROM image_tags WHERE tag = ? AND image_id IN ({placeholders})",
                    [tag] + chunk,
                )
                removed += cur.rowcount

        for tag in add:
            for image_id in image_ids:
                cur = conn.execute(
                    """INSERT INTO image_tags (image_id, tag, confidence, model, tagged_at)
                       SELECT ?, ?, 1.0, ?, ?
                       WHERE NOT EXISTS (
                           SELECT 1 FROM image_tags WHERE image_id = ? AND tag = ?
                       )""",
                    (image_id, tag, MANUAL_MODEL, now, image_id, tag),
                )
                added += cur.rowcount

    return {
        "images": len(image_ids),
        "added": added,
        "removed": removed,
        "add_tags": add,
        "remove_tags": remove,
    }
