"""Cuotas: quién era favorito, y para qué sirve saberlo.

No es para apostar. Es la variable que separa «rinde peor contra bloque bajo»
de «rinde peor cuando su equipo es favorito», que sin esto son la misma frase.
"""

from __future__ import annotations

import json

import pytest
from conftest import EVENT_ID

from cancha.almacen import Almacen
from cancha.cuotas import (
    UMBRAL_FAVORITO,
    desde_fila,
    extraer_1x2,
    favorito,
    fraccion_a_decimal,
    probabilidades,
)
from cancha.match import build_report
from cancha.sistemas import desglose_por_favorito, jugador_contra_sistema, lo_relevante

# ------------------------------------------------------------------ aritmética

@pytest.mark.parametrize("texto,decimal", [
    ("13/10", 2.3), ("1/1", 2.0), ("11/10", 2.1), ("1/2", 1.5), (2.5, 2.5),
    ("2.5", 2.5), ("abc", None), (None, None), ("3/0", None), (0.5, None),
])
def test_la_fraccion_se_traduce_a_cuota_decimal(texto, decimal):
    assert fraccion_a_decimal(texto) == decimal


def test_las_probabilidades_pierden_el_margen_de_la_casa():
    """Tres cuotas de 2.00 no son un 50 % cada una: son un tercio."""
    probs = probabilidades({"local": 2.0, "empate": 2.0, "visitante": 2.0})
    assert probs == {"local": 0.3333, "empate": 0.3333, "visitante": 0.3333}
    assert sum(probs.values()) == pytest.approx(1.0, abs=1e-3)


def test_una_cuota_que_falta_no_rompe_el_reparto():
    assert probabilidades({"local": 2.0, "empate": None, "visitante": 0}) == {"local": 1.0}
    assert probabilidades({}) == {}


def test_extrae_el_1x2_del_mercado_destacado():
    from conftest import cargar

    mercado = extraer_1x2(cargar("odds_featured"))
    assert mercado["mercado"] == "Full time"
    assert mercado["cuotas"] == {"local": 3.25, "empate": 3.6, "visitante": 1.8}
    assert mercado["probabilidades"]["visitante"] > mercado["probabilidades"]["local"]


def test_extrae_el_1x2_de_todos_los_mercados():
    datos = {"markets": [
        {"marketName": "Double chance", "choices": [{"name": "1X", "fractionalValue": "1/3"}]},
        {"marketName": "Full time", "choices": [
            {"name": "1", "fractionalValue": "1/1"},
            {"name": "X", "fractionalValue": "5/2"},
            {"name": "2", "fractionalValue": "3/1"}]},
    ]}
    assert extraer_1x2(datos)["cuotas"] == {"local": 2.0, "empate": 3.5, "visitante": 4.0}


def test_sin_un_1x2_completo_no_se_inventa_nada():
    incompleto = {"markets": [{"choices": [{"name": "1", "fractionalValue": "1/1"}]}]}
    assert extraer_1x2(incompleto) is None
    assert extraer_1x2(None) is None
    assert extraer_1x2({"featured": {}}) is None


def test_el_favorito_tiene_grados():
    assert favorito({"local": 0.7, "empate": 0.2, "visitante": 0.1})["claridad"] == "claro"
    ligero = favorito({"local": 0.2, "empate": 0.3, "visitante": 0.5})
    assert ligero["lado"] == "visitante" and ligero["claridad"] == "ligero"
    parejo = favorito({"local": 0.4, "empate": 0.25, "visitante": 0.35})
    assert parejo["lado"] is None and "parejo" in parejo["lectura"]
    assert UMBRAL_FAVORITO == 0.45


def test_desde_fila_devuelve_lo_guardado_o_nada():
    assert desde_fila(None) is None
    assert desde_fila({"prob_local": None}) is None
    bloque = desde_fila({"prob_local": 0.6, "prob_empate": 0.25, "prob_visitante": 0.15,
                         "local": 1.6, "empate": 4.0, "visitante": 6.0, "mercado": "Full time"})
    assert bloque["favorito"]["lado"] == "local"


# --------------------------------------------------------------------- memoria

@pytest.fixture
def almacen():
    with Almacen(":memory:") as base:
        yield base


def test_el_barrido_guarda_las_cuotas_con_el_informe(almacen, cliente):
    informe = build_report(cliente, EVENT_ID, sections=["odds_featured"])
    cuenta = almacen.guardar_informe(informe)
    assert cuenta["cuotas"] == 1
    guardadas = almacen.cuotas_de(EVENT_ID)
    assert guardadas["favorito"]["lado"] == "visitante"
    assert almacen.resumen()["con_cuotas"] == 1


def test_sin_seccion_de_cuotas_no_pasa_nada(almacen, cliente):
    informe = build_report(cliente, EVENT_ID, sections=["statistics"])
    assert almacen.guardar_informe(informe)["cuotas"] == 0
    assert almacen.cuotas_de(EVENT_ID) is None


def test_una_base_vieja_gana_la_tabla_de_cuotas_sin_perder_nada(tmp_path):
    import sqlite3

    ruta = tmp_path / "v2.db"
    viejo = sqlite3.connect(str(ruta))
    viejo.execute("CREATE TABLE partidos (id INTEGER PRIMARY KEY, custom_id TEXT, fecha TEXT, "
                  "momento INTEGER, deporte TEXT, liga_id INTEGER, liga TEXT, temporada_id "
                  "INTEGER, jornada INTEGER, local_id INTEGER, local TEXT, visitante_id INTEGER, "
                  "visitante TEXT, goles_local INTEGER, goles_visitante INTEGER, estado TEXT, "
                  "arbitro TEXT, sede TEXT, formacion_local TEXT, formacion_visitante TEXT, "
                  "visto_en TEXT)")
    viejo.execute("INSERT INTO partidos (id, local) VALUES (1, 'Sigo aquí')")
    viejo.commit()
    viejo.close()
    with Almacen(ruta) as base:
        assert base.consulta("SELECT local FROM partidos")[0]["local"] == "Sigo aquí"
        assert base.cuotas_de(1) is None
        assert base.nota("version_esquema") == "3"


# ------------------------------------------------------ el sistema o el contexto

@pytest.fixture
def base_con_cuotas():
    from test_sistemas import _poblar

    with Almacen(":memory:") as base:
        _poblar(base, repeticiones=2, favorito_alterno=True)
        yield base


def test_cada_grupo_dice_en_cuantos_partidos_era_favorito(base_con_cuotas):
    analisis = jugador_contra_sistema(base_con_cuotas, 999, eje="presion")
    assert analisis["partidos_con_cuotas"] == 18
    reparto = analisis["grupos"]["bloque bajo"]["siendo_favorito"]
    assert reparto == {"favorito": 3, "no_favorito": 3, "sin_cuotas": 0}
    assert all(c["favorito"] in ("favorito", "no_favorito")
               for c in analisis["grupos"]["bloque bajo"]["contra"])


def test_se_puede_mirar_solo_siendo_favorito(base_con_cuotas):
    solo = jugador_contra_sistema(base_con_cuotas, 999, eje="presion", solo="favorito")
    assert solo["solo"] == "favorito"
    assert solo["su_media"]["partidos"] == 9
    assert all(g["siendo_favorito"]["no_favorito"] == 0 for g in solo["grupos"].values())


def test_un_filtro_que_no_existe_se_rechaza(base_con_cuotas):
    with pytest.raises(ValueError):
        jugador_contra_sistema(base_con_cuotas, 999, solo="lo que sea")


def test_sin_cuotas_el_filtro_lo_dice():
    from test_sistemas import _poblar

    with Almacen(":memory:") as base:
        _poblar(base)
        salida = jugador_contra_sistema(base, 999, solo="favorito")
    assert salida["disponible"] is False and "cuotas" in salida["nota"]


def test_un_hallazgo_que_sale_en_los_dos_desgloses_es_del_sistema(base_con_cuotas):
    """El guion es idéntico siendo favorito y sin serlo: la señal tiene que
    aparecer en los dos, y la lectura tiene que decir que es el sistema."""
    desglose = desglose_por_favorito(base_con_cuotas, 999, eje="presion")
    assert desglose["disponible"]
    assert desglose["siendo_favorito"]["grupos"]["bloque bajo"]["partidos"] == 3
    assert desglose["sin_ser_favorito"]["grupos"]["bloque bajo"]["partidos"] == 3
    tiros = next(f for f in desglose["lectura"]
                 if f["contra"] == "bloque bajo" and f["metrica"] == "tiros")
    assert "es el sistema" in tiros["veredicto"]
    assert tiros["favorito"]["veredicto"] == "señal"


def test_un_hallazgo_que_solo_sale_siendo_favorito_se_atribuye_al_contexto():
    """Ahora el jugador desaparece contra el bloque bajo SOLO cuando es favorito."""
    from test_sistemas import GUION, _mete_actuacion, _poblar

    with Almacen(":memory:") as base:
        _poblar(base, repeticiones=2, favorito_alterno=True)
        # En la segunda pasada (sin ser favorito) tira igual contra todos.
        for n in range(len(GUION) + 1, 2 * len(GUION) + 1):
            _mete_actuacion(base, n, 999, "El Nueve", 100, 90,
                            totalShots=4, onTargetScoringAttempt=2, goals=0, keyPass=2)
        desglose = desglose_por_favorito(base, 999, eje="presion")
        hallazgos = {(f["contra"], f["metrica"]): f["veredicto"] for f in desglose["lectura"]}
        assert "contexto" in hallazgos[("bloque bajo", "tiros")]
        assert not lo_relevante(desglose["sin_ser_favorito"])


def test_el_analisis_entero_remite_al_desglose_cuando_hay_cuotas(base_con_cuotas):
    analisis = jugador_contra_sistema(base_con_cuotas, 999)
    assert "desglose_por_favorito" in analisis["lo_que_no_dice"]


def test_el_duelo_lleva_el_reparto_por_favorito(base_con_cuotas):
    from cancha.sistemas import duelo

    resultado = duelo(base_con_cuotas, 999, 301)
    assert resultado["por_eje"]["presion"]["resumen"]["siendo_favorito"]["favorito"] == 3


# ------------------------------------------------------------------- por consola

def test_la_consola_desglosa(tmp_path, capsys):
    from test_sistemas import _poblar

    from cancha import cli

    ruta = tmp_path / "c.db"
    with Almacen(ruta) as base:
        _poblar(base, repeticiones=2, favorito_alterno=True)
    assert cli.main(["contra", "999", "--desglose", "--db", str(ruta)]) == 0
    salida = capsys.readouterr().out
    assert "Siendo favorito" in salida and "es el sistema" in salida

    assert cli.main(["contra", "999", "--solo", "favorito", "--db", str(ruta),
                     "--stdout-json"]) == 0
    assert json.loads(capsys.readouterr().out)["solo"] == "favorito"


def test_la_herramienta_sistema_o_contexto_esta_registrada():
    from cancha.herramientas import TOOLS

    assert "sistema_o_contexto" in TOOLS
    assert "solo" in TOOLS["jugador_contra_sistema"].parameters["properties"]


# ------------------------------------------------------------------------ previa

def test_la_previa_pide_las_cuotas_si_no_las_tiene(almacen, cliente):
    from cancha.previa import previa, texto

    almacen.guardar_informe(build_report(cliente, EVENT_ID, sections=["statistics"]))
    datos = previa(almacen, EVENT_ID, cliente=cliente)
    assert datos["mercado"]["disponible"] and datos["mercado"]["origen"] == "api"
    assert datos["mercado"]["favorito"]["lado"] == "visitante"
    # Y las deja guardadas para la siguiente.
    assert almacen.cuotas_de(EVENT_ID)
    assert any("Mercado:" in linea for linea in texto(datos))


def test_la_previa_sin_cliente_ni_cuotas_lo_dice(almacen, cliente):
    from cancha.previa import previa

    almacen.guardar_informe(build_report(cliente, EVENT_ID, sections=["statistics"]))
    datos = previa(almacen, EVENT_ID, cliente=None)
    assert datos["mercado"]["disponible"] is False
