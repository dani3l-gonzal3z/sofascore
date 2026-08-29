"""Las herramientas que ve una IA, por familias.

Importar este paquete registra todas: el decorador de :mod:`.base` las va
apuntando en ``TOOLS`` conforme se cargan los módulos.

    from cancha.herramientas import TOOLS, esquemas, ejecutar

Están repartidas por lo que hacen —:mod:`.partido`, :mod:`.entidades`,
:mod:`.analisis`, :mod:`.fuentes`— porque en un solo fichero eran ochocientas
líneas y encontrar una era un ejercicio de paciencia.
"""

# El orden importa: es el que ve el modelo en `tools/list`, y conviene que
# empiece por las del partido, que son por donde se empieza a analizar.
from . import (
    analisis,  # noqa: F401,E402
    entidades,  # noqa: F401,E402
    fuentes,  # noqa: F401,E402
    partido,  # noqa: F401,E402  (se importa por sus efectos)
)
from .base import MAX_CHARS, TOOLS, Tool, ejecutar, esquemas, herramienta, recortar

__all__ = ["TOOLS", "Tool", "esquemas", "ejecutar", "recortar", "MAX_CHARS", "herramienta"]
