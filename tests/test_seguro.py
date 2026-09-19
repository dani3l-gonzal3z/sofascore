"""Casi seguro: que el recuento sea recuento y no una corazonada con cifras.

Las historias de este fichero están construidas para que la respuesta se sepa
de antemano. En una, la reacción del favorito existe de verdad; en la otra no
existe en absoluto y los favoritos ganan lo mismo hayan perdido o no. Un módulo
que diga «hallazgo» en la segunda no sirve para nada, y eso es lo que más se
comprueba aquí.
"""

from __future__ import annotations

import math

import pytest

from cancha.almacen import Almacen
from cancha.seguro import (
    ELEVACION_MINIMA,
    MINIMO_CASOS,
    PATRONES,
    POR_NOMBRE,
    UMBRAL_SEGURO,
    Antes,
    Despues,
    avisos,
    calibrar,
    medir,
    veredicto,
    wilson,
)

EQUIPOS = {100: "Favorito FC", 200: "Comparsa CF", 300: "Otro Favorito",
           400: "Otra Comparsa", 500: "Tercero", 600: "Cuarto"}


def _cdf_wilson_a_mano(exitos: int, casos: int, z: float = 1.96) -> tuple[float, float]:
    """La misma cuenta escrita de otra forma, para contrastar."""
    if casos == 0:
        return (0.0, 1.0)
    p = exitos / casos
    a = p + z * z / (2 * casos)
    b = z * math.sqrt((p * (1 - p) + z * z / (4 * casos)) / casos)
    c = 1 + z * z / casos
    return ((a - b) / c, (a + b) / c)


def _liga(almacen: Almacen, jornadas: int, resultado,
          prob_local: float = 0.70, arbitro: str = "El Árbitro") -> None:
    """Una liga inventada. ``resultado(jornada, local, historial)`` da el marcador."""
    historial: dict[int, list[str]] = {}
    pid, momento = 0, 1700000000
    for jornada in range(jornadas):
        for local, visitante in ((100, 200), (300, 400), (500, 600)):
            pid += 1
            momento += 86400
            goles = resultado(jornada, local, historial.get(local, []))
            gl, gv = goles
            almacen._conexion.execute(
                """INSERT INTO partidos (id,fecha,momento,liga_id,liga,local_id,local,
                   visitante_id,visitante,goles_local,goles_visitante,estado,arbitro)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (pid, f"2025-{1 + jornada // 28:02d}-{1 + jornada % 28:02d}", momento, 8,
                 "Liga", local, EQUIPOS[local], visitante, EQUIPOS[visitante],
                 gl, gv, "finished", arbitro))
            almacen._conexion.execute(
                """INSERT INTO cuotas (partido_id,fuente,mercado,prob_local,prob_empate,
                   prob_visitante) VALUES (?,?,?,?,?,?)""",
                (pid, "test", "FT", prob_local, 0.15, round(0.85 - prob_local, 2)))
            historial.setdefault(local, []).insert(
                0, "G" if gl > gv else ("E" if gl == gv else "P"))
    almacen._conexion.commit()


@pytest.fixture
def base():
    with Almacen(":memory:") as almacen:
        yield almacen


# ------------------------------------------------------------- la estadística

@pytest.mark.parametrize("exitos,casos", [(8, 8), (30, 30), (27, 30), (60, 100), (1, 2), (0, 5)])
def test_wilson_coincide_con_la_cuenta_escrita_de_otra_forma(exitos, casos):
    mio, otro = wilson(exitos, casos), _cdf_wilson_a_mano(exitos, casos)
    assert mio[0] == pytest.approx(otro[0], abs=1e-9)
    assert mio[1] == pytest.approx(otro[1], abs=1e-9)


def test_con_todo_acertado_el_suelo_no_es_el_cien_por_cien():
    """Ocho de ocho es 100 % y no significa 100 %: ese es el punto de Wilson."""
    suelo, techo = wilson(8, 8)
    assert techo == 1.0
    assert 0.6 < suelo < 0.72
    assert wilson(30, 30)[0] > suelo, "más casos, más suelo"
    assert wilson(200, 200)[0] > wilson(30, 30)[0]


def test_sin_casos_el_intervalo_es_todo():
    assert wilson(0, 0) == (0.0, 1.0)


@pytest.mark.parametrize("suelo,elevacion,casos,esperado", [
    (0.95, 0.20, 100, "casi seguro"),
    (0.70, 0.20, 100, "probable"),
    (0.40, 0.20, 100, "poco"),
    (0.95, 0.01, 100, "es la tasa base"),
    (0.95, 0.30, 10, "sin muestra"),
])
def test_el_veredicto_pone_cada_cosa_en_su_sitio(suelo, elevacion, casos, esperado):
    assert veredicto(suelo, elevacion, casos) == esperado


def test_la_muestra_manda_sobre_todo_lo_demas():
    """Un patrón perfecto con pocos casos sigue siendo pocos casos."""
    assert veredicto(0.99, 0.5, MINIMO_CASOS - 1) == "sin muestra"


# ---------------------------------------------------------------- el contexto

def test_el_antes_no_sabe_como_acabo_el_partido():
    """Lo que impide que una condición mire el marcador sin querer."""
    antes = Antes(equipo_id=1, rival_id=2, es_local=True, fecha="2025-01-01", liga_id=8)
    for prohibido in ("gano", "perdio", "marco", "goles_local", "total"):
        assert not hasattr(antes, prohibido), f"Antes expone {prohibido}"


def test_el_despues_lee_el_marcador_desde_el_lado_que_toca():
    local = Despues(equipo_id=1, es_local=True, goles_local=2, goles_visitante=0)
    assert local.favor == 2 and local.contra == 0
    assert local.gano and not local.perdio and not local.empato
    assert local.marco and not local.encajo and local.total == 2
    assert local.ambos_marcaron is False

    visitante = Despues(equipo_id=2, es_local=False, goles_local=2, goles_visitante=0)
    assert visitante.favor == 0 and visitante.perdio and not visitante.marco


def test_un_partido_sin_marcador_no_se_juzga():
    vacio = Despues(equipo_id=1, es_local=True, goles_local=None, goles_visitante=None)
    assert vacio.gano is None and vacio.total is None and vacio.ambos_marcaron is None


def test_el_antes_lee_el_mercado_desde_su_lado():
    mercado = {"local": 0.7, "empate": 0.15, "visitante": 0.15}
    local = Antes(1, 2, True, "2025-01-01", 8, mercado=mercado)
    visitante = Antes(2, 1, False, "2025-01-01", 8, mercado=mercado)
    assert local.prob_propia == 0.7 and local.era_favorito is True
    assert visitante.prob_propia == 0.15 and visitante.era_favorito is False
    assert Antes(1, 2, True, "2025-01-01", 8).era_favorito is None


# ------------------------------------------------------------- la medición

def test_un_patron_que_se_cumple_siempre_sale_con_su_numero(base):
    """El local gana siempre: «el favorito claro gana» tiene que dar 100 %."""
    _liga(base, 40, lambda j, local, historial: (2, 0))
    medida = medir(base, POR_NOMBRE["favorito_claro_gana"])
    assert medida["casos"] == 120 and medida["exitos"] == 120
    assert medida["frecuencia"] == 1.0
    assert medida["suelo"] > UMBRAL_SEGURO
    assert medida["veredicto"] == "casi seguro"


def test_un_patron_que_no_se_cumple_nunca_tambien(base):
    _liga(base, 40, lambda j, local, historial: (0, 2))
    medida = medir(base, POR_NOMBRE["favorito_claro_gana"])
    assert medida["frecuencia"] == 0.0 and medida["veredicto"] == "poco"


def test_la_reaccion_del_favorito_se_detecta_cuando_existe(base):
    """Aquí la reacción es real: tras no ganar, el favorito gana siempre."""
    def resultado(jornada, local, historial):
        if historial and historial[0] != "G":
            return (3, 0)          # tras pinchar, gana seguro
        return (2, 0) if jornada % 3 else (0, 1)   # y si no, pincha cada tres

    _liga(base, 60, resultado)
    datos = calibrar(base)
    medida = next(m for m in datos["patrones"] if m["patron"] == "reaccion_del_favorito")
    assert medida["casos"] >= MINIMO_CASOS
    assert medida["frecuencia"] == 1.0
    assert medida["elevacion"] > ELEVACION_MINIMA
    assert medida["veredicto"] == "casi seguro"
    assert medida["comparado_con"]["patron"] == "favorito_claro_gana"


def test_y_se_desmonta_cuando_no_existe(base):
    """Aquí no hay reacción: el favorito gana el 70 % pase lo que pase antes.

    Es el test que de verdad importa. Un módulo que aquí diga «casi seguro»
    está vendiendo la tasa base como si fuera un hallazgo.
    """
    import random

    generador = random.Random(11)
    _liga(base, 80, lambda j, local, historial: (2, 0) if generador.random() < 0.7 else (0, 1))
    datos = calibrar(base)
    medida = next(m for m in datos["patrones"] if m["patron"] == "reaccion_del_favorito")
    assert medida["casos"] >= MINIMO_CASOS
    assert medida["veredicto"] == "es la tasa base"
    assert medida["indistinguible_de_la_referencia"] is True
    assert "no añade nada" in medida["nota"]


def test_la_referencia_se_mide_aunque_no_la_pidas(base):
    # El favorito pincha de vez en cuando: si no, el patrón no tiene casos.
    _liga(base, 60, lambda j, local, historial: (2, 0) if j % 3 else (0, 1))
    datos = calibrar(base, patrones=["reaccion_del_favorito"])
    assert [m["patron"] for m in datos["patrones"]] == ["reaccion_del_favorito"]
    assert datos["patrones"][0]["comparado_con"]["patron"] == "favorito_claro_gana"


def test_un_patron_sin_casos_no_dice_nada(base):
    _liga(base, 3, lambda j, local, historial: (1, 1))
    medida = medir(base, POR_NOMBRE["racha_de_cuatro"])
    assert medida["casos"] < MINIMO_CASOS and medida["veredicto"] == "sin muestra"


def test_la_condicion_solo_mira_hacia_atras(base):
    """Si mirara el propio partido, «el que marca siempre» daría el 100 %."""
    def resultado(jornada, local, historial):
        # Marca en los pares y no en los impares: nunca encadena seis.
        return (1, 0) if jornada % 2 == 0 else (0, 1)

    _liga(base, 40, resultado)
    medida = medir(base, POR_NOMBRE["sigue_marcando"])
    assert medida["casos"] == 0, "la condición ha visto el resultado del propio partido"


def test_el_desenlace_de_goles_totales_cuenta_los_dos_equipos(base):
    _liga(base, 40, lambda j, local, historial: (2, 2))
    medida = medir(base, POR_NOMBRE["mas_de_2_5"])
    assert medida["frecuencia"] == 1.0 and medida["casos"] >= MINIMO_CASOS
    cerrado = medir(base, POR_NOMBRE["menos_de_3_5"])
    assert cerrado["casos"] == 0, "con cuatro goles por partido no se cumple la condición"


def test_los_patrones_de_partido_se_cuentan_una_vez_por_partido(base):
    _liga(base, 40, lambda j, local, historial: (2, 2))
    por_partido = medir(base, POR_NOMBRE["mas_de_2_5"])
    por_equipo = medir(base, POR_NOMBRE["favorito_no_pierde"])
    assert por_equipo["base_casos"] == 2 * por_partido["base_casos"]


def test_calibrar_ordena_y_resume(base):
    _liga(base, 40, lambda j, local, historial: (2, 0))
    datos = calibrar(base)
    assert datos["partidos_mirados"] == 120
    assert len(datos["patrones"]) == len(PATRONES)
    assert "favorito_claro_gana" in datos["utiles"]
    assert "Wilson" in datos["como_leerlo"]
    assert "azar" in datos["lo_que_no_dice"]


def test_calibrar_se_puede_acotar_por_liga_y_por_fecha(base):
    _liga(base, 40, lambda j, local, historial: (2, 0))
    assert calibrar(base, liga_id=999)["partidos_mirados"] == 0
    acotado = calibrar(base, desde="2025-02-01")["partidos_mirados"]
    assert 0 < acotado < 120


# ---------------------------------------------------------------- los avisos

def _evento(identificador, local_id, visitante_id, fecha="2025-03-01"):
    from cancha.models import Event

    return Event.from_api({
        "id": identificador, "startTimestamp": 1740787200,
        "status": {"type": "notstarted"},
        "tournament": {"name": "Liga", "uniqueTournament": {"id": 8}},
        "homeTeam": {"id": local_id, "name": EQUIPOS[local_id]},
        "awayTeam": {"id": visitante_id, "name": EQUIPOS[visitante_id]},
        "referee": {"name": "El Árbitro"},
    })


def test_los_avisos_solo_traen_lo_que_ha_pasado_el_filtro(base):
    _liga(base, 60, lambda j, local, historial: (2, 0))
    evento = _evento(9001, 100, 200)
    base.guardar_evento(evento)
    base._conexion.execute(
        """INSERT INTO cuotas (partido_id,fuente,mercado,prob_local,prob_empate,prob_visitante)
           VALUES (?,?,?,?,?,?)""", (9001, "test", "FT", 0.70, 0.15, 0.15))
    base._conexion.commit()

    datos = avisos(base, eventos=[evento])
    assert datos["avisos"], "el local gana siempre: algo tenía que salir"
    for aviso in datos["avisos"]:
        assert aviso["casos"] >= MINIMO_CASOS
        assert abs(aviso["elevacion"]) >= ELEVACION_MINIMA
        assert aviso["partido"] == "Favorito FC - Comparsa CF"
    assert [a["suelo"] for a in datos["avisos"]] == sorted(
        (a["suelo"] for a in datos["avisos"]), reverse=True)
    assert "apuesta segura" in datos["lo_que_no_dice"]


def test_sin_historial_no_hay_avisos(base):
    evento = _evento(9001, 100, 200)
    base.guardar_evento(evento)
    datos = avisos(base, eventos=[evento])
    assert datos["avisos"] == []


def test_el_aviso_lleva_lo_que_dice_el_mercado(base):
    _liga(base, 60, lambda j, local, historial: (2, 0))
    evento = _evento(9001, 100, 200)
    base.guardar_evento(evento)
    base._conexion.execute(
        """INSERT INTO cuotas (partido_id,fuente,mercado,prob_local,prob_empate,prob_visitante)
           VALUES (?,?,?,?,?,?)""", (9001, "test", "FT", 0.8, 0.1, 0.1))
    base._conexion.commit()
    datos = avisos(base, eventos=[evento])
    favorito = next(a for a in datos["avisos"] if a["patron"] == "favorito_claro_gana")
    assert favorito["mercado"] == 0.8
    assert favorito["sujeto"] == "Favorito FC"


def test_un_umbral_mas_alto_deja_pasar_menos(base):
    _liga(base, 60, lambda j, local, historial: (2, 0) if j % 4 else (0, 1))
    evento = _evento(9001, 100, 200)
    base.guardar_evento(evento)
    base._conexion.execute(
        """INSERT INTO cuotas (partido_id,fuente,mercado,prob_local,prob_empate,prob_visitante)
           VALUES (?,?,?,?,?,?)""", (9001, "test", "FT", 0.70, 0.15, 0.15))
    base._conexion.commit()
    flojo = len(avisos(base, eventos=[evento], umbral=0.5)["avisos"])
    duro = len(avisos(base, eventos=[evento], umbral=0.95)["avisos"])
    assert duro <= flojo


# -------------------------------------------------------------- por consola

def test_la_consola_calibra(base, tmp_path, capsys):
    from cancha import cli

    ruta = tmp_path / "s.db"
    with Almacen(ruta) as almacen:
        _liga(almacen, 40, lambda j, local, historial: (2, 0))
    assert cli.main(["seguro", "--calibrar", "--db", str(ruta)]) == 0
    salida = capsys.readouterr().out
    assert "Calibrado sobre 120 partidos" in salida
    assert "favorito_claro_gana" in salida and "VEREDICTO" in salida


def test_la_consola_avisa_y_lo_dice_cuando_no_hay_nada(tmp_path, capsys, inyectar_cliente,
                                                       cliente):
    from cancha import cli

    inyectar_cliente(cliente)
    ruta = tmp_path / "vacia.db"
    assert cli.main(["seguro", "--date", "2024-10-26", "--grupos", "grandes",
                     "--db", str(ruta)]) == 0
    assert "Nada que destacar" in capsys.readouterr().out


def test_la_herramienta_esta_registrada_y_avisa_de_lo_que_no_es():
    from cancha.herramientas import TOOLS

    herramienta = TOOLS["casi_seguro"]
    assert "ELEVACIÓN" in herramienta.description
    assert "99" in herramienta.description, "tiene que decir que no hay apuestas seguras"


def test_todos_los_patrones_estan_bien_formados():
    for patron in PATRONES:
        assert patron.nombre and patron.titulo and patron.pregunta
        assert patron.ambito in ("equipo", "partido")
        assert callable(patron.condicion) and callable(patron.desenlace)
        if patron.referencia:
            assert patron.referencia in POR_NOMBRE, patron.nombre
