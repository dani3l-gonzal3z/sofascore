"""Equipos, jugadores, competiciones y qué se juega.

El contexto que un partido suelto no da: quién es cada equipo, cómo va la
tabla, qué hay en directo. Y ``catalogo``, que le dice al modelo qué nombres
son válidos cuando no sabe qué pedir.
"""

from __future__ import annotations

from typing import Any

from ..catalog import KNOWN_STAT_KEYS, LEAGUES
from ..endpoints import CATALOGS
from ..entities import build_player_report, build_team_report, build_tournament_report
from ..models import Event
from .base import herramienta


@herramienta(
    "ficha_equipo",
    "Todo sobre un equipo: estadio, entrenador, plantilla, últimos y próximos "
    "partidos, forma reciente y traspasos.",
    {
        "equipo": {"type": "string", "description": "Nombre o id del equipo."},
        "secciones": {"type": "array", "items": {"type": "string"},
                      "description": "profile, players, last_events, next_events, "
                                     "performance, transfers..."},
    },
    ["equipo"],
)
def _ficha_equipo(sesion, equipo: str, secciones: list[str] | None = None):
    informe = build_team_report(sesion.cliente, equipo, sections=secciones)
    return informe.to_dict()


@herramienta(
    "ficha_jugador",
    "Todo sobre un jugador: ficha, radar de atributos, estadísticas de la "
    "temporada en curso, valoraciones del último año y traspasos.",
    {
        "jugador": {"type": "string", "description": "Nombre o id del jugador."},
        "secciones": {"type": "array", "items": {"type": "string"},
                      "description": "profile, attributes, season_statistics, "
                                     "last_year, transfers..."},
    },
    ["jugador"],
)
def _ficha_jugador(sesion, jugador: str, secciones: list[str] | None = None):
    informe = build_player_report(sesion.cliente, jugador, sections=secciones)
    return informe.to_dict()


@herramienta(
    "clasificacion",
    "La tabla de una competición, con puntos, partidos, goles y diferencia. "
    "Acepta alias ('laliga', 'premier', 'champions').",
    {
        "liga": {"type": "string", "description": "Nombre o alias de la competición."},
        "temporada": {"type": "integer",
                      "description": "Id de temporada (por defecto, la actual)."},
    },
    ["liga"],
)
def _clasificacion(sesion, liga: str, temporada: int | None = None):
    informe = build_tournament_report(
        sesion.cliente, liga, season_id=temporada, sections=["profile", "standings"]
    )
    filas = []
    for tabla in informe.get("standings") or []:
        for fila in tabla.get("rows") or []:
            filas.append({
                "posicion": fila.get("position"),
                "equipo": (fila.get("team") or {}).get("name"),
                "puntos": fila.get("points"),
                "jugados": fila.get("matches"),
                "ganados": fila.get("wins"),
                "empatados": fila.get("draws"),
                "perdidos": fila.get("losses"),
                "goles_favor": fila.get("scoresFor"),
                "goles_contra": fila.get("scoresAgainst"),
            })
    return {"competicion": informe.name, "temporada": informe.meta.get("contexto", {}),
            "clasificacion": filas}


@herramienta(
    "partidos",
    "Qué se juega: en directo ahora mismo, o todos los de una fecha. Se puede "
    "filtrar por competición para no ahogarse en amistosos y categorías menores.",
    {
        "fecha": {"type": "string", "description": "AAAA-MM-DD. Sin fecha, los de ahora mismo."},
        "liga": {"type": "string", "description": "Solo esta competición ('laliga', 'premier')."},
        "limite": {"type": "integer", "description": "Cuántos devolver (por defecto 30)."},
    },
)
def _partidos(sesion, fecha: str | None = None, liga: str | None = None, limite: int = 30):
    from ..catalog import find_league

    crudos = sesion.cliente.scheduled_events(fecha) if fecha else sesion.cliente.live_events()
    eventos = [Event.from_api(e) for e in crudos]
    if liga:
        identificador = find_league(liga)
        if identificador:
            eventos = [e for e in eventos if e.unique_tournament_id == identificador]
        else:
            from ..resolve import normalizar

            buscado = normalizar(liga)
            eventos = [e for e in eventos if buscado in normalizar(e.tournament)]
    return {
        "cuando": fecha or "en directo",
        "total": len(eventos),
        "partidos": [
            {"id": e.id, "partido": f"{e.home} {e.scoreline} {e.away}",
             "competicion": e.tournament, "estado": e.status_description or e.status_type}
            for e in eventos[:limite]
        ],
    }


@herramienta(
    "catalogo",
    "Qué sabe hacer este framework: todas las secciones de datos disponibles "
    "para partidos, equipos, jugadores y competiciones, las ligas conocidas con "
    "su id y las claves de estadística válidas. Consúltalo cuando no sepas qué "
    "pedir o qué nombre usar.",
    {
        "que": {"type": "string",
                "enum": ["secciones", "ligas", "estadisticas", "todo"],
                "description": "Qué parte del catálogo quieres."},
    },
)
def _catalogo(sesion, que: str = "todo"):
    salida: dict[str, Any] = {}
    if que in ("secciones", "todo"):
        salida["secciones"] = {
            tipo: {n: s.description for n, s in cat.items()}
            for tipo, cat in CATALOGS.items()
        }
    if que in ("ligas", "todo"):
        salida["ligas"] = LEAGUES
    if que in ("estadisticas", "todo"):
        salida["claves_de_estadistica"] = list(KNOWN_STAT_KEYS)
    return salida


