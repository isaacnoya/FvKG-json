#!/bin/sh

set -u

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
FRONTEND_DIR="$ROOT_DIR/jit-geosparql-frontend"
CONDA_ENV=${CONDA_ENV:-oeg}
BACKEND_HOST=${BACKEND_HOST:-127.0.0.1}
BACKEND_PORT=${BACKEND_PORT:-8000}
FRONTEND_HOST=${FRONTEND_HOST:-127.0.0.1}
FRONTEND_PORT=${FRONTEND_PORT:-5173}

BACKEND_PID=""
FRONTEND_PID=""
STOPPING=0

log() {
  printf '[MorphGEO] %s\n' "$*"
}

fail() {
  printf '[MorphGEO] ERROR: %s\n' "$*" >&2
  exit 1
}

find_conda() {
  if [ -n "${CONDA_EXE:-}" ] && [ -x "$CONDA_EXE" ]; then
    printf '%s\n' "$CONDA_EXE"
    return
  fi

  if command -v conda >/dev/null 2>&1; then
    command -v conda
    return
  fi

  for candidate in \
    /opt/miniconda3/bin/conda \
    "$HOME/miniconda3/bin/conda" \
    "$HOME/anaconda3/bin/conda" \
    "$HOME/miniforge3/bin/conda"
  do
    if [ -x "$candidate" ]; then
      printf '%s\n' "$candidate"
      return
    fi
  done

  return 1
}

port_is_busy() {
  host=$1
  port=$2

  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
    return
  fi

  nc -z "$host" "$port" >/dev/null 2>&1
}

stop_process() {
  pid=$1
  if [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1; then
    kill "$pid" >/dev/null 2>&1 || true
  fi
}

cleanup() {
  if [ "$STOPPING" -eq 1 ]; then
    return
  fi
  STOPPING=1

  log "Stopping services..."
  stop_process "$FRONTEND_PID"
  stop_process "$BACKEND_PID"

  [ -z "$FRONTEND_PID" ] || wait "$FRONTEND_PID" 2>/dev/null || true
  [ -z "$BACKEND_PID" ] || wait "$BACKEND_PID" 2>/dev/null || true
}

trap 'cleanup; exit 0' INT TERM HUP
trap cleanup EXIT

[ -d "$FRONTEND_DIR" ] || fail "Frontend directory not found: $FRONTEND_DIR"

CONDA_BIN=$(find_conda) || fail "Conda was not found."
ENV_PREFIX=$(
  "$CONDA_BIN" run -n "$CONDA_ENV" python -c "import sys; print(sys.prefix)" 2>/dev/null
) || fail "Conda environment '$CONDA_ENV' was not found."
ENV_PREFIX=$(printf '%s\n' "$ENV_PREFIX" | tail -n 1)
UVICORN_BIN="$ENV_PREFIX/bin/uvicorn"

[ -x "$UVICORN_BIN" ] ||
  fail "Uvicorn is not installed in Conda environment '$CONDA_ENV'."
command -v npm >/dev/null 2>&1 || fail "npm was not found."
command -v curl >/dev/null 2>&1 || fail "curl was not found."

if port_is_busy "$BACKEND_HOST" "$BACKEND_PORT"; then
  fail "Backend port $BACKEND_PORT is already in use."
fi

if port_is_busy "$FRONTEND_HOST" "$FRONTEND_PORT"; then
  fail "Frontend port $FRONTEND_PORT is already in use."
fi

if [ ! -x "$FRONTEND_DIR/node_modules/.bin/vite" ]; then
  log "Installing frontend dependencies..."
  (cd "$FRONTEND_DIR" && npm install) || fail "Frontend installation failed."
fi

log "Starting backend at http://$BACKEND_HOST:$BACKEND_PORT"
(
  cd "$ROOT_DIR" &&
    exec "$UVICORN_BIN" moprhgeo.api:app \
      --reload \
      --host "$BACKEND_HOST" \
      --port "$BACKEND_PORT"
) &
BACKEND_PID=$!

attempt=0
until curl --fail --silent "http://$BACKEND_HOST:$BACKEND_PORT/health" >/dev/null 2>&1; do
  if ! kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
    wait "$BACKEND_PID" || true
    fail "Backend stopped before becoming ready."
  fi

  attempt=$((attempt + 1))
  if [ "$attempt" -ge 60 ]; then
    fail "Backend did not become ready within 30 seconds."
  fi
  sleep 0.5
done

log "Backend is ready."
log "Starting frontend at http://$FRONTEND_HOST:$FRONTEND_PORT"
(
  cd "$FRONTEND_DIR" &&
    export VITE_API_URL="http://$BACKEND_HOST:$BACKEND_PORT/api/execute" &&
    exec ./node_modules/.bin/vite \
      --host "$FRONTEND_HOST" \
      --port "$FRONTEND_PORT" \
      --strictPort
) &
FRONTEND_PID=$!

log "MorphGEO is running."
log "Open http://$FRONTEND_HOST:$FRONTEND_PORT"
log "Press Ctrl+C to stop both services."

while :; do
  if ! kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
    wait "$BACKEND_PID" || true
    fail "Backend process stopped."
  fi

  if ! kill -0 "$FRONTEND_PID" >/dev/null 2>&1; then
    wait "$FRONTEND_PID" || true
    fail "Frontend process stopped."
  fi

  sleep 1
done
