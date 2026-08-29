"""Las métricas derivadas.

Aquí lo que se comprueba, además del comportamiento, es la **aritmética**: son
justo los números que un modelo calcularía mal, así que no basta con que salgan,
tienen que salir bien.
"""

from __future__ import annotations

import pytest
from conftest import EVENT_ID, rutas_por_defecto

from sofascore.analisis import (
    analisis_completo,
    aportacion_jugadores,
    calidad_de_tiro,
    carrera_xg,
    distribucion_de_goles,
    por_periodos,
    por_situacion,
    puntos_esperados,
)
from sofascore.cache import MemoryCache
from sofascore.client import SofascoreClient
from sofascore.config import Settings
from sofascore.match import build_report
from sofascore.transport import FakeTransport

LOCAL, VISITANTE = "Real Madrid", "Barcelona"


@pytest.fixture
def informe(tmp_path):
    cliente = SofascoreClient(
        Settings(cache_dir=tmp_path / "c", rate_limit=0, retries=0),
        transport=FakeTransport(rutas_por_defecto()), cache=MemoryCache(),
        sleep=lambda _s: None,
    )
    return build_report(cliente, EVENT_ID, sections=["all"])


@pytest.fixture
def sin_tiros(tmp_path):
    rutas = rutas_por_defecto()
    rutas[f"/event/{EVENT_ID}/shotmap"] = {"shotmap": []}
    cliente = SofascoreClient(
        Settings(cache_dir=tmp_path / "c2", rate_limit=0, retries=0),
        transport=FakeTransport(rutas), cache=MemoryCache(), sleep=lambda _s: None,
    )
    return build_report(cliente, EVENT_ID, sections=["all"])


# ------------------------------------------------------ la aritmética, exacta

def test_la_distribucion_de_goles_es_exacta():
    """Tres tiros de 0.5 son una binomial(3, 0.5): 1/8, 3/8, 3/8, 1/8."""
    assert distribucion_de_goles([0.5, 0.5, 0.5]) == pytest.approx([0.125, 0.375, 0.375, 0.125])


def test_la_distribucion_siempre_suma_uno():
    for tiros in ([0.1], [0.76], [0.03, 0.5, 0.9, 0.22], [0.5] * 12):
        assert sum(distribucion_de_goles(tiros)) == pytest.approx(1.0)


def test_sin_tiros_no_se_marca_seguro():
    assert distribucion_de_goles([]) == [1.0]


def test_un_xg_imposible_se_recorta():
    """Un valor corrupto no puede dar probabilidades negativas."""
    assert sum(distribucion_de_goles([1.5, -0.2])) == pytest.approx(1.0)


def test_un_penalti_solo():
    assert distribucion_de_goles([0.76]) == pytest.approx([0.24, 0.76])


# ------------------------------------------------------------ puntos esperados

def test_puntos_esperados_reparten_tres_puntos(informe):
    salida = puntos_esperados(informe)
    assert salida["disponible"]
    probabilidades = salida["probabilidades"]
    assert sum(probabilidades.values()) == pytest.approx(1.0)
    # Los puntos esperados de ambos nunca pueden pasar de 3 en total... salvo
    # por el empate, que da uno a cada uno: el tope real es 3.
    total = sum(salida["puntos_esperados"].values())
    assert 2.0 <= total <= 3.0


def test_el_que_genero_mas_tiene_mas_puntos_esperados(informe):
    """El Barça hizo 1.52 de xG contra 0.54: no puede salir por debajo."""
    esperados = puntos_esperados(informe)["puntos_esperados"]
    assert esperados[VISITANTE] > esperados[LOCAL]


def test_compara_lo_esperado_con_lo_que_pasó(informe):
    salida = puntos_esperados(informe)
    assert salida["puntos_reales"] == {LOCAL: 0, VISITANTE: 3}
    assert "lectura" in salida
    assert salida["supuesto"]


def test_sin_tiros_lo_dice_en_vez_de_inventar(sin_tiros):
    assert puntos_esperados(sin_tiros)["disponible"] is False


# ----------------------------------------------------------- calidad de tiro

def test_el_xg_por_tiro_cuadra(informe):
    equipos = calidad_de_tiro(informe)["por_equipo"]
    barca = equipos[VISITANTE]
    assert barca["xg_total"] == pytest.approx(1.52, abs=0.01)
    assert barca["tiros"] == 5
    assert barca["xg_por_tiro"] == pytest.approx(1.52 / 5, abs=0.01)


def test_distingue_ocasiones_claras_de_disparos_lejanos(informe):
    equipos = calidad_de_tiro(informe)["por_equipo"]
    assert equipos[VISITANTE]["ocasiones_claras"] == 3      # 0.34, 0.52, 0.41
    assert equipos[LOCAL]["tiros_lejanos"] == 2             # 0.04 y 0.02


def test_la_diferencia_entre_goles_y_xg_se_lee(informe):
    equipos = calidad_de_tiro(informe)["por_equipo"]
    assert equipos[VISITANTE]["goles"] == 4
    assert equipos[VISITANTE]["diferencia_goles_xg"] == pytest.approx(4 - 1.52, abs=0.01)
    assert "por encima" in equipos[VISITANTE]["lectura"]


# --------------------------------------------------------------- carrera de xG

def test_la_carrera_acumula_bien(informe):
    salida = carrera_xg(informe, cada=1)
    assert salida["total"][VISITANTE] == pytest.approx(1.52, abs=0.01)
    ultimo = salida["serie"][-1]
    assert ultimo[VISITANTE] == pytest.approx(1.52, abs=0.01)


def test_la_serie_va_en_orden_de_minuto(informe):
    minutos = [p["minuto"] for p in carrera_xg(informe, cada=1)["serie"]]
    assert minutos == sorted(minutos)


def test_dice_quien_manda_y_desde_cuando(informe):
    salida = carrera_xg(informe)
    assert salida["manda_en_xg"] == VISITANTE
    assert isinstance(salida["desde_el_minuto"], int)


def test_agrupar_reduce_la_serie(informe):
    completa = carrera_xg(informe, cada=1)["serie"]
    agrupada = carrera_xg(informe, cada=15)["serie"]
    assert len(agrupada) < len(completa)


# --------------------------------------------------------------- por situación

def test_desglosa_el_peligro_por_situacion(informe):
    bloques = por_situacion(informe)["por_equipo"][VISITANTE]
    assert "corner" in bloques
    assert bloques["corner"]["goles"] == 1
    assert bloques["assisted"]["tiros"] == 2


def test_las_situaciones_salen_de_mayor_a_menor_peligro(informe):
    bloques = por_situacion(informe)["por_equipo"][VISITANTE]
    xgs = [b["xg"] for b in bloques.values()]
    assert xgs == sorted(xgs, reverse=True)


# ------------------------------------------------------------------ aportación

def test_suma_el_xg_de_cada_jugador(informe):
    jugadores = {j["jugador"]: j for j in aportacion_jugadores(informe)["jugadores"]}
    lewa = jugadores["Robert Lewandowski"]
    assert lewa["tiros"] == 2
    assert lewa["xg"] == pytest.approx(0.86, abs=0.01)
    assert lewa["goles"] == 2


def test_ordena_por_xg_generado(informe):
    xgs = [j["xg"] for j in aportacion_jugadores(informe)["jugadores"]]
    assert xgs == sorted(xgs, reverse=True)


def test_recoge_las_asistencias_de_la_cronologia(informe):
    jugadores = {j["jugador"]: j for j in aportacion_jugadores(informe)["jugadores"]}
    assert any(j["asistencias"] for j in jugadores.values())


def test_el_minimo_deja_fuera_el_ruido(informe):
    todos = aportacion_jugadores(informe, minimo_xg=0)["jugadores"]
    filtrados = aportacion_jugadores(informe, minimo_xg=0.2)["jugadores"]
    assert len(filtrados) < len(todos)


# ----------------------------------------------------------------- periodos

def test_compara_las_dos_partes(informe):
    salida = por_periodos(informe)
    assert salida["disponible"]
    claves = {f["clave"] for f in salida["periodos"]}
    assert "ballPossession" in claves


# --------------------------------------------------------------------- el todo

def test_el_analisis_completo_trae_todos_los_bloques(informe):
    salida = analisis_completo(informe)
    assert set(salida) == {
        "partido", "puntos_esperados", "calidad_de_tiro", "carrera_xg",
        "por_situacion", "aportacion", "por_periodos",
    }
    assert salida["partido"]["titulo"].startswith("Real Madrid")


def test_un_partido_pelado_dice_que_no_puede_en_vez_de_fallar(sin_tiros):
    salida = analisis_completo(sin_tiros)
    assert salida["puntos_esperados"]["disponible"] is False
    assert salida["carrera_xg"]["disponible"] is False
    # Lo que no depende de los tiros sigue saliendo.
    assert salida["por_periodos"]["disponible"] is True


def test_las_respuestas_de_ejemplo_son_coherentes_con_el_marcador(informe):
    """Un mapa de tiros con más goles que el marcador delataría un fixture malo."""
    goles_en_tiros = {"local": 0, "visitante": 0}
    for tiro in informe.shots():
        if tiro.get("shotType") == "goal":
            goles_en_tiros["local" if tiro.get("isHome") else "visitante"] += 1
    assert goles_en_tiros["local"] == informe.event.home_score.current
    assert goles_en_tiros["visitante"] == informe.event.away_score.current


def test_quien_no_marca_no_puede_estar_por_encima_de_su_xg(informe):
    equipos = calidad_de_tiro(informe)["por_equipo"]
    assert equipos[LOCAL]["goles"] == 0
    assert equipos[LOCAL]["diferencia_goles_xg"] < 0
    assert "menos" in equipos[LOCAL]["lectura"]
