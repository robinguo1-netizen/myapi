#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
RUNTIME_DIR="${REPO_ROOT}/.local-tests/rs-local"
RUNTIME_ENV="${RUNTIME_DIR}/runtime.env"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"
PROJECT_NAME="rs-local-e2e"

generate_runtime_env() {
  local force="${1:-false}"
  local target="${RUNTIME_ENV}.tmp"
  if [[ -f "${RUNTIME_ENV}" && "${force}" != "true" ]]; then
    return
  fi

  umask 077
  mkdir -p "${RUNTIME_DIR}"
  {
    printf 'RS_APP_PORT=3308\n'
    printf 'RS_POSTGRES_PORT=15433\n'
    printf 'RS_REDIS_PORT=16380\n'
    printf 'RS_UPSTREAM_PORT=18081\n'
    printf 'RS_DB_USER=rs_local\n'
    printf 'RS_DB_NAME=rs_local\n'
    printf 'RS_DB_PASSWORD=%s\n' "$(openssl rand -hex 24)"
    printf 'RS_REDIS_PASSWORD=%s\n' "$(openssl rand -hex 24)"
    printf 'RS_SESSION_SECRET=%s\n' "$(openssl rand -hex 48)"
    printf 'RS_UPSTREAM_KEY=%s\n' "$(openssl rand -hex 24)"
    printf 'RS_UPSTREAM_MODEL=gpt-3.5-turbo\n'
    printf 'RS_ADMIN_USERNAME=rsroot\n'
    printf 'RS_ADMIN_PASSWORD=%s\n' "$(openssl rand -hex 10)"
    printf 'RS_USER_USERNAME=rsclient\n'
    printf 'RS_USER_PASSWORD=%s\n' "$(openssl rand -hex 10)"
  } >"${target}"
  chmod 600 "${target}"
  mv "${target}" "${RUNTIME_ENV}"
}

compose() {
  docker compose \
    --project-name "${PROJECT_NAME}" \
    --env-file "${RUNTIME_ENV}" \
    --file "${COMPOSE_FILE}" \
    "$@"
}

wait_for_app() {
  local url="http://127.0.0.1:3308/api/status"
  for _ in $(seq 1 90); do
    if curl --fail --silent --show-error "${url}" >/dev/null 2>&1; then
      printf 'RS local service is ready at http://127.0.0.1:3308\n'
      return
    fi
    sleep 2
  done
  printf 'RS local service did not become ready. Recent logs:\n' >&2
  compose logs --tail=120 app >&2
  return 1
}

run_acceptance() {
  set -a
  # shellcheck disable=SC1090
  source "${RUNTIME_ENV}"
  set +a
  RS_BASE_URL="http://127.0.0.1:${RS_APP_PORT}" \
    python3 "${SCRIPT_DIR}/acceptance.py"
}

generate_runtime_env

case "${1:-start}" in
  start)
    compose up --detach --build
    wait_for_app
    ;;
  test)
    wait_for_app
    run_acceptance
    ;;
  status)
    compose ps
    ;;
  logs)
    compose logs --tail=200 "${2:-app}"
    ;;
  stop)
    compose down --remove-orphans
    ;;
  reset)
    compose down --volumes --remove-orphans
    ;;
  rotate)
    compose down --volumes --remove-orphans
    generate_runtime_env true
    compose up --detach --build
    wait_for_app
    ;;
  *)
    printf 'Usage: %s {start|test|status|logs [service]|stop|reset|rotate}\n' "$0" >&2
    exit 2
    ;;
esac
