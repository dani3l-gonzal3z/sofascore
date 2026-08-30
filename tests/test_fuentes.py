"""Las otras fuentes y el cruce entre ellas.

Todo offline. Las respuestas de ejemplo tienen la forma que documentan
``soccerdata`` y ``ScraperFC``, que son las que sí han hablado con estos sitios.
"""

from __future__ import annotations

import json

import pytest

from cancha.cache import MemoryCache
from cancha.config import Settings
from cancha.errors import NotFound
from cancha.sources import FUENTES, ClubElo, Understat, construir, temporada_de
from cancha.sources.base import FuenteError
from cancha.transport import FakeTransport, Response

CSV_DIA = (
    "Rank,Club,Country,Level,Elo,From,To\n"
    "1,Man City,ENG,1,2032.4,2026-08-20,2026-08-24\n"
    "2,Real Madrid,ESP,1,2010.1,2026-08-20,2026-08-24\n"
    "3,Barcelona,ESP,1,1995.7,2026-08-20,2026-08-24\n"
    "4,Inter,ITA,1,1950.0,2026-08-20,2026-08-24\n"
)
CSV_BARCELONA = (
    "Rank,Club,Country,Level,Elo,From,To\n"
    "9,Barcelona,ESP,1,1899.0,2025-01-01,2025-06-30\n"
    "3,Barcelona,ESP,1,1995.7,2026-08-20,2026-08-24\n"
)
CSV_MADRID = (
    "Rank,Club,Country,Level,Elo,From,To\n"
    "2,Real Madrid,ESP,1,2010.1,2026-08-20,2026-08-24\n"
)


def _texto(cuerpo: str) -> Response:
    return Response(200, "x", cuerpo.encode("utf-8"))


def _elo(rutas=None):
    rutas = rutas or {
        "/2026-08-23": _texto(CSV_DIA),
        "/Barcelona": _texto(CSV_BARCELONA),
        "/RealMadrid": _texto(CSV_MADRID),
    }
    return ClubElo(settings=Settings(rate_limit=0), transport=FakeTransport(rutas),
                   cache=MemoryCache())


# ------------------------------------------------------------------- registro

def test_las_fuentes_se_registran_solas():
    assert set(FUENTES) == {"clubelo", "understat"}
    assert isinstance(construir("clubelo"), ClubElo)


def test_una_fuente_inventada_lo_dice():
    with pytest.raises(ValueError, match="Fuente desconocida"):
        construir("opta")


def test_cada_fuente_trae_su_ritmo_y_su_cache():
    """Cada sitio aguanta lo que aguanta: el ritmo no puede ser común."""
    for nombre in FUENTES:
        fuente = construir(nombre)
        assert fuente.rate_limit > 0
        assert fuente.ttl > 0
        assert fuente.descripcion


# -------------------------------------------------------------------- clubelo

def test_elo_del_dia():
    filas = _elo().por_fecha("2026-08-23")
    assert filas[0]["equipo"] == "Man City"
    assert filas[0]["elo"] == 2032.4
    assert filas[0]["puesto"] == 1


def test_historico_de_un_club_y_su_dato_actual():
    fuente = _elo()
    historico = fuente.equipo("Barcelona")
    assert len(historico) == 2
    assert fuente.actual("Barcelona")["elo"] == 1995.7


def test_el_nombre_va_sin_espacios_en_la_url():
    fuente = _elo()
    fuente.actual("Real Madrid")
    assert any("/RealMadrid" in url for url in fuente.transport.calls)


def test_top_filtrado_por_pais():
    equipos = [f["equipo"] for f in _elo().top(10, "2026-08-23", pais="ESP")]
    assert equipos == ["Real Madrid", "Barcelona"]


def test_comparar_dos_clubes():
    salida = _elo().comparar("Real Madrid", "Barcelona")
    assert salida["diferencia_elo"] == pytest.approx(14.4, abs=0.1)
    # Elo: una ventaja pequeña deja la probabilidad justo por encima del 50%.
    assert 0.5 < salida["probabilidad_local"] < 0.55


def test_un_csv_vacio_no_pasa_por_bueno():
    fuente = _elo({"/x": _texto("Rank,Club\n")})
    with pytest.raises(FuenteError):
        fuente.csv("/x")


def test_un_club_que_no_existe():
    fuente = _elo({"/NoExiste": Response(404, "x", b"")})
    with pytest.raises(NotFound):
        fuente.equipo("NoExiste")


# ------------------------------------------------------------------ understat

PARTIDO_UNDERSTAT = {
    "shots": {
        "h": [{"minute": "23", "player": "Lewandowski", "player_id": "1",
               "h_team": "Barcelona", "a_team": "Real Madrid", "xG": "0.7412",
               "result": "Goal", "situation": "OpenPlay", "shotType": "RightFoot",
               "X": "0.9", "Y": "0.5", "player_assisted": "Raphinha",
               "lastAction": "Pass"}],
        "a": [{"minute": "10", "player": "Mbappe", "player_id": "2",
               "h_team": "Barcelona", "a_team": "Real Madrid", "xG": "0.1102",
               "result": "SavedShot", "situation": "FromCorner", "shotType": "Head",
               "X": "0.8", "Y": "0.4"}],
    },
    "rosters": {"h": {}, "a": {}},
    "tmpl": {"home": "", "away": ""},
}
TEMPORADA_UNDERSTAT = {
    "dates": [{"id": "26123", "h": {"title": "Barcelona"}, "a": {"title": "Real Madrid"},
               "datetime": "2024-10-26 21:00:00"}],
    "players": [], "teams": {},
}


def _understat():
    rutas = {
        "/getMatchData/26123": _texto(json.dumps(PARTIDO_UNDERSTAT)),
        "/getLeagueData/La_liga/2024": _texto(json.dumps(TEMPORADA_UNDERSTAT)),
        "understat.com/": _texto("<html>portada</html>"),
    }
    return Understat(settings=Settings(rate_limit=0), transport=FakeTransport(rutas),
                     cache=MemoryCache())


@pytest.mark.parametrize("entrada,esperado", [
    ("laliga", "La_liga"), ("La Liga", "La_liga"), ("premier", "EPL"),
    ("EPL", "EPL"), ("serie a", "Serie_A"), ("Ligue 1", "Ligue_1"),
])
def test_los_alias_de_liga(entrada, esperado):
    assert Understat.slug(entrada) == esperado


def test_los_tiros_llegan_traducidos_y_en_orden():
    tiros = _understat().tiros(26123)
    assert [t["minuto"] for t in tiros] == [10, 23]
    assert tiros[1]["resultado"] == "gol"
    assert tiros[1]["situacion"] == "jugada abierta"
    assert tiros[1]["parte_cuerpo"] == "pie derecho"
    assert tiros[1]["asistio"] == "Raphinha"


def test_el_xg_se_suma_por_equipo():
    equipos = _understat().xg_partido(26123)["equipos"]
    assert equipos["Barcelona"] == {"xg": 0.74, "tiros": 1, "goles": 1}
    assert equipos["Real Madrid"]["goles"] == 0


def test_visita_la_portada_antes_de_pedir_datos():
    """Understat quiere una cookie de sesión que se coge en su portada."""
    fuente = _understat()
    fuente.tiros(26123)
    assert fuente.transport.calls[0].endswith("understat.com/")


def test_empareja_el_partido_aunque_venga_del_reves():
    fuente = _understat()
    encontrado = fuente.buscar_partido("laliga", 2024, "Real Madrid", "Barcelona")
    assert encontrado["id"] == 26123
    assert encontrado["orden_invertido"] is True


def test_no_empareja_lo_que_no_se_parece():
    assert _understat().buscar_partido("laliga", 2024, "Girona", "Osasuna") is None


def test_un_json_que_no_lo_es_da_un_error_claro():
    fuente = Understat(settings=Settings(rate_limit=0), cache=MemoryCache(),
                       transport=FakeTransport({"/getStatData": _texto("<html>vaya</html>")}))
    with pytest.raises(FuenteError, match="esperaba JSON"):
        fuente.ligas()


# ---------------------------------------------------------------------- cruce

def test_la_temporada_se_deduce_del_mes():
    from cancha.models import Event

    def evento(fecha_iso, momento):
        return Event.from_api({"id": 1, "startTimestamp": momento})

    # Octubre de 2024 pertenece a la temporada 2024; marzo de 2025, también.
    assert temporada_de(evento("2024-10-26", 1729944000)) == 2024
    assert temporada_de(evento("2025-03-01", 1740787200)) == 2024
    assert temporada_de(Event(id=1)) is None


def test_contexto_junta_las_fuentes_y_contrasta_los_modelos(monkeypatch, tmp_path):
    """Lo que ninguna de las dos librerías de referencia hace: cruzarlas."""
    import sys

    sys.path.insert(0, "tests")
    from conftest import EVENT_ID, rutas_por_defecto

    from cancha.client import SofascoreClient
    from cancha.sources import contexto_partido

    monkeypatch.setattr("cancha.sources.cruce.Understat", _understat)
    monkeypatch.setattr("cancha.sources.cruce.ClubElo", _elo)

    cliente = SofascoreClient(
        Settings(cache_dir=tmp_path / "c", rate_limit=0, retries=0),
        transport=FakeTransport(rutas_por_defecto()), cache=MemoryCache(),
        sleep=lambda _s: None,
    )
    salida = contexto_partido(cliente, EVENT_ID)

    assert salida["partido"]["local"] == "Real Madrid"
    assert salida["fuentes"]["understat"]["estado"] == "ok"
    assert salida["fuentes"]["clubelo"]["estado"] == "ok"
    contraste = salida["contraste_xg"]
    assert contraste["posible"] is True
    assert "local" in contraste["por_equipo"]
    assert "lectura" in contraste


def test_una_competicion_que_understat_no_cubre_se_dice(monkeypatch, tmp_path):
    import sys

    sys.path.insert(0, "tests")
    from conftest import EVENT_ID, cargar, rutas_por_defecto

    from cancha.client import SofascoreClient
    from cancha.sources import contexto_partido

    monkeypatch.setattr("cancha.sources.cruce.ClubElo", _elo)
    rutas = rutas_por_defecto()
    evento = cargar("event")
    evento["event"]["tournament"]["uniqueTournament"] = {"id": 999}
    rutas[f"/event/{EVENT_ID}"] = evento

    cliente = SofascoreClient(
        Settings(cache_dir=tmp_path / "c", rate_limit=0, retries=0),
        transport=FakeTransport(rutas), cache=MemoryCache(), sleep=lambda _s: None,
    )
    salida = contexto_partido(cliente, EVENT_ID)
    assert salida["fuentes"]["understat"]["estado"] == "no_cubierta"
    # Y aun así el resto sigue, que es la regla de la casa.
    assert salida["fuentes"]["clubelo"]["estado"] == "ok"


def test_una_fuente_que_falla_no_tumba_las_demas(monkeypatch, tmp_path):
    import sys

    sys.path.insert(0, "tests")
    from conftest import EVENT_ID, rutas_por_defecto

    from cancha.client import SofascoreClient
    from cancha.sources import contexto_partido

    def elo_roto():
        return _elo({"/RealMadrid": Response(500, "x", b"boom")})

    monkeypatch.setattr("cancha.sources.cruce.Understat", _understat)
    monkeypatch.setattr("cancha.sources.cruce.ClubElo", elo_roto)

    cliente = SofascoreClient(
        Settings(cache_dir=tmp_path / "c", rate_limit=0, retries=0),
        transport=FakeTransport(rutas_por_defecto()), cache=MemoryCache(),
        sleep=lambda _s: None,
    )
    salida = contexto_partido(cliente, EVENT_ID)
    # Un 500 en todas sus raíces: la fuente no ha contestado, no es el nombre.
    assert salida["fuentes"]["clubelo"]["estado"] == "sin_respuesta"
    assert salida["fuentes"]["understat"]["estado"] == "ok"


# ------------------------------------ que una raíz no conteste no es el final

def test_si_la_raiz_principal_no_responde_se_prueba_la_otra():
    """Lo que le pasó a ClubElo en http: 15 segundos y cero bytes."""
    from cancha.errors import TransportError

    class SoloHttps:
        def __init__(self):
            self.calls = []

        def request(self, method, url, headers):
            self.calls.append(url)
            if url.startswith("http://"):
                raise TransportError("timeout")
            return _texto(CSV_BARCELONA)

    transporte = SoloHttps()
    fuente = ClubElo(settings=Settings(rate_limit=0), transport=transporte,
                     cache=MemoryCache())
    fuente.base_url = "http://api.clubelo.com"
    fuente.urls_alternativas = ("https://api.clubelo.com",)
    assert fuente.actual("Barcelona")["elo"] == 1995.7
    assert len(transporte.calls) == 2


def test_por_defecto_se_intenta_https_antes_que_http():
    fuente = ClubElo()
    assert fuente.raices()[0].startswith("https://")
    assert any(r.startswith("http://") for r in fuente.raices())


def test_la_cache_no_depende_de_por_qué_raiz_entro():
    fuente = _elo()
    fuente.urls_alternativas = ("http://api.clubelo.com",)
    fuente.actual("Barcelona")
    peticiones = len(fuente.transport.calls)
    fuente.actual("Barcelona")
    assert len(fuente.transport.calls) == peticiones


def test_si_ninguna_raiz_contesta_se_dice():
    from cancha.errors import TransportError

    class Muerto:
        calls = []

        def request(self, *_a, **_k):
            raise TransportError("nada")

    fuente = ClubElo(settings=Settings(rate_limit=0), transport=Muerto(),
                     cache=MemoryCache())
    with pytest.raises(FuenteError, match="no responde"):
        fuente.por_fecha("2026-08-23")


def test_un_timeout_no_se_confunde_con_un_nombre_mal_escrito():
    """El mensaje culpaba al nombre del equipo cuando era la red."""
    from cancha.errors import TransportError
    from cancha.models import Event
    from cancha.sources import cruce

    class Muerto:
        def request(self, *_a, **_k):
            raise TransportError("timeout")

    def elo_muerto():
        return ClubElo(settings=Settings(rate_limit=0), transport=Muerto(),
                       cache=MemoryCache())

    original, cruce.ClubElo = cruce.ClubElo, elo_muerto
    try:
        salida = cruce._clubelo(Event.from_api({"id": 1, "homeTeam": {"name": "Real Madrid"},
                                                "awayTeam": {"name": "Barcelona"}}))
    finally:
        cruce.ClubElo = original
    assert salida["estado"] == "sin_respuesta"
    assert "No es el nombre del equipo" in salida["nota"]
