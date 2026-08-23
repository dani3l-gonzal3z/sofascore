"""Cliente HTTP: caché, reintentos, errores y credenciales."""

import pytest

from sofascore.cache import MemoryCache
from sofascore.client import SofascoreClient
from sofascore.config import Settings
from sofascore.errors import HTTPError, NotFound, OfflineError, PlusRequired, TransportError
from sofascore.transport import FakeTransport, Response

from conftest import EVENT_ID


def _cliente(rutas, **ajustes_extra):
    ajustes = Settings(rate_limit=0, retries=2, backoff=0, cache_ttl=60, **ajustes_extra)
    return SofascoreClient(
        ajustes, transport=FakeTransport(rutas), cache=MemoryCache(), sleep=lambda _s: None
    )


def test_evento_se_parsea(cliente):
    evento = cliente.event(EVENT_ID)
    assert evento.home.name == "Real Madrid"
    assert evento.away_score.current == 4
    assert evento.winner() == "away"
    assert evento.is_finished


def test_la_cache_evita_repetir_peticiones(cliente, transporte):
    cliente.event(EVENT_ID)
    cliente.event(EVENT_ID)
    assert len(transporte.calls) == 1
    assert cliente.stats.cache_hits == 1


def test_seccion_desenvuelve_la_clave(cliente):
    estadisticas = cliente.section("statistics", EVENT_ID)
    assert isinstance(estadisticas, list)
    assert estadisticas[0]["period"] == "ALL"


def test_404_es_notfound():
    cli = _cliente({})
    with pytest.raises(NotFound):
        cli.event(1)


def test_403_en_seccion_plus_es_plusrequired():
    cli = _cliente({f"/event/{EVENT_ID}/shotmap": 403})
    with pytest.raises(PlusRequired) as error:
        cli.section("shotmap", EVENT_ID)
    assert "shotmap" in str(error.value)


def test_403_en_seccion_publica_es_httperror():
    cli = _cliente({f"/event/{EVENT_ID}/lineups": 403})
    with pytest.raises(HTTPError) as error:
        cli.section("lineups", EVENT_ID)
    assert error.value.status == 403


def test_reintenta_los_500_y_acaba_acertando():
    intentos = {"n": 0}

    def flaky(url):
        intentos["n"] += 1
        if intentos["n"] < 3:
            return Response(status=502, url=url, body=b"boom")
        return Response(status=200, url=url, body=b'{"event": {"id": 1}}')

    cli = _cliente({"/event/1": flaky})
    assert cli.event(1).id == 1
    assert intentos["n"] == 3
    assert cli.stats.retries == 2


def test_se_rinde_tras_agotar_reintentos():
    cli = _cliente({"/event/1": 500})
    with pytest.raises(HTTPError):
        cli.event(1)


def test_error_de_red_tambien_reintenta():
    class Roto:
        def __init__(self):
            self.n = 0

        def request(self, method, url, headers):
            self.n += 1
            raise TransportError("sin DNS")

    ajustes = Settings(rate_limit=0, retries=1, backoff=0)
    roto = Roto()
    cli = SofascoreClient(ajustes, transport=roto, cache=MemoryCache(), sleep=lambda _s: None)
    with pytest.raises(TransportError):
        cli.event(1)
    assert roto.n == 2


def test_modo_offline_sin_cache_falla():
    cli = _cliente({f"/event/{EVENT_ID}": {"event": {"id": EVENT_ID}}}, offline=True)
    with pytest.raises(OfflineError):
        cli.event(EVENT_ID)


def test_modo_offline_usa_la_cache():
    cache = MemoryCache()
    ajustes = Settings(rate_limit=0, cache_ttl=600)
    transporte = FakeTransport({f"/event/{EVENT_ID}": {"event": {"id": EVENT_ID}}})
    caliente = SofascoreClient(ajustes, transport=transporte, cache=cache, sleep=lambda _s: None)
    caliente.event(EVENT_ID)

    frio = SofascoreClient(
        Settings(rate_limit=0, cache_ttl=600, offline=True),
        transport=FakeTransport({}), cache=cache, sleep=lambda _s: None,
    )
    assert frio.event(EVENT_ID).id == EVENT_ID


def test_las_credenciales_viajan_en_las_cabeceras():
    capturadas = {}

    class Espia:
        def request(self, method, url, headers):
            capturadas.update(headers)
            return Response(status=200, url=url, body=b'{"event": {"id": 1}}')

    ajustes = Settings(rate_limit=0, plus_cookie="sesion=abc", cache_ttl=0)
    cli = SofascoreClient(ajustes, transport=Espia(), cache=MemoryCache(), sleep=lambda _s: None)
    cli.event(1)
    assert capturadas["Cookie"] == "sesion=abc"
    assert capturadas["Referer"].startswith("https://www.sofascore.com")
    assert cli.has_plus


def test_la_cache_separa_anonimo_de_autenticado():
    cache = MemoryCache()
    rutas = {"/event/1": {"event": {"id": 1}}}
    anon = SofascoreClient(Settings(rate_limit=0, cache_ttl=600),
                           transport=FakeTransport(rutas), cache=cache, sleep=lambda _s: None)
    anon.event(1)
    espia = FakeTransport(rutas)
    autenticado = SofascoreClient(
        Settings(rate_limit=0, cache_ttl=600, plus_token="t"),
        transport=espia, cache=cache, sleep=lambda _s: None,
    )
    autenticado.event(1)
    assert len(espia.calls) == 1  # no reutiliza la respuesta anónima


def test_partido_terminado_se_cachea_mas_tiempo(cliente):
    evento = cliente.event(EVENT_ID)
    assert cliente.ttl_for_event(evento) == cliente.settings.cache_ttl_finished
    evento.status_type = "inprogress"
    assert cliente.ttl_for_event(evento) == cliente.settings.cache_ttl
