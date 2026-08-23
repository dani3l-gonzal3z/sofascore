"""El host alternativo, el paralelismo y las rutas contrastadas."""

from __future__ import annotations

import pytest

from conftest import EVENT_ID, rutas_por_defecto
from sofascore.cache import MemoryCache
from sofascore.client import SofascoreClient
from sofascore.config import DEFAULT_FALLBACK_BASE_URLS, Settings
from sofascore.endpoints import SECTIONS, resolve_sections
from sofascore.errors import HTTPError, PlusRequired, TransportError
from sofascore.match import build_report
from sofascore.transport import FakeTransport, Response


def _cliente(transporte, **ajustes):
    settings = Settings(rate_limit=0, retries=0, backoff=0, **ajustes)
    return SofascoreClient(
        settings, transport=transporte, cache=MemoryCache(), sleep=lambda _s: None
    )


class BloqueaElPrimerHost:
    """Contesta 403 desde ``api.`` y bien desde ``www.`` (el caso real)."""

    def __init__(self, payload):
        self.payload = payload
        self.urls: list[str] = []

    def request(self, method, url, headers):
        import json

        self.urls.append(url)
        if url.startswith("https://api.sofascore.com"):
            return Response(status=403, url=url, body=b"blocked")
        return Response(status=200, url=url, body=json.dumps(self.payload).encode())


def test_un_403_del_primer_host_no_es_la_ultima_palabra():
    transporte = BloqueaElPrimerHost({"event": {"id": EVENT_ID}})
    cliente = _cliente(transporte)
    assert cliente.event(EVENT_ID).id == EVENT_ID
    assert len(transporte.urls) == 2
    assert transporte.urls[1].startswith("https://www.sofascore.com")
    assert cliente.stats.host_switches == 1


def test_si_todos_los_hosts_bloquean_se_rinde():
    transporte = FakeTransport({"/event/": 403})
    cliente = _cliente(transporte)
    with pytest.raises(HTTPError):
        cliente.event(EVENT_ID)
    # Lo ha intentado en los dos hosts antes de darse por vencido.
    assert len(transporte.calls) == 2


def test_un_404_no_dispara_el_cambio_de_host():
    """Un 404 es una respuesta sobre el dato, no un bloqueo: no se reintenta."""
    transporte = FakeTransport({"/event/": 404})
    cliente = _cliente(transporte)
    with pytest.raises(HTTPError):
        cliente.event(EVENT_ID)
    assert len(transporte.calls) == 1


def test_seccion_plus_tambien_prueba_el_otro_host_antes_de_rendirse():
    transporte = FakeTransport({"/shotmap": 403})
    cliente = _cliente(transporte)
    with pytest.raises(PlusRequired):
        cliente.section("shotmap", EVENT_ID)
    assert len(transporte.calls) == 2


def test_sin_hosts_alternativos_se_comporta_como_antes():
    transporte = FakeTransport({"/event/": 403})
    cliente = _cliente(transporte, fallback_base_urls=())
    with pytest.raises(HTTPError):
        cliente.event(EVENT_ID)
    assert len(transporte.calls) == 1


def test_la_cache_no_depende_del_host():
    """Si la respuesta llegó por el host alternativo, se reutiliza igual."""
    transporte = BloqueaElPrimerHost({"event": {"id": EVENT_ID}})
    cliente = _cliente(transporte)
    cliente.event(EVENT_ID)
    peticiones = len(transporte.urls)
    cliente.event(EVENT_ID)
    assert len(transporte.urls) == peticiones
    assert cliente.stats.cache_hits == 1


def test_el_host_alternativo_por_defecto_es_el_de_la_web():
    assert DEFAULT_FALLBACK_BASE_URLS == ("https://www.sofascore.com/api/v1",)


# ------------------------------------------------------------------ paralelismo

def test_en_paralelo_da_lo_mismo_que_en_fila():
    def informe(hilos):
        cliente = _cliente(FakeTransport(rutas_por_defecto()), concurrency=hilos)
        return build_report(cliente, EVENT_ID)

    secuencial, paralelo = informe(1), informe(4)
    assert list(secuencial.sections) == list(paralelo.sections)
    assert secuencial.available() == paralelo.available()


def test_el_paralelismo_respeta_el_orden_pedido():
    cliente = _cliente(FakeTransport(rutas_por_defecto()), concurrency=8)
    informe = build_report(cliente, EVENT_ID, sections=["event", "incidents", "statistics"])
    assert list(informe.sections) == ["event", "incidents", "statistics"]


def test_las_alineaciones_se_traen_antes_aunque_haya_paralelismo():
    rutas = rutas_por_defecto()
    rutas["/player/"] = {"statistics": {"rating": 8.8}}
    cliente = _cliente(FakeTransport(rutas), concurrency=4, plus_cookie="sesion=mia")
    informe = build_report(cliente, EVENT_ID, sections=["heatmaps"], max_players=2)
    assert "lineups" in informe.sections
    assert list(informe.sections).index("lineups") < list(informe.sections).index("heatmaps")


# ------------------------------------------------------------------- las rutas

@pytest.mark.parametrize("nombre,ruta", [
    ("event", "/event/{event_id}"),
    ("statistics", "/event/{event_id}/statistics"),
    ("lineups", "/event/{event_id}/lineups"),
    ("incidents", "/event/{event_id}/incidents"),
    ("momentum", "/event/{event_id}/graph"),
    ("shotmap", "/event/{event_id}/shotmap"),
    ("average_positions", "/event/{event_id}/average-positions"),
    ("best_players", "/event/{event_id}/best-players/summary"),
    ("heatmaps", "/event/{event_id}/player/{player_id}/heatmap"),
    # Esta estaba mal: la probabilidad de victoria cuelga de /graph.
    ("win_probability", "/event/{event_id}/graph/win-probability"),
    ("tv_channels", "/tv/event/{event_id}/country-channels"),
    ("point_by_point", "/event/{event_id}/point-by-point"),
])
def test_rutas_contrastadas_con_las_librerias_publicas(nombre, ruta):
    assert SECTIONS[nombre].path == ruta


def test_las_secciones_de_otro_deporte_no_se_piden():
    futbol = [s.name for s in resolve_sections(["all"], sport="football")]
    tenis = [s.name for s in resolve_sections(["all"], sport="tennis")]
    assert "point_by_point" not in futbol
    assert "point_by_point" in tenis
    assert "innings" not in futbol


def test_pedir_una_seccion_de_otro_deporte_a_mano_se_respeta():
    elegidas = [s.name for s in resolve_sections(["innings"], sport="football")]
    assert "innings" in elegidas


def test_sin_saber_el_deporte_no_se_descarta_nada():
    assert "point_by_point" in [s.name for s in resolve_sections(["all"], sport=None)]


def test_un_error_de_red_en_todos_los_hosts_se_propaga():
    class Roto:
        def request(self, method, url, headers):
            raise TransportError("sin DNS")

    with pytest.raises(TransportError):
        _cliente(Roto()).event(EVENT_ID)
