"""Las herramientas que ve una IA, por familias.

Importar este paquete registra todas: el decorador de :mod:`.base` las va
apuntando en ``TOOLS`` conforme se cargan los módulos.

    from cancha.herramientas import TOOLS, esquemas, ejecutar

Están repartidas por lo que hacen —:mod:`.partido`, :mod:`.memoria`,
:mod:`.analisis`, :mod:`.entidades`, :mod:`.fuentes`— porque en un solo fichero
eran ochocientas líneas y encontrar una era un ejercicio de paciencia.
"""

from . import (
    analisis,  # noqa: F401  (se importan por sus efectos: registran herramientas)
    entidades,  # noqa: F401
    fuentes,  # noqa: F401
    memoria,  # noqa: F401
    partido,  # noqa: F401
)
from .base import MAX_CHARS, TOOLS, Tool, ejecutar, esquemas, herramienta, recortar

#: El orden en que las ve el modelo en ``tools/list``. Se declara aquí en vez
#: de dejarlo al orden de los imports, que cualquier formateador reordena sin
#: avisar. Primero por dónde se empieza a analizar.
ORDEN_FAMILIAS = ("partido", "analisis", "memoria", "entidades", "fuentes")


def _ordenar() -> None:
    """Recoloca TOOLS por familias, sin perder ninguna."""
    por_familia = {nombre: [] for nombre in ORDEN_FAMILIAS}
    sueltas = []
    modulos = {"partido": partido, "analisis": analisis, "memoria": memoria,
               "entidades": entidades, "fuentes": fuentes}
    de_quien = {}
    for familia, modulo in modulos.items():
        for atributo in vars(modulo).values():
            nombre = getattr(atributo, "__name__", "")
            if nombre.startswith("_"):
                de_quien[nombre] = familia

    for nombre, herramienta_ in list(TOOLS.items()):
        familia = de_quien.get(herramienta_.handler.__name__)
        por_familia.get(familia, sueltas).append(nombre)

    ordenadas = [n for familia in ORDEN_FAMILIAS for n in por_familia[familia]] + sueltas
    copia = dict(TOOLS)
    TOOLS.clear()
    for nombre in ordenadas:
        TOOLS[nombre] = copia[nombre]


_ordenar()

__all__ = ["TOOLS", "Tool", "esquemas", "ejecutar", "recortar", "MAX_CHARS", "herramienta",
           "ORDEN_FAMILIAS"]
