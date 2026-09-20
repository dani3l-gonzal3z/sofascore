#!/usr/bin/env bash
# Lo mismo que cancha.bat, para macOS y Linux.
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

exec .venv/bin/python -m cancha arrancar "$@"
