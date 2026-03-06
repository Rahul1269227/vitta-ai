#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

# shellcheck disable=SC1091
source "${ROOT_DIR}/scripts/common_runtime.sh"

BUILD_FLAG=""
if [[ "${1:-}" == "--build" ]]; then
  BUILD_FLAG="--build"
fi

ensure_python3
ensure_uv
ensure_docker_compose

if [[ ! -f ".env" ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

uv run python scripts/allocate_runtime_ports.py --output .env.runtime

set -a
# shellcheck disable=SC1091
source .env.runtime
set +a

echo "Starting stack with HOST_API_PORT=${HOST_API_PORT} HOST_POSTGRES_PORT=${HOST_POSTGRES_PORT}"
run_docker_compose --profile app --env-file .env --env-file .env.runtime up -d ${BUILD_FLAG}

echo "Waiting for API readiness on port ${HOST_API_PORT}..."
uv run python - "${HOST_API_PORT}" <<'PY'
import http.client
import sys
import time
import urllib.error
import urllib.request

port = int(sys.argv[1])
url = f"http://127.0.0.1:{port}/readyz"
for _ in range(60):
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            if resp.status == 200:
                print(f"API is ready at {url}")
                raise SystemExit(0)
    except (urllib.error.URLError, http.client.HTTPException, OSError):
        pass
    time.sleep(2)
print("API not ready yet. Check logs: docker compose logs api (or docker-compose logs api)")
raise SystemExit(1)
PY

echo "Control Room: http://127.0.0.1:${HOST_API_PORT}/"
echo "API docs:     http://127.0.0.1:${HOST_API_PORT}/docs"
