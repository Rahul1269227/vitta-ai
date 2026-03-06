#!/usr/bin/env bash

DOCKER_COMPOSE_CMD=()

require_command() {
  local cmd="$1"
  local message="$2"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "${message}"
    exit 1
  fi
}

ensure_python3() {
  require_command "python3" "python3 is required but not installed."
}

ensure_uv() {
  if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required but not installed."
    echo "Install: https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
  fi
}

ensure_docker_compose() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    DOCKER_COMPOSE_CMD=("docker" "compose")
    return
  fi

  if command -v docker-compose >/dev/null 2>&1; then
    DOCKER_COMPOSE_CMD=("docker-compose")
    return
  fi

  echo "docker compose is required but unavailable (tried 'docker compose' and 'docker-compose')."
  exit 1
}

run_docker_compose() {
  if [[ ${#DOCKER_COMPOSE_CMD[@]} -eq 0 ]]; then
    ensure_docker_compose
  fi
  "${DOCKER_COMPOSE_CMD[@]}" "$@"
}
