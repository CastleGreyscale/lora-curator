#!/usr/bin/env python3
"""
Mass Image Tagger
Tags all indexed images using Ollama vision models.
Stores structured tags in SQLite for filtering in the curator UI.

Designed for 250k+ images: lean prompt, terse output, fully resumable.
"""

import os
import sys
import json
import time
import base64
import signal
import argparse
import sqlite3
import requests
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager

# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────

DEFAULT_MODEL = "qwen2.5vl:7b"
DEFAULT_API_URL = "http://localhost:11434"
DEFAULT_DB_PATH = os.environ.get("CURATOR_DB_PATH", "curator.db")

# Short prompt = fast inference. We want tags, not essays.
TAG_PROMPT = """List comma-separated tags for this image. Include:
- shot type (close-up, medium, wide, extreme wide, overhead, low angle)
- lighting (high-key, low-key, natural, neon, backlit, silhouette, golden hour, harsh, soft)
- mood (tense, calm, romantic, eerie, melancholy, joyful, ominous, chaotic)
- setting (interior, exterior, urban, rural, underwater, vehicle, office, bar, street)
- people (none, single, couple, group, crowd)
- notable elements (rain, smoke, mirror, shadows, fire, snow, blood, weapon, phone, car)

Tags only. No sentences. No descriptions."""

# Status file for the web UI to read
STATUS_FILE = "tagger_status.json"

# ──────────────────────────────────────────────
# Globals for graceful shutdown
# ──────────────────────────────────────────────

shutdown_requested = False


def signal_handler(sig, frame):
    global shutdown_requested
    print("\n⚠ Shutdown requested — finishing current image...")
    shutdown_requested = True


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# ──────────────────────────────────────────────
# Database helpers
# ──────────────────────────────────────────────


@contextmanager
def get_db(db_path):
    conn = sqlite3.connect(db_path)
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


def get_untagged_images(db_path, model, limit=None, movie_id=None):
    """Get images that haven't been tagged by this model yet."""
    with get_db(db_path) as conn:
        query = """
            SELECT i.id, i.filepath, i.movie_id, m.title as movie_title
            FROM images i
            JOIN movies m ON i.movie_id = m.id
            WHERE i.id NOT IN (
                SELECT DISTINCT image_id FROM image_tags WHERE model = ?
            )
        """
        params = [model]

        if movie_id:
            query += " AND i.movie_id = ?"
            params.append(movie_id)

        query += " ORDER BY i.movie_id, i.filename"

        if limit:
            query += " LIMIT ?"
            params.append(limit)

        return [dict(r) for r in conn.execute(query, params).fetchall()]


def get_tag_stats(db_path, model):
    """Get tagging progress stats."""
    with get_db(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) as c FROM images").fetchone()["c"]
        tagged = conn.execute(
            "SELECT COUNT(DISTINCT image_id) as c FROM image_tags WHERE model = ?",
            (model,),
        ).fetchone()["c"]
        return {"total": total, "tagged": tagged, "remaining": total - tagged}


def save_tags(db_path, image_id, tags, raw_response, model):
    """Save parsed tags and raw caption to the database."""
    now = datetime.now().isoformat()
    with get_db(db_path) as conn:
        # Save individual tags
        for tag in tags:
            tag = tag.strip().lower()
            if tag and len(tag) < 100:  # Skip garbage
                conn.execute(
                    """INSERT INTO image_tags (image_id, tag, model, tagged_at)
                       VALUES (?, ?, ?, ?)""",
                    (image_id, tag, model, now),
                )

        # Save raw response as caption
        conn.execute(
            """INSERT INTO image_captions (image_id, caption, model, tagged_at)
               VALUES (?, ?, ?, ?)""",
            (image_id, raw_response, model, now),
        )


# ──────────────────────────────────────────────
# Ollama interaction
# ──────────────────────────────────────────────


def check_ollama(api_url, model):
    """Verify Ollama is running and model is available."""
    try:
        resp = requests.get(f"{api_url}/api/tags", timeout=5)
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]

        # Check for exact or partial match
        model_base = model.split(":")[0]
        available = any(model_base in m for m in models)

        if not available:
            print(f"⚠ Model '{model}' not found. Available models:")
            for m in models:
                print(f"  - {m}")
            print(f"\nPull it with: ollama pull {model}")
            return False

        return True
    except requests.ConnectionError:
        print(f"✗ Cannot connect to Ollama at {api_url}")
        print("  Start it with: ollama serve")
        return False


def tag_image(filepath, api_url, model, prompt):
    """Send image to Ollama and get tags back."""
    # Read and encode image
    with open(filepath, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")

    try:
        resp = requests.post(
            f"{api_url}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "images": [image_b64],
                "stream": False,
                "options": {
                    "temperature": 0.1,  # Low temp = consistent tags
                    "num_predict": 150,  # Cap output length — tags are short
                },
            },
            timeout=60,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "").strip()
        return raw
    except requests.Timeout:
        return None
    except Exception as e:
        print(f"  ✗ API error: {e}")
        return None


def parse_tags(raw_response):
    """Parse comma-separated tags from model response."""
    if not raw_response:
        return []

    # Clean up common formatting issues
    text = raw_response.strip()

    # Remove any markdown/bullet formatting the model might add
    text = text.replace("- ", "").replace("• ", "").replace("* ", "")

    # Split on commas and newlines
    tags = []
    for part in text.replace("\n", ",").split(","):
        tag = part.strip().strip(".-•*").strip()
        # Skip empty, too short, or sentence-like responses
        if tag and 2 <= len(tag) <= 80 and tag.count(" ") < 6:
            tags.append(tag.lower())

    return list(dict.fromkeys(tags))  # Dedupe preserving order


# ──────────────────────────────────────────────
# Status tracking
# ──────────────────────────────────────────────


def write_status(db_path, status_data):
    """Write status to JSON file for the web UI."""
    status_path = Path(db_path).parent / STATUS_FILE
    try:
        with open(status_path, "w") as f:
            json.dump(status_data, f)
    except Exception:
        pass  # Non-critical


# ──────────────────────────────────────────────
# Main tagger loop
# ──────────────────────────────────────────────


def run_tagger(
    db_path,
    model=DEFAULT_MODEL,
    api_url=DEFAULT_API_URL,
    prompt=TAG_PROMPT,
    batch_size=None,
    movie_id=None,
):
    """Main tagging loop. Fully resumable — skips already-tagged images."""
    global shutdown_requested

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  Mass Image Tagger")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  Model:    {model}")
    print(f"  API:      {api_url}")
    print(f"  Database: {db_path}")

    # Check Ollama
    if not check_ollama(api_url, model):
        return 1

    # Get stats
    stats = get_tag_stats(db_path, model)
    print(f"  Total:    {stats['total']:,} images")
    print(f"  Tagged:   {stats['tagged']:,}")
    print(f"  Remaining:{stats['remaining']:,}")
    if batch_size:
        print(f"  Batch:    {batch_size}")
    if movie_id:
        print(f"  Movie ID: {movie_id}")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  Press Ctrl+C to stop gracefully")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

    if stats["remaining"] == 0 and not movie_id:
        print("✓ All images already tagged!")
        return 0

    # Get untagged images
    images = get_untagged_images(db_path, model, limit=batch_size, movie_id=movie_id)
    total_to_process = len(images)

    if total_to_process == 0:
        print("✓ No untagged images found.")
        return 0

    print(f"Processing {total_to_process:,} images...\n")

    # Track progress
    processed = 0
    failed = 0
    current_movie = None
    start_time = time.time()
    batch_start = time.time()

    for img in images:
        if shutdown_requested:
            print(f"\n⚠ Stopped after {processed} images. Run again to resume.")
            break

        # Log movie transitions
        if img["movie_title"] != current_movie:
            current_movie = img["movie_title"]
            print(f"\n▸ {current_movie}")

        filepath = img["filepath"]

        # Verify file exists
        if not os.path.exists(filepath):
            failed += 1
            continue

        # Tag it
        raw = tag_image(filepath, api_url, model, prompt)

        if raw is None:
            failed += 1
            print(f"  ✗ {Path(filepath).name}")
            continue

        # Parse and save
        tags = parse_tags(raw)

        if not tags:
            failed += 1
            print(f"  ✗ {Path(filepath).name} (no tags parsed)")
            continue

        save_tags(db_path, img["id"], tags, raw, model)
        processed += 1

        # Progress display every 10 images
        if processed % 10 == 0:
            elapsed = time.time() - start_time
            rate = processed / elapsed if elapsed > 0 else 0
            remaining_est = (total_to_process - processed) / rate if rate > 0 else 0

            hours = int(remaining_est // 3600)
            mins = int((remaining_est % 3600) // 60)

            print(
                f"  [{processed}/{total_to_process}] "
                f"{rate:.1f} img/s — "
                f"~{hours}h{mins:02d}m remaining"
            )

            # Write status for web UI
            write_status(
                db_path,
                {
                    "running": True,
                    "model": model,
                    "processed": processed,
                    "failed": failed,
                    "total": total_to_process,
                    "rate": round(rate, 2),
                    "eta_seconds": int(remaining_est),
                    "current_movie": current_movie,
                    "updated_at": datetime.now().isoformat(),
                },
            )

    # Final stats
    elapsed = time.time() - start_time
    rate = processed / elapsed if elapsed > 0 else 0

    print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  Done!")
    print(f"  Tagged:   {processed:,}")
    print(f"  Failed:   {failed:,}")
    print(f"  Rate:     {rate:.1f} img/s")
    print(f"  Time:     {elapsed/60:.1f} minutes")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # Final status
    write_status(
        db_path,
        {
            "running": False,
            "model": model,
            "processed": processed,
            "failed": failed,
            "total": total_to_process,
            "rate": round(rate, 2),
            "completed_at": datetime.now().isoformat(),
        },
    )

    return 0


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Mass image tagger using Ollama vision models",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Tag all untagged images (resumable)
  python tagger.py

  # Tag a batch of 500, then stop
  python tagger.py --batch 500

  # Tag images from a specific movie only
  python tagger.py --movie-id 42

  # Use a different model
  python tagger.py --model llava:13b

  # Check progress
  python tagger.py --stats

  # Custom database path
  python tagger.py --db /path/to/curator.db
        """,
    )

    parser.add_argument(
        "--db",
        default=DEFAULT_DB_PATH,
        help=f"Database path (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Ollama model (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help=f"Ollama API URL (default: {DEFAULT_API_URL})",
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=None,
        help="Process N images then stop (default: all)",
    )
    parser.add_argument(
        "--movie-id",
        type=int,
        default=None,
        help="Only tag images from this movie ID",
    )
    parser.add_argument(
        "--stats", action="store_true", help="Show tagging stats and exit"
    )

    args = parser.parse_args()

    if not Path(args.db).exists():
        print(f"✗ Database not found: {args.db}")
        print("  Run the curator scan first to create it.")
        return 1

    if args.stats:
        stats = get_tag_stats(args.db, args.model)
        pct = (stats["tagged"] / stats["total"] * 100) if stats["total"] > 0 else 0
        print(f"Model:     {args.model}")
        print(f"Total:     {stats['total']:,}")
        print(f"Tagged:    {stats['tagged']:,} ({pct:.1f}%)")
        print(f"Remaining: {stats['remaining']:,}")
        return 0

    return run_tagger(
        db_path=args.db,
        model=args.model,
        api_url=args.api_url,
        batch_size=args.batch,
        movie_id=args.movie_id,
    )


if __name__ == "__main__":
    sys.exit(main())
