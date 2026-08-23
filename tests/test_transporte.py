"""Elegir transporte y traducir el bloqueo de Cloudflare a algo accionable."""

from __future__ import annotations

import pytest

from sofascore.cache import MemoryCache
from sofascore.client import SofascoreClient
from sofascore.config import Settings
from sofascore.errors import Blocked, HTTPError, PlusRequired
from sofascore.transport import (
    AUTO_ORDER,
    CallableTransport,
    CurlTransport,
    FakeTransport,
    UrllibTransport,
    build_transport,
    transport_disponible,
)


def _cliente(transporte, **ajustes):
    return SofascoreClient(
        Settings(rate_limit=0, retries=0, backoff=0, **ajustes),
        transport=transporte,
        cache=MemoryCache(),
        sleep=lambda _s: None,
    )


# ------------------------------------------------------------ elegir transporte

def test_urllib_siempre_esta():
    assert transport_disponible("urllib")
    assert isinstance(build_transport("urllib"), UrllibTransport)


def test_auto_prefiere_el_que_llega_mas_lejos():
    """curl_cffi primero: es el único que atraviesa el anti-bot."""
    assert AUTO_ORDER[0] == "curl"


def test_auto_cae_a_urllib_si_no_hay_nada_instalado(monkeypatch):
    import sofascore.transport as t

    monkeypatch.setattr(t, "transport_disponible", lambda kind: kind == "urllib")
    assert isinstance(t.build_transport("auto"), UrllibTransport)


def test_transporte_desconocido_lo_dice():
    with pytest.raises(ValueError, match="Transporte desconocido"):
        build_transport("carrito")


def test_el_ajuste_manda_al_construir_el_cliente():
    cliente = SofascoreClient(Settings(transport="urllib", rate_limit=0), cache=MemoryCache())
    assert isinstance(cliente.transport, UrllibTransport)


def test_el_transporte_sale_en_los_ajustes_redactados():
    assert Settings(transport="curl").redacted()["transport"] == "curl"


def test_se_configura_por_entorno():
    ajustes = Settings.from_env(dotenv=None, env={"SOFA_TRANSPORT": "urllib"})
    assert ajustes.transport == "urllib"


# ------------------------------------------------------------------ curl_cffi

def test_curl_no_manda_nuestro_user_agent():
    """El perfil imitado ya trae el suyo; mandar otro nos volvería a delatar."""
    enviadas = {}

    class SesionFalsa:
        def request(self, method, url, headers=None):
            enviadas.update(headers or {})

            class R:
                status_code = 200
                content = b"{}"
                headers = {}

            return R()

    transporte = CurlTransport(session=SesionFalsa())
    transporte.request("GET", "https://x/y", {"User-Agent": "yo", "Accept": "application/json"})
    assert "User-Agent" not in enviadas
    assert enviadas["Accept"] == "application/json"


def test_curl_traduce_sus_errores_a_los_nuestros():
    from sofascore.errors import TransportError

    class SesionRota:
        def request(self, *_a, **_k):
            raise RuntimeError("curl se quejó")

    with pytest.raises(TransportError):
        CurlTransport(session=SesionRota()).request("GET", "https://x/y", {})


# --------------------------------------------------------- el 403 dice qué hacer

def test_un_403_en_datos_publicos_explica_la_salida():
    cliente = _cliente(FakeTransport({"/event/": 403}))
    with pytest.raises(Blocked) as excinfo:
        cliente.event(1)
    mensaje = str(excinfo.value)
    assert "pip install curl_cffi" in mensaje
    assert "403" in mensaje


def test_si_ya_imitas_a_chrome_el_consejo_es_otro():
    error = Blocked(403, "https://x", transporte="CurlTransport")
    assert "pip install" not in str(error)
    assert "otra red" in str(error)


def test_el_bloqueo_sigue_siendo_un_httperror():
    """Quien ya capturaba HTTPError no tiene que cambiar nada."""
    assert issubclass(Blocked, HTTPError)
    cliente = _cliente(FakeTransport({"/event/": 403}))
    with pytest.raises(HTTPError):
        cliente.event(1)


def test_una_seccion_de_pago_sigue_diciendo_plus_no_bloqueo():
    """Un 403 en una sección de pago es el muro, no Cloudflare: no confundirlos."""
    cliente = _cliente(FakeTransport({"/win-probability": 403}))
    with pytest.raises(PlusRequired):
        cliente.section("win_probability", 1)


def test_un_404_no_se_convierte_en_bloqueo():
    from sofascore.errors import NotFound

    cliente = _cliente(FakeTransport({"/event/": 404}))
    with pytest.raises(NotFound):
        cliente.event(1)


def test_transporte_a_medida_para_cuando_nada_funciona():
    """La puerta de atrás: playwright, un proxy tuyo, lo que haga falta."""
    cliente = _cliente(CallableTransport(lambda m, url, h: (200, b'{"event":{"id":9}}')))
    assert cliente.event(9).id == 9
