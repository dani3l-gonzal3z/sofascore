"""football-data.co.uk, ESPN y los adaptadores a ScraperFC y soccerdata.

Todo offline, contra respuestas con la forma que documentan ``soccerdata``
(que lee estos mismos sitios) y las propias fuentes. Lo que no se puede probar
aquí es que el sitio real siga sirviendo esa forma: eso es cosa de una
ejecución con red.
"""

from __future__ import annotations

import sys
import types

import pytest
from test_fuentes import CSV_FUTBOLDATA, _futboldata, _texto

from cancha.almacen import Almacen
from cancha.cache import MemoryCache
from cancha.config import Settings
from cancha.models import Event
from cancha.sources import ESPN, FutbolData, rellenar_cuotas
from cancha.sources.espn import moneyline_a_decimal
from cancha.sources.externas import (
    AdaptadorNoDisponible,
    ScraperFCAdaptador,
    SoccerdataAdaptador,
    _registros,
    adaptador,
    disponibles,
    nombre_de_liga,
)
from cancha.transport import FakeTransport

# ------------------------------------------------------------ football-data

def test_la_temporada_se_traduce_a_nombres_que_se_entienden():
    partidos = _futboldata().temporada("laliga", 2024)
    assert len(partidos) == 3
    clasico = partidos[0]
    assert clasico["fecha"] == "2024-10-26" and clasico["hora"] == "20:00"
    assert (clasico["local"], clasico["visitante"]) == ("Real Madrid", "Barcelona")
    assert (clasico["goles_local"], clasico["goles_visitante"]) == (0, 4)
    assert clasico["resultado"] == "visitante"
    assert clasico["tiros"] == (9, 13) and clasico["arbitro"] == "C Soto Grado"


def test_se_prefiere_la_cuota_de_cierre_y_si_no_hay_la_de_apertura():
    partidos = _futboldata().temporada("SP1", 2024)
    con_cierre = partidos[0]
    assert con_cierre["casa"] == "media del mercado (cierre)"
    assert con_cierre["cuotas"] == {"local": 3.1, "empate": 3.7, "visitante": 1.9}
    assert con_cierre["favorito"]["lado"] == "visitante"
    sin_cierre = partidos[1]
    assert sin_cierre["casa"] == "media del mercado (apertura)"
    assert sin_cierre["cuotas"]["local"] == 1.91


@pytest.mark.parametrize("liga,codigo", [
    (8, "SP1"), ("8", "SP1"), ("laliga", "SP1"), ("premier", "E0"), ("E0", "E0"),
    ("Spain La Liga", "SP1"), ("bundesliga", "D1"), ("championship", "E1"),
])
def test_cualquier_forma_de_nombrar_la_liga_da_su_codigo(liga, codigo):
    assert FutbolData.codigo(liga) == codigo


def test_una_liga_que_no_cubre_lo_dice():
    with pytest.raises(ValueError, match="no cubre"):
        FutbolData.codigo(242)  # MLS
    with pytest.raises(ValueError):
        FutbolData.codigo("liga de mi barrio")


@pytest.mark.parametrize("año,codigo", [(2024, "2425"), (1999, "9900"), (2009, "0910")])
def test_la_temporada_se_nombra_como_lo_hace_la_fuente(año, codigo):
    assert FutbolData.temporada_codigo(año) == codigo


def test_las_fechas_admiten_los_dos_formatos_del_sitio():
    assert FutbolData._fecha("26/10/2024") == "2024-10-26"
    assert FutbolData._fecha("26/10/24") == "2024-10-26"
    assert FutbolData._fecha("") is None and FutbolData._fecha("ayer") is None


def test_los_partidos_de_un_equipo_van_del_mas_reciente_atras():
    partidos = _futboldata().equipo("laliga", 2024, "Atlético de Madrid")
    assert [p["local"] for p in partidos] == ["Ath Madrid"]


def test_empareja_un_partido_de_sofascore_por_nombres_y_fecha():
    fuente = _futboldata()
    encontrado = fuente.buscar_partido("laliga", 2024, "Real Madrid", "FC Barcelona",
                                       fecha="2024-10-26")
    assert encontrado and encontrado["encaje"] >= 0.55
    assert fuente.buscar_partido("laliga", 2024, "Real Madrid", "FC Barcelona",
                                 fecha="2024-11-30") is None
    assert fuente.buscar_partido("laliga", 2024, "Girona", "Osasuna") is None


def test_las_cuotas_de_un_evento_llegan_listas_para_la_memoria():
    evento = Event.from_api({
        "id": 1, "startTimestamp": 1729972800,
        "tournament": {"uniqueTournament": {"id": 8}},
        "homeTeam": {"id": 2829, "name": "Real Madrid"},
        "awayTeam": {"id": 2817, "name": "Barcelona"},
    })
    bloque = _futboldata().cuotas_de(evento)
    assert bloque["fuente"] == "futboldata"
    assert bloque["favorito"]["lado"] == "visitante" and bloque["arbitro"] == "C Soto Grado"
    # Una liga sin cobertura devuelve None sin pedir nada.
    fuera = Event.from_api({"id": 2, "startTimestamp": 1729972800,
                            "tournament": {"uniqueTournament": {"id": 242}},
                            "homeTeam": {"name": "A"}, "awayTeam": {"name": "B"}})
    assert _futboldata().cuotas_de(fuera) is None


def test_rellenar_cuotas_pone_favorito_a_lo_barrido_sin_cuotas():
    with Almacen(":memory:") as base:
        for pid, local, visitante, momento in (
                (1, "Real Madrid", "Barcelona", 1729972800),
                (2, "Sevilla", "Osasuna", 1729972800 + 86400),
                (3, "Girona", "Valencia", 1729972800 + 5 * 86400)):
            base.guardar_evento(Event.from_api({
                "id": pid, "startTimestamp": momento, "status": {"type": "finished"},
                "tournament": {"uniqueTournament": {"id": 8}, "name": "LaLiga"},
                "homeTeam": {"id": pid * 10, "name": local},
                "awayTeam": {"id": pid * 10 + 1, "name": visitante}}))
        # Y uno de una liga sin cobertura.
        base.guardar_evento(Event.from_api({
            "id": 9, "startTimestamp": 1729972800, "status": {"type": "finished"},
            "tournament": {"uniqueTournament": {"id": 242}, "name": "MLS"},
            "homeTeam": {"id": 90, "name": "LA Galaxy"}, "awayTeam": {"id": 91, "name": "LAFC"}}))
        avisos = []
        resumen = rellenar_cuotas(base, fuente=_futboldata(), avisar=avisos.append)
        assert resumen["rellenados"] == 2
        assert resumen["sin_cobertura"] == 1
        assert resumen["no_encontrados"] == 1
        assert base.cuotas_de(1)["favorito"]["lado"] == "visitante"
        assert base.cuotas_de(2)["favorito"]["lado"] == "local"
        assert base.cuotas_de(3) is None
        assert len(avisos) == 2
        # Repetirlo no vuelve a rellenar nada.
        assert rellenar_cuotas(base, fuente=_futboldata())["rellenados"] == 0


def test_rellenar_cuotas_no_se_cae_si_un_csv_falla():
    from cancha.transport import Response

    with Almacen(":memory:") as base:
        base.guardar_evento(Event.from_api({
            "id": 1, "startTimestamp": 1729972800, "status": {"type": "finished"},
            "tournament": {"uniqueTournament": {"id": 17}, "name": "Premier"},
            "homeTeam": {"id": 1, "name": "Arsenal"}, "awayTeam": {"id": 2, "name": "Chelsea"}}))
        roto = _futboldata({"/mmz4281/2425/E0.csv": Response(500, "x", b"")})
        resumen = rellenar_cuotas(base, fuente=roto)
        assert resumen["rellenados"] == 0 and resumen["fallos"]


def test_la_consola_rellena_cuotas(tmp_path, monkeypatch, capsys):
    from cancha import cli
    from cancha.sources import futboldata as modulo

    monkeypatch.setattr(modulo, "FutbolData", lambda: _futboldata())
    ruta = tmp_path / "c.db"
    with Almacen(ruta) as base:
        base.guardar_evento(Event.from_api({
            "id": 1, "startTimestamp": 1729972800, "status": {"type": "finished"},
            "tournament": {"uniqueTournament": {"id": 8}, "name": "LaLiga"},
            "homeTeam": {"id": 1, "name": "Real Madrid"},
            "awayTeam": {"id": 2, "name": "Barcelona"}}))
    assert cli.main(["cuotas", "--db", str(ruta)]) == 0
    assert "Rellenados 1" in capsys.readouterr().out


def test_el_csv_lleva_bom_y_no_pasa_nada():
    con_bom = "﻿" + CSV_FUTBOLDATA
    fuente = _futboldata({"/mmz4281/2425/SP1.csv": _texto(con_bom)})
    assert fuente.temporada("laliga", 2024)[0]["local"] == "Real Madrid"


# ------------------------------------------------------------------- ESPN

SCOREBOARD = {
    "leagues": [{"id": "740", "name": "Spanish LALIGA", "abbreviation": "ESP.1"}],
    "events": [{
        "id": "704912", "date": "2024-10-26T19:00Z", "name": "Real Madrid at FC Barcelona",
        "status": {"type": {"state": "post", "completed": True, "description": "Full Time"}},
        "competitions": [{
            "id": "704912",
            "venue": {"fullName": "Estadio Santiago Bernabéu", "address": {"city": "Madrid"}},
            "competitors": [
                {"homeAway": "home", "winner": False, "score": "0", "form": "WWDWL",
                 "team": {"id": "86", "displayName": "Real Madrid",
                          "shortDisplayName": "Real Madrid", "abbreviation": "RMA"}},
                {"homeAway": "away", "winner": True, "score": "4", "form": "WWWWW",
                 "team": {"id": "83", "displayName": "Barcelona", "shortDisplayName": "Barcelona",
                          "abbreviation": "BAR"}},
            ],
            "odds": [{"provider": {"name": "ESPN BET"}, "details": "RMA -110", "overUnder": 3.5,
                      "homeTeamOdds": {"moneyLine": -110}, "awayTeamOdds": {"moneyLine": 250},
                      "drawOdds": {"moneyLine": 300}}],
        }],
    }],
}
STANDINGS = {"children": [{"name": "Spanish LALIGA", "standings": {"entries": [
    {"team": {"id": "83", "displayName": "Barcelona"}, "stats": [
        {"name": "rank", "value": 1}, {"name": "points", "value": 30},
        {"name": "gamesPlayed", "value": 11}, {"name": "wins", "value": 10},
        {"name": "ties", "value": 0}, {"name": "losses", "value": 1},
        {"name": "pointsFor", "value": 37}, {"name": "pointsAgainst", "value": 11},
        {"name": "pointDifferential", "displayValue": "+26"}]},
    {"team": {"id": "86", "displayName": "Real Madrid"}, "stats": [
        {"name": "rank", "value": 2}, {"name": "points", "value": 24}]},
]}}]}
NEWS = {"articles": [
    {"headline": "Vinicius out three weeks with hamstring injury",
     "description": "Real Madrid confirm the forward will miss the Clásico.",
     "published": "2024-10-20T10:00Z", "links": {"web": {"href": "https://espn.com/a"}},
     "categories": [{"type": "team", "description": "Real Madrid"}]},
    {"headline": "Flick praises Barcelona's press", "description": "…",
     "published": "2024-10-21T10:00Z", "links": {"web": {"href": "https://espn.com/b"}},
     "categories": [{"type": "team", "description": "Barcelona"}]},
]}
SUMMARY = {
    "gameInfo": {"venue": {"fullName": "Bernabéu"}, "attendance": 78000},
    "boxscore": {"teams": [
        {"team": {"displayName": "Real Madrid"},
         "statistics": [{"name": "possessionPct", "displayValue": "48"}]},
        {"team": {"displayName": "Barcelona"},
         "statistics": [{"name": "possessionPct", "displayValue": "52"}]}]},
    "keyEvents": [{"clock": {"displayValue": "54'"}, "type": {"text": "Goal"},
                   "text": "Goal! Lewandowski", "team": {"displayName": "Barcelona"}}],
}


def _espn(rutas=None):
    rutas = rutas or {
        "/esp.1/scoreboard": SCOREBOARD,
        "/esp.1/standings": STANDINGS,
        "/esp.1/news": NEWS,
        "/esp.1/summary?event=704912": SUMMARY,
    }
    return ESPN(settings=Settings(rate_limit=0), transport=FakeTransport(rutas),
                cache=MemoryCache())


def test_la_agenda_de_espn_se_traduce():
    partidos = _espn().agenda("laliga", "2024-10-26")
    assert len(partidos) == 1
    p = partidos[0]
    assert p["local"] == "Real Madrid" and p["visitante"] == "Barcelona"
    assert p["fecha"] == "2024-10-26" and p["hora_utc"] == "19:00"
    assert p["goles_local"] == 0 and p["goles_visitante"] == 4 and p["terminado"]
    assert p["estadio"] == "Estadio Santiago Bernabéu"


def test_la_linea_de_espn_se_traduce_a_probabilidades():
    mercado = _espn().agenda("laliga")[0]["mercado"]
    assert mercado["casa"] == "ESPN BET" and mercado["mas_menos"] == 3.5
    assert mercado["cuotas"] == {"local": 1.909, "empate": 4.0, "visitante": 3.5}
    assert mercado["favorito"]["lado"] == "local"


@pytest.mark.parametrize("ml,decimal", [(-110, 1.909), (250, 3.5), (-200, 1.5), (100, 2.0),
                                        (0, None), (None, None), ("x", None)])
def test_la_cuota_americana_se_traduce(ml, decimal):
    assert moneyline_a_decimal(ml) == decimal


def test_la_clasificacion_de_espn():
    tabla = _espn().clasificacion("laliga")
    assert tabla[0]["equipo"] == "Barcelona" and tabla[0]["puntos"] == 30
    assert tabla[0]["diferencia"] == 26
    assert tabla[1]["puesto"] == 2


def test_las_noticias_se_filtran_por_equipo():
    todas = _espn().noticias("laliga")
    assert len(todas) == 2 and todas[0]["enlace"] == "https://espn.com/a"
    del_madrid = _espn().noticias("laliga", equipo="Real Madrid")
    assert len(del_madrid) == 1 and "Vinicius" in del_madrid[0]["titulo"]
    assert _espn().noticias("laliga", equipo="Getafe") == []


def test_el_resumen_de_un_partido_de_espn():
    resumen = _espn().partido("laliga", 704912)
    assert resumen["asistencia"] == 78000
    assert resumen["equipos"][1]["estadisticas"]["possessionPct"] == "52"
    assert resumen["momentos"][0]["tipo"] == "Goal"


def test_empareja_un_partido_de_sofascore_en_espn():
    encontrado = _espn().buscar_partido("laliga", "2024-10-26", "Real Madrid", "FC Barcelona")
    assert encontrado and encontrado["partido_id"] == 704912


def test_la_agenda_de_varias_ligas_no_se_cae_por_una():
    fuente = _espn({"/esp.1/scoreboard": SCOREBOARD})  # el resto: 404
    partidos = fuente.agenda_del_dia("2024-10-26", ligas=["laliga", "premier"])
    assert len(partidos) == 1


@pytest.mark.parametrize("liga,codigo", [
    (8, "esp.1"), ("laliga", "esp.1"), ("mls", "usa.1"), ("champions", "uefa.champions"),
    ("eng.1", "eng.1"), ("Saudi Arabia Pro League", "ksa.1"),
])
def test_cualquier_forma_de_nombrar_la_liga_da_su_codigo_espn(liga, codigo):
    assert ESPN.codigo(liga) == codigo


def test_la_consola_enseña_noticias(monkeypatch, capsys):
    from cancha import cli
    from cancha.comandos import datos as modulo

    monkeypatch.setattr("cancha.sources.ESPN", lambda: _espn())
    del modulo
    assert cli.main(["noticias", "laliga", "--equipo", "Real Madrid"]) == 0
    assert "Vinicius" in capsys.readouterr().out


# ------------------------------------------------------------ adaptadores

class _Tabla:
    """Un DataFrame de mentira: lo justo que usa _registros."""

    def __init__(self, filas, multinivel=False):
        self._filas = filas
        self.columns = types.SimpleNamespace(nlevels=2 if multinivel else 1)

    def reset_index(self):
        return self

    def head(self, n):
        return _Tabla(self._filas[:n])

    def to_dict(self, orient="records"):
        return self._filas


def _scraperfc_falso():
    class FBref:
        def get_valid_seasons(self, league):
            assert league == "Spain La Liga"
            return {"2024-2025": "/x", "2023-2024": "/y"}

        def scrape_stats(self, year, league, stat_category):
            assert (year, league, stat_category) == ("2024-2025", "Spain La Liga", "shooting")
            return (_Tabla([{"Squad": "Barcelona", "Sh": 200}]),
                    _Tabla([{"Squad": "vs Barcelona", "Sh": 90}]),
                    _Tabla([{"Player": "Lewandowski", "Sh": 80}, {"Player": "Raphinha", "Sh": 70}]))

    class Transfermarkt:
        def get_valid_seasons(self, league):
            return {"24/25": 2024}

        def scrape_players(self, year, league):
            return _Tabla([{"Name": "Lamine Yamal", "Value": "€180.00m", "Age": float("nan")}])

    class Capology:
        def get_valid_seasons(self, league):
            return ["2024-2025"]

        def scrape_salaries(self, year, league, currency):
            return _Tabla([{"Player": "Lewandowski", "Weekly Gross": 500000, "cur": currency}])

    modulo = types.ModuleType("ScraperFC")
    modulo.FBref, modulo.Transfermarkt, modulo.Capology = FBref, Transfermarkt, Capology
    return modulo


def _soccerdata_falso():
    class FBref:
        def __init__(self, leagues, seasons):
            assert leagues == "ESP-La Liga"
            self.seasons = seasons

        def read_team_season_stats(self, stat_type="standard", opponent_stats=False):
            return _Tabla([{"team": "Barcelona", "Performance Gls": 37,
                            "tipo": stat_type, "rivales": opponent_stats}])

        def read_player_season_stats(self, stat_type="standard"):
            return _Tabla([{"player": "Lewandowski", "Performance Gls": 14}])

        def read_schedule(self):
            return _Tabla([{"home_team": "Real Madrid", "away_team": "Barcelona", "score": "0–4"}])

    modulo = types.ModuleType("soccerdata")
    modulo.FBref = FBref
    return modulo


def test_sin_las_librerias_se_dice_que_instalar(monkeypatch):
    monkeypatch.setitem(sys.modules, "ScraperFC", None)
    monkeypatch.setitem(sys.modules, "soccerdata", None)
    with pytest.raises(AdaptadorNoDisponible, match="pip install ScraperFC"):
        ScraperFCAdaptador()
    with pytest.raises(AdaptadorNoDisponible, match="pip install soccerdata"):
        SoccerdataAdaptador()
    with pytest.raises(ValueError):
        adaptador("otra")


def test_disponibles_dice_lo_que_hay_y_como_instalar_lo_que_no():
    estado = disponibles()
    assert set(estado) == {"scraperfc", "soccerdata"}
    for info in estado.values():
        assert "instalar" in info and "aporta" in info


def test_scraperfc_devuelve_registros_y_no_dataframes(monkeypatch):
    monkeypatch.setitem(sys.modules, "ScraperFC", _scraperfc_falso())
    sfc = adaptador("scraperfc")
    assert sfc.temporadas("fbref", "laliga") == ["2024-2025", "2023-2024"]
    tablas = sfc.fbref_estadisticas("laliga", "2024-2025", "shooting", maximo=1)
    assert tablas["equipos"] == [{"Squad": "Barcelona", "Sh": 200}]
    assert len(tablas["jugadores"]) == 1
    valores = sfc.transfermarkt_valores(8, "24/25")
    assert valores[0]["Name"] == "Lamine Yamal" and valores[0]["Age"] is None
    salarios = sfc.capology_salarios("laliga", "2024-2025", moneda="gbp")
    assert salarios[0]["cur"] == "gbp"


def test_soccerdata_devuelve_registros(monkeypatch):
    monkeypatch.setitem(sys.modules, "soccerdata", _soccerdata_falso())
    sd = adaptador("soccerdata")
    equipos = sd.fbref_equipos("laliga", 2024, tipo="shooting", rivales=True)
    assert equipos[0]["tipo"] == "shooting" and equipos[0]["rivales"] is True
    assert sd.fbref_jugadores(8, "24-25")[0]["player"] == "Lewandowski"
    assert sd.fbref_calendario("laliga", 2024)[0]["score"] == "0–4"
    with pytest.raises(ValueError, match="no trae de serie"):
        sd.fbref_equipos("mls", 2024)


def test_los_nombres_de_liga_son_los_del_catalogo():
    assert nombre_de_liga(8) == "Spain La Liga"
    assert nombre_de_liga("laliga") == "Spain La Liga"
    assert nombre_de_liga("Spain La Liga") == "Spain La Liga"
    with pytest.raises(ValueError):
        nombre_de_liga("liga de mi barrio")


def test_registros_aplana_lo_que_le_echen():
    assert _registros(None) == []
    assert _registros([1, {"a": 2}]) == [{"valor": 1}, {"a": 2}]
    assert _registros({"x": {"a": 1}, "y": 2}) == [{"clave": "x", "a": 1},
                                                  {"clave": "y", "valor": 2}]
    assert _registros(_Tabla([{"a": float("nan")}]))[0]["a"] is None


def test_la_herramienta_de_datos_externos_explica_que_instalar(monkeypatch):
    from cancha.herramientas import TOOLS, ejecutar

    monkeypatch.setitem(sys.modules, "soccerdata", None)
    salida = ejecutar("datos_externos", {"que": "fbref_equipos", "liga": "laliga"})
    assert "error" in salida and "pip install" in salida["instalar"]
    for nombre in ("noticias", "agenda_espn", "historial_de_liga", "rellenar_cuotas"):
        assert nombre in TOOLS


def test_la_herramienta_de_datos_externos_funciona_con_la_libreria(monkeypatch):
    from cancha.herramientas import ejecutar

    monkeypatch.setitem(sys.modules, "soccerdata", _soccerdata_falso())
    monkeypatch.setitem(sys.modules, "ScraperFC", _scraperfc_falso())
    salida = ejecutar("datos_externos", {"que": "fbref_jugadores", "liga": "laliga",
                                         "temporada": "2024"})
    assert salida["libreria"] == "soccerdata" and salida["filas"][0]["player"] == "Lewandowski"
    temporadas = ejecutar("datos_externos", {"que": "temporadas", "liga": "laliga"})
    assert temporadas["temporadas"]["fbref"] == ["2024-2025", "2023-2024"]
    sin_temporada = ejecutar("datos_externos", {"que": "transfermarkt_valores", "liga": "laliga"})
    assert "error" in sin_temporada


def test_fuentes_lista_las_librerias_externas(capsys):
    from cancha import cli

    assert cli.main(["fuentes"]) == 0
    salida = capsys.readouterr().out
    assert "futboldata" in salida and "espn" in salida and "scraperfc" in salida


def test_un_numero_que_ya_lo_es_no_se_trunca():
    from cancha.sources.base import _numero

    assert _numero(3.5) == 3.5 and _numero(3) == 3 and _numero("3.5") == 3.5
    assert _numero("7") == 7 and _numero(True) is True and _numero("NA") is None
