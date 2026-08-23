"""Permite ejecutar el framework sin depender del PATH.

    python -m sofascore match "Real Madrid vs Barcelona"

Cuando ``pip install`` deja el ``sofascore.exe`` en una carpeta que no está en
el PATH —lo típico en Windows con una instalación de usuario— esta es la vía
que siempre funciona: no hace falta configurar nada.
"""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
