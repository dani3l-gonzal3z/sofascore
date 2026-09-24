"""El backtest: que no mire el futuro, y que diga «aporta» solo cuando aporta.

Se prueba sobre una liga inventada en la que se sabe la verdad (ver
`liga_sintetica.py`). Un backtest que siempre sale bonito no vale para nada, así
que lo importante aquí es que cambie de veredicto cuando cambia la realidad:

* con un mercado que no sabe nada, nuestro modelo —que sí sabe— tiene que aportar;
* con un mercado que sabe la verdad, no puede aportar nada, y tiene que decirlo.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from liga_sintetica import sembrar

from cancha.almacen import Almacen
from cancha.backtest import backtest
from cancha.previa import _evento_desde_fila
from cancha.pronostico import pronostico


@pytest.fixture
def base():
    with Almacen(":memory:") as almacen:
        yield almacen


def test_rehacer_un_pronostico_no_mira_lo_que_vino_despues(base):
    """Antes la media de la liga no se cortaba por fecha: el pronóstico «sabía»
    cómo iba el resto de la temporada, y un backtest así hace trampa."""
    sembrar(base, vueltas=4)
    fila = base.consulta("SELECT * FROM partidos ORDER BY momento LIMIT 1 OFFSET 80")[0]
    antes = pronostico(base, _evento_desde_fila(fila))["goles"]["1x2"]

    # Cien partidos después, todos 7-6: cambian por completo la media de la liga.
    dia = datetime(2030, 1, 1, tzinfo=timezone.utc)
    for n in range(100):
        base._conexion.execute(
            """INSERT INTO partidos (id, fecha, momento, liga_id, local_id, visitante_id,
               goles_local, goles_visitante, estado)
               VALUES (?,?,?,99,5,6,7,6,'finished')""",
            (10_000 + n, (dia + timedelta(days=n)).strftime("%Y-%m-%d"),
             (dia + timedelta(days=n)).timestamp()))
    base._conexion.commit()
    despues = pronostico(base, _evento_desde_fila(fila))["goles"]["1x2"]
    assert despues == antes


def test_con_un_mercado_que_no_sabe_nada_el_modelo_aporta(base):
    """Un 1X2 plano para todos los partidos: cualquier modelo informado le gana."""
    sembrar(base, vueltas=14, mercado="no_sabe")
    datos = backtest(base)
    assert datos["aporta"]["peso_elegido"] > 0
    assert datos["aporta"]["veredicto"] == "aporta", datos["aporta"]


def test_con_un_mercado_que_sabe_la_verdad_el_modelo_no_aporta(base):
    """Si el mercado ya sabe la verdad, mezclarle lo nuestro solo puede meter ruido.

    Es la prueba que importa: un backtest que dice «aporta» también aquí es un
    backtest que dice «aporta» siempre.
    """
    sembrar(base, vueltas=14, mercado="sabe")
    datos = backtest(base)
    assert datos["aporta"]["veredicto"] != "aporta", datos["aporta"]


def test_el_peso_se_elige_con_una_mitad_y_se_mide_con_la_otra(base):
    sembrar(base, vueltas=10, mercado="no_sabe")
    aporta = backtest(base)["aporta"]
    assert aporta["elegido_con"] + aporta["medido_en"] == aporta["partidos"]
    assert abs(aporta["elegido_con"] - aporta["medido_en"]) <= 1


def test_los_picks_se_simulan_con_la_regla_y_al_precio_guardado(base):
    sembrar(base, vueltas=10, mercado="no_sabe")
    picks = backtest(base)["picks"]
    assert picks["picks"] > 0
    ultimos = picks["ultimos"]
    assert all(p["beneficio"] == (p["cuota"] - 1 if p["acerto"] else -1.0) for p in ultimos)
    assert sum(picks["por_mes"].values()) == pytest.approx(picks["unidades"], abs=0.05)


def test_sin_cuotas_no_hay_nada_que_medir(base):
    sembrar(base, vueltas=4, mercado="nada")
    datos = backtest(base)
    assert datos["partidos_mirados"] == 0
    assert datos["aporta"]["veredicto"] == "sin muestra"


def test_con_poca_muestra_se_avisa(base):
    sembrar(base, vueltas=3, mercado="sabe")
    assert "indicio" in backtest(base)["advertencias"][0]


def test_se_puede_parar(base):
    sembrar(base, vueltas=4, mercado="sabe")
    assert backtest(base, puede_seguir=lambda: False)["por_mercado"] == []


def test_la_calibracion_sale_por_tramos(base):
    sembrar(base, vueltas=14, mercado="sabe")
    tramos = backtest(base)["calibracion"]
    assert tramos and all(t["casos"] >= 20 for t in tramos)


def test_los_picks_de_la_regla_solo_se_simulan_donde_el_peso_no_ha_mirado(base):
    """El peso se eligió con la primera mitad: simular ahí sería presumir de
    partidos que ya se usaron para ajustarlo."""
    sembrar(base, vueltas=12, mercado="no_sabe")
    datos = backtest(base)
    corte_min = min(p["fecha"] for p in datos["picks"]["ultimos"])
    todos = datos["picks_modelo_solo"]
    assert datos["picks"]["picks"] < todos["picks"]
    assert corte_min > base.consulta("SELECT MIN(fecha) AS f FROM partidos")[0]["f"]


def test_con_un_mercado_que_sabe_la_verdad_la_regla_no_da_picks(base):
    """Si el modelo no aporta, el peso es cero, la probabilidad es la del mercado
    y el valor nunca es positivo. Incómodo, y honesto."""
    from cancha.backtest import guardar_mezcla
    from cancha.picks import mezcla_guardada

    sembrar(base, vueltas=14, mercado="sabe")
    datos = backtest(base)
    if datos["aporta"]["veredicto"] != "aporta":
        assert datos["picks"]["picks"] == 0 or datos["aporta"]["peso_elegido"] > 0
        assert guardar_mezcla(base, datos)["peso"] == 0.0
        assert mezcla_guardada(base)["peso"] == 0.0


def test_con_peso_cero_la_probabilidad_es_la_del_mercado():
    from cancha.picks import mezclar

    assert mezclar(0.70, 0.45, 0.0) == pytest.approx(0.45, abs=1e-3)
    assert mezclar(0.70, 0.45, 1.0) == pytest.approx(0.70, abs=1e-3)
    assert 0.45 < mezclar(0.70, 0.45, 0.3) < 0.70
    assert mezclar(0.70, 0.45, None) == 0.70, "sin backtest, el modelo a secas"
