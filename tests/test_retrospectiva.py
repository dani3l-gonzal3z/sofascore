"""Un partido ya jugado: lo dicho antes, al lado de lo que pasó.

Lo delicado es medir bien «quién estuvo más cerca»: se mira la probabilidad
que cada uno le dio **a lo que pasó**, y en los sucesos de sí/no con una sola
fila apuntada eso es a veces la contraria de lo apuntado.
"""

from __future__ import annotations

import json

import pytest

from cancha.almacen import Almacen
from cancha.retrospectiva import retrospectiva

SAQUE = 1_790_000_000  # 2026-09-21 14:13 UTC


@pytest.fixture
def base():
    with Almacen(":memory:") as almacen:
        almacen._conexion.execute(
            """INSERT INTO partidos (id, fecha, momento, liga, local, visitante,
                                     goles_local, goles_visitante, estado)
               VALUES (1, '2026-09-21', ?, 'LaLiga', 'Betis', 'Sevilla', 1, 1, 'finished')""",
            (SAQUE,))
        almacen._conexion.commit()
        yield almacen


def _apuntar(almacen, autor, mercado, seleccion, prob):
    almacen._conexion.execute(
        """INSERT INTO predicciones (partido_id, fecha, autor, mercado, seleccion,
                                     probabilidad, horas_antes)
           VALUES (1, '2026-09-21', ?, ?, ?, ?, 20)""", (autor, mercado, seleccion, prob))
    almacen._conexion.commit()


def _sembrar(almacen):
    for lado, nuestra, suya in (("local", 0.45, 0.40), ("empate", 0.30, 0.27),
                                ("visitante", 0.25, 0.33)):
        _apuntar(almacen, "calculo", "1x2", lado, nuestra)
        _apuntar(almacen, "mercado", "1x2", lado, suya)
    # Nosotros apuntamos solo el «sí»; el mercado, las dos caras.
    _apuntar(almacen, "calculo", "mas_2_5", "si", 0.60)
    _apuntar(almacen, "mercado", "mas_2_5", "si", 0.52)
    _apuntar(almacen, "mercado", "mas_2_5", "no", 0.48)
    _apuntar(almacen, "calculo", "ambos_marcan", "si", 0.55)
    _apuntar(almacen, "calculo", "marcador", "1-0", 0.12)
    for marcador, prob in (("1-0", 0.12), ("1-1", 0.11), ("0-0", 0.09)):
        _apuntar(almacen, "calculo", "marcador_exacto", marcador, prob)


def test_cada_uno_se_mide_por_lo_que_le_dio_a_lo_que_paso(base):
    _sembrar(base)
    r = retrospectiva(base, 1, carpeta_briefings="/no/existe")
    assert r["jugado"] and r["marcador"] == "1-1"
    sucesos = {s["mercado"]: s for s in r["sucesos"]}

    uno = sucesos["1x2"]
    assert uno["paso"] == "empate"
    assert uno["autores"] == {"calculo": 0.30, "mercado": 0.27}
    assert uno["mas_cerca"] == "nosotros"

    # 1-1 son dos goles: no hubo más de 2,5. Apuntamos «sí» al 60 %, así que a lo
    # que pasó le dimos un 40 %; el mercado, un 48 %.
    goles = sucesos["mas_2_5"]
    assert goles["autores"]["calculo"] == pytest.approx(0.40)
    assert goles["autores"]["mercado"] == pytest.approx(0.48)
    assert goles["mas_cerca"] == "el mercado"

    assert sucesos["ambos_marcan"]["autores"]["calculo"] == pytest.approx(0.55)
    assert sucesos["ambos_marcan"]["mas_cerca"] == "sin mercado"


def test_el_marcador_que_salio_y_en_que_puesto_lo_teniamos(base):
    _sembrar(base)
    ac = retrospectiva(base, 1, carpeta_briefings="/no/existe")["aciertos"]
    assert ac["marcador_mas_probable"] == "1-0" and ac["acerto_marcador"] is False
    assert ac["puesto_del_marcador"] == 2 and ac["prob_del_marcador"] == 0.11
    assert ac["favorito_nuestro"] == "local" and ac["favorito_mercado"] == "local"
    assert ac["gano"] == "empate"


def test_lo_que_dijo_el_briefing_de_ese_dia(base, tmp_path):
    briefing = {"fecha": "2026-09-20", "generado": "2026-09-20T07:00:00+00:00", "partidos": [
        {"partido": {"id": 1, "local": "Betis", "visitante": "Sevilla"},
         "pronostico": {"disponible": True, "1x2": {"local": 0.45, "empate": 0.3,
                                                    "visitante": 0.25},
                        "marcadores": [{"marcador": "1-0", "probabilidad": 0.12}]},
         "mercado": {"disponible": True, "probabilidades": {"local": 0.4}},
         "frente_al_mercado": {"sucesos": [{"suceso": "1X2 visitante", "discrepa": True},
                                           {"suceso": "otro", "discrepa": False}]},
         "candidatos": [{"suceso": "Gana Betis", "cuota": 2.4}],
         "equipos": {"local": {"lo_que_le_distingue": [{"rasgo": "presiona alto"}]}}}]}
    (tmp_path / "2026-09-20.json").write_text(json.dumps(briefing))

    # El partido es del 21 en UTC, y el briefing se hizo el 20: se encuentra igual.
    b = retrospectiva(base, 1, carpeta_briefings=tmp_path)["briefing"]
    assert b["del_dia"] == "2026-09-20"
    assert b["pronostico"]["1x2"]["local"] == 0.45
    assert [d["suceso"] for d in b["discrepancias"]] == ["1X2 visitante"]
    assert b["pick"]["suceso"] == "Gana Betis"
    assert b["rasgos"]["local"] == ["presiona alto"]


def test_un_dictamen_hecho_despues_del_saque_no_cuenta_como_prediccion(base):
    """Ya sabía el resultado: ponerlo al lado del marcador sería hacerse trampas."""
    for hecho, texto in (("2026-09-21 10:00:00", "Antes: veo un empate."),
                         ("2026-09-22 10:00:00", "Después: se vio venir el empate.")):
        base._conexion.execute(
            "INSERT INTO dictamenes (partido_id, hecho_el, respuesta) VALUES (1, ?, ?)",
            (hecho, texto))
    base._conexion.commit()
    d = retrospectiva(base, 1, carpeta_briefings="/no/existe")["dictamen"]
    assert d["resumen"] == "Antes: veo un empate." and d["cuantos"] == 1


def test_sin_nada_apuntado_lo_dice_en_vez_de_inventar(base):
    r = retrospectiva(base, 1, carpeta_briefings="/no/existe")
    assert r["sucesos"] == []
    assert "No se apuntó nada" in r["lectura"]


def test_un_partido_por_jugar_no_se_compara(base):
    base._conexion.execute("UPDATE partidos SET goles_local = NULL, goles_visitante = NULL, "
                           "estado = 'notstarted'")
    _sembrar(base)
    r = retrospectiva(base, 1, carpeta_briefings="/no/existe")
    assert not r["jugado"] and "sucesos" not in r
    assert r["apuntado"]["calculo"]["sucesos"] == 9


def test_un_partido_que_no_esta(base):
    assert retrospectiva(base, 999)["disponible"] is False
