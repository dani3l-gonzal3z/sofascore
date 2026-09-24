"""El briefing del día empieza por lo que importa: lo de ayer, el pick, y dónde no
estamos de acuerdo con el mercado. Antes empezaba por la primera liga del
alfabeto y no llevaba ni nuestro pronóstico ni el mercado de cada cosa."""

from __future__ import annotations

import pytest

from cancha.almacen import Almacen
from cancha.briefing import _ayer, a_markdown, portada


def _partido(nombre, candidatos=(), discrepancias=()):
    local, visitante = nombre.split(" - ")
    return {"partido": {"local": local, "visitante": visitante, "competicion": "LaLiga",
                        "hora_utc": "19:00"},
            "candidatos": list(candidatos),
            "frente_al_mercado": {"sucesos": list(discrepancias)},
            "pronostico": {"disponible": True,
                           "1x2": {"local": 0.5, "empate": 0.27, "visitante": 0.23},
                           "esperados": {"local": 1.6, "visitante": 1.0},
                           "marcadores": [{"marcador": "1-0", "probabilidad": 0.12}],
                           "muestra": 10},
            "equipos": {}}


def _candidato(partido, valor):
    return {"partido": partido, "suceso": "Gana el local", "cuota": 2.1,
            "casa": "bet365", "prob_nuestra": 0.55, "prob_mercado": 0.46,
            "valor": valor}


@pytest.fixture
def base():
    with Almacen(":memory:") as almacen:
        yield almacen


def test_el_pick_del_dia_es_el_de_mas_valor(base):
    partidos = [_partido("A - B", [_candidato("A - B", 0.06)]),
                _partido("C - D", [_candidato("C - D", 0.12)])]
    datos = portada(base, "2026-09-26", partidos)
    assert datos["pick"][0]["partido"] == "C - D"
    assert len(datos["picks"]) == 2


def test_las_discrepancias_van_de_mayor_a_menor(base):
    s = lambda d: {"suceso": "Empate", "nuestra": 0.3, "mercado": 0.3 - d,  # noqa: E731
                   "diferencia": d, "discrepa": True}
    partidos = [_partido("A - B", discrepancias=[s(0.06)]),
                _partido("C - D", discrepancias=[s(-0.11)])]
    datos = portada(base, "2026-09-26", partidos)
    assert [d["partido"] for d in datos["discrepancias"]] == ["C - D", "A - B"]


def test_el_documento_empieza_por_el_pick_y_no_por_la_primera_liga(base):
    partidos = [_partido("A - B", [_candidato("A - B", 0.1)])]
    texto = a_markdown({"fecha": "2026-09-26", "total": 1, "competiciones": ["LaLiga"],
                        "partidos": partidos, "memoria": {},
                        "portada": portada(base, "2026-09-26", partidos),
                        "lo_que_no_dice": "x"})
    assert texto.index("El pick del día") < texto.index("## LaLiga")
    assert "**Nuestro pronóstico:**" in texto, "y cada partido lleva sus números"


def test_un_dia_sin_pick_lo_dice_en_la_portada(base):
    partidos = [_partido("A - B")]
    texto = a_markdown({"fecha": "2026-09-26", "total": 1, "competiciones": ["LaLiga"],
                        "partidos": partidos, "memoria": {},
                        "portada": portada(base, "2026-09-26", partidos),
                        "lo_que_no_dice": "x"})
    assert "no hay pick" in texto


def test_lo_de_ayer_sale_con_sus_resultados(base):
    base._conexion.execute(
        "INSERT INTO partidos (id, local, visitante, fecha) VALUES (1,'A','B','2026-09-25')")
    base._conexion.execute(
        """INSERT INTO picks (fecha, nivel, partido_id, suceso, mercado, seleccion,
           prob_nuestra, cuota, valor, resuelto, acerto, beneficio)
           VALUES ('2026-09-25','premium',1,'Gana el local','1x2','local',0.55,2.1,
                   0.15,1,1,1.1)""")
    base._conexion.commit()
    ayer = _ayer(base, "2026-09-26")
    assert ayer["fecha"] == "2026-09-25"
    assert ayer["picks"][0]["acerto"] == 1
    assert ayer["unidades"] == pytest.approx(1.1)


def test_el_resumen_del_bot_empieza_por_lo_de_ayer(tmp_path, monkeypatch):
    """Empezar viendo si lo de ayer salió es más honesto que empezar prometiendo."""
    import cancha.telegrama as modulo
    from cancha.sesion import Sesion
    from cancha.telegrama import Bot

    monkeypatch.setattr(modulo, "_hoy", lambda *a, **k: "AGENDA DE HOY")
    monkeypatch.setattr(modulo, "_seguro", lambda *a, **k: "")
    sesion = Sesion(ruta_almacen=str(tmp_path / "r.db"))
    almacen = sesion.almacen
    almacen._conexion.execute(
        "INSERT INTO partidos (id, local, visitante, fecha) VALUES (1,'A','B','2026-09-25')")
    almacen._conexion.execute(
        "INSERT INTO partidos (id, local, visitante, fecha) VALUES (2,'C','D','2026-09-26')")
    for fecha, pid in (("2026-09-25", 1), ("2026-09-26", 2)):
        for nivel in ("gratis", "premium"):
            almacen._conexion.execute(
                """INSERT INTO picks (fecha, nivel, partido_id, suceso, mercado,
                   seleccion, prob_nuestra, cuota, casa, valor)
                   VALUES (?,?,?,'Gana el local','1x2','local',0.55,2.1,'bet365',0.15)""",
                (fecha, nivel, pid))
    almacen._conexion.commit()
    texto = Bot(token="x", sesion=sesion, pedir=lambda *a, **k: {"ok": True}).responder(
        "/resumen 2026-09-26")
    sesion.close()
    assert texto.index("Lo de ayer") < texto.index("El pick de hoy") < texto.index("AGENDA")
