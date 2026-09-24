"""Nombre antiguo del módulo. Las herramientas viven ahora en :mod:`cancha.herramientas`.

Eran ochocientas líneas en un solo fichero y encontrar una era un ejercicio de
paciencia, así que están repartidas por familias. Este puente sigue aquí para
que nada de lo que ya las importaba se rompa::

    from cancha.tools import TOOLS, ejecutar, esquemas   # sigue valiendo
"""

from __future__ import annotations

from .herramientas import MAX_CHARS, TOOLS, Tool, ejecutar, esquemas, herramienta, recortar

__all__ = ["TOOLS", "Tool", "esquemas", "ejecutar", "recortar", "MAX_CHARS", "herramienta"]
