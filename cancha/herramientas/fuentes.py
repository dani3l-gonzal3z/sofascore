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
    "noticias",
    "TITULARES de una liga o de un equipo, de ESPN: lesiones, sanciones, "
    "destituciones, fichajes. Es el contexto que ningún número trae. Úsala "
    "antes de una previa para saber si falta alguien o si el entrenador es "
    "nuevo. Cubre las grandes ligas, MLS, Arabia y las copas europeas.",
    {
        "liga": {"type": "string", "description": "'laliga', 'premier', 'mls', 'champions'..."},
        "equipo": {"type": "string", "description": "Solo las que mencionen a este equipo."},
        "cuantas": {"type": "integer", "description": "Cuántas (por defecto 15)."},
    },
    ["liga"],
)
def _noticias(sesion, liga: str, equipo: str | None = None, cuantas: int = 15):
    from ..sources import ESPN

    fuente = ESPN()
    try:
        return {"liga": liga, "equipo": equipo,
                "noticias": fuente.noticias(liga, cuantas=cuantas, equipo=equipo)}
    finally:
        fuente.close()


@herramienta(
    "agenda_espn",
    "La agenda de un día según ESPN, con su línea de apuestas (favorito y "
    "más/menos de goles) y, en partidos acabados, el marcador. Es una fuente "
    "independiente de Sofascore: úsala para contrastar la agenda o cuando la "
    "otra no conteste. Sus ids no son los de Sofascore.",
    {
        "fecha": {"type": "string", "description": "AAAA-MM-DD (por defecto, hoy)."},
        "liga": {"type": "string",
                 "description": "Una liga concreta; sin ella, todas las que cubre."},
    },
)
def _agenda_espn(sesion, fecha: str | None = None, liga: str | None = None):
    from ..sources import ESPN

    fuente = ESPN()
    try:
        partidos = fuente.agenda(liga, fecha) if liga else fuente.agenda_del_dia(fecha)
        return {"fecha": fecha or "hoy", "total": len(partidos), "partidos": partidos}
    finally:
        fuente.close()


@herramienta(
    "historial_de_liga",
    "TODOS LOS PARTIDOS de una liga en una temporada según football-data.co.uk: "
    "resultado, tiros, córners, tarjetas, árbitro y cuotas de cierre. Desde "
    "1993, sin límite. Con `equipo`, solo los suyos. Es de donde sale el "
    "historial largo (veinte temporadas) y quién era favorito en cada partido. "
    "Cubre las cinco grandes, sus segundas, Países Bajos, Portugal y Turquía.",
    {
        "liga": {"type": "string", "description": "'laliga', 'premier', 'SP1', 'E0'..."},
        "temporada": {"type": "integer",
                      "description": "Año de inicio: 2024 para la 24/25."},
        "equipo": {"type": "string", "description": "Solo los partidos de este equipo."},
        "cuantos": {"type": "integer", "description": "Tope de partidos (por defecto 60)."},
    },
    ["liga", "temporada"],
)
def _historial_de_liga(sesion, liga: str, temporada: int, equipo: str | None = None,
                       cuantos: int = 60):
    from ..sources import FutbolData

    fuente = FutbolData()
    try:
        partidos = (fuente.equipo(liga, temporada, equipo) if equipo
                    else fuente.temporada(liga, temporada))
        return {"liga": fuente.codigo(liga), "temporada": temporada, "equipo": equipo,
                "total": len(partidos), "partidos": partidos[:cuantos]}
    finally:
        fuente.close()


@herramienta(
    "rellenar_cuotas",
    "Pone QUIÉN ERA FAVORITO a los partidos guardados en la memoria que no "
    "tienen cuotas, con las de cierre de football-data.co.uk. Hazlo antes de "
    "usar sistema_o_contexto si la memoria se barrió sin cuotas. Tarda: un CSV "
    "por liga y temporada.",
    {
        "maximo": {"type": "integer", "description": "Tope de partidos a rellenar."},
    },
)
def _rellenar_cuotas(sesion, maximo: int = 0):
    from ..sources import rellenar_cuotas

    return rellenar_cuotas(sesion.almacen, maximo=maximo)


@herramienta(
    "datos_externos",
    "FBref, Transfermarkt, Capology y SoFIFA a través de ScraperFC o soccerdata, "
    "si están instaladas (mira `fuentes`). `que` es: fbref_equipos, "
    "fbref_jugadores, fbref_calendario (soccerdata, sin navegador, cinco grandes "
    "ligas) o fbref_estadisticas, transfermarkt_valores, capology_salarios "
    "(ScraperFC; FBref abre un navegador). Tarda y necesita red: pide poco y "
    "concreto. Si la librería no está, la respuesta dice qué instalar.",
    {
        "que": {"type": "string",
                "enum": ["fbref_equipos", "fbref_jugadores", "fbref_calendario",
                         "fbref_estadisticas", "transfermarkt_valores", "capology_salarios",
                         "sofifa_valoraciones", "temporadas"],
                "description": "Qué tabla."},
        "liga": {"type": "string", "description": "'laliga', 'premier'..."},
        "temporada": {"type": "string",
                      "description": "soccerdata: 2024 o '24-25'. ScraperFC: como diga "
                                     "`temporadas` ('2024-2025', '24/25')."},
        "tipo": {"type": "string",
                 "description": "Categoría de FBref: standard, shooting, passing, "
                                "defense, possession, misc, keeper..."},
        "maximo": {"type": "integer", "description": "Tope de filas (por defecto 60)."},
    },
    ["que", "liga"],
)
def _datos_externos(sesion, que: str, liga: str, temporada: str | None = None,
                    tipo: str = "standard", maximo: int = 60):
    from ..sources import AdaptadorNoDisponible, adaptador

    try:
        if que in ("fbref_equipos", "fbref_jugadores", "fbref_calendario", "sofifa_valoraciones"):
            sd = adaptador("soccerdata")
            temporada_sd: int | str = int(temporada) if temporada and temporada.isdigit() \
                else (temporada or 2024)
            if que == "fbref_equipos":
                filas = sd.fbref_equipos(liga, temporada_sd, tipo=tipo, maximo=maximo)
            elif que == "fbref_jugadores":
                filas = sd.fbref_jugadores(liga, temporada_sd, tipo=tipo, maximo=maximo)
            elif que == "fbref_calendario":
                filas = sd.fbref_calendario(liga, temporada_sd, maximo=maximo)
            else:
                filas = sd.sofifa_valoraciones(liga, temporada_sd, maximo=maximo)
            return {"libreria": "soccerdata", "que": que, "filas": filas}
        sfc = adaptador("scraperfc")
        if que == "temporadas":
            return {"libreria": "scraperfc", "temporadas": {
                modulo: sfc.temporadas(modulo, liga)
                for modulo in ("fbref", "transfermarkt", "capology")}}
        if not temporada:
            return {"error": "Hace falta `temporada`; pide `que: temporadas` para ver el formato."}
        if que == "fbref_estadisticas":
            return {"libreria": "scraperfc", "que": que,
                    "tablas": sfc.fbref_estadisticas(liga, temporada, tipo, maximo=maximo)}
        if que == "transfermarkt_valores":
            return {"libreria": "scraperfc", "que": que,
                    "filas": sfc.transfermarkt_valores(liga, temporada, maximo=maximo)}
        return {"libreria": "scraperfc", "que": que,
                "filas": sfc.capology_salarios(liga, temporada, maximo=maximo)}
    except AdaptadorNoDisponible as exc:
        return {"error": str(exc), "instalar": "pip install ScraperFC soccerdata"}
    except (ValueError, KeyError) as exc:
        return {"error": str(exc)}


@herramienta(
    "fuentes",
    "Qué fuentes de datos hay además de Sofascore y qué aporta cada una. "
    "Consúltalo si no sabes de dónde puede salir un dato.",
    {},
)
def _fuentes(sesion):
    from ..sources import FUENTES, construir, disponibles

    return {
        "principal": {
            "sofascore": "Partidos, equipos, jugadores y competiciones. "
                         "Es la fuente de todas las demás herramientas."
        },
        "adicionales": {n: construir(n).descripcion for n in sorted(FUENTES)},
        "librerias_externas": disponibles(),
        "cruzarlas": "contexto_externo junta todas sobre un mismo partido y "
                     "calcula la diferencia entre los dos modelos de xG.",
    }


