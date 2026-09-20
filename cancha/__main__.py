"""Permite ejecutar el framework sin depender del PATH.

    python -m cancha match "Real Madrid vs Barcelona"

Cuando ``pip install`` deja el ``cancha.exe`` en una carpeta que no está en el
PATH —lo típico en Windows con una instalación de usuario— esta es la vía que
siempre funciona: no hace falta configurar nada.

**También vale ``python cancha``**, que es lo que sale escribir cuando tienes la
carpeta delante. Python entonces ejecuta este fichero suelto, sin paquete
alrededor, y el ``from .cli`` de abajo reventaría con un
«attempted relative import with no known parent package» que no dice nada de lo
que hay que hacer. Así que se arregla en vez de explicarlo.
"""

from __future__ import annotations

try:
    from .cli import main
except ImportError:  # pragma: no cover - se cubre lanzando un proceso aparte
    # Ejecutado como `python cancha` o `python cancha/__main__.py`: no hay
    # paquete, así que se añade la carpeta que lo contiene y se importa por su
    # nombre completo. A partir de aquí es exactamente lo mismo.
    import pathlib
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    from cancha.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
