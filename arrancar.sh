#!/usr/bin/env bash
# Lo mismo que cancha.bat, para macOS y Linux.
#
#   ./arrancar.sh                    -> la interfaz, la guardia y el bot
#   ./arrancar.sh doctor             -> cualquier otro comando
#   ./arrancar.sh ajustes ligas=grandes
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null; then
  echo; echo "  ✗ No encuentro python3. Instálalo y vuelve."; echo; exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "  Primera vez: preparando el entorno. Esto tarda un minuto."
  python3 -m venv .venv
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -e ".[curl]"
  echo "  Listo."
fi

# Si el primer argumento es un comando (no empieza por guion), se pasa tal
# cual; si no, se supone que quieres arrancarlo todo.
if [ $# -gt 0 ] && [ "${1#-}" = "$1" ]; then
  exec .venv/bin/python -m cancha "$@"
fi
exec .venv/bin/python -m cancha arrancar "$@"
