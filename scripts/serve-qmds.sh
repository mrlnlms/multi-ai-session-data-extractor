#!/usr/bin/env bash
# Sobe / para servidor HTTP local pra ver os data profiles em
# notebooks/_output/<plat>.html no navegador.
#
# Uso:
#   scripts/serve-qmds.sh           # comportamento default = start
#   scripts/serve-qmds.sh start     # sobe servidor + abre browser
#   scripts/serve-qmds.sh stop      # mata servidor
#   scripts/serve-qmds.sh restart   # stop + start
#   scripts/serve-qmds.sh status    # ta rodando ou nao?
#   scripts/serve-qmds.sh open      # abre todas as 15 abas no browser
#
# Variaveis (opcionais):
#   PORT=8765         (porta do servidor)
#   OUTPUT_DIR=...    (default: notebooks/_output)

set -euo pipefail

PORT="${PORT:-8765}"
OUTPUT_DIR="${OUTPUT_DIR:-notebooks/_output}"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIDFILE="$PROJECT_ROOT/.serve-qmds.pid"
LOGFILE="$PROJECT_ROOT/.serve-qmds.log"

cd "$PROJECT_ROOT"

is_running() {
  [[ -f "$PIDFILE" ]] || return 1
  local pid
  pid=$(<"$PIDFILE")
  kill -0 "$pid" 2>/dev/null
}

cmd_start() {
  if is_running; then
    echo "ja esta rodando (pid $(<"$PIDFILE"), porta $PORT)"
    echo "abra: http://localhost:$PORT/"
    return 0
  fi

  if [[ ! -d "$OUTPUT_DIR" ]]; then
    echo "ERRO: $OUTPUT_DIR nao existe. Renderize antes:" >&2
    echo "  QUARTO_PYTHON=\"\$(pwd)/.venv/bin/python\" quarto render notebooks/<plat>.qmd" >&2
    return 1
  fi

  if lsof -ti:"$PORT" >/dev/null 2>&1; then
    echo "ERRO: porta $PORT ja em uso por outro processo" >&2
    echo "  rode com PORT=8766 scripts/serve-qmds.sh, ou identifique:" >&2
    echo "  lsof -i:$PORT" >&2
    return 1
  fi

  nohup .venv/bin/python -m http.server "$PORT" --directory "$OUTPUT_DIR" \
    >"$LOGFILE" 2>&1 &
  echo $! >"$PIDFILE"
  sleep 0.5

  if is_running; then
    echo "subiu (pid $(<"$PIDFILE"), porta $PORT)"
    echo "  http://localhost:$PORT/"
  else
    echo "ERRO: nao subiu. log:" >&2
    cat "$LOGFILE" >&2
    rm -f "$PIDFILE"
    return 1
  fi
}

cmd_stop() {
  if ! is_running; then
    echo "ja estava parado"
    rm -f "$PIDFILE"
    return 0
  fi
  local pid
  pid=$(<"$PIDFILE")
  kill "$pid" 2>/dev/null || true
  rm -f "$PIDFILE"
  echo "parado (pid $pid)"
}

cmd_status() {
  if is_running; then
    echo "rodando (pid $(<"$PIDFILE"), porta $PORT)"
    echo "  http://localhost:$PORT/"
  else
    echo "parado"
  fi
}

cmd_open() {
  if ! is_running; then
    echo "servidor nao esta rodando — subindo..."
    cmd_start
  fi
  for f in "$OUTPUT_DIR"/*.html; do
    [[ -f "$f" ]] || continue
    name=$(basename "$f")
    open "http://localhost:$PORT/$name"
  done
  echo "abriu $(ls "$OUTPUT_DIR"/*.html 2>/dev/null | wc -l | tr -d ' ') abas"
}

case "${1:-start}" in
  start)   cmd_start ;;
  stop)    cmd_stop ;;
  restart) cmd_stop; cmd_start ;;
  status)  cmd_status ;;
  open)    cmd_open ;;
  *) echo "uso: $0 [start|stop|restart|status|open]" >&2; exit 2 ;;
esac
