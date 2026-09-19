"""Las tablas del partido, en crudo o como ``DataFrame``.

Es lo que hacen bien ``soccerdata`` y ``ScraperFC``: que los datos lleguen ya
en forma de tabla, listos para analizar. Aquí está lo mismo, con dos matices:

* :func:`to_tables` no necesita nada: devuelve listas de diccionarios;
* :func:`to_frames` devuelve ``DataFrame`` **si tienes pandas instalado**, y si
  no lo tienes te lo dice claramente en vez de fallar de forma críptica.

El framework sigue sin dependencias obligatorias: pandas es opcional
(``pip install sofascore-framework[pandas]``).
"""

from __future__ import annotations

from typing import Any

from .export import TABLAS


def to_tables(informe, incluir_vacias: bool = False) -> dict[str, list[dict]]:
    """Todas las tablas del informe como listas de diccionarios."""
    salida: dict[str, list[dict]] = {}
    for nombre, constructor in TABLAS.items():
        filas = constructor(informe)
        if filas or incluir_vacias:
            salida[nombre] = filas
    return salida


def _pandas():
    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise ImportError(
            "Esta función necesita pandas, que es opcional. "
            "Instálalo con: pip install pandas  (o pip install sofascore-framework[pandas])"
        ) from exc
    return pd


def to_frames(informe, incluir_vacias: bool = False) -> dict[str, Any]:
    """Las mismas tablas, como ``DataFrame`` de pandas."""
    pd = _pandas()
    return {
        nombre: pd.DataFrame(filas)
        for nombre, filas in to_tables(informe, incluir_vacias).items()
    }


def to_frame(filas: list[dict]):
    """Convierte una lista de diccionarios cualquiera en un ``DataFrame``."""
    return _pandas().DataFrame(filas)


def flatten(datos: Any, prefijo: str = "", separador: str = ".") -> dict:
    """Aplana un JSON anidado a un solo nivel: ``{"player.name": "..."}``.

    Útil para meter en una tabla respuestas de la API que vienen con
    diccionarios dentro de diccionarios (las estadísticas de temporada, por
    ejemplo).
    """
    plano: dict[str, Any] = {}
    if isinstance(datos, dict):
        for clave, valor in datos.items():
            nombre = f"{prefijo}{separador}{clave}" if prefijo else str(clave)
            if isinstance(valor, (dict, list)):
                plano.update(flatten(valor, nombre, separador))
            else:
                plano[nombre] = valor
    elif isinstance(datos, list):
        for indice, valor in enumerate(datos):
            nombre = f"{prefijo}{separador}{indice}" if prefijo else str(indice)
            if isinstance(valor, (dict, list)):
                plano.update(flatten(valor, nombre, separador))
            else:
                plano[nombre] = valor
    elif prefijo:
        plano[prefijo] = datos
    return plano


__all__ = ["to_tables", "to_frames", "to_frame", "flatten"]
