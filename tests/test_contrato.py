"""¿Lo que el código da por supuesto está de verdad en la respuesta?

Los demás tests usan respuestas de ejemplo escritas a mano: demuestran que el
código es coherente consigo mismo. Estos usan respuestas **reales**, grabadas
con ``cancha grabar``, y comprueban lo único que aquellos no pueden: que la API
devuelva lo que aquí se supone que devuelve.

No es paranoia. De los dos fallos serios que ha tenido este proyecto, los dos
habrían caído aquí:

* ``/h2h/events`` pide el ``customId``, no el id — estuvo roto dos rondas en
  silencio porque las respuestas de ejemplo no traían ``customId``;
* los cambios de jugador no usan la clave ``player``, así que salían sin nadie.

Sin grabaciones, todo esto se salta con un aviso de cómo grabarlas. No es un
fallo: es que todavía no se ha hecho.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from cancha.grabacion import cargar

REALES = Path(__file__).parent / "fixtures" / "reales"
GRABACIONES = cargar(REALES)

COMO_GRABAR = (
    "No hay respuestas reales grabadas. Consíguelas con:\n"
    "    cancha grabar 12437616\n"
    "y vuelve a lanzar los tests."
)


#: Qué fichero es cada cosa. Con patrones anclados y no con trozos sueltos:
#: buscar "statistics" a secas encuentra antes la de un jugador que la del
#: partido, y el test acabaría comprobando otra cosa sin enterarse.
PATRONES = {
    "evento": r"^sofascore_event_\d+\.json$",
    "estadisticas": r"^sofascore_event_\d+_statistics\.json$",
    "alineaciones": r"^sofascore_event_\d+_lineups\.json$",
    "incidencias": r"^sofascore_event_\d+_incidents\.json$",
    "tiros": r"^sofascore_event_\d+_shotmap\.json$",
    "momento": r"^sofascore_event_\d+_graph\.json$",
    "equipo": r"^sofascore_team_\d+\.json$",
    "plantilla": r"^sofascore_team_\d+_players\.json$",
    "jugador": r"^sofascore_player_\d+\.json$",
    "temporadas_jugador": r"^sofascore_player_\d+_statistics_seasons\.json$",
    "clasificacion": r"^sofascore_unique_tournament_\d+_season_\d+_standings_total\.json$",
    "historico": r"^sofascore_event_[A-Za-z]\w*_h2h_events\.json$",
}


def _buscar(clave: str) -> list[dict]:
    """Los cuerpos de las grabaciones que encajen con ese patrón."""
    patron = re.compile(PATRONES[clave])
    return [
        g.cuerpo for nombre, g in GRABACIONES.items()
        if patron.match(nombre) and not g.texto_plano
    ]


def _una(clave: str):
    """La primera que encaje, o se salta el test diciendo cuál falta."""
    encontradas = _buscar(clave)
    if not encontradas:
        pytest.skip(f"Sin grabación de '{clave}'. {COMO_GRABAR}")
    return encontradas[0]


pytestmark = pytest.mark.skipif(not GRABACIONES, reason=COMO_GRABAR)


def test_hay_grabaciones_y_se_leen():
    assert GRABACIONES
    for nombre, grabacion in GRABACIONES.items():
        assert grabacion.url, nombre
        assert grabacion.estado == 200, nombre


# ------------------------------------------------------------------- el partido

def test_el_evento_trae_lo_que_el_modelo_espera():
    from cancha.models import Event

    crudo = _una("evento")
    evento = Event.from_api(crudo)
    assert evento.id, "sin id"
    assert evento.home.name and evento.away.name, "sin equipos"
    assert evento.status_type, "sin estado"
    assert evento.sport, "sin deporte: el filtro por deporte no funcionaría"


def test_el_evento_trae_el_customId():
    """El fallo que estuvo dos rondas escondido: /h2h/events lo necesita."""
    from cancha.models import Event

    evento = Event.from_api(_una("evento"))
    assert evento.custom_id, (
        "El evento real no trae 'customId'. La sección h2h_events y la última "
        "vía de búsqueda de partidos antiguos dependen de él."
    )


def test_las_estadisticas_tienen_la_forma_que_se_recorre():
    bloques = _una("estadisticas").get("statistics")
    assert bloques, "la clave 'statistics' no está donde se espera"
    periodos = {b.get("period") for b in bloques}
    assert "ALL" in periodos
    item = bloques[0]["groups"][0]["statisticsItems"][0]
    for clave in ("key", "name", "home", "away"):
        assert clave in item, f"un item de estadística sin '{clave}'"


def test_las_alineaciones_traen_valoraciones_y_dorsales():
    crudo = _una("alineaciones")
    assert "home" in crudo and "away" in crudo
    jugadores = crudo["home"]["players"]
    assert jugadores
    alguno = jugadores[0]
    assert "player" in alguno, "el jugador no viene envuelto en 'player'"
    con_nota = [j for j in jugadores if (j.get("statistics") or {}).get("rating")]
    assert con_nota, "ningún jugador trae 'statistics.rating'"


def test_los_cambios_no_usan_la_clave_player():
    """La suposición que quedó sin contrastar al arreglar el exportador."""
    incidencias = _una("incidencias").get("incidents")
    assert incidencias, "la clave 'incidents' no está donde se espera"
    cambios = [i for i in incidencias if i.get("incidentType") == "substitution"]
    if not cambios:
        pytest.skip("El partido grabado no tiene cambios.")
    alguno = cambios[0]
    assert "player" not in alguno or not alguno.get("player"), (
        "Resulta que los cambios SÍ usan 'player': _nombre() en export.py "
        "puede simplificarse."
    )
    claves = set(alguno)
    assert claves & {"playerIn", "playerOut"}, (
        f"Un cambio real trae estas claves: {sorted(claves)}. "
        "Ninguna es playerIn/playerOut, así que export.py los pierde."
    )


def test_los_goles_traen_la_asistencia_donde_se_busca():
    incidencias = _una("incidencias").get("incidents")
    goles = [i for i in incidencias if i.get("incidentType") == "goal"]
    if not goles:
        pytest.skip("El partido grabado no tiene goles.")
    asistidos = [g for g in goles if g.get("assist1")]
    if not asistidos:
        pytest.skip("Ningún gol del partido grabado llevó asistencia.")
    assert (asistidos[0]["assist1"] or {}).get("name"), "assist1 sin 'name'"


def test_el_mapa_de_tiros_trae_el_xg():
    tiros = _una("tiros").get("shotmap")
    assert tiros, "la clave 'shotmap' no está donde se espera"
    alguno = tiros[0]
    for clave in ("isHome", "shotType", "xg", "player"):
        assert clave in alguno, f"un tiro sin '{clave}': el análisis lo necesita"
    assert isinstance(alguno["xg"], (int, float)), "el xg no es un número"


def test_los_goles_del_mapa_de_tiros_cuadran_con_el_marcador():
    """El fallo que tenían las respuestas de ejemplo, ahora contra la realidad."""
    from cancha.models import Event

    evento = Event.from_api(_una("evento"))
    tiros = _una("tiros").get("shotmap") or []
    if not tiros:
        pytest.skip("Sin mapa de tiros.")
    goles = {"local": 0, "visitante": 0}
    for tiro in tiros:
        if tiro.get("shotType") == "goal":
            goles["local" if tiro.get("isHome") else "visitante"] += 1
    # Un penalti en la tanda no cuenta para el marcador del tiempo reglamentario.
    assert goles["local"] <= (evento.home_score.current or 0)
    assert goles["visitante"] <= (evento.away_score.current or 0)


# ---------------------------------------------------- equipos, jugadores, ligas

def test_la_ficha_de_equipo_se_desenvuelve_por_team():
    crudo = _una("equipo")
    assert "team" in crudo, "TEAM_SECTIONS['profile'] desenvuelve por 'team'"
    assert crudo["team"].get("name")


def test_la_ficha_de_jugador_se_desenvuelve_por_player():
    crudo = _una("jugador")
    assert "player" in crudo, "PLAYER_SECTIONS['profile'] desenvuelve por 'player'"
    assert crudo["player"].get("name")


def test_el_indice_de_temporadas_permite_deducir_liga_y_temporada():
    """De aquí salen los ids con los que se piden las estadísticas de temporada."""
    from cancha.entities import temporada_mas_reciente

    crudo = _una("temporadas_jugador")
    deducido = temporada_mas_reciente(crudo)
    assert deducido.get("tournament_id") and deducido.get("season_id"), (
        f"No se han podido deducir los ids del índice real. Claves: {sorted(crudo)}"
    )


def test_la_clasificacion_se_desenvuelve_por_standings():
    crudo = _una("clasificacion")
    assert "standings" in crudo
    filas = crudo["standings"][0].get("rows")
    assert filas and filas[0].get("team", {}).get("name")


# ------------------------------------------------------- el informe, de verdad

def test_un_informe_completo_contra_respuestas_reales():
    """La prueba de fuego: montar el informe sirviendo lo que la API respondió."""
    from cancha.cache import MemoryCache
    from cancha.client import SofascoreClient
    from cancha.config import Settings
    from cancha.grabacion import Reproductor
    from cancha.models import Event

    evento = Event.from_api(_una("evento"))
    reproductor = Reproductor(REALES)
    cliente = SofascoreClient(
        Settings(rate_limit=0, retries=0, cache_ttl=0, fallback_base_urls=()),
        transport=reproductor, cache=MemoryCache(), sleep=lambda _s: None,
    )
    from cancha.match import build_report

    informe = build_report(cliente, evento.id, sections=["all"], max_players=3)
    assert informe.available(), "ninguna sección ha salido adelante"
    # Lo que sí se grabó tiene que salir bien; lo que no, queda como no disponible.
    assert "event" in informe.available()
    for seccion in ("statistics", "lineups", "incidents"):
        if _buscar({"statistics": "estadisticas", "lineups": "alineaciones",
                    "incidents": "incidencias"}[seccion]):
            assert seccion in informe.available(), f"{seccion} estaba grabada y no ha salido"


def test_esta_carpeta_no_lleva_grabaciones_inventadas():
    """Salvaguarda: aquí solo pueden entrar respuestas reales.

    Si alguien (yo el primero) generara grabaciones con el transporte falso y
    las dejara commiteadas, estos tests pasarían contra datos inventados y
    volveríamos justo al problema que vienen a resolver.
    """
    leeme = REALES / "LEEME.md"
    assert leeme.is_file(), "falta el LEEME que explica qué va aquí"
    for grabacion in GRABACIONES.values():
        assert "sofascore.com" in grabacion.url or "://" in grabacion.url, (
            f"Grabación con una URL que no parece real: {grabacion.url}"
        )
        assert grabacion.grabado_en, "una grabación sin fecha: ¿de dónde ha salido?"
