"""El pronóstico: que los números salgan de la aritmética y no de una corazonada.

Las ligas de este fichero están construidas para que la respuesta se sepa antes
de calcularla: en una hay un equipo que marca el doble que los demás y tiene
que salir favorito; en otra todos son iguales y el pronóstico tiene que
parecerse a la media. Un módulo que no distinga esos dos casos no vale.

Y lo que más se vigila: que no mire partidos posteriores al que pronostica.
Pronosticar con datos del futuro acierta siempre y no sirve para nada.
"""

from __future__ import annotations

import math

import pytest

from cancha.almacen import Almacen
from cancha.pronostico import (
    MINIMO_PARTIDOS,
    cola_superior,
    fuerza_de,
    matriz,
    poisson,
    pronostico,
    texto,
)

EQUIPOS = {10: "Artillero FC", 20: "Normalito CF", 30: "Otro Normal", 40: "Cuarto"}


def _liga(base: Almacen, jornadas: int = 12, goles=None, corners: int = 5,
          amarillas: int = 2, arbitro: str = "El Árbitro") -> None:
    """Una liga de mentira con estadísticas completas."""
    def por_defecto(local, visitante):
        return (2, 1) if local == 10 else (1, 1)

    marcador = goles or por_defecto
    pid, momento = 0, 1_700_000_000
    parejas = [(10, 20), (30, 40), (20, 10), (40, 30), (10, 30), (20, 40)]
    for jornada in range(jornadas):
        for local, visitante in parejas:
            pid += 1
            momento += 86_400
            gl, gv = marcador(local, visitante)
            base._conexion.execute(
                """INSERT INTO partidos (id,fecha,momento,liga_id,liga,local_id,local,
                   visitante_id,visitante,goles_local,goles_visitante,estado,arbitro)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (pid, f"2025-{1 + jornada // 28:02d}-{1 + jornada % 28:02d}", momento,
                 8, "Liga", local, EQUIPOS[local], visitante, EQUIPOS[visitante],
                 gl, gv, "finished", arbitro))
            for clave, valor_l, valor_v in (
                    ("expectedGoals", gl * 0.9, gv * 0.9),
                    ("cornerKicks", corners, corners),
                    ("yellowCards", amarillas, amarillas)):
                base._conexion.execute(
                    """INSERT INTO estadisticas (partido_id,periodo,grupo,clave,nombre,
                       local,visitante) VALUES (?,?,?,?,?,?,?)""",
                    (pid, "ALL", "G", clave, clave, valor_l, valor_v))
    base._conexion.commit()


def _evento(identificador, local_id, visitante_id, fecha="2025-06-01",
            arbitro="El Árbitro"):
    from cancha.models import Event

    return Event.from_api({
        "id": identificador, "customId": f"c{identificador}",
        "startTimestamp": 1_800_000_000,
        "status": {"type": "notstarted"},
        "tournament": {"name": "Liga", "uniqueTournament": {"id": 8}},
        "referee": {"name": arbitro},
        "homeTeam": {"id": local_id, "name": EQUIPOS[local_id]},
        "awayTeam": {"id": visitante_id, "name": EQUIPOS[visitante_id]},
        "homeScore": {}, "awayScore": {},
    })


@pytest.fixture
def base():
    with Almacen(":memory:") as almacen:
        yield almacen


# ----------------------------------------------------------------- la Poisson

@pytest.mark.parametrize("lam", [0.3, 1.0, 1.65, 3.2])
def test_la_poisson_suma_uno(lam):
    assert sum(poisson(lam, k) for k in range(60)) == pytest.approx(1.0, abs=1e-9)


@pytest.mark.parametrize("lam,k", [(1.5, 0), (1.5, 3), (2.7, 5), (0.8, 2)])
def test_la_poisson_coincide_con_la_formula_de_toda_la_vida(lam, k):
    """La misma cuenta sin logaritmos, para contrastar la implementación."""
    directa = math.exp(-lam) * lam**k / math.factorial(k)
    assert poisson(lam, k) == pytest.approx(directa, abs=1e-12)


def test_con_lambda_cero_solo_cabe_el_cero():
    assert poisson(0, 0) == 1.0
    assert poisson(0, 1) == 0.0


@pytest.mark.parametrize("lam,linea", [(2.7, 2.5), (1.2, 0.5), (4.0, 3.5)])
def test_la_cola_superior_es_lo_que_queda(lam, linea):
    """P(X > 2,5) es P(X ≥ 3): las líneas con medio punto existen para eso."""
    umbral = math.floor(linea) + 1
    a_mano = 1 - sum(poisson(lam, k) for k in range(umbral))
    assert cola_superior(lam, linea) == pytest.approx(a_mano, abs=1e-12)


def test_mas_goles_esperados_hace_mas_probable_pasarse():
    assert cola_superior(3.5, 2.5) > cola_superior(2.5, 2.5) > cola_superior(1.5, 2.5)


def test_la_matriz_de_marcadores_suma_casi_uno():
    """Casi: la cola por encima de ocho goles se corta, y es despreciable."""
    total = sum(map(sum, matriz(1.6, 1.1)))
    assert 0.9999 < total <= 1.0


# ------------------------------------------------------------------ fuerzas

def test_el_que_marca_el_doble_sale_con_mas_ataque(base):
    _liga(base)
    liga = {"por_equipo": 1.5}
    artillero = fuerza_de(base, 10, "Artillero FC", liga, ultimos=10)
    normal = fuerza_de(base, 20, "Normalito CF", liga, ultimos=10)
    assert artillero.ataque > normal.ataque
    assert artillero.partidos >= MINIMO_PARTIDOS


def test_con_pocos_partidos_no_se_inventa_una_fuerza(base):
    _liga(base, jornadas=1)          # dos partidos por equipo como mucho
    assert fuerza_de(base, 10, "Artillero FC", {"por_equipo": 1.5}, ultimos=10) is None


def test_no_se_miran_partidos_posteriores_al_que_se_pronostica(base):
    """Pronosticar con datos del futuro acierta siempre y no vale nada."""
    _liga(base, jornadas=12)
    todos = fuerza_de(base, 10, "Artillero FC", {"por_equipo": 1.5}, ultimos=40)
    cortado = fuerza_de(base, 10, "Artillero FC", {"por_equipo": 1.5}, ultimos=40,
                        antes_de="2025-01-05")
    assert cortado is not None
    assert cortado.partidos < todos.partidos, "el corte por fecha no ha hecho nada"


# --------------------------------------------------------------- el pronóstico

def test_el_favorito_de_verdad_sale_favorito(base):
    _liga(base)
    datos = pronostico(base, _evento(9001, 10, 20))
    assert datos["disponible"] is True
    uno = datos["goles"]["1x2"]
    assert uno["local"] > uno["visitante"], "el que marca el doble tiene que salir arriba"
    assert uno["local"] + uno["empate"] + uno["visitante"] == pytest.approx(1.0, abs=1e-3)
    assert datos["goles"]["esperados"]["local"] > datos["goles"]["esperados"]["visitante"]


def test_entre_dos_iguales_el_pronostico_no_se_moja(base):
    """Si nadie destaca, decir que uno es favorito sería inventárselo."""
    _liga(base, goles=lambda local, visitante: (1, 1))
    datos = pronostico(base, _evento(9002, 20, 30))
    uno = datos["goles"]["1x2"]
    assert abs(uno["local"] - uno["visitante"]) < 0.12


def test_el_marcador_mas_probable_viene_con_su_probabilidad_y_es_pequena(base):
    """Lo importante no es cuál encabeza, es que encabezar sea el 10 % y no el 80 %."""
    _liga(base)
    marcadores = pronostico(base, _evento(9003, 10, 20))["goles"]["marcadores"]
    assert len(marcadores) == 8
    assert marcadores[0]["probabilidad"] < 0.30, "ningún marcador de fútbol es seguro"
    probabilidades = [m["probabilidad"] for m in marcadores]
    assert probabilidades == sorted(probabilidades, reverse=True)


def test_las_lineas_de_goles_son_coherentes_entre_si(base):
    _liga(base)
    mas_de = pronostico(base, _evento(9004, 10, 20))["goles"]["mas_de"]
    valores = [mas_de[str(x)] for x in (0.5, 1.5, 2.5, 3.5, 4.5)]
    assert valores == sorted(valores, reverse=True), (
        "pasar de 4,5 no puede ser más fácil que pasar de 0,5")
    assert all(0 <= v <= 1 for v in valores)


def test_los_corners_salen_de_lo_que_hace_uno_y_concede_el_otro(base):
    _liga(base, corners=6)
    corners = pronostico(base, _evento(9005, 10, 20))["corners"]
    assert corners["disponible"] is True
    # Los dos sacan seis y conceden seis: lo esperado son doce entre los dos.
    assert corners["esperado_total"] == pytest.approx(12.0, abs=0.5)
    assert corners["mas_de"]["9.5"] > corners["mas_de"]["11.5"]


def test_un_arbitro_tarjetero_sube_las_amarillas(base):
    """Y solo si tiene partidos suficientes: con tres, su media no dice nada."""
    _liga(base, amarillas=2, arbitro="El Tranquilo")
    suave = pronostico(base, _evento(9006, 10, 20, arbitro="El Tranquilo"))["tarjetas"]
    assert suave["arbitro"]["disponible"] is True
    assert suave["arbitro"]["factor"] == pytest.approx(1.0, abs=0.05), (
        "si pita como la media de su liga, no cambia nada; un factor de 0,5 "
        "clavado significa que se están comparando unidades distintas")
    assert suave["arbitro"]["amarillas_por_partido"] == pytest.approx(4.0, abs=0.1), (
        "las dos partes juntas, no por equipo")
    assert suave["mas_de"]["3.5"] > suave["mas_de"]["5.5"]


def test_un_arbitro_sin_partidos_no_ajusta_nada_y_lo_dice(base):
    _liga(base)
    tarjetas = pronostico(base, _evento(9007, 10, 20, arbitro="Recién Llegado"))["tarjetas"]
    assert tarjetas["arbitro"]["disponible"] is False
    assert "hacen falta" in tarjetas["arbitro"]["nota"]
    assert tarjetas["esperado_total_con_arbitro"] == tarjetas["esperado_total"]


def test_sin_memoria_lo_dice_y_dice_como_arreglarlo(base):
    datos = pronostico(base, _evento(9008, 10, 20))
    assert datos["disponible"] is False
    assert "Abastece" in datos["nota"]


def test_con_un_equipo_sin_muestra_no_se_pronostica_a_medias(base):
    _liga(base, jornadas=12)
    base._conexion.execute("DELETE FROM partidos WHERE local_id = 40 OR visitante_id = 40")
    base._conexion.commit()
    datos = pronostico(base, _evento(9009, 10, 40))
    assert datos["disponible"] is False
    assert "visitante" in datos["nota"]


# ------------------------------------------------------------ contra el mercado

def test_cuando_coincide_con_el_mercado_lo_dice(base):
    _liga(base)
    datos = pronostico(base, _evento(9010, 10, 20))
    uno = datos["goles"]["1x2"]
    base.guardar_evento(_evento(9010, 10, 20))
    base._conexion.execute(
        """INSERT INTO cuotas (partido_id,fuente,mercado,prob_local,prob_empate,
           prob_visitante) VALUES (?,?,?,?,?,?)""",
        (9010, "test", "FT", uno["local"], uno["empate"], uno["visitante"]))
    base._conexion.commit()
    mercado = pronostico(base, _evento(9010, 10, 20))["mercado"]
    assert mercado["disponible"] is True
    assert "nada que ganar" in mercado["lectura"]


def test_cuando_se_separa_del_mercado_avisa_de_quien_suele_tener_razon(base):
    _liga(base)
    base.guardar_evento(_evento(9011, 10, 20))
    base._conexion.execute(
        """INSERT INTO cuotas (partido_id,fuente,mercado,prob_local,prob_empate,
           prob_visitante) VALUES (?,?,?,?,?,?)""",
        (9011, "test", "FT", 0.10, 0.20, 0.70))
    base._conexion.commit()
    mercado = pronostico(base, _evento(9011, 10, 20))["mercado"]
    assert "alineaciones" in mercado["lectura"]


def test_sin_cuotas_lo_dice_en_vez_de_callarse(base):
    _liga(base)
    mercado = pronostico(base, _evento(9012, 10, 20))["mercado"]
    assert mercado["disponible"] is False
    assert "mercado" in mercado["nota"]


# ------------------------------------------------------------------ el texto

def test_el_texto_lleva_lo_que_hay_que_leer(base):
    _liga(base)
    lineas = texto(pronostico(base, _evento(9013, 10, 20)))
    junto = "\n".join(lineas)
    for pieza in ("Goles esperados", "1X2", "Marcadores más probables",
                  "Córners", "Amarillas", "Más de"):
        assert pieza in junto, pieza
    assert "10-12 %" in junto, "el aviso de que ningún marcador es seguro"


def test_sin_pronostico_el_texto_es_la_explicacion(base):
    lineas = texto(pronostico(base, _evento(9014, 10, 20)))
    assert len(lineas) == 1 and "Abastece" in lineas[0]


# --------------------------------------------------------------- encoger

def test_con_poca_muestra_la_fuerza_se_queda_cerca_de_la_media():
    """Con cinco partidos no se sabe que alguien sea el doble de bueno: lo parece."""
    from cancha.pronostico import encoger

    assert encoger(2.0, 5) < encoger(2.0, 20) < encoger(2.0, 100) < 2.0
    assert encoger(0.5, 5) > encoger(0.5, 20) > encoger(0.5, 100) > 0.5
    assert encoger(2.0, 100) == pytest.approx(2.0, abs=0.1), "con mucha muestra, apenas la toca"


def test_encoger_no_mueve_a_quien_ya_es_la_media():
    from cancha.pronostico import encoger

    for partidos in (1, 10, 50):
        assert encoger(1.0, partidos) == pytest.approx(1.0)


def test_sin_partidos_no_se_presume_nada():
    from cancha.pronostico import encoger

    assert encoger(3.0, 0) == 1.0


def test_un_buen_ataque_contra_una_mala_defensa_no_se_dispara(base):
    """El modelo multiplicativo puro amplifica: ataque alto × defensa mala se
    multiplican y salen lambdas de cinco goles que no existen en el fútbol.

    Lo que se exige no es que el favorito no domine —debe dominar—, sino que el
    pronóstico no se salga mucho de lo que ese equipo hace de verdad.
    """
    def desigual(local, visitante):
        if local == 10:
            return (3, 0)            # marca tres en casa, y encaja poco
        return (0, 2) if visitante == 10 else (1, 1)

    _liga(base, jornadas=12, goles=desigual)
    datos = pronostico(base, _evento(9015, 10, 20))
    esperados = datos["goles"]["esperados"]
    marca = datos["goles"]["fuerzas"]["local"]["marca_por_partido"]
    assert esperados["local"] > esperados["visitante"], "el fuerte tiene que dominar"
    assert esperados["local"] <= marca * 1.4, (
        f"{esperados['local']} esperados contra {marca} que marca de verdad: "
        "el modelo se está amplificando a sí mismo")
    assert datos["goles"]["marcadores"][0]["probabilidad"] < 0.30
    # Y la ficha enseña las dos cifras, para que se vea lo que se ha encogido.
    fuerza = datos["goles"]["fuerzas"]["local"]
    assert fuerza["ataque"] < fuerza["ataque_sin_encoger"]
