"""
DiffSynth backend support for the curator pipeline.

The curator historically built musubi commands itself, duplicating the CLI's
logic -- which is how the cache steps and the training step came to disagree
about --edit_plus and produced caches training could not read. Rather than add a
third copy for DiffSynth, this builds its commands through the same
`lora_backends` package the CLI uses, so the UI and the terminal cannot drift.

The split of responsibilities:
  * command building happens here, in the curator's own interpreter, which only
    needs tomllib and pathlib;
  * the commands run under the TRAINING venv, which has torch, controlnet_aux
    and the rest. The curator's interpreter has none of those.
"""

import os
import subprocess
from pathlib import Path

TRAINING_ROOT = Path(os.environ.get("TRAINING_ROOT", "/home/brad/ai/training"))

# Blankness threshold for a control image, matching the diffsynth backend's own
# min_control_coverage default. A detector returns an all-black frame when it
# finds nothing, and training on that teaches the model to ignore control.
BLANK_COVERAGE = 0.002

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def training_python() -> Path:
    """The interpreter that has torch, diffsynth and controlnet_aux."""
    return TRAINING_ROOT / "venv" / "bin" / "python"


def _load_backends():
    """Import lora_backends from the training root, not from site-packages."""
    import sys
    if str(TRAINING_ROOT) not in sys.path:
        sys.path.insert(0, str(TRAINING_ROOT))
    import lora_backends
    from lora_config_loader import load_config
    return lora_backends, load_config


def project_backend(project_dir) -> str:
    """Which backend a project asks for. Defaults to the package's own default."""
    try:
        lora_backends, load_config = _load_backends()
        config = load_config(Path(project_dir) / "project.toml")
        return lora_backends.backend_name(config)
    except SystemExit:
        # load_config exits on a malformed file; the caller surfaces that
        # through its own validation rather than taking the process down.
        return "musubi"
    except Exception:
        return "musubi"


def project_config_path(project_dir) -> Path:
    return Path(project_dir) / "project.toml"


# ──────────────────────────────────────────────
# Control images
# ──────────────────────────────────────────────

def control_dir_for(project_dir):
    """The project's configured control_dir, or None if it has none."""
    try:
        lora_backends, load_config = _load_backends()
        config = load_config(project_config_path(project_dir))
        backend = lora_backends.get_backend(config, name="diffsynth")
        return backend.control_dir(config)
    except Exception:
        return None


def list_control_images(project_dir):
    """Dataset images paired with their control images, for review in the UI.

    Returns every dataset image, including those with no control image yet, so
    the grid shows coverage gaps rather than hiding them.
    """
    project_dir = Path(project_dir)
    dataset_dir = project_dir / "dataset"
    control_dir = control_dir_for(project_dir)

    result = {
        "control_dir": str(control_dir) if control_dir else None,
        "images": [],
        "blank_count": 0,
        "missing_count": 0,
    }
    if not dataset_dir.exists():
        return result

    coverage_fn = None
    try:
        lora_backends, _ = _load_backends()
        from lora_backends.diffsynth import DiffSynthBackend
        coverage_fn = DiffSynthBackend.control_coverage
    except Exception:
        pass

    for f in sorted(dataset_dir.iterdir()):
        if not f.is_file() or f.suffix.lower() not in _IMAGE_EXTS:
            continue
        entry = {
            "filename": f.name,
            "source_path": str(f),
            "control_path": None,
            "coverage": None,
            "blank": False,
        }
        if control_dir and control_dir.exists():
            for ext in _IMAGE_EXTS:
                candidate = control_dir / f"{f.stem}{ext}"
                if candidate.exists():
                    entry["control_path"] = str(candidate)
                    break
        if entry["control_path"] and coverage_fn:
            try:
                cov = coverage_fn(Path(entry["control_path"]))
                entry["coverage"] = round(cov, 5)
                entry["blank"] = cov < BLANK_COVERAGE
            except Exception:
                pass

        if not entry["control_path"]:
            result["missing_count"] += 1
        elif entry["blank"]:
            result["blank_count"] += 1
        result["images"].append(entry)

    return result


def annotate_command(project_dir, annotator=None, overwrite=False):
    """argv for the annotation step."""
    cmd = [str(training_python()), str(TRAINING_ROOT / "annotate_dataset"),
           "-c", str(project_config_path(project_dir))]
    if annotator:
        cmd += ["-a", annotator]
    if overwrite:
        cmd.append("--overwrite")
    return cmd


# ──────────────────────────────────────────────
# Cache / train, built through lora_backends
# ──────────────────────────────────────────────

def build_steps(project_dir, which="train"):
    """[(step_name, argv, cwd, env_overlay, label)] for the requested phase.

    `which` is "train", or "cache" for whatever pre-encoding the backend wants
    (DiffSynth returns nothing unless precompute is on, which is correct -- it
    encodes inline).
    """
    lora_backends, load_config = _load_backends()
    config = load_config(project_config_path(project_dir))
    backend = lora_backends.get_backend(config)

    errors = backend.validate(config)
    if errors:
        return {"error": "\n".join(errors)}

    notes = backend.prepare(config)
    warnings = backend.warnings(config)

    steps = []
    if which == "cache":
        for step in backend.cache_steps(config, which="both"):
            steps.append((step.name, step.argv, step.cwd, step.env, step.label))
        if not steps:
            note = backend.cache_note(config, "both")
            return {"steps": [], "skipped": note or "Nothing to cache.",
                    "notes": notes, "warnings": warnings}
    else:
        step = backend.train_step(config)
        steps.append((step.name, step.argv, step.cwd, step.env, step.label))

    return {"steps": steps, "notes": notes, "warnings": warnings,
            "backend": backend.name}


def resolve_executable(argv):
    """Point bare `python` / `accelerate` at the training venv.

    The backends emit the names a user would type in an activated shell. The
    curator runs under a different interpreter with neither on PATH, so the
    first element is rewritten rather than relying on the environment.
    """
    if not argv:
        return argv
    head = argv[0]
    bindir = training_python().parent
    if head in ("python", "python3"):
        return [str(training_python())] + argv[1:]
    if head == "accelerate":
        candidate = bindir / "accelerate"
        if candidate.exists():
            return [str(candidate)] + argv[1:]
    return argv
