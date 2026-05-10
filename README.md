# lora-curator

A web UI for browsing, filtering, and curating image datasets for LoRA training. Scans tags and collections, indexes metadata into SQLite, and provides tools for tagging images with a vision model (via Ollama) and running a training pipeline (via Musubi-Tuner). Preset caption instructions for style, character, object, and environment training.

## Stack

- **Backend**: FastAPI on `:8042`, SQLite
- **Frontend**: React + Vite on `:5173`
- **Tagger**: Ollama vision model (default: `qwen2.5vl:7b`)

## Install

```bash
# Backend
cd backend
pip install -r requirements.txt

# Frontend
cd frontend
bun install
```

## Run

```bash
./start.sh
```

Then open http://localhost:5173.

By default the app looks for datasets at `/home/brad/ai/training/main_datasets`. Override with env vars:

```bash
DATASET_ROOT=/path/to/datasets TRAINING_ROOT=/path/to/training ./start.sh
```

## First use

1. Click **Scan Dataset** to index your image folders into the database
2. Use the filters to browse by year, genre, aspect ratio, etc.
3. Select images and build a training project from the **Pipeline** tab

## Expected folder structure

```
main_datasets/
└── aspect_ratios/
    └── 2.35_scope/
        └── Movie Name/
            ├── .movie_metadata.json
            ├── frame_001.jpg
            └── ...
```
