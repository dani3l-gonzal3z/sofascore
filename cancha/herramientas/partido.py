"""Lo que se puede preguntar de un partido concreto.

De ``resumen_partido``, que es por donde se empieza, al detalle de los tiros y
la cronología. Todas reciben la sesión, así que preguntar ocho cosas del mismo
partido no lo pide ocho veces.
"""

from __future__ import annotations

from typing import Any

from ..endpoints import SECTIONS
from ..models import Event
from ..resolve import normalizar
from .base import herramienta


def _lado(evento: Event, es_local: Any) -> str:
    if es_local is None:
        return ""
    return evento.home.name if es_local else evento.away.name


def _filtrar_por_equipo(filas: list[dict], equipo: str | None,
                        clave: str = "equipo") -> list[dict]:
    if not equipo:
        return filas
    buscado = normalizar(equipo)
    return [f for f in filas if buscado in normalizar(str(f.get(clave, "")))]


@herramienta(
    "buscar_partido",
    "Encuentra partidos a partir de un texto libre ('Real Madrid vs Barcelona', "
    "una URL de Sofascore o un id). Devuelve los candidatos con su id, fecha y "
    "competición. Úsala primero cuando no tengas claro de qué partido se habla, "
    "o cuando dos equipos se hayan cruzado varias veces.",
    {
        "consulta": {"type": "string", "description": "Equipos, URL o id del partido."},
        "fecha": {"type": "string", "description": "AAAA-MM-DD. Filtra a ese día exacto."},
        "limite": {"type": "integer",
                   "description": "Cuántos candidatos devolver (por defecto 8)."},
    },
    ["consulta"],
)
def _buscar_partido(sesion, consulta: str, fecha: str | None = None, limite: int = 8):
    resolucion = sesion.resolucion(consulta, fecha)
    return {
        "elegido": resolucion.event.to_dict(),
        "aviso": resolucion.warning or None,
        "candidatos": [
            {
                "id": c.event.id,
                "partido": f"{c.event.home} - {c.event.away}",
                "marcador": c.event.scoreline,
                "fecha": c.event.date,
                "competicion": c.event.tournament,
                "encaje": round(c.score, 2),
            }
            for c in resolucion.candidates[:limite]
        ],
    }


@herramienta(
    "resumen_partido",
    "El punto de partida para analizar un partido: marcador, competición, sede, "
    "árbitro, goles, mejores valoraciones y —lo importante— QUÉ SECCIONES DE "
    "DATOS hay disponibles para ese partido. Empieza siempre por aquí y luego "
    "pide el detalle que necesites con las demás herramientas.",
    {
        "partido": {"type": "string", "description": "Id, URL o 'Equipo A vs Equipo B'."},
        "fecha": {"type": "string", "description": "AAAA-MM-DD, para desambiguar."},
    },
    ["partido"],
)
def _resumen_partido(sesion, partido: str, fecha: str | None = None):
    evento = sesion.evento(partido, fecha)
    informe = sesion.informe(evento)
    posesion = informe.statistic("ballPossession")
    xg = informe.statistic("expectedGoals")
    return {
        "partido": evento.to_dict(),
        "goles": [
            {
                "minuto": g.get("time"),
                "jugador": (g.get("player") or {}).get("name", ""),
                "equipo": _lado(evento, g.get("isHome")),
                "marcador": f"{g.get('homeScore')}-{g.get('awayScore')}",
            }
            for g in informe.goals()
        ],
        "claves": {
            "posesion": [posesion.get("home"), posesion.get("away")] if posesion else None,
            "xg": [xg.get("home"), xg.get("away")] if xg else None,
        },
        "mejores_valoraciones": informe.ratings()[:5],
        "secciones_con_datos": informe.available(),
        "secciones_vacias_o_no_disponibles": informe.empty() + informe.failed(),
        "secciones_que_requieren_plus": informe.locked(),
        "como_seguir": "Usa estadisticas_partido, jugadores_partido, tiros_partido, "
                       "cronologia_partido, momento_partido o seccion_partido "
                       "(esta última para cualquier sección del catálogo).",
    }


@herramienta(
    "estadisticas_partido",
    "Las estadísticas de equipo de un partido, en filas planas: posesión, tiros, "
    "xG, pases, duelos, defensa, portería. Se pueden pedir por periodo para "
    "comparar primera y segunda parte.",
    {
        "partido": {"type": "string", "description": "Id, URL o nombres de los equipos."},
        "periodo": {"type": "string", "enum": ["ALL", "1ST", "2ND"],
                    "description": "Todo el partido (ALL, por defecto), 1ª o 2ª parte."},
        "grupo": {"type": "string",
                  "description": "Filtra a un bloque: Shots, Attack, Passes, Duels, "
                                 "Defending, Goalkeeping..."},
    },
    ["partido"],
)
def _estadisticas_partido(sesion, partido: str, periodo: str = "ALL", grupo: str | None = None):
    evento = sesion.evento(partido)
    informe = sesion.informe(evento, ["statistics"])
    filas = informe.statistics_table(periodo)
    if grupo:
        from ..resolve import normalizar

        buscado = normalizar(grupo)
        filas = [f for f in filas if buscado in normalizar(str(f.get("grupo", "")))]
    return {
        "partido": f"{evento.home} {evento.scoreline} {evento.away}",
        "periodo": periodo,
        "local": evento.home.name,
        "visitante": evento.away.name,
        "estadisticas": filas,
        "grupos_disponibles": sorted({f["grupo"] for f in informe.statistics_table(periodo)}),
    }


@herramienta(
    "jugadores_partido",
    "Los jugadores de un partido con su valoración, minutos, posición y dorsal, "
    "ordenados de mejor a peor nota. Sirve para saber quién decidió el partido "
    "y quién falló.",
    {
        "partido": {"type": "string", "description": "Id, URL o nombres de los equipos."},
        "equipo": {"type": "string", "description": "Solo los de este equipo."},
        "solo_titulares": {"type": "boolean", "description": "Dejar fuera a los suplentes."},
    },
    ["partido"],
)
def _jugadores_partido(sesion, partido: str, equipo: str | None = None,
                       solo_titulares: bool = False):
    evento = sesion.evento(partido)
    informe = sesion.informe(evento, ["lineups"])
    equipos = {evento.home.id: evento.home.name, evento.away.id: evento.away.name}
    filas = []
    for jugador in informe.players():
        if solo_titulares and jugador.substitute:
            continue
        estadisticas = (jugador.raw or {}).get("statistics") or {}
        filas.append({
            "jugador": jugador.name,
            "id": jugador.id,
            "equipo": equipos.get(jugador.team_id, ""),
            "posicion": jugador.position,
            "dorsal": jugador.shirt_number,
            "suplente": jugador.substitute,
            "minutos": estadisticas.get("minutesPlayed"),
            "rating": estadisticas.get("rating"),
            "goles": estadisticas.get("goals"),
            "asistencias": estadisticas.get("goalAssist"),
        })
    filas = _filtrar_por_equipo(filas, equipo)
    filas.sort(key=lambda f: -(f["rating"] or 0))
    return {"partido": f"{evento.home} {evento.scoreline} {evento.away}", "jugadores": filas}


@herramienta(
    "tiros_partido",
    "El mapa de tiros: cada disparo con su xG, minuto, jugador, parte del cuerpo, "
    "situación (jugada, córner, penalti) y resultado. Es lo que permite decir si "
    "un resultado fue justo o si alguien acertó por encima de lo esperable.",
    {
        "partido": {"type": "string", "description": "Id, URL o nombres de los equipos."},
        "equipo": {"type": "string", "description": "Solo los tiros de este equipo."},
        "jugador": {"type": "string", "description": "Solo los tiros de este jugador."},
        "solo_goles": {"type": "boolean", "description": "Únicamente los que acabaron en gol."},
    },
    ["partido"],
)
def _tiros_partido(sesion, partido: str, equipo: str | None = None,
                   jugador: str | None = None, solo_goles: bool = False):
    from ..resolve import normalizar

    evento = sesion.evento(partido)
    informe = sesion.informe(evento, ["shotmap"])
    filas = []
    for tiro in informe.shots():
        filas.append({
            "minuto": tiro.get("time"),
            "jugador": (tiro.get("player") or {}).get("name", ""),
            "equipo": _lado(evento, tiro.get("isHome")),
            "resultado": tiro.get("shotType"),
            "situacion": tiro.get("situation"),
            "parte_cuerpo": tiro.get("bodyPart"),
            "xg": tiro.get("xg"),
            "xgot": tiro.get("xgot"),
            "distancia": (tiro.get("playerCoordinates") or {}).get("x"),
        })
    filas = _filtrar_por_equipo(filas, equipo)
    if jugador:
        buscado = normalizar(jugador)
        filas = [f for f in filas if buscado in normalizar(f["jugador"])]
    if solo_goles:
        filas = [f for f in filas if f["resultado"] == "goal"]
    filas.sort(key=lambda f: f["minuto"] or 0)
    xg_total: dict[str, float] = {}
    for fila in filas:
        if fila["xg"]:
            xg_total[fila["equipo"]] = round(xg_total.get(fila["equipo"], 0) + fila["xg"], 2)
    return {
        "partido": f"{evento.home} {evento.scoreline} {evento.away}",
        "tiros": filas,
        "xg_acumulado": xg_total,
        "nota": None if filas else "Este partido no trae mapa de tiros.",
    }


@herramienta(
    "cronologia_partido",
    "Qué pasó y cuándo: goles, tarjetas, cambios, penaltis y decisiones del VAR, "
    "en orden. Útil para explicar cómo se torció o se decidió un partido.",
    {
        "partido": {"type": "string", "description": "Id, URL o nombres de los equipos."},
        "tipo": {"type": "string",
                 "description": "Filtra por tipo: goal, card, substitution, varDecision."},
    },
    ["partido"],
)
def _cronologia_partido(sesion, partido: str, tipo: str | None = None):
    evento = sesion.evento(partido)
    informe = sesion.informe(evento, ["incidents"])
    filas = []
    for i in informe.incidents(tipo):
        if i.get("incidentType") in {"period", "injuryTime"} and not tipo:
            continue
        filas.append({
            "minuto": i.get("time"),
            "anadido": i.get("addedTime"),
            "tipo": i.get("incidentType"),
            "detalle": i.get("incidentClass"),
            "equipo": _lado(evento, i.get("isHome")),
            "jugador": (i.get("player") or i.get("playerIn") or {}).get("name", ""),
            "sale": (i.get("playerOut") or {}).get("name", ""),
            "asistencia": (i.get("assist1") or {}).get("name", ""),
            "marcador": (f"{i.get('homeScore')}-{i.get('awayScore')}"
                         if i.get("homeScore") is not None else None),
        })
    return {"partido": f"{evento.home} {evento.scoreline} {evento.away}", "cronologia": filas}


@herramienta(
    "momento_partido",
    "El gráfico de dominio minuto a minuto: valores positivos, ataca el local; "
    "negativos, el visitante. Sirve para localizar los tramos en que un equipo "
    "se hizo dueño del partido.",
    {
        "partido": {"type": "string", "description": "Id, URL o nombres de los equipos."},
        "cada": {"type": "integer",
                 "description": "Agrupar en tramos de N minutos (por defecto 5). "
                                "Usa 1 para el detalle completo."},
    },
    ["partido"],
)
def _momento_partido(sesion, partido: str, cada: int = 5):
    evento = sesion.evento(partido)
    informe = sesion.informe(evento, ["momentum"])
    puntos = [p for p in (informe.get("momentum") or []) if isinstance(p, dict)]
    if cada <= 1:
        serie = [{"minuto": p.get("minute"), "valor": p.get("value")} for p in puntos]
    else:
        tramos: dict[int, list[float]] = {}
        for punto in puntos:
            minuto = punto.get("minute") or 0
            tramos.setdefault(int(minuto // cada) * cada, []).append(punto.get("value") or 0)
        serie = [
            {"desde_minuto": inicio, "hasta_minuto": inicio + cada - 1,
             "media": round(sum(v) / len(v), 1), "dominio": (
                 evento.home.name if sum(v) > 0 else evento.away.name)}
            for inicio, v in sorted(tramos.items())
        ]
    return {
        "partido": f"{evento.home} {evento.scoreline} {evento.away}",
        "positivo_es": evento.home.name,
        "negativo_es": evento.away.name,
        "serie": serie,
    }


@herramienta(
    "seccion_partido",
    "La escotilla de escape: devuelve cualquier sección del catálogo tal como la "
    "da Sofascore. Úsala cuando ninguna de las herramientas anteriores cubra lo "
    "que buscas. Consulta antes 'catalogo' para ver los nombres válidos.",
    {
        "partido": {"type": "string", "description": "Id, URL o nombres de los equipos."},
        "seccion": {"type": "string",
                    "description": "Nombre de la sección: odds, h2h, pregame_form, "
                                   "average_positions, best_players, managers..."},
    },
    ["partido", "seccion"],
)
def _seccion_partido(sesion, partido: str, seccion: str):
    if seccion not in SECTIONS:
        return {"error": f"Sección desconocida: '{seccion}'.",
                "disponibles": sorted(SECTIONS)}
    evento = sesion.evento(partido)
    informe = sesion.informe(evento, [seccion])
    resultado = informe.sections[seccion]
    return {
        "partido": f"{evento.home} {evento.scoreline} {evento.away}",
        "seccion": seccion,
        "estado": resultado.status,
        "descripcion": resultado.description,
        "datos": resultado.data,
        "error": resultado.error or None,
    }


@herramienta(
    "historial_entre_equipos",
    "El cara a cara: cuántas veces ha ganado cada uno y sus enfrentamientos "
    "anteriores con resultado y fecha. Da el contexto que un solo partido no tiene.",
    {"partido": {"type": "string", "description": "Un partido entre los dos equipos."}},
    ["partido"],
)
def _historial(sesion, partido: str):
    evento = sesion.evento(partido)
    informe = sesion.informe(evento, ["h2h", "h2h_events"])
    anteriores = [
        {
            "fecha": Event.from_api(e).date,
            "partido": f"{Event.from_api(e).home} {Event.from_api(e).scoreline} "
                       f"{Event.from_api(e).away}",
            "competicion": Event.from_api(e).tournament,
            "id": Event.from_api(e).id,
        }
        for e in (informe.get("h2h_events") or [])
    ]
    return {
        "equipos": [evento.home.name, evento.away.name],
        "balance": informe.get("h2h"),
        "enfrentamientos_anteriores": sorted(anteriores, key=lambda a: a["fecha"], reverse=True),
    }


