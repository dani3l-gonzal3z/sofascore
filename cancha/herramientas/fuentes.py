"""Understat, ClubElo y el cruce entre fuentes.

Lo que permite contestar "¿ganó el que mereció?" con dos modelos de xG en vez
de uno, y "¿cuánto valía ganar ahí?" con el Elo de los dos equipos.
"""

from __future__ import annotations

from .base import herramienta


@herramienta(
    "contexto_externo",
    "LO MÁS POTENTE para juzgar un partido: reúne lo que dicen TODAS las fuentes "
    "sobre él. Trae el xG de Sofascore y el de Understat —dos modelos "
    "independientes— con su diferencia calculada, y la fuerza real de ambos "
    "equipos según el Elo de ClubElo. Donde los dos modelos de xG discrepan es "
    "donde hay algo que explicar. Úsala cuando te pidan valorar si un resultado "
    "fue justo o cuánto valía ganar ahí.",
    {
        "partido": {"type": "string", "description": "Id, URL o 'Equipo A vs Equipo B'."},
        "fecha": {"type": "string", "description": "AAAA-MM-DD, para desambiguar."},
    },
    ["partido"],
)
def _contexto_externo(sesion, partido: str, fecha: str | None = None):
    from ..sources import contexto_partido

    return contexto_partido(sesion.cliente, partido, fecha=fecha)


@herramienta(
    "elo_equipo",
    "La fuerza histórica de un club según ClubElo: su Elo actual, su puesto en "
    "el ranking europeo y cómo ha evolucionado. Contesta a '¿está mejor o peor "
    "que hace un año?' y a '¿cuánto vale de verdad este rival?'.",
    {
        "equipo": {"type": "string",
                   "description": "Nombre como lo escribe ClubElo: 'Real Madrid', "
                                  "'Barcelona', 'Man City', 'Inter'."},
        "historico": {"type": "boolean",
                      "description": "Devolver toda su evolución en vez de solo el dato de hoy."},
    },
    ["equipo"],
)
def _elo_equipo(sesion, equipo: str, historico: bool = False):
    from ..sources import ClubElo

    fuente = ClubElo()
    try:
        if historico:
            tramos = fuente.equipo(equipo)
            return {"equipo": equipo, "actual": tramos[-1], "tramos": tramos}
        return {"equipo": equipo, "actual": fuente.actual(equipo)}
    finally:
        fuente.close()


@herramienta(
    "ranking_elo",
    "El ranking Elo de clubes europeos: los mejores en una fecha, opcionalmente "
    "de un solo país. Sirve para situar a un equipo entre sus iguales.",
    {
        "cuantos": {"type": "integer", "description": "Cuántos devolver (por defecto 20)."},
        "pais": {"type": "string", "description": "Código de país: ESP, ENG, GER, ITA, FRA."},
        "fecha": {"type": "string", "description": "AAAA-MM-DD (por defecto, hoy)."},
    },
)
def _ranking_elo(sesion, cuantos: int = 20, pais: str | None = None, fecha: str | None = None):
    from ..sources import ClubElo

    fuente = ClubElo()
    try:
        return {"fecha": fecha or "hoy", "pais": pais,
                "ranking": fuente.top(cuantos, fecha, pais)}
    finally:
        fuente.close()


@herramienta(
    "tiros_understat",
    "El mapa de tiros de Understat, que es un modelo de xG distinto al de "
    "Sofascore: cada disparo con su xG, quién asistió y qué acción lo precedió. "
    "Compáralo con tiros_partido cuando los dos modelos no coincidan. Solo "
    "cubre las cinco grandes ligas europeas.",
    {
        "partido_understat": {"type": "integer",
                              "description": "Id de Understat (lo da contexto_externo)."},
    },
    ["partido_understat"],
)
def _tiros_understat(sesion, partido_understat: int):
    from ..sources import Understat

    fuente = Understat()
    try:
        return {"fuente": "understat", "partido_id": partido_understat,
                "tiros": fuente.tiros(partido_understat),
                "totales": fuente.xg_partido(partido_understat)["equipos"]}
    finally:
        fuente.close()


@herramienta(
    "fuentes",
    "Qué fuentes de datos hay además de Sofascore y qué aporta cada una. "
    "Consúltalo si no sabes de dónde puede salir un dato.",
    {},
)
def _fuentes(sesion):
    from ..sources import FUENTES, construir

    return {
        "principal": {
            "sofascore": "Partidos, equipos, jugadores y competiciones. "
                         "Es la fuente de todas las demás herramientas."
        },
        "adicionales": {n: construir(n).descripcion for n in sorted(FUENTES)},
        "cruzarlas": "contexto_externo junta todas sobre un mismo partido y "
                     "calcula la diferencia entre los dos modelos de xG.",
    }


