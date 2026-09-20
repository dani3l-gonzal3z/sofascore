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


# ------------------------------------------------------- fuera de muestra

def test_un_patron_que_solo_pasaba_antes_se_cae_fuera_de_muestra(base):
    """Construido para que se caiga: el efecto existe y luego desaparece.

    Es el caso que de verdad importa. Un patrón medido sobre todo el historial
    sale alto porque la mitad vieja tira de la media, y el número parece bueno.
    La comprobación tiene que decir que el número se apoya en lo viejo.
    """
    import random

    azar = random.Random(7)

    def con_reaccion_que_se_apaga(jornada, local, historial):
        perdio = historial[:1] == ["P"]
        if jornada < 70:                       # antes: reacciona siempre
            return (2, 0) if perdio else ((0, 1) if jornada % 5 == 0 else (1, 0))
        # Después haber perdido deja de decir nada: el resultado sale de una
        # moneda que no mira el historial.
        return (2, 0) if azar.random() < 0.5 else (0, 1)

    _liga(base, 100, con_reaccion_que_se_apaga)
    calibracion = calibrar(base)
    medida = next(m for m in calibracion["patrones"]
                  if m["patron"] == "reaccion_del_favorito")
    fuera = medida["fuera_de_muestra"]
    assert fuera is not None
    assert fuera["veredicto"] == "se cae", fuera["lectura"]
    assert fuera["antes"]["frecuencia"] > fuera["despues"]["frecuencia"]
    assert "se apoya sobre todo en lo viejo" in fuera["lectura"]
    assert "reaccion_del_favorito" not in calibracion["aguantan_fuera_de_muestra"]


def test_un_patron_constante_aguanta_fuera_de_muestra(base):
    """El mismo efecto de principio a fin: la comprobación no lo tumba."""
    def siempre_reacciona(jornada, local, historial):
        perdio = historial[:1] == ["P"]
        return (2, 0) if perdio else ((0, 1) if jornada % 5 == 0 else (1, 0))

    _liga(base, 100, siempre_reacciona)
    medida = next(m for m in calibrar(base)["patrones"]
                  if m["patron"] == "reaccion_del_favorito")
    fuera = medida["fuera_de_muestra"]
    assert fuera["veredicto"] == "aguanta", fuera["lectura"]
    assert fuera["despues"]["casos"] > 0
    assert fuera["corte"], "tiene que decir por dónde partió el historial"


def test_con_poco_historial_lo_dice_en_vez_de_dar_un_veredicto(base):
    def sencillo(jornada, local, historial):
        return (1, 0)

    _liga(base, 6, sencillo)
    medida = next(m for m in calibrar(base)["patrones"]
                  if m["patron"] == "reaccion_del_favorito")
    fuera = medida["fuera_de_muestra"]
    assert fuera["veredicto"] == "sin muestra"
    assert "no alcanza" in fuera["lectura"]


def test_el_corte_es_por_fecha_y_no_al_azar(base):
    """Partir al azar metería partidos nuevos en la parte con la que se mide."""
    from cancha.seguro import _Historial

    def sencillo(jornada, local, historial):
        return (1, 0)

    _liga(base, 20, sencillo)
    indice = _Historial(base)
    corte = indice.corte(0.7)
    viejos = [p for p in indice.partidos if (p["momento"] or 0) < corte]
    nuevos = [p for p in indice.partidos if (p["momento"] or 0) >= corte]
    assert viejos and nuevos
    assert max(p["momento"] for p in viejos) < min(p["momento"] for p in nuevos)
    assert len(viejos) == pytest.approx(len(indice.partidos) * 0.7, abs=2)


def test_un_aviso_del_dia_lleva_la_comprobacion_encima(base):
    """No vale comprobarlo en la calibración y no enseñarlo donde se decide."""
    def siempre_reacciona(jornada, local, historial):
        perdio = historial[:1] == ["P"]
        return (2, 0) if perdio else ((0, 1) if jornada % 5 == 0 else (1, 0))

    _liga(base, 100, siempre_reacciona)
    evento = _evento(9001, 100, 200)
    base.guardar_evento(evento)
    base._conexion.execute(
        """INSERT INTO cuotas (partido_id,fuente,mercado,prob_local,prob_empate,prob_visitante)
           VALUES (?,?,?,?,?,?)""", (9001, "test", "FT", 0.70, 0.15, 0.15))
    base._conexion.commit()

    salida = avisos(base, eventos=[evento], umbral=0.5)
    assert salida["avisos"], "la historia tenía que disparar algún aviso"
    for aviso in salida["avisos"]:
        assert "fuera_de_muestra" in aviso
    assert "aguantan_fuera_de_muestra" in salida


# ------------------------------------------- un patrón, no sesenta fichas
# Esto sale de una pantalla real: sesenta partidos del día, y en los sesenta la
# misma ficha —«Sale de favorito: ¿evita la derrota?», 84 % en 64 casos, +22 %,
# el mismo suelo—. Solo cambiaba el nombre del equipo. No estaba mal calculado:
# estaba mal contado. Un patrón se mide UNA vez sobre todo el historial.

def _con_cuotas(base, partido_id: int, local: float, empate: float, visitante: float):
    base._conexion.execute(
        """INSERT INTO cuotas (partido_id,fuente,mercado,prob_local,prob_empate,prob_visitante)
           VALUES (?,?,?,?,?,?)""",
        (partido_id, "test", "FT", local, empate, visitante))
    base._conexion.commit()


def test_el_patron_se_enseña_una_vez_y_sus_partidos_debajo(base):
    _liga(base, 60, lambda j, local, historial: (2, 0))
    eventos = []
    for numero, (local_id, visitante_id) in enumerate(
            ((100, 200), (100, 300), (100, 400)), start=1):
        evento = _evento(9000 + numero, local_id, visitante_id)
        base.guardar_evento(evento)
        _con_cuotas(base, 9000 + numero, 0.70 + numero / 100, 0.15, 0.15 - numero / 100)
        eventos.append(evento)

    datos = avisos(base, eventos=eventos)
    assert datos["avisos"], "el local gana siempre: algo tiene que salir"
    grupos = datos["por_patron"]
    assert grupos, "tiene que venir agrupado"
    # Un grupo por patrón, no uno por partido.
    assert len(grupos) == len({a["patron"] for a in datos["avisos"]})
    for grupo in grupos:
        # La medición vive en el grupo, no repetida en cada partido.
        for clave in ("frecuencia", "suelo", "casos", "elevacion", "veredicto"):
            assert clave in grupo
            assert clave not in grupo["partidos"][0]
        assert grupo["cuantos_partidos"] == len(grupo["partidos"])


def test_los_partidos_de_un_patron_van_por_distancia_al_mercado(base):
    """Es lo único que distingue un partido de otro dentro del mismo patrón."""
    _liga(base, 60, lambda j, local, historial: (2, 0))
    eventos = []
    for numero, (local_id, precio) in enumerate(
            ((200, 0.50), (300, 0.90), (400, 0.70)), start=1):
        evento = _evento(9100 + numero, 100, local_id)
        base.guardar_evento(evento)
        _con_cuotas(base, 9100 + numero, precio, 0.05, 0.95 - precio)
        eventos.append(evento)

    grupo = next(g for g in avisos(base, eventos=eventos)["por_patron"]
                 if g["patron"] == "favorito_no_pierde")
    diferencias = [abs(p["diferencia"]) for p in grupo["partidos"]]
    assert diferencias == sorted(diferencias, reverse=True)
    assert grupo["mayor_diferencia"] is not None


def test_el_mercado_responde_a_la_misma_pregunta_que_el_patron(base):
    """«¿Evita la derrota?» no se compara con la probabilidad de ganar."""
    _liga(base, 60, lambda j, local, historial: (2, 0))
    evento = _evento(9201, 100, 200)
    base.guardar_evento(evento)
    _con_cuotas(base, 9201, 0.70, 0.15, 0.15)

    datos = avisos(base, eventos=[evento])
    no_pierde = next(a for a in datos["avisos"] if a["patron"] == "favorito_no_pierde")
    # No perder es ganar o empatar: 1 - 0.15, no 0.70.
    assert no_pierde["mercado"] == pytest.approx(0.85)
    assert no_pierde["mercado_de"] == "que no pierda"
    gana = next(a for a in datos["avisos"] if a["patron"] == "favorito_claro_gana")
    assert gana["mercado"] == pytest.approx(0.70)
    assert gana["mercado_de"] == "que gane"
    assert gana["diferencia"] == pytest.approx(gana["frecuencia"] - 0.70, abs=1e-6)


def test_sin_equivalente_en_el_mercado_no_se_inventa_uno(base):
    """Los córners y las tarjetas no están en el 1X2."""
    from cancha.seguro import POR_NOMBRE, mercado_comparable
    from cancha.seguro import Antes as Contexto

    antes = Contexto(equipo_id=100, rival_id=200, es_local=True, fecha="2026-01-01",
                     liga_id=8, mercado={"local": 0.6, "empate": 0.25, "visitante": 0.15})
    valor, etiqueta = mercado_comparable(antes, POR_NOMBRE["corners"])
    assert valor is None and etiqueta == ""


def test_sin_cuotas_el_aviso_lo_dice_y_no_compara(base):
    _liga(base, 60, lambda j, local, historial: (2, 0))
    evento = _evento(9301, 100, 200)
    base.guardar_evento(evento)
    datos = avisos(base, eventos=[evento])
    for aviso in datos["avisos"]:
        assert aviso["mercado"] is None
        assert aviso["diferencia"] is None
