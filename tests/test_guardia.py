"""La guardia nocturna: que prepare el día siguiente sin tocar nada a mano.

Lo que más importa comprobar aquí es lo aburrido: que la hora se calcule bien
(una guardia que dispara a la hora equivocada no sirve), que un fallo en una
fase no se lleve por delante las otras, y que el tope se respete. Lo de
impedir la suspensión no se puede probar fuera de Windows, así que se
comprueba que al menos lo diga en voz alta en vez de fingirlo.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from cancha.almacen import Almacen
from cancha.guardia import Diario, despierto, preparar_dia, segundos_hasta, vigilar

# --------------------------------------------------------------------- la hora

@pytest.mark.parametrize("ahora,hora,esperado_horas", [
    ((2026, 9, 20, 22, 30), "03:00", 4.5),
    ((2026, 9, 20, 2, 0), "03:00", 1.0),
    ((2026, 9, 20, 3, 0), "03:00", 24.0),      # justo a la hora: la de mañana
    ((2026, 9, 20, 23, 59), "00:00", 1 / 60),
])
def test_cuanto_falta_para_la_proxima_vez(ahora, hora, esperado_horas):
    faltan = segundos_hasta(hora, datetime(*ahora))
    assert faltan == pytest.approx(esperado_horas * 3600, abs=1)


def test_una_hora_mal_escrita_lo_dice_en_vez_de_disparar_cuando_sea():
    with pytest.raises(ValueError, match="03:00"):
        segundos_hasta("las tres")
    with pytest.raises(ValueError):
        segundos_hasta("25-00")


# ------------------------------------------------------------------ el diario

def test_el_diario_escribe_en_pantalla_y_en_fichero(tmp_path, capsys):
    ruta = tmp_path / "g.log"
    diario = Diario(ruta=ruta)
    diario("empezando")
    diario.error("algo ha salido mal")
    diario.cerrar()

    en_pantalla = capsys.readouterr().out
    assert "empezando" in en_pantalla
    assert "ERROR" in en_pantalla and "algo ha salido mal" in en_pantalla
    guardado = ruta.read_text(encoding="utf-8")
    assert "empezando" in guardado and "algo ha salido mal" in guardado
    assert diario.errores == ["algo ha salido mal"]


def test_el_diario_se_acuerda_de_los_errores_para_resumirlos(tmp_path):
    diario = Diario(ruta=None, en_pantalla=False)
    diario("normal")
    diario.error("uno")
    diario.error("dos")
    assert diario.errores == ["uno", "dos"]


# -------------------------------------------------------------- la suspensión

def test_fuera_de_windows_se_dice_en_vez_de_fingir():
    """Prometer que no se suspenderá cuando no puedes es peor que no prometerlo."""
    dichos = []
    with despierto(dichos.append) as logrado:
        pass
    import ctypes

    if getattr(ctypes, "windll", None) is None:
        assert logrado is False
        assert dichos and "suspensión" in dichos[0]
        assert "ajustes de energía" in dichos[0]


# ------------------------------------------------------------- una vuelta

def test_una_vuelta_deja_el_dia_preparado(tmp_path, cliente):
    with Almacen(tmp_path / "g.db") as base:
        resumen = preparar_dia(cliente, base, fecha="2024-10-26", grupos=["grandes"],
                               abastecer_partidos=2,
                               carpeta_briefings=str(tmp_path / "briefings"),
                               diario=Diario(ruta=None, en_pantalla=False))
    assert resumen["fecha"] == "2024-10-26"
    assert "barrido" in resumen and "seguro" in resumen
    assert resumen["peticiones"] > 0
    assert (tmp_path / "briefings" / "2024-10-26.md").exists()


def test_un_fallo_en_una_fase_no_se_lleva_las_demas(tmp_path, cliente, monkeypatch):
    """Si el barrido cae, el briefing y la calibración tienen que seguir."""
    import cancha.barrido as barrido

    def barrido_roto(*_a, **_k):
        from cancha.errors import SofascoreError

        raise SofascoreError("Sofascore no contesta")

    monkeypatch.setattr(barrido, "barrer", barrido_roto)
    diario = Diario(ruta=None, en_pantalla=False)
    with Almacen(tmp_path / "g2.db") as base:
        resumen = preparar_dia(cliente, base, fecha="2024-10-26",
                               abastecer_partidos=0,
                               carpeta_briefings=str(tmp_path / "b2"),
                               diario=diario)
    assert "error" in resumen["barrido"]
    assert "seguro" in resumen and "error" not in resumen["seguro"]
    assert any("barrido ha fallado" in e for e in resumen["errores"])


def test_la_vuelta_queda_anotada_para_poder_mirarla_manana(tmp_path, cliente):
    with Almacen(tmp_path / "g3.db") as base:
        preparar_dia(cliente, base, fecha="2024-10-26", abastecer_partidos=0,
                     carpeta_briefings=str(tmp_path / "b3"),
                     diario=Diario(ruta=None, en_pantalla=False))
        assert base.nota("ultima_guardia")
        assert base.nota("ultima_guardia_fecha") == "2024-10-26"


# ----------------------------------------------------------------- el bucle

def test_vigilar_hace_las_vueltas_que_se_le_piden_y_sale(tmp_path, cliente):
    """Sin esto, probar la guardia obligaría a esperar a las tres de la mañana."""
    dormido = []
    with Almacen(tmp_path / "g4.db") as base:
        salida = vigilar(cliente, base, ahora=True, vueltas=1, abastecer_partidos=0,
                         carpeta_briefings=str(tmp_path / "b4"),
                         registro=None, en_pantalla=False,
                         dormir=lambda s: dormido.append(s))
    assert salida["cuantas"] == 1
    assert dormido == [], "con --ahora la primera vuelta no espera"


def test_la_espera_se_parte_en_trozos_para_poder_cortar(tmp_path, cliente):
    """Un sleep de ocho horas deja Ctrl+C sin respuesta ocho horas."""
    dormido = []
    with Almacen(tmp_path / "g5.db") as base:
        vigilar(cliente, base, a_las="03:00", vueltas=1, abastecer_partidos=0,
                carpeta_briefings=str(tmp_path / "b5"), registro=None,
                en_pantalla=False, dormir=lambda s: dormido.append(s))
    assert len(dormido) > 10, "ha dormido de una sentada"
    assert max(dormido) <= 5.0
