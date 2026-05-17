"""
Pipeline API routes.
Add to main.py:
    from pipeline_routes import router as pipeline_router
    app.include_router(pipeline_router)
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
import pipeline

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


class CreateProjectRequest(BaseModel):
    name: str
    description: str = ""
    trigger_word: str = ""
    tagging_prompt: str = "Describe this image in detail for AI training. Include the subject, setting, lighting, mood, color palette, composition, and any notable visual elements."
    tagging_model: str = "qwen2.5vl:32b"
    learning_rate: str = "5e-5"
    network_dim: int = 32
    network_alpha: int = 16
    max_epochs: int = 16
    save_every_n_epochs: int = 2
    resolution: int = 1024
    enable_samples: bool = False
    sample_prompts: List[str] = []
    dit_model: str = "qwen_image_bf16.safetensors"


class CreateFromPathRequest(BaseModel):
    source_path: str
    name: str
    description: str = ""
    trigger_word: str = ""
    tagging_prompt: str = "Describe this image in detail for AI training. Include the subject, setting, lighting, mood, color palette, composition, and any notable visual elements."
    tagging_model: str = "qwen2.5vl:32b"
    learning_rate: str = "5e-5"
    network_dim: int = 32
    network_alpha: int = 16
    max_epochs: int = 16
    save_every_n_epochs: int = 2
    resolution: int = 1024
    enable_samples: bool = False
    sample_prompts: List[str] = []
    dit_model: str = "qwen_image_bf16.safetensors"


class LoadProjectRequest(BaseModel):
    project_dir: str


@router.post("/create")
async def create_project(req: CreateProjectRequest):
    """Create project, export selected images, write config."""
    if pipeline.status["running"]:
        raise HTTPException(400, "Pipeline step already running")

    result = pipeline.create_project(
        name=req.name,
        description=req.description,
        trigger_word=req.trigger_word,
        tagging_prompt=req.tagging_prompt,
        tagging_model=req.tagging_model,
        learning_rate=req.learning_rate,
        network_dim=req.network_dim,
        network_alpha=req.network_alpha,
        max_epochs=req.max_epochs,
        save_every_n_epochs=req.save_every_n_epochs,
        resolution=req.resolution,
        enable_samples=req.enable_samples,
        sample_prompts=req.sample_prompts,
        dit_model=req.dit_model,
    )
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/create-from-path")
async def create_project_from_path(req: CreateFromPathRequest):
    """Create project from an existing directory of images, bypassing Browse selection."""
    if pipeline.status["running"]:
        raise HTTPException(400, "Pipeline step already running")

    result = pipeline.create_project_from_path(
        source_path=req.source_path,
        name=req.name,
        description=req.description,
        trigger_word=req.trigger_word,
        tagging_prompt=req.tagging_prompt,
        tagging_model=req.tagging_model,
        learning_rate=req.learning_rate,
        network_dim=req.network_dim,
        network_alpha=req.network_alpha,
        max_epochs=req.max_epochs,
        save_every_n_epochs=req.save_every_n_epochs,
        resolution=req.resolution,
        enable_samples=req.enable_samples,
        sample_prompts=req.sample_prompts,
        dit_model=req.dit_model,
    )
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/load")
async def load_project(req: LoadProjectRequest):
    """Load an existing project to resume the pipeline."""
    import os
    from pathlib import Path
    project_dir = Path(req.project_dir)
    if not (project_dir / "project.toml").exists():
        raise HTTPException(404, "project.toml not found in that directory")

    config = pipeline._read_toml(project_dir / "project.toml")
    name = config.get("project", {}).get("name", project_dir.name)

    pipeline.reset_status(name, project_dir)

    # Check which steps are already done
    dataset_dir = project_dir / "dataset"
    cache_dir = project_dir / "cache_directory"

    if dataset_dir.exists():
        exts = {".jpg", ".jpeg", ".png", ".webp"}
        imgs = [f for f in dataset_dir.iterdir() if f.suffix.lower() in exts]
        txts = list(dataset_dir.glob("*.txt"))
        if imgs:
            pipeline._set_step("export", "done", f"{len(imgs)} images")
        if txts and len(txts) >= len(imgs) * 0.9:
            pipeline._set_step("tag", "done", f"{len(txts)} captions")

    if cache_dir.exists() and any(cache_dir.glob("*.safetensors")):
        pipeline._set_step("cache_vae", "done", "Cached")
        pipeline._set_step("cache_te", "done", "Cached")

    return {"project_name": name, "project_dir": str(project_dir)}


@router.post("/tag")
async def start_tagging():
    """Start image tagging with Ollama."""
    if pipeline.status["running"]:
        raise HTTPException(400, "Pipeline step already running")
    if not pipeline.status["project_dir"]:
        raise HTTPException(400, "No project loaded")

    result = pipeline.start_tagging(pipeline.status["project_dir"])
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/cache")
async def start_cache(cache_type: str = "both"):
    """Start VAE and/or text encoder caching."""
    if pipeline.status["running"]:
        raise HTTPException(400, "Pipeline step already running")
    if not pipeline.status["project_dir"]:
        raise HTTPException(400, "No project loaded")

    result = pipeline.start_cache(pipeline.status["project_dir"], cache_type)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/train")
async def start_training():
    """Start LoRA training."""
    if pipeline.status["running"]:
        raise HTTPException(400, "Pipeline step already running")
    if not pipeline.status["project_dir"]:
        raise HTTPException(400, "No project loaded")

    result = pipeline.start_training(pipeline.status["project_dir"])
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.get("/status")
async def get_status():
    """Get current pipeline status."""
    return pipeline.get_status()


@router.post("/stop")
async def stop_current():
    """Stop the currently running step."""
    stopped = pipeline.stop_current()
    return {"stopped": stopped}


@router.get("/projects")
async def list_projects():
    """List existing projects."""
    return pipeline.list_projects()


@router.get("/env")
async def check_env():
    """Check that required environment variables are set."""
    import os
    from pathlib import Path
    env_file = Path(__file__).parent / ".env"
    return {
        "LORA_PROJECTS_ROOT": pipeline._env("LORA_PROJECTS_ROOT", "(not set)"),
        "COMFYUI_MODELS_ROOT": pipeline._env("COMFYUI_MODELS_ROOT", "(not set)"),
        "MUSUBI_TUNER_ROOT": pipeline._env("MUSUBI_TUNER_ROOT", "(not set)"),
        "projects_root_exists": pipeline.get_projects_root().exists(),
        "models_root_exists": pipeline.get_models_root().exists() if pipeline._env("COMFYUI_MODELS_ROOT") else False,
        "musubi_root_exists": pipeline.get_musubi_root().exists() if pipeline._env("MUSUBI_TUNER_ROOT") else False,
        "env_file": str(env_file),
        "env_file_exists": env_file.exists(),
        "hint": "Create backend/.env with your paths if env vars aren't propagating from Fish",
    }