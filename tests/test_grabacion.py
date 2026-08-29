"""Grabar y reproducir respuestas.

La maquinaria que permite que los tests de contrato existan, probada con el
transporte falso: aquí sí vale, porque lo que se comprueba es la grabadora, no
la forma de los datos.
"""

from __future__ import annotations

import json

import pytest

from cancha.cache import MemoryCache
from cancha.client import SofascoreClient
from cancha.config import Settings
from cancha.grabacion import (
    Grabacion,
    Grabadora,
    Reproductor,
    cargar,
    nombre_de_fichero,
    preparar_transporte,
    resumen,
)
from cancha.transport import FakeTransport, Response

URL = "https://api.sofascore.com/api/v1/event/12437616"


@pytest.mark.parametrize("url,esperado", [
    ("https://api.sofascore.com/api/v1/event/1/statistics", "sofascore_event_1_statistics.json"),
    ("https://www.sofascore.com/api/v1/event/1", "sofascore_event_1.json"),
    ("http://api.clubelo.com/Barcelona", "clubelo_barcelona.json"),
    ("https://understat.com/getMatchData/26123", "understat_getmatchdata_26123.json"),
    ("https://understat.com/", "understat_raiz.json"),
])
def test_el_nombre_de_fichero_es_legible(url, esperado):
    assert nombre_de_fichero(url) == esperado


def test_los_dos_hosts_de_sofascore_van_al_mismo_fichero():
    """Es el mismo dato: da igual por cuál de los dos haya entrado."""
    assert nombre_de_fichero("https://api.sofascore.com/api/v1/event/1") == \
           nombre_de_fichero("https://www.sofascore.com/api/v1/event/1")


def test_las_fuentes_no_chocan_entre_ellas():
    """Sin el prefijo de la fuente, un /Barcelona pisaría a otro."""
    assert nombre_de_fichero("http://api.clubelo.com/Barcelona") != \
           nombre_de_fichero("https://understat.com/Barcelona")


def test_graba_lo_que_pasa_y_no_lo_cambia(tmp_path):
    falso = FakeTransport({"/event/": {"event": {"id": 1, "customId": "OR"}}})
    grabadora = Grabadora(falso, tmp_path)
    respuesta = grabadora.request("GET", URL, {})
    assert respuesta.json() == {"event": {"id": 1, "customId": "OR"}}
    assert grabadora.guardadas == ["sofascore_event_12437616.json"]


def test_lo_grabado_se_reproduce_igual(tmp_path):
    payload = {"event": {"id": 1, "customId": "OR"}}
    Grabadora(FakeTransport({"/event/": payload}), tmp_path).request("GET", URL, {})
    reproducida = Reproductor(tmp_path).request("GET", URL, {})
    assert reproducida.status == 200
    assert reproducida.json() == payload


def test_lo_que_no_esta_grabado_se_dice(tmp_path):
    """Un 404 explícito, no una espera a un servidor que nadie llamó."""
    reproductor = Reproductor(tmp_path)
    respuesta = reproductor.request("GET", URL, {})
    assert respuesta.status == 404
    assert reproductor.no_encontradas == [URL]


def test_no_se_guardan_las_respuestas_con_error(tmp_path):
    grabadora = Grabadora(FakeTransport({"/event/": 500}), tmp_path)
    grabadora.request("GET", URL, {})
    assert grabadora.guardadas == []
    assert not cargar(tmp_path)


def test_tambien_graba_lo_que_no_es_json(tmp_path):
    """ClubElo sirve CSV: tiene que poder guardarse igual."""
    csv = "Rank,Club,Elo\n1,Man City,2032.4\n"
    falso = FakeTransport({"/Barcelona": Response(200, "x", csv.encode())})
    grabadora = Grabadora(falso, tmp_path)
    grabadora.request("GET", "http://api.clubelo.com/Barcelona", {})
    grabada = cargar(tmp_path)["clubelo_barcelona.json"]
    assert grabada.texto_plano is True
    assert grabada.cuerpo == csv
    assert grabada.como_respuesta().text() == csv


def test_que_falle_el_disco_no_tumba_la_peticion(tmp_path, monkeypatch):
    grabadora = Grabadora(FakeTransport({"/event/": {"event": {"id": 1}}}), tmp_path)
    monkeypatch.setattr(
        Grabadora, "_guardar",
        lambda self, r: (_ for _ in ()).throw(OSError("disco lleno")),
    )
    assert grabadora.request("GET", URL, {}).status == 200


def test_una_grabacion_corrupta_se_ignora(tmp_path):
    (tmp_path / "rota.json").write_text("{esto no es json", encoding="utf-8")
    (tmp_path / "buena.json").write_text(
        json.dumps({"url": URL, "estado": 200, "cuerpo": {"ok": True}}), encoding="utf-8"
    )
    assert set(cargar(tmp_path)) == {"buena.json"}


def test_una_carpeta_que_no_existe_no_es_un_error(tmp_path):
    assert cargar(tmp_path / "no_existe") == {}
    assert resumen(tmp_path / "no_existe") == {"grabaciones": 0}


def test_el_resumen_cuenta_lo_que_hay(tmp_path):
    Grabadora(FakeTransport({"/event/": {"a": 1}}), tmp_path).request("GET", URL, {})
    datos = resumen(tmp_path)
    assert datos["grabaciones"] == 1
    assert datos["rutas"] == ["/event/12437616"]
    assert datos["desde"]


def test_los_ajustes_deciden_si_se_graba_o_se_reproduce(tmp_path):
    base = FakeTransport({})
    assert preparar_transporte(base, Settings()) is base
    assert isinstance(preparar_transporte(base, Settings(grabar_en=str(tmp_path))), Grabadora)
    assert isinstance(preparar_transporte(base, Settings(reproducir_de=str(tmp_path))), Reproductor)


def test_reproducir_gana_a_grabar(tmp_path):
    """Sirviendo de una grabación no tiene sentido volver a grabarla."""
    ajustes = Settings(grabar_en=str(tmp_path), reproducir_de=str(tmp_path))
    assert isinstance(preparar_transporte(FakeTransport({}), ajustes), Reproductor)


def test_el_cliente_graba_solo_si_se_lo_pides(tmp_path):
    cliente = SofascoreClient(
        Settings(rate_limit=0, retries=0, grabar_en=str(tmp_path), fallback_base_urls=()),
        transport=FakeTransport({"/event/": {"event": {"id": 12437616}}}),
        cache=MemoryCache(), sleep=lambda _s: None,
    )
    cliente.event(12437616)
    assert cargar(tmp_path)


def test_un_comando_entero_se_puede_reproducir_sin_red(tmp_path):
    """Lo que hace útil el modo --replay: repetir lo que pasó, tal cual."""
    import sys

    sys.path.insert(0, "tests")
    from conftest import EVENT_ID, rutas_por_defecto

    from cancha.match import build_report

    grabando = SofascoreClient(
        Settings(rate_limit=0, retries=0, cache_ttl=0, grabar_en=str(tmp_path),
                 fallback_base_urls=()),
        transport=FakeTransport(rutas_por_defecto()), cache=MemoryCache(),
        sleep=lambda _s: None,
    )
    original = build_report(grabando, EVENT_ID)

    reproduciendo = SofascoreClient(
        Settings(rate_limit=0, retries=0, cache_ttl=0, reproducir_de=str(tmp_path),
                 fallback_base_urls=()),
        cache=MemoryCache(), sleep=lambda _s: None,
    )
    repetido = build_report(reproduciendo, EVENT_ID)

    assert repetido.available() == original.available()
    assert repetido.event.label == original.event.label


def test_una_grabacion_va_y_vuelve_sin_perder_nada():
    respuesta = Response(200, URL, b'{"a": [1, 2]}', {"content-type": "application/json"})
    ida = Grabacion.desde_respuesta(respuesta)
    vuelta = Grabacion.from_dict(ida.to_dict())
    assert vuelta.como_respuesta().json() == {"a": [1, 2]}
    assert vuelta.cabeceras == {"content-type": "application/json"}


def test_la_suite_no_puede_salir_a_la_red():
    """La red de seguridad que faltaba, comprobada.

    Al partir el CLI cambió el punto donde los tests inyectan el cliente falso,
    varios empezaron a llamar a la API de verdad y la suite se quedó colgada dos
    minutos sin decir por qué. Ahora eso es un fallo inmediato y con nombre.
    """
    from cancha.transport import UrllibTransport

    with pytest.raises(AssertionError, match="salir a la red"):
        UrllibTransport().request("GET", "https://api.sofascore.com/api/v1/event/1", {})
