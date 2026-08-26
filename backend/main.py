"""
LoRA Dataset Curator - FastAPI Backend
Serves the API for the dataset curation UI
"""

import os
import sys
import json
import signal
import asyncio
import subprocess
import threading
from collections import deque
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from database import (
    init_db, scan_dataset_root, get_filter_options, filter_movies,
    get_random_images, get_db_stats, get_db, DB_PATH
)





# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────

DATASET_ROOT = os.environ.get("DATASET_ROOT", "/home/brad/ai/training/main_datasets")
TRAINING_ROOT = os.environ.get("TRAINING_ROOT", "/home/brad/ai/training")

# Track scan progress globally
scan_status = {
    "running": False,
    "progress": 0,
    "total": 0,
    "current": "",
    "stats": None,
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB on startup"""
    init_db()
    import selections
    selections.init_selection_tables()
    yield


app = FastAPI(
    title="LoRA Dataset Curator",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS for dev (React dev server on :5173)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from browse_routes import router as browse_router
app.include_router(browse_router)

from pipeline_routes import router as pipeline_router
app.include_router(pipeline_router)


@app.get("/api/config/defaults")
async def get_config_defaults():
    """Serve lora-curator/defaults.toml to the frontend.

    Re-read per request, so editing the file only needs a page reload.
    """
    import defaults
    return defaults.load()

# ──────────────────────────────────────────────
# Request/Response Models
# ──────────────────────────────────────────────

class FilterRequest(BaseModel):
    year_min: Optional[int] = None
    year_max: Optional[int] = None
    genres: Optional[list[str]] = None
    countries: Optional[list[str]] = None
    languages: Optional[list[str]] = None
    keywords_include: Optional[list[str]] = None
    keywords_exclude: Optional[list[str]] = None
    aspect_groups: Optional[list[str]] = None
    search: Optional[str] = None
    page: int = 1
    per_page: int = 50


class SampleRequest(BaseModel):
    """Request to sample images from filtered movies"""
    count: int = 24
    # Embed filter criteria
    year_min: Optional[int] = None
    year_max: Optional[int] = None
    genres: Optional[list[str]] = None
    countries: Optional[list[str]] = None
    languages: Optional[list[str]] = None
    keywords_include: Optional[list[str]] = None
    keywords_exclude: Optional[list[str]] = None
    aspect_groups: Optional[list[str]] = None
    search: Optional[str] = None


class ScanRequest(BaseModel):
    root_path: Optional[str] = None


# ──────────────────────────────────────────────
# API Routes
# ──────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "dataset_root": DATASET_ROOT}


@app.get("/api/stats")
async def stats():
    """Get overall database statistics"""
    return get_db_stats()


# ── Scanning ──────────────────────────────────

@app.post("/api/scan")
async def start_scan(req: ScanRequest, background_tasks: BackgroundTasks):
    """Start scanning the dataset root directory"""
    if scan_status["running"]:
        raise HTTPException(400, "Scan already in progress")
    
    root = req.root_path or DATASET_ROOT
    if not Path(root).exists():
        raise HTTPException(404, f"Path not found: {root}")
    
    scan_status["running"] = True
    scan_status["progress"] = 0
    scan_status["total"] = 0
    scan_status["current"] = ""
    scan_status["stats"] = None
    
    background_tasks.add_task(_run_scan, root)
    return {"status": "started", "root": root}


def _run_scan(root: str):
    """Background scan task"""
    def progress_callback(current, total, name):
        scan_status["progress"] = current
        scan_status["total"] = total
        scan_status["current"] = name
    
    try:
        stats = scan_dataset_root(root, progress_callback)
        scan_status["stats"] = stats
    except Exception as e:
        scan_status["stats"] = {"error": str(e)}
    finally:
        scan_status["running"] = False


@app.get("/api/scan/status")
async def scan_progress():
    """Get current scan progress"""
    return scan_status


# ── Filter Options ────────────────────────────

@app.get("/api/filters")
async def filters():
    """Get all available filter values for the UI dropdowns"""
    return get_filter_options()


# ── Movie Filtering ──────────────────────────

@app.post("/api/movies/filter")
async def filter_movies_endpoint(req: FilterRequest):
    """Filter movies based on metadata criteria"""
    return filter_movies(
        year_min=req.year_min,
        year_max=req.year_max,
        genres=req.genres,
        countries=req.countries,
        languages=req.languages,
        keywords_include=req.keywords_include,
        keywords_exclude=req.keywords_exclude,
        aspect_groups=req.aspect_groups,
        search=req.search,
        page=req.page,
        per_page=req.per_page,
    )


@app.get("/api/movies/{movie_id}")
async def get_movie(movie_id: int):
    """Get a single movie with its images"""
    with get_db() as conn:
        movie = conn.execute("SELECT * FROM movies WHERE id = ?", (movie_id,)).fetchone()
        if not movie:
            raise HTTPException(404, "Movie not found")
        
        movie_dict = dict(movie)
        movie_dict['countries'] = json.loads(movie_dict.get('countries') or '[]')
        movie_dict['genres'] = json.loads(movie_dict.get('genres') or '[]')
        movie_dict['keywords'] = json.loads(movie_dict.get('keywords') or '[]')
        
        images = conn.execute(
            """SELECT * FROM images WHERE movie_id = ? ORDER BY filename""",
            (movie_id,)
        ).fetchall()
        movie_dict['images'] = [dict(img) for img in images]
        
        return movie_dict


# ── Image Endpoints ───────────────────────────

@app.get("/api/images/random")
async def random_images(
    count: int = Query(20, ge=1, le=200),
    movie_ids: Optional[str] = None,
):
    """Get random sample of images. movie_ids is comma-separated."""
    ids = None
    if movie_ids:
        ids = [int(x) for x in movie_ids.split(",")]
    return get_random_images(movie_ids=ids, count=count)


@app.post("/api/images/sample")
async def sample_images_from_filters(req: SampleRequest):
    """
    Stratified random sample from the full filtered movie set.
    Uses ALL matching movies (not just the current page).
    """
    # Get ALL matching movie IDs (no pagination)
    result = filter_movies(
        year_min=req.year_min,
        year_max=req.year_max,
        genres=req.genres,
        countries=req.countries,
        languages=req.languages,
        keywords_include=req.keywords_include,
        keywords_exclude=req.keywords_exclude,
        aspect_groups=req.aspect_groups,
        search=req.search,
        page=1,
        per_page=100000,
    )
    
    movie_ids = [m['id'] for m in result['movies']]
    if not movie_ids:
        return []
    
    return get_random_images(movie_ids=movie_ids, count=min(req.count, 200))


@app.get("/api/images/sample-from-filter")
async def sample_from_filter(
    count: int = Query(20, ge=1, le=100),
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    genres: Optional[str] = None,
    countries: Optional[str] = None,
    languages: Optional[str] = None,
    aspect_groups: Optional[str] = None,
    search: Optional[str] = None,
):
    """Get random image samples from the current filter set"""
    # First get matching movie IDs
    result = filter_movies(
        year_min=year_min,
        year_max=year_max,
        genres=genres.split(",") if genres else None,
        countries=countries.split(",") if countries else None,
        languages=languages.split(",") if languages else None,
        aspect_groups=aspect_groups.split(",") if aspect_groups else None,
        search=search,
        page=1,
        per_page=10000,  # Get all matching
    )
    
    movie_ids = [m['id'] for m in result['movies']]
    if not movie_ids:
        return []
    
    return get_random_images(movie_ids=movie_ids, count=count)


@app.get("/api/image/serve/{image_id}")
async def serve_image(image_id: int):
    """Serve an actual image file (for thumbnails/preview)"""
    with get_db() as conn:
        row = conn.execute("SELECT filepath FROM images WHERE id = ?", (image_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Image not found")
        
        filepath = Path(row['filepath'])
        if not filepath.exists():
            raise HTTPException(404, "Image file missing from disk")
        
        return FileResponse(
            filepath,
            media_type=f"image/{filepath.suffix.lstrip('.').lower().replace('jpg', 'jpeg')}",
        )


@app.get("/api/image/serve-by-path")
async def serve_image_by_path(path: str):
    """Serve an image by its filesystem path (with validation)"""
    filepath = Path(path)
    
    # Security: only serve from known dataset roots
    allowed_roots = [Path(DATASET_ROOT), Path(TRAINING_ROOT)]
    if not any(filepath.is_relative_to(root) for root in allowed_roots if root.exists()):
        raise HTTPException(403, "Path not in allowed directory")
    
    if not filepath.exists():
        raise HTTPException(404, "File not found")
    
    return FileResponse(
        filepath,
        media_type=f"image/{filepath.suffix.lstrip('.').lower().replace('jpg', 'jpeg')}",
    )


# ── Aggregation Endpoints ────────────────────

@app.get("/api/movies/by-decade")
async def movies_by_decade():
    """Get movie counts grouped by decade"""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT (year / 10) * 10 as decade, 
                   COUNT(*) as movie_count,
                   SUM(image_count) as image_count
            FROM movies 
            WHERE year IS NOT NULL
            GROUP BY decade
            ORDER BY decade
        """).fetchall()
        return [dict(r) for r in rows]


@app.get("/api/movies/by-aspect")
async def movies_by_aspect():
    """Get movie counts grouped by aspect ratio"""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT aspect_ratio_group,
                   COUNT(*) as movie_count,
                   SUM(image_count) as image_count
            FROM movies
            GROUP BY aspect_ratio_group
            ORDER BY aspect_ratio_group
        """).fetchall()
        return [dict(r) for r in rows]


# ──────────────────────────────────────────────
# Tagger Process Management
# ──────────────────────────────────────────────

tagger_process = {
    "proc": None,         # subprocess.Popen object
    "log": deque(maxlen=200),  # rolling tail of stdout/stderr lines
    "exit_code": None,    # last completed run's exit code
    "reader": None,       # background thread draining the pipe
}


def _drain_tagger_output(proc, buf):
    """Forward subprocess output to parent stdout AND a rolling buffer."""
    try:
        for line in iter(proc.stdout.readline, ""):
            if not line:
                break
            line = line.rstrip("\n")
            buf.append(line)
            print(f"[tagger] {line}", flush=True)
    except Exception as e:
        buf.append(f"[reader error] {e}")
    finally:
        try:
            proc.stdout.close()
        except Exception:
            pass


class TaggerRequest(BaseModel):
    model: str = "qwen3-vl:8b"
    api_url: str = "http://localhost:11434"
    batch_size: Optional[int] = None
    movie_id: Optional[int] = None


# ── Tagger Endpoints ──────────────────────────

@app.post("/api/tagger/start")
async def start_tagger(req: TaggerRequest):
    """Start the tagger as a background subprocess."""
    if tagger_process["proc"] is not None and tagger_process["proc"].poll() is None:
        raise HTTPException(400, "Tagger already running")

    db_path = DB_PATH
    script_path = Path(__file__).parent / "tagger.py"

    cmd = [
        sys.executable, str(script_path),
        "--db", db_path,
        "--model", req.model,
        "--api-url", req.api_url,
    ]
    if req.batch_size:
        cmd.extend(["--batch", str(req.batch_size)])
    if req.movie_id:
        cmd.extend(["--movie-id", str(req.movie_id)])

    # Reset state from any prior run
    tagger_process["log"].clear()
    tagger_process["exit_code"] = None

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # line-buffered so the UI gets output promptly
        )
    except Exception as e:
        raise HTTPException(500, f"Failed to launch tagger: {e}")

    tagger_process["proc"] = proc
    reader = threading.Thread(
        target=_drain_tagger_output,
        args=(proc, tagger_process["log"]),
        daemon=True,
    )
    reader.start()
    tagger_process["reader"] = reader

    # Brief sleep so we can catch instant-fail crashes (e.g. missing model)
    # and surface them in the response instead of returning a phantom "started".
    await asyncio.sleep(0.4)
    if proc.poll() is not None:
        # Give the reader a moment to flush remaining output
        reader.join(timeout=0.5)
        tagger_process["exit_code"] = proc.returncode
        tagger_process["proc"] = None
        tail = "\n".join(list(tagger_process["log"])[-30:])
        raise HTTPException(
            500,
            f"Tagger exited immediately (code {proc.returncode}). Output:\n{tail or '(no output)'}",
        )

    return {"status": "started", "pid": proc.pid, "model": req.model}


@app.post("/api/tagger/stop")
async def stop_tagger():
    """Kill the tagger: SIGTERM first, escalate to SIGKILL if it doesn't die."""
    proc = tagger_process.get("proc")
    if proc is None or proc.poll() is not None:
        return {"status": "not_running"}

    pid = proc.pid
    proc.terminate()
    # Give it 2 seconds to clean up (DB commits, status flush, VRAM unload)
    for _ in range(20):
        await asyncio.sleep(0.1)
        if proc.poll() is not None:
            return {"status": "stopped", "pid": pid, "exit_code": proc.returncode, "method": "SIGTERM"}

    # Still alive — hard kill
    proc.kill()
    await asyncio.sleep(0.2)
    return {"status": "killed", "pid": pid, "exit_code": proc.returncode, "method": "SIGKILL"}


@app.get("/api/tagger/status")
async def tagger_status():
    """Get tagger status from the status file + process state."""
    db_path = DB_PATH
    status_path = Path(db_path).parent / "tagger_status.json"

    status = {}
    if status_path.exists():
        try:
            with open(status_path) as f:
                status = json.load(f)
        except Exception:
            pass

    # Check if process is actually running
    proc = tagger_process.get("proc")
    if proc is not None:
        if proc.poll() is None:
            status["process_running"] = True
            status["pid"] = proc.pid
        else:
            status["process_running"] = False
            tagger_process["exit_code"] = proc.returncode
            tagger_process["proc"] = None
    else:
        status["process_running"] = False

    # Always include the rolling log + last exit code so the UI can show
    # something meaningful when a run dies (e.g. missing Ollama model).
    status["log_tail"] = list(tagger_process["log"])[-40:]
    status["exit_code"] = tagger_process["exit_code"]

    return status


@app.get("/api/tagger/stats")
async def tagger_stats(model: str = "qwen3-vl:8b"):
    """Get tagging progress statistics."""
    from tagger import get_tag_stats
    db_path = DB_PATH
    return get_tag_stats(db_path, model)


# ── Tag Search / Browse Endpoints ─────────────

@app.get("/api/tags/search")
async def search_tags(q: str = "", limit: int = 50):
    """Search available tags with counts."""
    with get_db() as conn:
        if q:
            rows = conn.execute(
                """SELECT tag, COUNT(*) as count 
                   FROM image_tags 
                   WHERE tag LIKE ?
                   GROUP BY tag 
                   ORDER BY count DESC 
                   LIMIT ?""",
                (f"%{q}%", limit)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT tag, COUNT(*) as count 
                   FROM image_tags 
                   GROUP BY tag 
                   ORDER BY count DESC 
                   LIMIT ?""",
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


@app.get("/api/tags/top")
async def top_tags(limit: int = 100):
    """Get the most common tags."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT tag, COUNT(*) as count 
               FROM image_tags 
               GROUP BY tag 
               ORDER BY count DESC 
               LIMIT ?""",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


@app.post("/api/images/filter-by-tags")
async def filter_images_by_tags(
    include_tags: list[str] = [],
    exclude_tags: list[str] = [],
    count: int = 24,
):
    """Get random images that have specific tags (and don't have excluded tags)."""
    with get_db() as conn:
        if not include_tags and not exclude_tags:
            raise HTTPException(400, "Provide at least one include or exclude tag")

        conditions = []
        params = []

        # Images must have ALL include tags
        if include_tags:
            for tag in include_tags:
                conditions.append(
                    """i.id IN (
                        SELECT image_id FROM image_tags WHERE tag LIKE ?
                    )"""
                )
                params.append(f"%{tag}%")

        # Images must NOT have any exclude tags
        if exclude_tags:
            for tag in exclude_tags:
                conditions.append(
                    """i.id NOT IN (
                        SELECT image_id FROM image_tags WHERE tag LIKE ?
                    )"""
                )
                params.append(f"%{tag}%")

        where = " AND ".join(conditions)
        params.append(count)

        rows = conn.execute(
            f"""SELECT i.*, m.title as movie_title, m.year as movie_year,
                       m.aspect_ratio_group
                FROM images i
                JOIN movies m ON i.movie_id = m.id
                WHERE {where}
                ORDER BY RANDOM()
                LIMIT ?""",
            params
        ).fetchall()

        return [dict(r) for r in rows]


# ──────────────────────────────────────────────
# Run
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8042)
