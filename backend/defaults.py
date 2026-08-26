"""
Loader for the universal defaults file (lora-curator/defaults.toml).

Single source of truth for caption prompts and new-project defaults, shared by
the bulk tagger (tagger.py), the pipeline API (pipeline_routes.py), and the
frontend (via GET /api/config/defaults).

Nothing here touches an existing project — datasets/<name>/project.toml is
written once at creation time and is authoritative from then on.
"""

from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # Python 3.10 fallback

DEFAULTS_PATH = Path(__file__).resolve().parent.parent / "defaults.toml"

# Fallbacks if defaults.toml is missing or unparseable. Deliberately minimal —
# enough to keep the app running, not a second copy of the config.
_FALLBACK = {
    "tagger": {
        "model": "qwen3-vl:8b",
        "api_url": "http://localhost:11434",
        "prompt": "Describe this image using short comma-separated tags. Use 1-3 words per tag.",
    },
    "pipeline": {
        "tagging_model": "qwen3-vl:8b",
        "learning_rate": "5e-5",
        "network_dim": 32,
        "network_alpha": 16,
        "max_epochs": 16,
        "save_every_n_epochs": 2,
        "num_repeats": 1,
        "resolution": 1024,
        "dit_model": "qwen_image_bf16.safetensors",
        "enable_samples": False,
        "sample_prompts": [],
        "prompt": "Describe this image in detail for AI training.",
    },
    "presets": {},
}


def _strip_prompts(section):
    """Trim the newlines TOML ''' blocks leave around prompt text."""
    if isinstance(section, dict) and isinstance(section.get("prompt"), str):
        section["prompt"] = section["prompt"].strip()
    return section


def load(path=None):
    """Read defaults.toml fresh. Returns the fallback dict on any failure.

    Not cached: the file is small, and re-reading means an edit takes effect on
    the next request rather than needing a backend restart.
    """
    path = Path(path) if path else DEFAULTS_PATH
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        print(f"[defaults] {path} not found — using built-in fallbacks")
        return _FALLBACK
    except Exception as e:
        print(f"[defaults] Could not parse {path}: {e} — using built-in fallbacks")
        return _FALLBACK

    merged = {
        "tagger": {**_FALLBACK["tagger"], **data.get("tagger", {})},
        "pipeline": {**_FALLBACK["pipeline"], **data.get("pipeline", {})},
        "presets": data.get("presets", {}),
    }
    _strip_prompts(merged["tagger"])
    _strip_prompts(merged["pipeline"])
    for preset in merged["presets"].values():
        _strip_prompts(preset)
    return merged


def pipeline_default(key):
    """One [pipeline] value — used for Pydantic field defaults."""
    return load()["pipeline"].get(key)


def tagger_default(key):
    """One [tagger] value."""
    return load()["tagger"].get(key)
