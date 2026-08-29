"""Herramientas para que una IA use el framework.

Un modelo no puede tragarse el JSON completo de un partido: son megas de datos
anidados. Lo que necesita es un puñado de herramientas bien descritas que
devuelvan poco y le dejen **ir tirando del hilo**: primero qué hay, luego el
trozo que le interese, luego el detalle.

Eso es lo que hay aquí. Cada herramienta trae su esquema JSON, pensado para
function calling, y devuelve datos ya aplanados y recortados. Se usan desde
cualquier sitio::

    from cancha.tools import TOOLS, ejecutar, esquemas

    esquemas()                       # las definiciones, para dárselas al modelo
    ejecutar("resumen_partido", {"partido": "Real Madrid vs Barcelona"})

Y por MCP, que es como se conecta una IA local (:mod:`cancha.mcp`).

Sobre el recorte: toda respuesta pasa por un tope de caracteres. Cuando algo no
cabe, se corta y se dice cuánto se ha quedado fuera, en vez de reventar la
ventana de contexto del modelo en silencio.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .catalog import KNOWN_STAT_KEYS, LEAGUES
from .client import SofascoreClient
from .endpoints import CATALOGS, SECTIONS
from .entities import build_player_report, build_team_report, build_tournament_report
from .errors import SofascoreError
from .match import build_report
from .models import Event
from .resolve import resolve_event

#: Tope de caracteres por respuesta. Generoso para un modelo de 128k, pero
#: suficiente para que un mapa de tiros entero no se lleve el contexto por
#: delante.
MAX_CHARS = 20_000


@dataclass(frozen=True)
class Tool:
    """Una herramienta que la IA puede llamar."""

    name: str
    description: str
    parameters: dict
    handler: Callable[..., Any]

    def schema(self) -> dict:
        """La definición en el formato que esperan los modelos con function calling."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }


TOOLS: dict[str, Tool] = {}


def herramienta(nombre: str, descripcion: str, propiedades: dict,
                obligatorios: list[str] | None = None):
    """Registra una función como herramienta."""
    def decorador(fn):
        TOOLS[nombre] = Tool(
            name=nombre,
            description=descripcion,
            parameters={
                "type": "object",
                "properties": propiedades,
                "required": obligatorios or [],
            },
            handler=fn,
        )
        return fn
    return decorador


# --------------------------------------------------------------------- recorte

def recortar(datos: Any, max_chars: int = MAX_CHARS) -> Any:
    """Deja los datos por debajo del tope, diciendo qué se ha quitado.

    Con una lista se van soltando elementos del final hasta que cabe, y se
    añade una nota con cuántos faltan: el modelo sabe entonces que hay más y
    puede pedir el resto afinando la consulta.
    """
    texto = json.dumps(datos, ensure_ascii=False, default=str)
    if len(texto) <= max_chars:
        return datos

    if isinstance(datos, list):
        cabe = datos
        while cabe and len(json.dumps(cabe, ensure_ascii=False, default=str)) > max_chars - 200:
            cabe = cabe[: int(len(cabe) * 0.8)] if len(cabe) > 10 else cabe[:-1]
        return {
            "elementos": cabe,
            "recortado": True,
            "nota": f"Se enseñan {len(cabe)} de {len(datos)}. "
                    "Afina la consulta (por equipo, por jugador, por periodo) para ver el resto.",
        }

    if isinstance(datos, dict):
        salida: dict[str, Any] = {}
        fuera = []
        for clave, valor in datos.items():
            trozo = json.dumps({clave: valor}, ensure_ascii=False, default=str)
            if len(json.dumps(salida, ensure_ascii=False, default=str)) + len(trozo) < max_chars:
                salida[clave] = valor
            else:
                fuera.append(clave)
        if fuera:
            salida["_recortado"] = f"Faltan estas claves por tamaño: {', '.join(fuera)}."
        return salida

    return texto[:max_chars] + " …[recortado]"


# ------------------------------------------------------------------- ayudantes

def _evento(cliente: SofascoreClient, partido: str | int, fecha: str | None = None) -> Event:
    """Resuelve lo que la IA haya escrito (id, URL o nombres) a un partido."""
    return resolve_event(cliente, partido, date=fecha).event


def _lado(evento: Event, es_local: Any) -> str:
    if es_local is None:
        return ""
    return evento.home.name if es_local else evento.away.name


def _filtrar_por_equipo(filas: list[dict], equipo: str | None, clave: str = "equipo") -> list[dict]:
    if not equipo:
        return filas
    from .resolve import normalizar

    buscado = normalizar(equipo)
    return [f for f in filas if buscado in normalizar(str(f.get(clave, "")))]


# ---------------------------------------------------------------- herramientas

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
def _buscar_partido(cliente, consulta: str, fecha: str | None = None, limite: int = 8):
    resolucion = resolve_event(cliente, consulta, date=fecha)
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
def _resumen_partido(cliente, partido: str, fecha: str | None = None):
    evento = _evento(cliente, partido, fecha)
    informe = build_report(cliente, evento)
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
def _estadisticas_partido(cliente, partido: str, periodo: str = "ALL", grupo: str | None = None):
    evento = _evento(cliente, partido)
    informe = build_report(cliente, evento, sections=["statistics"])
    filas = informe.statistics_table(periodo)
    if grupo:
        from .resolve import normalizar

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
def _jugadores_partido(cliente, partido: str, equipo: str | None = None,
                       solo_titulares: bool = False):
    evento = _evento(cliente, partido)
    informe = build_report(cliente, evento, sections=["lineups"])
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
def _tiros_partido(cliente, partido: str, equipo: str | None = None,
                   jugador: str | None = None, solo_goles: bool = False):
    from .resolve import normalizar

    evento = _evento(cliente, partido)
    informe = build_report(cliente, evento, sections=["shotmap"])
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
def _cronologia_partido(cliente, partido: str, tipo: str | None = None):
    evento = _evento(cliente, partido)
    informe = build_report(cliente, evento, sections=["incidents"])
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
def _momento_partido(cliente, partido: str, cada: int = 5):
    evento = _evento(cliente, partido)
    informe = build_report(cliente, evento, sections=["momentum"])
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
def _seccion_partido(cliente, partido: str, seccion: str):
    if seccion not in SECTIONS:
        return {"error": f"Sección desconocida: '{seccion}'.",
                "disponibles": sorted(SECTIONS)}
    evento = _evento(cliente, partido)
    informe = build_report(cliente, evento, sections=[seccion])
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
def _historial(cliente, partido: str):
    evento = _evento(cliente, partido)
    informe = build_report(cliente, evento, sections=["h2h", "h2h_events"])
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
def _ficha_equipo(cliente, equipo: str, secciones: list[str] | None = None):
    informe = build_team_report(cliente, equipo, sections=secciones)
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
def _ficha_jugador(cliente, jugador: str, secciones: list[str] | None = None):
    informe = build_player_report(cliente, jugador, sections=secciones)
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
def _clasificacion(cliente, liga: str, temporada: int | None = None):
    informe = build_tournament_report(
        cliente, liga, season_id=temporada, sections=["profile", "standings"]
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
def _partidos(cliente, fecha: str | None = None, liga: str | None = None, limite: int = 30):
    from .catalog import find_league

    crudos = cliente.scheduled_events(fecha) if fecha else cliente.live_events()
    eventos = [Event.from_api(e) for e in crudos]
    if liga:
        identificador = find_league(liga)
        if identificador:
            eventos = [e for e in eventos if e.unique_tournament_id == identificador]
        else:
            from .resolve import normalizar

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
def _catalogo(cliente, que: str = "todo"):
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


# ----------------------------------------------------------- métricas calculadas

@herramienta(
    "analisis_partido",
    "LAS CUENTAS YA HECHAS. No devuelve filas para que las sumes: devuelve los "
    "números calculados, que es lo que un modelo hace mal. Trae puntos "
    "esperados (¿ganó el que mereció?), calidad de tiro (¿tres ocasiones claras "
    "o quince chutes de lejos?), la carrera de xG minuto a minuto, el desglose "
    "por situación de juego, quién generó el peligro y la comparación entre las "
    "dos partes. Úsala en cuanto te pidan valorar un partido; no rehagas tú "
    "estas cuentas.",
    {
        "partido": {"type": "string", "description": "Id, URL o 'Equipo A vs Equipo B'."},
        "fecha": {"type": "string", "description": "AAAA-MM-DD, para desambiguar."},
        "cada": {"type": "integer",
                 "description": "Minutos por tramo en la carrera de xG (por defecto 15)."},
    },
    ["partido"],
)
def _analisis_partido(cliente, partido: str, fecha: str | None = None, cada: int = 15):
    from .analisis import analisis_completo

    evento = _evento(cliente, partido, fecha)
    informe = build_report(cliente, evento, sections=["statistics", "shotmap", "incidents",
                                                      "lineups"])
    return analisis_completo(informe, cada=cada)


@herramienta(
    "puntos_esperados",
    "¿Ganó el que mereció? Calcula, a partir del xG de cada disparo, la "
    "probabilidad de victoria, empate y derrota, y los puntos que merecía cada "
    "equipo. Es una convolución exacta sobre los tiros, no una estimación a "
    "ojo: no intentes reproducirla tú.",
    {
        "partido": {"type": "string", "description": "Id, URL o 'Equipo A vs Equipo B'."},
        "fecha": {"type": "string", "description": "AAAA-MM-DD, para desambiguar."},
    },
    ["partido"],
)
def _puntos_esperados(cliente, partido: str, fecha: str | None = None):
    from .analisis import puntos_esperados

    evento = _evento(cliente, partido, fecha)
    return puntos_esperados(build_report(cliente, evento, sections=["shotmap"]))


@herramienta(
    "carrera_xg",
    "El xG acumulado de cada equipo minuto a minuto: cuándo se generó el "
    "peligro, no solo cuánto. Dice además quién manda en xG y desde qué minuto "
    "dejó de perder esa ventaja. Un 2.5 hecho en diez minutos finales no es el "
    "mismo partido que un 2.5 repartido.",
    {
        "partido": {"type": "string", "description": "Id, URL o 'Equipo A vs Equipo B'."},
        "cada": {"type": "integer", "description": "Minutos por tramo (1 para el detalle)."},
    },
    ["partido"],
)
def _carrera_xg(cliente, partido: str, cada: int = 5):
    from .analisis import carrera_xg

    evento = _evento(cliente, partido)
    return carrera_xg(build_report(cliente, evento, sections=["shotmap"]), cada=cada)


@herramienta(
    "aportacion_jugadores",
    "Quién generó el peligro de verdad: xG disparado, goles, asistencias y "
    "valoración, por jugador y ordenado por xG. Más informativo que la nota, "
    "que premia el partido completo.",
    {
        "partido": {"type": "string", "description": "Id, URL o 'Equipo A vs Equipo B'."},
        "minimo_xg": {"type": "number",
                      "description": "Deja fuera a quien no llegue a este xG (por defecto 0.05)."},
    },
    ["partido"],
)
def _aportacion_jugadores(cliente, partido: str, minimo_xg: float = 0.05):
    from .analisis import aportacion_jugadores

    evento = _evento(cliente, partido)
    informe = build_report(cliente, evento, sections=["shotmap", "incidents", "lineups"])
    return aportacion_jugadores(informe, minimo_xg=minimo_xg)


# ------------------------------------------- otras fuentes, y el cruce entre ellas

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
def _contexto_externo(cliente, partido: str, fecha: str | None = None):
    from .sources import contexto_partido

    return contexto_partido(cliente, partido, fecha=fecha)


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
def _elo_equipo(cliente, equipo: str, historico: bool = False):
    from .sources import ClubElo

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
def _ranking_elo(cliente, cuantos: int = 20, pais: str | None = None, fecha: str | None = None):
    from .sources import ClubElo

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
def _tiros_understat(cliente, partido_understat: int):
    from .sources import Understat

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
def _fuentes(cliente):
    from .sources import FUENTES, construir

    return {
        "principal": {
            "sofascore": "Partidos, equipos, jugadores y competiciones. "
                         "Es la fuente de todas las demás herramientas."
        },
        "adicionales": {n: construir(n).descripcion for n in sorted(FUENTES)},
        "cruzarlas": "contexto_externo junta todas sobre un mismo partido y "
                     "calcula la diferencia entre los dos modelos de xG.",
    }


# ------------------------------------------------------------------- ejecución

def esquemas() -> list[dict]:
    """Las definiciones de todas las herramientas, para dárselas al modelo."""
    return [t.schema() for t in TOOLS.values()]


def ejecutar(
    nombre: str,
    argumentos: dict | None = None,
    cliente: SofascoreClient | None = None,
    max_chars: int = MAX_CHARS,
) -> dict:
    """Ejecuta una herramienta y devuelve su resultado, ya recortado.

    Nunca lanza: un fallo se devuelve como ``{"error": ...}`` para que el modelo
    pueda leerlo, entenderlo y reintentar de otra forma.
    """
    if nombre not in TOOLS:
        return {"error": f"No existe la herramienta '{nombre}'.",
                "disponibles": sorted(TOOLS)}
    propio = cliente is None
    cliente = cliente or SofascoreClient()
    try:
        resultado = TOOLS[nombre].handler(cliente, **(argumentos or {}))
        return recortar(resultado, max_chars)
    except SofascoreError as exc:
        return {"error": str(exc), "herramienta": nombre}
    except TypeError as exc:
        return {"error": f"Argumentos incorrectos para '{nombre}': {exc}",
                "esperados": TOOLS[nombre].parameters}
    finally:
        if propio:
            cliente.close()


__all__ = ["TOOLS", "Tool", "esquemas", "ejecutar", "recortar", "MAX_CHARS"]
