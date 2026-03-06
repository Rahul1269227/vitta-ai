#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

# shellcheck disable=SC1091
source "${ROOT_DIR}/scripts/common_runtime.sh"

ensure_python3
ensure_uv
ensure_docker_compose

if [[ ! -d ".venv" ]]; then
  echo "Creating virtual environment at .venv (uv)"
  uv venv .venv
fi

echo "Installing Python dependencies with uv (dev + OCR)..."
uv sync --dev --extra ocr

uv run pre-commit install || true

if [[ ! -f ".env" ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

echo "Running stack startup with image build..."
bash scripts/run_regular.sh --build
