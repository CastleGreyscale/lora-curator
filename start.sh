#!/bin/bash
# LoRA Dataset Curator - Development Startup
# Starts both the FastAPI backend and Vite dev server

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Default paths (override with environment variables)
export DATASET_ROOT="${DATASET_ROOT:-/home/brad/ai/training/main_datasets}"
export TRAINING_ROOT="${TRAINING_ROOT:-/home/brad/ai/training}"
export CURATOR_DB_PATH="${CURATOR_DB_PATH:-$SCRIPT_DIR/curator.db}"

echo "═══════════════════════════════════════════"
echo "  LoRA Dataset Curator"
echo "═══════════════════════════════════════════"
echo "  Dataset Root:  $DATASET_ROOT"
echo "  Training Root: $TRAINING_ROOT"
echo "  Database:      $CURATOR_DB_PATH"
echo ""
echo "  Backend:  http://localhost:8042"
echo "  Frontend: http://localhost:5173"
echo "═══════════════════════════════════════════"
echo ""

# Function to cleanup background processes
cleanup() {
    echo ""
    echo "Shutting down..."
    kill $BACKEND_PID 2>/dev/null
    kill $FRONTEND_PID 2>/dev/null
    exit 0
}
trap cleanup SIGINT SIGTERM

# Start backend
echo "Starting backend..."
cd "$SCRIPT_DIR/backend"
python -m uvicorn main:app --host 0.0.0.0 --port 8042 --reload &
BACKEND_PID=$!

# Give backend a moment to start
sleep 2

# Start frontend
echo "Starting frontend..."
cd "$SCRIPT_DIR/frontend"
bun run dev &
FRONTEND_PID=$!

echo ""
echo "Both servers running. Press Ctrl+C to stop."
echo ""

# Wait for either process to exit
wait
