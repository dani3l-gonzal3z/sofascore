"""La capa de herramientas para una IA.

Lo que se comprueba aquí es lo que le importa a un modelo: que las
descripciones y esquemas sean utilizables, que las respuestas quepan en su
contexto y que un fallo llegue como dato legible y no como excepción.
"""

from __future__ import annotations

import json

import pytest
from conftest import EVENT_ID, rutas_por_defecto

from sofascore.cache import MemoryCache
from sofascore.client import SofascoreClient
from sofascore.config import Settings
from sofascore.tools import TOOLS, ejecutar, esquemas, recortar
from sofascore.transport import FakeTransport


@pytest.fixture
def cliente():
    return SofascoreClient(
        Settings(rate_limit=0, cache_ttl=0, retries=0),
        transport=FakeTransport(rutas_por_defecto()),
        cache=MemoryCache(), sleep=lambda _s: None,
    )


# ------------------------------------------------------------------- esquemas

def test_todas_las_herramientas_estan_bien_descritas():
    for herramienta in TOOLS.values():
        assert len(herramienta.description) > 60, herramienta.name
        assert herramienta.parameters["type"] == "object"
        for nombre, prop in herramienta.parameters["properties"].items():
            assert "type" in prop, f"{herramienta.name}.{nombre}"
            assert prop.get("description"), f"{herramienta.name}.{nombre} sin descripción"


def test_los_obligatorios_existen_como_parametros():
    for herramienta in TOOLS.values():
        propiedades = herramienta.parameters["properties"]
        for obligatorio in herramienta.parameters.get("required", []):
            assert obligatorio in propiedades, f"{herramienta.name}: {obligatorio}"


def test_los_esquemas_se_serializan():
    assert json.loads(json.dumps(esquemas()))
    assert len(esquemas()) == len(TOOLS)


# ---------------------------------------------------------------------- uso

def test_resumen_es_el_punto_de_partida(cliente):
    salida = ejecutar("resumen_partido", {"partido": str(EVENT_ID)}, cliente)
    assert salida["partido"]["home"]["name"] == "Real Madrid"
    assert salida["goles"]
    # Lo que hace que la IA pueda seguir indagando:
    assert "statistics" in salida["secciones_con_datos"]
    assert "como_seguir" in salida


def test_estadisticas_en_filas_planas(cliente):
    salida = ejecutar("estadisticas_partido", {"partido": str(EVENT_ID)}, cliente)
    claves = {f["clave"] for f in salida["estadisticas"]}
    assert "ballPossession" in claves
    assert salida["grupos_disponibles"]


def test_estadisticas_por_grupo(cliente):
    salida = ejecutar(
        "estadisticas_partido", {"partido": str(EVENT_ID), "grupo": "Match overview"}, cliente
    )
    assert all(f["grupo"] == "Match overview" for f in salida["estadisticas"])


def test_jugadores_ordenados_por_nota(cliente):
    salida = ejecutar("jugadores_partido", {"partido": str(EVENT_ID)}, cliente)
    notas = [j["rating"] for j in salida["jugadores"] if j["rating"]]
    assert notas == sorted(notas, reverse=True)


def test_jugadores_de_un_solo_equipo(cliente):
    salida = ejecutar(
        "jugadores_partido", {"partido": str(EVENT_ID), "equipo": "Barcelona"}, cliente
    )
    assert salida["jugadores"]
    assert all(j["equipo"] == "Barcelona" for j in salida["jugadores"])


def test_tiros_con_xg_acumulado(cliente):
    salida = ejecutar("tiros_partido", {"partido": str(EVENT_ID)}, cliente)
    assert "xg_acumulado" in salida


def test_cronologia_filtrable(cliente):
    salida = ejecutar("cronologia_partido", {"partido": str(EVENT_ID), "tipo": "goal"}, cliente)
    assert salida["cronologia"]
    assert all(i["tipo"] == "goal" for i in salida["cronologia"])


def test_momento_agrupado_dice_quien_dominaba(cliente):
    salida = ejecutar("momento_partido", {"partido": str(EVENT_ID), "cada": 5}, cliente)
    assert salida["positivo_es"] == "Real Madrid"
    assert all("dominio" in tramo for tramo in salida["serie"])


def test_momento_al_detalle(cliente):
    salida = ejecutar("momento_partido", {"partido": str(EVENT_ID), "cada": 1}, cliente)
    assert all("minuto" in punto for punto in salida["serie"])


def test_seccion_es_la_escotilla_de_escape(cliente):
    salida = ejecutar("seccion_partido", {"partido": str(EVENT_ID), "seccion": "h2h"}, cliente)
    assert salida["estado"] == "ok"
    assert salida["datos"]


def test_una_seccion_inventada_devuelve_las_validas(cliente):
    salida = ejecutar(
        "seccion_partido", {"partido": str(EVENT_ID), "seccion": "no_existe"}, cliente
    )
    assert "error" in salida
    assert "statistics" in salida["disponibles"]


def test_catalogo_para_saber_que_pedir(cliente):
    salida = ejecutar("catalogo", {"que": "secciones"}, cliente)
    assert "match" in salida["secciones"]
    assert "team" in salida["secciones"]


def test_catalogo_de_ligas(cliente):
    assert ejecutar("catalogo", {"que": "ligas"}, cliente)["ligas"]["Spain La Liga"] == 8


def test_ficha_de_equipo(cliente):
    salida = ejecutar("ficha_equipo", {"equipo": "Real Madrid"}, cliente)
    assert salida["tipo"] == "team"


def test_clasificacion_en_filas(cliente):
    salida = ejecutar("clasificacion", {"liga": "laliga"}, cliente)
    assert salida["clasificacion"][0]["equipo"] == "Barcelona"


def test_partidos_en_directo(cliente):
    salida = ejecutar("partidos", {}, cliente)
    assert salida["cuando"] == "en directo"
    assert salida["total"] >= 1


# ------------------------------------------------------ errores y contexto

def test_una_herramienta_que_no_existe_lo_dice_sin_reventar(cliente):
    salida = ejecutar("inventada", {}, cliente)
    assert "error" in salida
    assert "resumen_partido" in salida["disponibles"]


def test_un_argumento_de_más_devuelve_el_esquema(cliente):
    salida = ejecutar("catalogo", {"parametro_raro": 1}, cliente)
    assert "error" in salida
    assert "esperados" in salida


def test_un_partido_inexistente_llega_como_dato_no_como_excepcion(cliente):
    salida = ejecutar("resumen_partido", {"partido": "Equipo Inventado vs Otro"}, cliente)
    assert "error" in salida


def test_el_recorte_de_una_lista_dice_cuanto_falta():
    salida = recortar([{"n": i, "relleno": "x" * 100} for i in range(500)], max_chars=2000)
    assert salida["recortado"] is True
    assert len(salida["elementos"]) < 500
    assert "Afina la consulta" in salida["nota"]


def test_el_recorte_de_un_diccionario_avisa_de_las_claves_perdidas():
    salida = recortar({f"c{i}": "x" * 500 for i in range(20)}, max_chars=2000)
    assert "_recortado" in salida


def test_lo_que_cabe_se_devuelve_intacto():
    datos = {"a": 1, "b": [1, 2, 3]}
    assert recortar(datos, max_chars=10_000) == datos


def test_ninguna_respuesta_se_pasa_del_tope(cliente):
    """El contexto de un modelo es finito: ninguna herramienta puede reventarlo."""
    for nombre in ("resumen_partido", "estadisticas_partido", "jugadores_partido",
                   "cronologia_partido", "momento_partido"):
        salida = ejecutar(nombre, {"partido": str(EVENT_ID)}, cliente, max_chars=4000)
        assert len(json.dumps(salida, ensure_ascii=False, default=str)) <= 6000, nombre
