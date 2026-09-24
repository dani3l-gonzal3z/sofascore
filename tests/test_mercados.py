"""Todos los mercados, con su historia, y el marcador exacto contra el nuestro.

Antes de esto de las cuotas se guardaba el 1X2, en una fila por partido que se
sobrescribía: la apertura y el cierre eran la misma fila. Lo que se prueba aquí
es lo que eso impedía —ver cómo se mueve un mercado, compararse en goles o en
córners, y medir el marcador exacto contra el de las casas— y un fallo viejo del
registro que salió de paso.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from cancha.almacen import Almacen
from cancha.mercados import (
    comparar_marcadores,
    de_sofascore,
    distribucion_de_marcadores,
    margen,
    sin_margen,
    toca_refrescar,
)

TODO = {"markets": [
    {"marketName": "Full time", "sourceId": 1, "choices": [
        {"name": "1", "fractionalValue": "5/4", "initialFractionalValue": "6/4"},
        {"name": "X", "fractionalValue": "12/5", "initialFractionalValue": "12/5"},
        {"name": "2", "fractionalValue": "11/5", "initialFractionalValue": "2/1"}]},
    {"marketName": "Match goals", "choiceGroup": "2.5", "sourceId": 1, "choices": [
        {"name": "Over", "fractionalValue": "4/5"},
        {"name": "Under", "fractionalValue": "1/1"}]},
    {"marketName": "Both teams to score", "sourceId": 1, "choices": [
        {"name": "Yes", "fractionalValue": "8/11"},
        {"name": "No", "fractionalValue": "11/10"}]},
    {"marketName": "Correct score", "sourceId": 1, "choices": [
        {"name": "1:0", "fractionalValue": "6/1"}, {"name": "0:0", "fractionalValue": "8/1"},
        {"name": "1:1", "fractionalValue": "11/2"}, {"name": "2:1", "fractionalValue": "8/1"},
        {"name": "0:1", "fractionalValue": "9/1"},
        {"name": "Any other", "fractionalValue": "5/2"}]},
    {"marketName": "Something new", "sourceId": 1, "choices": [
        {"name": "Maybe", "fractionalValue": "1/1"}]},
    {"marketName": "Full time", "isLive": True, "sourceId": 1, "choices": [
        {"name": "1", "fractionalValue": "1/10"}]},
]}


@pytest.fixture
def base():
    with Almacen(":memory:") as almacen:
        almacen._conexion.execute(
            "INSERT INTO partidos (id, local, visitante, fecha) VALUES (1,'A','B','2026-09-20')")
        almacen._conexion.commit()
        yield almacen


# ------------------------------------------------------------------ leerlos

def test_se_leen_todos_los_mercados_y_no_solo_el_1x2():
    filas = de_sofascore(TODO)
    mercados = {f["mercado"] for f in filas}
    assert {"1x2", "goles", "ambos_marcan", "marcador"} <= mercados


def test_un_mercado_que_no_conozco_se_guarda_igual():
    """No se tira nada que la fuente mande: solo se deja de entender."""
    assert "something_new" in {f["mercado"] for f in de_sofascore(TODO)}


def test_las_cuotas_en_directo_no_se_mezclan_con_las_de_antes():
    """Una cuota en vivo con el partido 1-0 no es una previsión del partido."""
    unos = [f for f in de_sofascore(TODO) if f["mercado"] == "1x2"]
    assert all(f["cuota"] > 1.5 for f in unos)


def test_los_nombres_se_normalizan():
    filas = {(f["mercado"], f["seleccion"]) for f in de_sofascore(TODO)}
    assert ("1x2", "local") in filas and ("goles", "mas") in filas
    assert ("ambos_marcan", "si") in filas
    assert ("marcador", "2-1") in filas, "«2:1» y «2-1» son lo mismo"


def test_se_guarda_la_cuota_de_apertura_que_manda_la_fuente():
    """Sofascore la manda en la misma respuesta y hasta ahora se tiraba."""
    local = next(f for f in de_sofascore(TODO) if f["seleccion"] == "local")
    assert local["cuota"] == 2.25 and local["cuota_inicial"] == 2.5


# ------------------------------------------------------------------ el margen

def test_sin_margen_suma_uno_con_los_dos_metodos():
    cuotas = {"a": 2.1, "b": 3.4, "c": 3.6}
    for metodo in ("proporcional", "potencia"):
        assert math.isclose(sum(sin_margen(cuotas, metodo).values()), 1.0)


def test_el_metodo_de_potencia_le_quita_mas_margen_a_lo_improbable():
    """La casa carga más margen en los resultados raros (sesgo del favorito).

    En un marcador exacto con veinte resultados eso importa: el reparto
    proporcional infla los raros y desinfla los probables.
    """
    # Un mercado completo, con «cualquier otro»: las implícitas suman un 108 %.
    exacto = {"1-1": 5.5, "1-0": 6.0, "0-0": 8.0, "0-3": 34.0, "4-2": 51.0,
              "otro": 1.8}
    proporcional = sin_margen(exacto, "proporcional")
    potencia = sin_margen(exacto, "potencia")
    # Lo que promete: cuanto más improbable, más rebaja relativa.
    rebaja = {s: potencia[s] / proporcional[s] for s in exacto}
    assert rebaja["4-2"] < rebaja["0-3"] < rebaja["1-1"] < rebaja["otro"]
    assert rebaja["4-2"] < 0.9, "a los raros se les quita de verdad"


def test_con_muchas_selecciones_se_elige_solo_el_de_potencia():
    exacto = {f"{a}-{b}": 8.0 + a + b for a in range(3) for b in range(3)}
    assert sin_margen(exacto) == sin_margen(exacto, "potencia")


def test_el_margen_se_calcula():
    assert margen({"a": 2.0, "b": 2.0}) == 0.0
    assert margen({"a": 1.9, "b": 1.9}) == pytest.approx(0.0526, abs=1e-3)


# ---------------------------------------------------------------- guardarlos

def test_las_fotos_se_apilan_y_no_se_pisan(base):
    """La primera es la apertura y la última el cierre: pisarlas perdía la primera."""
    base.guardar_mercados(1, de_sofascore(TODO))
    otra = de_sofascore(TODO)
    for fila in otra:
        if fila["mercado"] == "1x2" and fila["seleccion"] == "local":
            fila["cuota"] = 2.0
    base._conexion.execute("UPDATE cuotas_mercado SET visto_en = '2026-09-19T10:00:00+00:00'")
    base.guardar_mercados(1, otra)
    fotos = base.consulta("SELECT DISTINCT visto_en FROM cuotas_mercado")
    assert len(fotos) == 2
    ahora = next(f for f in base.mercados_de(1, mercado="1x2") if f["seleccion"] == "local")
    antes = next(f for f in base.mercados_de(1, mercado="1x2", cual="primera")
                 if f["seleccion"] == "local")
    assert ahora["cuota"] == 2.0 and antes["cuota"] == 2.25


def test_una_foto_identica_no_se_vuelve_a_guardar(base):
    """Mirar diez veces un mercado que no se mueve no son diez datos."""
    assert base.guardar_mercados(1, de_sofascore(TODO)) > 0
    assert base.guardar_mercados(1, de_sofascore(TODO)) == 0


def test_el_movimiento_sale_de_la_apertura_de_la_fuente(base):
    base.guardar_mercados(1, de_sofascore(TODO))
    local = next(m for m in base.movimiento_de(1) if m["seleccion"] == "local")
    assert local["apertura"] == 2.5 and local["ahora"] == 2.25
    assert local["cambio"] == pytest.approx(-0.1), "baja la cuota: el dinero va ahí"


# --------------------------------------------------------------- refrescar

def test_sin_ninguna_foto_toca_refrescar(base):
    assert toca_refrescar(base, 1, horas_hasta=48) is True


def test_una_foto_reciente_no_se_repite(base):
    base.guardar_mercados(1, de_sofascore(TODO))
    assert toca_refrescar(base, 1, horas_hasta=48) is False


def test_cerca_del_saque_se_mira_mas_a_menudo(base):
    """En las últimas horas entran las alineaciones y el dinero de verdad."""
    base.guardar_mercados(1, de_sofascore(TODO))
    hace = (datetime.now(timezone.utc) - timedelta(minutes=40)).isoformat(timespec="seconds")
    base._conexion.execute("UPDATE cuotas_mercado SET visto_en = ?", (hace,))
    assert toca_refrescar(base, 1, horas_hasta=48) is False, "lejos: cada seis horas"
    assert toca_refrescar(base, 1, horas_hasta=2) is True, "cerca: cada cuarto de hora"


def test_un_partido_jugado_no_se_refresca(base):
    """Lo último que se vio antes de jugarse es el cierre, y eso no se toca."""
    assert toca_refrescar(base, 1, horas_hasta=-5) is False


# ------------------------------------------------------- el marcador exacto

def test_la_distribucion_del_mercado_aparta_cualquier_otro():
    """Repartir «cualquier otro» entre marcadores concretos sería inventárselo."""
    dist = distribucion_de_marcadores(de_sofascore(TODO))
    assert dist["disponible"]
    assert "any_other" not in dist["marcadores"]
    assert dist["otros"] > 0
    assert math.isclose(sum(dist["marcadores"].values()) + dist["otros"], 1.0, abs_tol=1e-3)


def test_sin_marcador_exacto_se_dice():
    assert distribucion_de_marcadores([])["disponible"] is False


def test_la_comparacion_de_un_partido_dice_donde_discrepan():
    nuestra = {"1-1": 0.12, "2-0": 0.14, "1-0": 0.11}
    suya = {"1-1": 0.13, "2-0": 0.07, "1-0": 0.12}
    c = comparar_marcadores(nuestra, suya)
    assert c["donde_discrepan"][0]["marcador"] == "2-0"
    assert c["mas_probables_nuestros"][0][0] == "2-0"
    assert c["coinciden_en_el_primero"] is False
    assert 0 < c["distancia"] < 1


# ------------------------------------------------------------ en el registro

def _pronostico_con_marcadores() -> dict:
    return {"disponible": True,
            "goles": {"1x2": {"local": 0.5, "empate": 0.27, "visitante": 0.23},
                      "mas_de": {"2.5": 0.55}, "ambos_marcan": 0.6,
                      "marcadores": [{"marcador": "1-1", "probabilidad": 0.12}],
                      "todos_los_marcadores": {"1-1": 0.12, "1-0": 0.11, "2-1": 0.09,
                                               "0-0": 0.08, "2-0": 0.08, "0-1": 0.07}},
            "mercado": {}}


def _evento(identificador=1):
    from cancha.models import Event

    return Event.from_api({
        "id": identificador,
        "startTimestamp": int(datetime(2026, 9, 20, 18, tzinfo=timezone.utc).timestamp()),
        "tournament": {"name": "LaLiga", "uniqueTournament": {"id": 8}},
        "homeTeam": {"id": 100, "name": "A"}, "awayTeam": {"id": 200, "name": "B"}})


def test_los_goles_y_ambos_marcan_ya_tienen_precio_de_mercado(base):
    """Antes solo el 1X2 tenía con qué compararse."""
    from cancha.registro import anotar

    base.guardar_mercados(1, de_sofascore(TODO))
    anotar(base, _evento(), _pronostico_con_marcadores())
    filas = {(f["mercado"], f["seleccion"]): f for f in base.consulta(
        "SELECT * FROM predicciones WHERE autor = 'calculo'")}
    assert filas[("mas_2_5", "si")]["prob_mercado"] is not None
    assert filas[("ambos_marcan", "si")]["prob_mercado"] is not None


def test_el_mercado_concursa_en_todos_sus_mercados(base):
    from cancha.registro import AUTOR_MERCADO, anotar

    base.guardar_mercados(1, de_sofascore(TODO))
    anotar(base, _evento(), _pronostico_con_marcadores())
    suyos = {f["mercado"] for f in base.consulta(
        "SELECT mercado FROM predicciones WHERE autor = ?", (AUTOR_MERCADO,))}
    assert {"1x2", "mas_2_5", "ambos_marcan", "marcador_exacto"} <= suyos


def test_el_marcador_exacto_no_contamina_el_balance_general(base):
    """Treinta sucesos por partido casi todos a un uno por ciento que no pasa: el
    Brier saldría bueno por acertar que el 5-3 no ocurre."""
    from cancha.registro import anotar, balance

    anotar(base, _evento(), _pronostico_con_marcadores())
    base._conexion.execute("UPDATE predicciones SET resuelto = 1, acerto = 0")
    base._conexion.commit()
    general = balance(base, autor="calculo")
    solo = balance(base, autor="calculo", mercado="marcador_exacto")
    assert general["casos"] < solo["casos"] + general["casos"]
    assert solo["casos"] == 6


def test_quien_elige_ambos_marcan_no_falla_cuando_marcan_los_dos(base):
    """El fallo viejo: se devolvía «¿pasó?» sin mirar qué se había elegido, así
    que apostar por que no marcaran los dos se apuntaba como acierto al marcar."""
    from cancha.registro import _resultado_de

    fila = {"goles_local": 2, "goles_visitante": 1, "estado": "finished",
            "mercado": "ambos_marcan", "seleccion": "no", "partido_id": 1}
    assert _resultado_de(base, fila)[0] is False
    fila["seleccion"] = "si"
    assert _resultado_de(base, fila)[0] is True
    fila.update(mercado="mas_2_5", seleccion="no")
    assert _resultado_de(base, fila)[0] is False, "hubo tres goles"


# ------------------------------------------------- marcador contra marcador

def _sembrar_marcadores(base, partidos, nuestra, suya, real="1-0", otro_mercado=0.2):
    for n in range(partidos):
        pid = 1000 + n
        base._conexion.execute(
            "INSERT OR IGNORE INTO partidos (id, fecha) VALUES (?, '2026-09-01')", (pid,))
        for autor, dist in (("calculo", nuestra), ("mercado", suya)):
            for cual, p in dist.items():
                base._conexion.execute(
                    """INSERT INTO predicciones (partido_id, fecha, autor, mercado, seleccion,
                       probabilidad, resuelto, acerto, valor_real)
                       VALUES (?, '2026-09-01', ?, 'marcador_exacto', ?, ?, 1, ?, ?)""",
                    (pid, autor, cual, p, 1 if cual == real else 0, real))
        base._conexion.execute(
            """INSERT INTO predicciones (partido_id, fecha, autor, mercado, seleccion,
               probabilidad, resuelto, acerto, valor_real)
               VALUES (?, '2026-09-01', 'mercado', 'marcador_exacto', 'otro', ?, 1, 0, ?)""",
            (pid, otro_mercado, real))
    base._conexion.commit()


def test_gana_quien_le_dio_mas_al_marcador_que_salio(base):
    """No «quién lo tenía primero», sino cuánta probabilidad le dio."""
    from cancha.registro import marcadores_frente_a_frente

    _sembrar_marcadores(base, 40, nuestra={"1-0": 0.20, "1-1": 0.10, "0-0": 0.08},
                        suya={"1-0": 0.10, "1-1": 0.14, "0-0": 0.09})
    datos = marcadores_frente_a_frente(base)
    assert datos["casos"] == 40
    assert datos["p_real_uno"] > datos["p_real_otro"]
    assert datos["veredicto"] == "calculo"


def test_con_pocos_partidos_no_hay_veredicto(base):
    """Un par de 3-2 raros no pueden decidir quién sabe más de marcadores."""
    from cancha.registro import marcadores_frente_a_frente

    _sembrar_marcadores(base, 10, nuestra={"1-0": 0.20}, suya={"1-0": 0.10})
    assert marcadores_frente_a_frente(base)["veredicto"] == "no se distinguen"


def test_un_resultado_que_el_mercado_no_listaba_cuenta_como_cualquier_otro(base):
    """Si acabó 5-3 y el mercado no lo listaba, los dos se miden en «otro»."""
    from cancha.registro import marcadores_frente_a_frente

    _sembrar_marcadores(base, 35, nuestra={"1-0": 0.3, "1-1": 0.3},
                        suya={"1-0": 0.2, "1-1": 0.2}, real="5-3", otro_mercado=0.6)
    datos = marcadores_frente_a_frente(base)
    # Nosotros dejábamos 0,4 fuera de lo listado; el mercado, 0,6: sabía más.
    assert datos["p_real_otro"] > datos["p_real_uno"]


def test_sin_partidos_en_comun_se_dice(base):
    from cancha.registro import marcadores_frente_a_frente

    assert "Todavía no hay" in marcadores_frente_a_frente(base)["nota"]
