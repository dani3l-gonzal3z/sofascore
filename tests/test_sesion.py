"""La sesión de análisis: pagar una vez por lo que se pregunta varias veces.

Lo que se comprueba aquí no es que devuelva los datos —eso ya lo prueban otros—
sino que **no repita trabajo**, contando las peticiones que salen de verdad.
"""

from __future__ import annotations

import pytest
from conftest import EVENT_ID, rutas_por_defecto

from cancha.cache import MemoryCache, NullCache
from cancha.client import SofascoreClient
from cancha.config import Settings
from cancha.models import Event
from cancha.sesion import Sesion
from cancha.transport import FakeTransport


@pytest.fixture
def espia():
    return FakeTransport(rutas_por_defecto())


@pytest.fixture
def sesion(espia):
    # Sin caché de ninguna clase: así lo que se cuenta es lo que ahorra la
    # sesión, no lo que taparía la caché en disco.
    cliente = SofascoreClient(
        Settings(rate_limit=0, retries=0, fallback_base_urls=()),
        transport=espia, cache=NullCache(), sleep=lambda _s: None,
    )
    return Sesion(cliente=cliente)


def test_repetir_la_misma_pregunta_no_cuesta_nada(sesion, espia):
    sesion.informe(EVENT_ID, ["statistics"])
    gastado = len(espia.calls)
    sesion.informe(EVENT_ID, ["statistics"])
    assert len(espia.calls) == gastado
    assert sesion.reutilizados >= 1


def test_pedir_otra_seccion_solo_cuesta_esa(sesion, espia):
    sesion.informe(EVENT_ID, ["statistics"])
    gastado = len(espia.calls)
    sesion.informe(EVENT_ID, ["shotmap"])
    assert len(espia.calls) == gastado + 1, "debería haber pedido solo el mapa de tiros"


def test_el_informe_va_acumulando_secciones(sesion):
    sesion.informe(EVENT_ID, ["statistics"])
    informe = sesion.informe(EVENT_ID, ["shotmap"])
    assert {"event", "statistics", "shotmap"} <= set(informe.sections)


def test_resolver_el_mismo_partido_dos_veces_no_vuelve_a_buscar(sesion, espia):
    sesion.evento("Real Madrid vs Barcelona", "2024-10-26")
    gastado = len(espia.calls)
    sesion.evento("Real Madrid vs Barcelona", "2024-10-26")
    assert len(espia.calls) == gastado


def test_lo_resuelto_por_nombre_vale_luego_por_id(sesion, espia):
    evento = sesion.evento("Real Madrid vs Barcelona", "2024-10-26")
    gastado = len(espia.calls)
    assert sesion.evento(evento.id).id == evento.id
    assert len(espia.calls) == gastado


def test_guarda_los_candidatos_y_no_solo_el_elegido(sesion, espia):
    """Preguntar "¿cuál de todos?" no debería pagar otra búsqueda."""
    primera = sesion.resolucion("Real Madrid vs Barcelona", "2024-10-26")
    gastado = len(espia.calls)
    segunda = sesion.resolucion("Real Madrid vs Barcelona", "2024-10-26")
    assert len(espia.calls) == gastado
    assert segunda.candidates == primera.candidates


def test_un_evento_ya_resuelto_se_devuelve_tal_cual(sesion, espia):
    evento = Event(id=99, slug="x")
    assert sesion.evento(evento) is evento
    assert espia.calls == []


def test_olvidar_un_partido_obliga_a_volver_a_pedirlo(sesion, espia):
    sesion.informe(EVENT_ID, ["statistics"])
    gastado = len(espia.calls)
    sesion.olvidar(EVENT_ID)
    sesion.informe(EVENT_ID, ["statistics"])
    assert len(espia.calls) > gastado


def test_olvidarlo_todo(sesion):
    sesion.informe(EVENT_ID, ["statistics"])
    sesion.olvidar()
    assert sesion.estado()["partidos_resueltos"] == 0
    assert sesion.estado()["informes"] == {}


def test_el_estado_dice_lo_que_hay_guardado(sesion):
    sesion.informe(EVENT_ID, ["statistics"])
    estado = sesion.estado()
    assert estado["partidos_resueltos"] == 1
    assert "statistics" in estado["informes"][EVENT_ID]
    assert "peticiones" in estado


def test_una_sesion_propia_se_cierra_sola():
    with Sesion(settings=Settings(rate_limit=0, offline=True)) as sesion:
        assert sesion.cliente is not None
    # Cerrar una sesión con cliente prestado no cierra el cliente de otro.
    cliente = SofascoreClient(Settings(rate_limit=0), cache=MemoryCache())
    Sesion(cliente=cliente).close()
    assert cliente.transport is not None


# ------------------------------------------------- lo que gana una IA con esto

def test_una_conversacion_entera_paga_cada_seccion_una_vez(espia):
    """Ocho preguntas sobre el mismo partido, como las haría un modelo."""
    from cancha.tools import ejecutar

    cliente = SofascoreClient(
        Settings(rate_limit=0, retries=0, fallback_base_urls=()),
        transport=espia, cache=NullCache(), sleep=lambda _s: None,
    )
    sesion = Sesion(cliente=cliente)
    preguntas = [
        ("resumen_partido", {"partido": str(EVENT_ID)}),
        ("estadisticas_partido", {"partido": str(EVENT_ID)}),
        ("jugadores_partido", {"partido": str(EVENT_ID)}),
        ("cronologia_partido", {"partido": str(EVENT_ID)}),
        ("tiros_partido", {"partido": str(EVENT_ID)}),
        ("momento_partido", {"partido": str(EVENT_ID)}),
        ("estadisticas_partido", {"partido": str(EVENT_ID), "periodo": "1ST"}),
        ("jugadores_partido", {"partido": str(EVENT_ID), "equipo": "Barcelona"}),
    ]
    for nombre, argumentos in preguntas:
        salida = ejecutar(nombre, argumentos, sesion=sesion)
        assert "error" not in salida, (nombre, salida)

    con_sesion = len(espia.calls)

    # Lo mismo sin sesión: cada herramienta empieza de cero.
    espia.calls.clear()
    for nombre, argumentos in preguntas:
        ejecutar(nombre, argumentos, cliente=SofascoreClient(
            Settings(rate_limit=0, retries=0, fallback_base_urls=()),
            transport=espia, cache=NullCache(), sleep=lambda _s: None))
    sin_sesion = len(espia.calls)

    assert con_sesion < sin_sesion, "la sesión no está ahorrando nada"
    print(f"\n  con sesión: {con_sesion} peticiones · sin sesión: {sin_sesion}")
