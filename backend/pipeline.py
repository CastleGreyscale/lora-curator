"""
Pipeline orchestrator for the LoRA training workflow.
Steps: Export selected images → Tag with Ollama → Cache VAE/TE → Train LoRA

Each step is either in-process (export, tag) or a subprocess (cache, train).
Status is tracked in a global dict that the API polls.
"""

import os
import sys
import json
import shutil
import time
import base64
import signal
import threading
import subprocess
import requests
import re
import zipfile
from pathlib import Path
from datetime import datetime
from typing import Optional
from database import get_db
import selections

# ──────────────────────────────────────────────
# Environment / Paths
# ──────────────────────────────────────────────

# Load from .env file if it exists (so Fish env vars don't need to propagate)
_env_file = Path(__file__).parent / ".env"
_env_overrides = {}
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            _env_overrides[k.strip()] = v.strip().strip('"').strip("'")

def _env(name, fallback=""):
    # Check .env overrides first, then os.environ, then fallback
    return _env_overrides.get(name, os.environ.get(name, fallback))

def get_projects_root():
    return Path(_env("LORA_PROJECTS_ROOT", "/home/brad/ai/training/lora_projects"))

def get_models_root():
    return Path(_env("COMFYUI_MODELS_ROOT", ""))

def get_musubi_root():
    return Path(_env("MUSUBI_TUNER_ROOT", ""))

# ──────────────────────────────────────────────
# Global status tracking
# ──────────────────────────────────────────────

status = {
    "project_name": None,
    "project_dir": None,
    "step": None,          # current step name or None
    "running": False,
    "steps": {
        "export":   {"status": "pending", "detail": ""},
        "tag":      {"status": "pending", "detail": "", "progress": 0, "total": 0},
        "cache_vae": {"status": "pending", "detail": ""},
        "cache_te":  {"status": "pending", "detail": ""},
        "train":    {"status": "pending", "detail": ""},
    },
    "log_lines": [],       # last N lines of output
    "loss_data": [],       # [{step, loss}] parsed from tqdm during training
}

_EPOCH_RE = re.compile(r'\bepoch\s+(\d+)/\d+', re.IGNORECASE)
_LOSS_RE = re.compile(r'avr_loss=([\d.eE+\-]+)')
_TQDM_LOSS_RE = re.compile(r'(\d+)/\d+.*?avr_loss=([\d.eE+\-]+)')

_current_proc = None       # subprocess.Popen for cache/train
_current_thread = None     # threading.Thread for tag
_stop_flag = False

LOG_MAX = 200

def _log(msg):
    status["log_lines"].append(msg)
    if len(status["log_lines"]) > LOG_MAX:
        status["log_lines"] = status["log_lines"][-LOG_MAX:]

def _set_step(step, st, detail=""):
    status["steps"][step]["status"] = st
    status["steps"][step]["detail"] = detail
    if st == "running":
        status["step"] = step
        status["running"] = True
    elif st in ("done", "error"):
        if status["step"] == step:
            status["step"] = None
            status["running"] = False

def get_status():
    return {**status, "_proc_alive": _current_proc is not None and _current_proc.poll() is None}

def reset_status(project_name=None, project_dir=None):
    status["project_name"] = project_name
    status["project_dir"] = str(project_dir) if project_dir else None
    status["step"] = None
    status["running"] = False
    status["log_lines"] = []
    status["loss_data"] = []
    for s in status["steps"].values():
        s["status"] = "pending"
        s["detail"] = ""
        if "progress" in s:
            s["progress"] = 0
            s["total"] = 0

def stop_current():
    global _stop_flag, _current_proc
    _stop_flag = True
    if _current_proc and _current_proc.poll() is None:
        _current_proc.send_signal(signal.SIGINT)
        return True
    return _stop_flag


# ──────────────────────────────────────────────
# Step 1: Export selected images
# ──────────────────────────────────────────────

def create_project(
    name: str,
    description: str = "",
    trigger_word: str = "",
    tagging_prompt: str = "",
    tagging_model: str = "qwen2.5vl:32b ",
    learning_rate: str = "5e-5",
    network_dim: int = 32,
    network_alpha: int = 16,
    max_epochs: int = 16,
    save_every_n_epochs: int = 2,
    resolution: int = 1024,
    enable_samples: bool = False,
    sample_prompts: list = None,
    dit_model: str = "qwen_image_bf16.safetensors",
) -> dict:
    """Create project dir, copy selected images, write project.toml."""
    global _stop_flag
    _stop_flag = False

    projects_root = get_projects_root()

    # Validate paths before doing anything
    if not projects_root or str(projects_root) in ("", ".", "/"):
        return {"error": f"LORA_PROJECTS_ROOT not set or invalid: '{projects_root}'. Create a backend/.env file with LORA_PROJECTS_ROOT=/path/to/your/projects"}
    if not projects_root.parent.exists():
        return {"error": f"Parent directory does not exist: {projects_root.parent}. Check LORA_PROJECTS_ROOT."}

    project_dir = projects_root / name
    dataset_dir = project_dir / "dataset"
    cache_dir = project_dir / "cache_directory"

    reset_status(name, project_dir)
    _set_step("export", "running", "Creating project directory...")
    _log(f"Creating project: {name}")

    # Create directories
    dataset_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Get selected image IDs and copy files
    image_ids = selections.get_all_selected_image_ids()
    if not image_ids:
        _set_step("export", "error", "No images selected")
        return {"error": "No images selected in the curator"}

    _log(f"Exporting {len(image_ids)} images...")
    status["steps"]["export"]["detail"] = f"Copying {len(image_ids)} images..."

    copied = 0
    errors = 0
    with get_db() as conn:
        for i, img_id in enumerate(image_ids):
            if _stop_flag:
                _set_step("export", "error", f"Stopped at {copied} images")
                return {"error": "Stopped by user"}

            row = conn.execute("SELECT filepath, filename FROM images WHERE id = ?", (img_id,)).fetchone()
            if not row:
                errors += 1
                continue

            src = Path(row["filepath"])
            dest = dataset_dir / row["filename"]

            # Handle dupes
            if dest.exists():
                stem, suffix = dest.stem, dest.suffix
                c = 1
                while dest.exists():
                    dest = dataset_dir / f"{stem}_{c}{suffix}"
                    c += 1

            try:
                shutil.copy2(src, dest)
                copied += 1
            except Exception as e:
                errors += 1
                _log(f"  Error copying {src.name}: {e}")

            if (i + 1) % 100 == 0:
                status["steps"]["export"]["detail"] = f"Copied {copied}/{len(image_ids)} images..."

    _log(f"Exported {copied} images ({errors} errors)")

    # Write project.toml
    _log("Writing project.toml...")
    _write_project_toml(
        project_dir, name, description, trigger_word, tagging_prompt, tagging_model,
        learning_rate, network_dim, network_alpha, max_epochs, save_every_n_epochs, resolution,
        enable_samples, sample_prompts or [], dit_model=dit_model,
    )

    # Save selection manifest
    manifest = {
        "created_at": datetime.now().isoformat(),
        "image_count": copied,
        "selection_summary": selections.get_selection_summary(),
    }
    (project_dir / "export_manifest.json").write_text(json.dumps(manifest, indent=2))

    _set_step("export", "done", f"{copied} images exported")
    return {"project_dir": str(project_dir), "images_exported": copied, "errors": errors}


def create_project_from_path(
    source_path: str,
    name: str,
    description: str = "",
    trigger_word: str = "",
    tagging_prompt: str = "",
    tagging_model: str = "qwen2.5vl:32b",
    learning_rate: str = "5e-5",
    network_dim: int = 32,
    network_alpha: int = 16,
    max_epochs: int = 16,
    save_every_n_epochs: int = 2,
    resolution: int = 1024,
    enable_samples: bool = False,
    sample_prompts: list = None,
    dit_model: str = "qwen_image_bf16.safetensors",
) -> dict:
    """Create project from an existing directory of images (bypasses Browse selection)."""
    global _stop_flag
    _stop_flag = False

    source_dir = Path(source_path)
    if not source_dir.exists() or not source_dir.is_dir():
        return {"error": f"Source path does not exist or is not a directory: {source_path}"}

    projects_root = get_projects_root()
    if not projects_root or str(projects_root) in ("", ".", "/"):
        return {"error": f"LORA_PROJECTS_ROOT not set or invalid: '{projects_root}'"}
    if not projects_root.parent.exists():
        return {"error": f"Parent directory does not exist: {projects_root.parent}"}

    project_dir = projects_root / name
    dataset_dir = project_dir / "dataset"
    cache_dir = project_dir / "cache_directory"

    reset_status(name, project_dir)
    _set_step("export", "running", "Creating project directory...")
    _log(f"Creating project from path: {source_path}")

    dataset_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    image_exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}
    source_images = sorted([f for f in source_dir.iterdir() if f.is_file() and f.suffix.lower() in image_exts])

    if not source_images:
        _set_step("export", "error", "No images found in source path")
        return {"error": f"No images found in {source_path}"}

    _log(f"Found {len(source_images)} images in source directory")
    status["steps"]["export"]["detail"] = f"Copying {len(source_images)} images..."

    copied = 0
    captions_copied = 0
    errors = 0

    for i, src in enumerate(source_images):
        if _stop_flag:
            _set_step("export", "error", f"Stopped at {copied} images")
            return {"error": "Stopped by user"}

        dest = dataset_dir / src.name
        if dest.exists():
            stem, suffix = dest.stem, dest.suffix
            c = 1
            while dest.exists():
                dest = dataset_dir / f"{stem}_{c}{suffix}"
                c += 1

        try:
            shutil.copy2(src, dest)
            copied += 1

            # Copy paired caption file if it exists
            caption_src = src.with_suffix(".txt")
            if caption_src.exists():
                shutil.copy2(caption_src, dest.with_suffix(".txt"))
                captions_copied += 1
        except Exception as e:
            errors += 1
            _log(f"  Error copying {src.name}: {e}")

        if (i + 1) % 100 == 0:
            status["steps"]["export"]["detail"] = f"Copied {copied}/{len(source_images)} images..."

    _log(f"Copied {copied} images, {captions_copied} captions ({errors} errors)")

    _write_project_toml(
        project_dir, name, description, trigger_word, tagging_prompt, tagging_model,
        learning_rate, network_dim, network_alpha, max_epochs, save_every_n_epochs, resolution,
        enable_samples, sample_prompts or [], dit_model=dit_model,
    )

    manifest = {
        "created_at": datetime.now().isoformat(),
        "image_count": copied,
        "source": "external_path",
        "source_path": str(source_dir),
        "captions_copied": captions_copied,
    }
    (project_dir / "export_manifest.json").write_text(json.dumps(manifest, indent=2))

    _set_step("export", "done", f"{copied} images from external path")

    # If all images already have captions, mark tag step as done too
    if captions_copied >= copied * 0.9 and copied > 0:
        _set_step("tag", "done", f"{captions_copied} captions pre-existing")
        _log("Captions found for all images — tagging step pre-marked as done")

    return {
        "project_dir": str(project_dir),
        "images_exported": copied,
        "captions_copied": captions_copied,
        "errors": errors,
    }


def _write_project_toml(project_dir, name, description, trigger_word, tagging_prompt,
                         tagging_model, lr, rank, network_alpha, epochs, save_every, resolution,
                         enable_samples, sample_prompts, dit_model="qwen_image_bf16.safetensors"):
    """Generate project.toml with user settings + sensible defaults."""

    models_root = str(get_models_root()) or "${COMFYUI_MODELS_ROOT}"
    projects_root = str(get_projects_root()) or "${LORA_PROJECTS_ROOT}"
    musubi_root = str(get_musubi_root()) or "${MUSUBI_TUNER_ROOT}"

    # Build TOML manually line by line for reliability
    lines = [
        "# Auto-generated by LoRA Dataset Curator",
        f"# {datetime.now().isoformat()}",
        "",
        "[project]",
        f'name = "{name}"',
        f'description = "{description}"',
        "",
        "[paths]",
        f'models_root = "{models_root}"',
        f'projects_root = "{projects_root}"',
        f'musubi_tuner_root = "{musubi_root}"',
        'dataset_dir = "./dataset"',
        'cache_dir = "./cache_directory"',
        "",
        "[tagging]",
        f'model = "{tagging_model}"',
        'api_url = "http://localhost:11434"',
        "temperature = 0.3",
        'image_extensions = [".jpg", ".jpeg", ".png", ".webp"]',
        f'trigger_word = "{trigger_word}"',
        "overwrite_existing = false",
    ]

    # Write prompt as multi-line literal string (TOML uses ''' for literal multi-line)
    # Escape any single quotes in the prompt
    safe_prompt = tagging_prompt.replace("\\", "\\\\")
    lines.append("prompt = '''")
    lines.append(safe_prompt)
    lines.append("'''")
    lines.append("")

    lines += [
        "[training]",
        f'learning_rate = "{lr}"',
        f"network_dim = {rank}",
        f"network_alpha = {network_alpha}",
        f"max_epochs = {epochs}",
        f"save_every_n_epochs = {save_every}",
        "seed = 42",
        "blocks_to_swap = 16",
        'fp8_mode = "fp8_base"',
        'optimizer = "adamw8bit"',
        'mixed_precision = "bf16"',
        "max_workers = 2",
        "discrete_flow_shift = 2.2",
        "",
        "[training.models]",
        f'dit_model = "{dit_model}"',
        'vae_model = "diffusion_pytorch_model.safetensors"',
        'text_encoder = "qwen_2.5_vl_7b.safetensors"',
        "",
        "[training.advanced]",
    ]

    if enable_samples and sample_prompts:
        lines.append("enable_sample_prompts = true")
        lines.append(f"sample_every_n_epochs = {save_every}")
        lines.append("sample_at_first = true")
        prompts_str = ", ".join(f'"{p}"' for p in sample_prompts)
        lines.append(f"sample_prompts = [{prompts_str}]")
    else:
        lines.append("enable_sample_prompts = false")

    lines += [
        "save_state = true",
        "save_state_on_train_end = false",
        "cache_text_encoder_outputs = true",
        "cache_latents = true",
        "persistent_data_loader_workers = true",
        "gradient_accumulation_steps = 1",
        "full_bf16 = false",
        'logging_dir = "./logs"',
        'log_with = "tensorboard"',
        f'log_prefix = "{trigger_word or name}"',
        "",
        "[dataset]",
        "shuffle_caption = false",
        'caption_extension = ".txt"',
        "caption_dropout_rate = 0.0",
        f"resolution = {resolution}",
        "batch_size = 1",
        "num_repeats = 1",
        "enable_bucket = true",
        "bucket_no_upscale = true",
    ]

    (project_dir / "project.toml").write_text("\n".join(lines) + "\n")


def _write_dataset_toml(project_dir, name, resolution=1024):
    """Write the musubi-tuner dataset config TOML."""
    dataset_dir = project_dir / "dataset"
    cache_dir = project_dir / "cache_directory"
    config_path = project_dir / f"{name}.toml"

    content = f'''[general]
caption_extension = ".txt"
enable_bucket = true
bucket_no_upscale = true

[[datasets]]
image_directory = "{dataset_dir}"
cache_directory = "{cache_dir}"
resolution = {resolution}
batch_size = 1
num_repeats = 1
'''
    config_path.write_text(content)
    return config_path


# ──────────────────────────────────────────────
# Step 2: Tag images with Ollama
# ──────────────────────────────────────────────

def start_tagging(project_dir: str):
    """Start tagging in a background thread."""
    global _current_thread, _stop_flag
    _stop_flag = False

    project_dir = Path(project_dir)
    if not project_dir.exists():
        return {"error": "Project directory not found"}

    # Read config
    try:
        config = _read_toml(project_dir / "project.toml")
    except Exception as e:
        _log(f"WARNING: Could not parse project.toml: {e}. Using defaults.")
        config = {}
    tagging = config.get("tagging", {})
    model = tagging.get("model", "qwen2.5vl:32b  ")
    api_url = tagging.get("api_url", "http://localhost:11434")
    prompt = tagging.get("prompt", "Describe this image in detail.")
    trigger_word = tagging.get("trigger_word", "")
    overwrite = tagging.get("overwrite_existing", False)

    # Always use standard image extensions — don't rely on TOML parsing
    extensions = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}

    dataset_dir = project_dir / "dataset"
    if not dataset_dir.exists():
        _set_step("tag", "error", f"Dataset directory not found: {dataset_dir}")
        return {"error": f"Dataset directory not found: {dataset_dir}"}

    # Scan for images (case-insensitive)
    images = sorted([f for f in dataset_dir.iterdir() if f.is_file() and f.suffix.lower() in extensions])
    _log(f"Scanned {dataset_dir}: found {len(images)} images (of {len(list(dataset_dir.iterdir()))} total files)")

    if not images:
        # Extra debug: list what IS in the directory
        sample_files = [f.name for f in list(dataset_dir.iterdir())[:10]]
        _log(f"  Sample files: {sample_files}")
        _set_step("tag", "error", f"No images found in {dataset_dir}")
        return {"error": f"No images in dataset directory. Files found: {sample_files}"}

    # Check Ollama
    try:
        requests.get(f"{api_url}/api/tags", timeout=5).raise_for_status()
    except Exception:
        _set_step("tag", "error", "Cannot connect to Ollama")
        return {"error": f"Cannot connect to Ollama at {api_url}"}

    status["steps"]["tag"]["total"] = len(images)
    status["steps"]["tag"]["progress"] = 0

    def _tag_worker():
        global _stop_flag
        _set_step("tag", "running", "Starting...")
        tagged = 0
        skipped = 0
        failed = 0

        for i, img_path in enumerate(images):
            if _stop_flag:
                _set_step("tag", "error", f"Stopped at {tagged}/{len(images)}")
                _log(f"Tagging stopped. Tagged: {tagged}, Skipped: {skipped}, Failed: {failed}")
                return

            caption_path = img_path.with_suffix(".txt")
            if caption_path.exists() and not overwrite:
                skipped += 1
                status["steps"]["tag"]["progress"] = i + 1
                continue

            # Encode image once
            try:
                with open(img_path, "rb") as f:
                    img_b64 = base64.b64encode(f.read()).decode("utf-8")
            except Exception as e:
                failed += 1
                _log(f"  Can't read {img_path.name}: {e}")
                continue

            # Call Ollama — simple /api/generate (proven pattern from tag_images)
            caption = None
            try:
                resp = requests.post(
                    f"{api_url}/api/generate",
                    json={
                        "model": model,
                        "prompt": prompt,
                        "images": [img_b64],
                        "stream": False,
                        "options": {"temperature": 0.3},
                    },
                    timeout=120,
                )
                resp.raise_for_status()
                caption = resp.json().get("response", "").strip()
            except Exception as e:
                if failed <= 5:
                    _log(f"  API Error on {img_path.name}: {e}")
                failed += 1

            if caption:
                if trigger_word:
                    caption = f"{trigger_word} {caption}"
                caption_path.write_text(caption, encoding="utf-8")
                tagged += 1
            else:
                failed += 1

            status["steps"]["tag"]["progress"] = i + 1
            status["steps"]["tag"]["detail"] = f"{tagged} tagged, {skipped} skipped, {failed} failed ({i+1}/{len(images)})"

            if (i + 1) % 10 == 0:
                _log(f"Tag progress: {i+1}/{len(images)} ({tagged} tagged)")

        _set_step("tag", "done", f"{tagged} tagged, {skipped} skipped, {failed} failed")
        _log(f"Tagging complete. Tagged: {tagged}, Skipped: {skipped}, Failed: {failed}")

    _current_thread = threading.Thread(target=_tag_worker, daemon=True)
    _current_thread.start()
    return {"started": True, "total_images": len(images)}


# ──────────────────────────────────────────────
# Step 3: Cache VAE + Text Encoder
# ──────────────────────────────────────────────

def start_cache(project_dir: str, cache_type: str = "both"):
    """Run VAE and/or text encoder caching as subprocess."""
    global _current_proc, _stop_flag
    _stop_flag = False

    project_dir = Path(project_dir)
    config = _read_toml(project_dir / "project.toml")
    name = config.get("project", {}).get("name", "project")

    models_root = Path(config.get("paths", {}).get("models_root", str(get_models_root())))
    musubi_root = Path(config.get("paths", {}).get("musubi_tuner_root", str(get_musubi_root())))

    if not musubi_root.exists():
        msg = f"Musubi-tuner not found: {musubi_root}"
        _set_step("cache_vae", "error", msg)
        return {"error": msg}

    # Write dataset config for musubi-tuner
    dataset_config = _write_dataset_toml(project_dir, name,
        config.get("dataset", {}).get("resolution", 1024))

    models = config.get("training", {}).get("models", {})
    vae_path = models_root / "vae" / models.get("vae_model", "diffusion_pytorch_model.safetensors")
    te_path = models_root / "text_encoders" / models.get("text_encoder", "qwen_2.5_vl_7b.safetensors")

    steps_to_run = []
    if cache_type in ("both", "vae"):
        steps_to_run.append(("cache_vae", vae_path, "qwen_image_cache_latents.py", [
            "--dataset_config", str(dataset_config), "--vae", str(vae_path)
        ]))
    if cache_type in ("both", "te"):
        steps_to_run.append(("cache_te", te_path, "qwen_image_cache_text_encoder_outputs.py", [
            "--dataset_config", str(dataset_config), "--text_encoder", str(te_path),
            "--batch_size", "1", "--num_workers", "1"
        ]))

    def _cache_worker():
        global _current_proc
        for step_name, model_path, script_name, args in steps_to_run:
            if _stop_flag:
                _set_step(step_name, "error", "Stopped")
                return

            script = musubi_root / "src" / "musubi_tuner" / script_name
            if not script.exists():
                _set_step(step_name, "error", f"Script not found: {script}")
                _log(f"Missing: {script}")
                continue

            if not model_path.exists():
                _set_step(step_name, "error", f"Model not found: {model_path}")
                _log(f"Missing model: {model_path}")
                continue

            _set_step(step_name, "running", f"Running {script_name}...")
            _log(f"Starting {step_name}: {script_name}")

            env = {**os.environ, "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"}
            cmd = [sys.executable, str(script)] + args

            try:
                _current_proc = subprocess.Popen(
                    cmd, cwd=str(musubi_root), env=env,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                )
                for line in _current_proc.stdout:
                    line = line.rstrip()
                    if line:
                        _log(line)
                _current_proc.wait()

                if _current_proc.returncode == 0:
                    _set_step(step_name, "done", "Complete")
                    _log(f"{step_name} finished successfully")
                else:
                    _set_step(step_name, "error", f"Exit code {_current_proc.returncode}")
                    _log(f"{step_name} failed with exit code {_current_proc.returncode}")
            except Exception as e:
                _set_step(step_name, "error", str(e))
                _log(f"{step_name} error: {e}")
            finally:
                _current_proc = None

            # Flush VRAM between cache steps
            _log("Flushing VRAM...")
            _flush_vram()

    t = threading.Thread(target=_cache_worker, daemon=True)
    t.start()
    return {"started": True, "steps": [s[0] for s in steps_to_run]}


# ──────────────────────────────────────────────
# Step 4: Train LoRA
# ──────────────────────────────────────────────

def start_training(project_dir: str):
    """Run LoRA training as subprocess."""
    global _current_proc, _stop_flag
    _stop_flag = False

    project_dir = Path(project_dir)
    config = _read_toml(project_dir / "project.toml")
    name = config.get("project", {}).get("name", "project")
    training = config.get("training", {})
    advanced = training.get("advanced", {})
    models_cfg = training.get("models", {})

    models_root = Path(config.get("paths", {}).get("models_root", str(get_models_root())))
    musubi_root = Path(config.get("paths", {}).get("musubi_tuner_root", str(get_musubi_root())))

    if not musubi_root.exists():
        _set_step("train", "error", f"Musubi-tuner not found: {musubi_root}")
        return {"error": f"Musubi-tuner not found: {musubi_root}"}

    # Write dataset config
    resolution = config.get("dataset", {}).get("resolution", 1024)
    dataset_config = _write_dataset_toml(project_dir, name, resolution)

    # Model paths
    dit_path = models_root / "checkpoints" / models_cfg.get("dit_model", "qwen_image_bf16.safetensors")
    vae_path = models_root / "vae" / models_cfg.get("vae_model", "diffusion_pytorch_model.safetensors")
    te_path = models_root / "text_encoders" / models_cfg.get("text_encoder", "qwen_2.5_vl_7b.safetensors")
    output_dir = models_root / "loras"

    for p, label in [(dit_path, "DIT"), (vae_path, "VAE"), (te_path, "Text Encoder")]:
        if not p.exists():
            _set_step("train", "error", f"{label} model not found: {p}")
            return {"error": f"{label} not found: {p}"}

    output_dir.mkdir(parents=True, exist_ok=True)

    script = musubi_root / "src" / "musubi_tuner" / "qwen_image_train_network.py"
    if not script.exists():
        _set_step("train", "error", f"Training script not found: {script}")
        return {"error": f"Script not found: {script}"}

    # Build command
    cmd = [
        "accelerate", "launch",
        "--num_cpu_threads_per_process", "1",
        "--mixed_precision", training.get("mixed_precision", "bf16"),
        str(script),
        "--dit", str(dit_path),
        "--vae", str(vae_path),
        "--text_encoder", str(te_path),
        "--dataset_config", str(dataset_config),
        "--sdpa",
        "--mixed_precision", training.get("mixed_precision", "bf16"),
        "--timestep_sampling", "shift",
        "--weighting_scheme", "none",
        "--discrete_flow_shift", str(training.get("discrete_flow_shift", 2.2)),
        "--optimizer_type", training.get("optimizer", "adamw8bit"),
        "--learning_rate", str(training.get("learning_rate", "5e-5")),
        "--gradient_checkpointing",
        "--max_data_loader_n_workers", str(training.get("max_workers", 2)),
        "--network_module", "networks.lora_qwen_image",
        "--network_dim", str(training.get("network_dim", 32)),
        "--network_alpha", str(training.get("network_alpha", 16)),
        "--blocks_to_swap", str(training.get("blocks_to_swap", 16)),
        f"--{training.get('fp8_mode', 'fp8_base')}",
        "--max_train_epochs", str(training.get("max_epochs", 16)),
        "--save_every_n_epochs", str(training.get("save_every_n_epochs", 2)),
        "--seed", str(training.get("seed", 42)),
        "--output_dir", str(output_dir),
        "--output_name", name,
    ]

    if advanced.get("save_state", True):
        cmd.append("--save_state")
    if advanced.get("persistent_data_loader_workers", True):
        cmd.append("--persistent_data_loader_workers")

    # Sample prompts
    if advanced.get("enable_sample_prompts"):
        prompts = advanced.get("sample_prompts", [])
        if prompts:
            prompts_file = project_dir / "sample_prompts.txt"
            prompts_file.write_text("\n".join(prompts))
            cmd.extend(["--sample_prompts", str(prompts_file)])
            se = advanced.get("sample_every_n_epochs", 0)
            if se > 0:
                cmd.extend(["--sample_every_n_epochs", str(se)])
            if advanced.get("sample_at_first"):
                cmd.append("--sample_at_first")

    # Logging
    log_dir = advanced.get("logging_dir", "")
    if log_dir:
        cmd.extend(["--logging_dir", str(project_dir / log_dir.lstrip("./"))])
    log_with = advanced.get("log_with", "")
    if log_with:
        cmd.extend(["--log_with", log_with])
    log_prefix = advanced.get("log_prefix", "")
    if log_prefix:
        cmd.extend(["--log_prefix", log_prefix])

    _set_step("train", "running", "Flushing VRAM before training...")
    _flush_vram()
    _log(f"Starting training: {name}")
    _log(f"Output: {output_dir}")
    _log(f"Command: {' '.join(cmd[:8])}...")

    def _train_worker():
        global _current_proc
        env = {**os.environ, "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"}
        try:
            _current_proc = subprocess.Popen(
                cmd, cwd=str(musubi_root), env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            for line in _current_proc.stdout:
                line = line.rstrip()
                if line:
                    _log(line)
                    # Parse loss from tqdm set_postfix output
                    m = _TQDM_LOSS_RE.search(line)
                    if m:
                        try:
                            status["loss_data"].append({
                                "step": int(m.group(1)),
                                "loss": round(float(m.group(2)), 6),
                            })
                        except (ValueError, IndexError):
                            pass
                    # Try to parse epoch progress
                    if "epoch" in line.lower():
                        status["steps"]["train"]["detail"] = line[:120]
            _current_proc.wait()

            if _current_proc.returncode == 0:
                _log("Training finished successfully!")

                convert_script = musubi_root / "convert_lora.py"
                _set_step("train", "running", "Converting LoRA checkpoints...")

                # Find all checkpoint safetensors for this run (final + incremental, skip _diff outputs)
                all_tensors = sorted(output_dir.glob(f"{name}*.safetensors"))
                source_tensors = [p for p in all_tensors if not p.stem.endswith("_diff")]

                converted = []
                if not convert_script.exists():
                    _log(f"WARNING: convert_lora.py not found at {convert_script}, skipping conversion")
                else:
                    for input_lora in source_tensors:
                        output_lora = input_lora.with_stem(input_lora.stem + "_diff")
                        _log(f"Converting {input_lora.name} → {output_lora.name}")
                        try:
                            convert_proc = subprocess.run(
                                [sys.executable, str(convert_script),
                                 "--input", str(input_lora),
                                 "--output", str(output_lora),
                                 "--target", "other"],
                                cwd=str(musubi_root), env=env,
                                capture_output=True, text=True, timeout=300,
                            )
                            if convert_proc.returncode == 0:
                                _log(f"  Converted: {output_lora.name}")
                                converted.append(output_lora)
                            else:
                                _log(f"  Conversion failed: {convert_proc.stderr[:200]}")
                        except Exception as ce:
                            _log(f"  Conversion error: {ce}")

                # Zip original safetensors + state directories
                _set_step("train", "running", "Archiving training files...")
                zip_path = output_dir / f"{name}_archive.zip"
                items_to_zip = list(source_tensors) + sorted(output_dir.glob(f"{name}*-state"))
                if items_to_zip:
                    _log(f"Archiving {len(items_to_zip)} items → {zip_path.name}")
                    try:
                        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                            for item in items_to_zip:
                                if item.is_file():
                                    zf.write(item, item.name)
                                elif item.is_dir():
                                    for f in sorted(item.rglob("*")):
                                        if f.is_file():
                                            zf.write(f, f.relative_to(output_dir))
                        _log(f"Archive created: {zip_path.name}")
                        for item in items_to_zip:
                            if item.is_file():
                                item.unlink()
                            elif item.is_dir():
                                shutil.rmtree(item)
                        _log(f"Deleted {len(items_to_zip)} archived items")
                    except Exception as ze:
                        _log(f"Archive error: {ze}")

                _set_step("train", "done", "Training + conversion complete!")
                _log(f"Done! Converted {len(converted)} LoRA(s) in {output_dir}")
            else:
                _set_step("train", "error", f"Exit code {_current_proc.returncode}")
                _log(f"Training failed with exit code {_current_proc.returncode}")
        except Exception as e:
            _set_step("train", "error", str(e))
            _log(f"Training error: {e}")
        finally:
            _current_proc = None

    t = threading.Thread(target=_train_worker, daemon=True)
    t.start()
    return {"started": True, "output_dir": str(output_dir)}


# ──────────────────────────────────────────────
# Project config read/write
# ──────────────────────────────────────────────

def read_project_config(project_dir) -> dict:
    """Read project.toml and return form-friendly dict."""
    config = _read_toml(Path(project_dir) / "project.toml")
    tagging = config.get("tagging", {})
    training = config.get("training", {})
    models = training.get("models", {})
    advanced = training.get("advanced", {})
    dataset = config.get("dataset", {})
    return {
        "name": config.get("project", {}).get("name", ""),
        "description": config.get("project", {}).get("description", ""),
        "trigger_word": tagging.get("trigger_word", ""),
        "tagging_prompt": tagging.get("prompt", ""),
        "tagging_model": tagging.get("model", "qwen2.5vl:32b"),
        "learning_rate": str(training.get("learning_rate", "5e-5")),
        "network_dim": int(training.get("network_dim", 32)),
        "network_alpha": int(training.get("network_alpha", 16)),
        "max_epochs": int(training.get("max_epochs", 16)),
        "save_every_n_epochs": int(training.get("save_every_n_epochs", 2)),
        "resolution": int(dataset.get("resolution", 1024)),
        "dit_model": models.get("dit_model", "qwen_image_bf16.safetensors"),
        "enable_samples": bool(advanced.get("enable_sample_prompts", False)),
        "sample_prompts": advanced.get("sample_prompts", []),
    }


def update_project_config(project_dir, name, description, trigger_word, tagging_prompt,
                           tagging_model, learning_rate, network_dim, network_alpha,
                           max_epochs, save_every_n_epochs, resolution, enable_samples,
                           sample_prompts, dit_model):
    """Rewrite project.toml with updated params, preserving structure."""
    _write_project_toml(
        Path(project_dir), name, description, trigger_word, tagging_prompt, tagging_model,
        learning_rate, network_dim, network_alpha, max_epochs, save_every_n_epochs, resolution,
        enable_samples, sample_prompts or [], dit_model=dit_model,
    )


# ──────────────────────────────────────────────
# Project listing
# ──────────────────────────────────────────────

def list_projects():
    """List existing projects."""
    root = get_projects_root()
    if not root.exists():
        return []
    projects = []
    for d in sorted(root.iterdir()):
        if d.is_dir() and (d / "project.toml").exists():
            try:
                config = _read_toml(d / "project.toml")
            except Exception:
                config = {}
            dataset_dir = d / "dataset"
            image_count = len([f for f in dataset_dir.iterdir() if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}]) if dataset_dir.exists() else 0
            caption_count = len(list(dataset_dir.glob("*.txt"))) if dataset_dir.exists() else 0
            projects.append({
                "name": config.get("project", {}).get("name", d.name),
                "path": str(d),
                "description": config.get("project", {}).get("description", ""),
                "image_count": image_count,
                "caption_count": caption_count,
                "created": datetime.fromtimestamp(d.stat().st_ctime).isoformat() if d.exists() else "",
            })
    return projects


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _flush_vram():
    """Release VRAM between steps by triggering garbage collection and emptying the CUDA cache."""
    try:
        import gc
        import torch
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            _log(f"VRAM flushed. Free: {torch.cuda.mem_get_info()[0] / 1024**3:.1f} GB")
    except Exception as e:
        _log(f"VRAM flush skipped: {e}")

def _read_toml(path):
    """Read a TOML file."""
    try:
        import tomllib
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (ModuleNotFoundError, ImportError):
        pass
    try:
        import tomli as tomllib
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (ModuleNotFoundError, ImportError):
        pass
    # If neither is available, try to install tomli automatically
    try:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "tomli", "-q"])
        import tomli as tomllib
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        pass
    # Last resort: basic parser (limited but functional for our generated configs)
    _log("WARNING: tomli not available. Install with: pip install tomli")
    return _basic_toml_parse(path)

def _basic_toml_parse(path):
    """Improved basic TOML reader as fallback. Handles arrays and multi-line strings."""
    import re, json
    data = {}
    current_section = data

    text = open(path, "r").read()

    # Remove multi-line strings first (replace with placeholder)
    ml_strings = {}
    idx = 0
    while '"""' in text:
        start = text.index('"""')
        end = text.index('"""', start + 3) + 3
        key = f"__ML_{idx}__"
        ml_strings[key] = text[start+3:end-3]
        text = text[:start] + f'"{key}"' + text[end:]
        idx += 1

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r'\[([^\]]+)\]', line)
        if m:
            keys = m.group(1).split(".")
            current_section = data
            for k in keys:
                if k not in current_section:
                    current_section[k] = {}
                current_section = current_section[k]
            continue
        if "=" in line:
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip()
            # Try JSON parse for arrays
            if val.startswith("["):
                try:
                    val = json.loads(val)
                except:
                    val = val
            elif val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
                # Restore multi-line string
                if val in ml_strings:
                    val = ml_strings[val]
            else:
                # Try numeric
                try: val = int(val)
                except ValueError:
                    try: val = float(val)
                    except ValueError:
                        if val.lower() == "true": val = True
                        elif val.lower() == "false": val = False
            current_section[key] = val
    return data