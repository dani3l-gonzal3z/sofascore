"""Jugador contra sistema.

Este módulo dice cosas fuertes —«contra bloque bajo tira la mitad»— y la única
razón para creérselas es que aquí se compruebe lo que las sostiene: que la
prueba de Poisson está bien hecha, que una muestra corta se rechaza en vez de
publicarse, y que «presiona alto» significa *alto para su liga* y no un número
sacado de ningún sitio.

La liga de mentira está construida para que los cortes por terciles caigan en
sitios conocidos (10 y 14 de presión, 45 y 60 de posesión), así que cuando un
test dice «este rival es bloque bajo» se puede seguir el número a mano.
"""

from __future__ import annotations

import json
import math

import pytest

from cancha.almacen import Almacen
from cancha.sistemas import (
    MINIMO_MINUTOS,
    MINIMO_PARTIDOS,
    _defensas,
    _veredicto,
    clasificar,
    duelo,
    jugador_contra_sistema,
    lo_relevante,
    poisson_cdf,
    presion_aproximada,
    probabilidad_de_azar,
    sistema_del_rival,
    sistema_habitual,
    umbrales_de_liga,
)

PASES = 400.0


def _cdf_a_mano(k: int, lam: float) -> float:
    """La misma cuenta sin logaritmos, para contrastar la implementación.

    Con medias pequeñas esto es exacto y no comparte una línea de código con
    :func:`poisson_cdf`, que es lo que hace que la comparación valga.
    """
    return sum(math.exp(-lam) * lam**i / math.factorial(i) for i in range(k + 1))


# ------------------------------------------------------------------ la liga falsa

def _mete_partido(base, pid, fecha, local_id, local, visitante_id, visitante,
                  presion_local, presion_visitante, posesion_local,
                  formacion_local="4-4-2", formacion_visitante="4-4-2",
                  liga_id=8, liga="LaLiga", estado="finished"):
    """Un partido con la presión y la posesión que se le pidan.

    La presión se fabrica al revés: si se quieren *p* pases concedidos por
    acción defensiva, con 400 pases del rival hacen falta 400/p acciones.
    """
    base._conexion.execute(
        """INSERT OR REPLACE INTO partidos
           (id,fecha,momento,liga_id,liga,temporada_id,local_id,local,
            visitante_id,visitante,goles_local,goles_visitante,estado,arbitro,
            formacion_local,formacion_visitante)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (pid, fecha, 1780000000 + pid * 86400, liga_id, liga, 61643,
         local_id, local, visitante_id, visitante, 1, 1, estado, "Un Árbitro",
         formacion_local, formacion_visitante))
    valores = {
        "passes": (PASES, PASES),
        "totalTackle": (PASES / presion_local, PASES / presion_visitante),
        "interceptionWon": (0.0, 0.0),
        "fouls": (0.0, 0.0),
        "ballPossession": (float(posesion_local), float(100 - posesion_local)),
        "totalShotsOnGoal": (12.0, 9.0),
        "expectedGoals": (1.4, 0.9),
        "totalClearance": (18.0, 24.0),
    }
    for clave, (izq, der) in valores.items():
        base._conexion.execute(
            """INSERT OR REPLACE INTO estadisticas
               (partido_id,periodo,clave,local,visitante) VALUES (?,?,?,?,?)""",
            (pid, "ALL", clave, izq, der))
    base._conexion.commit()


def _mete_actuacion(base, pid, jugador_id, nombre, equipo_id, minutos, **conteos):
    datos = {"minutesPlayed": minutos, "expectedGoals": 0.3}
    datos.update(conteos)
    base._conexion.execute(
        """INSERT OR REPLACE INTO actuaciones
           (partido_id,jugador_id,jugador,equipo_id,titular,minutos,rating,datos)
           VALUES (?,?,?,?,?,?,?,?)""",
        (pid, jugador_id, nombre, equipo_id, 1, minutos, 7.0,
         json.dumps(datos)))
    base._conexion.commit()


#: (rival, presión del rival, posesión del rival, formación, tiros del jugador)
GUION = [
    # Tres contra un equipo que presiona alto: tira más de la cuenta.
    (201, "Presión FC", 4.0, 50, "4-3-3", 5, 3),
    (201, "Presión FC", 4.0, 50, "4-3-3", 5, 3),
    (201, "Presión FC", 4.0, 50, "4-3-3", 5, 3),
    # Tres contra uno de presión media: lo normal.
    (211, "Medio CF", 11.0, 40, "4-4-2", 4, 2),
    (211, "Medio CF", 11.0, 40, "4-4-2", 4, 2),
    (211, "Medio CF", 11.0, 40, "4-4-2", 4, 2),
    # Tres contra un bloque bajo de cinco atrás: desaparece.
    (301, "Muro CD", 22.0, 30, "5-3-2", 1, 0),
    (301, "Muro CD", 22.0, 30, "5-3-2", 1, 0),
    (301, "Muro CD", 22.0, 30, "5-3-2", 1, 0),
]

#: Partidos entre otros equipos, solo para que la liga tenga distribución.
RELLENO = [(6.0, 6.0, 45), (6.0, 6.0, 45), (6.0, 6.0, 45),
           (14.0, 14.0, 40), (14.0, 14.0, 40), (14.0, 14.0, 40),
           (18.0, 18.0, 35), (18.0, 18.0, 35), (18.0, 18.0, 35)]


@pytest.fixture
def base():
    with Almacen(":memory:") as almacen:
        _poblar(almacen)
        yield almacen


def _poblar(almacen: Almacen) -> None:
    for n, (rival_id, rival, presion, posesion, formacion, tiros, a_puerta) in enumerate(
            GUION, start=1):
        en_casa = n % 2 == 1
        if en_casa:
            _mete_partido(almacen, n, f"2026-02-{n:02d}", 100, "Nuestro CF",
                          rival_id, rival,
                          presion_local=10.0, presion_visitante=presion,
                          posesion_local=100 - posesion,
                          formacion_local="4-3-3", formacion_visitante=formacion)
        else:
            _mete_partido(almacen, n, f"2026-02-{n:02d}", rival_id, rival,
                          100, "Nuestro CF",
                          presion_local=presion, presion_visitante=10.0,
                          posesion_local=posesion,
                          formacion_local=formacion, formacion_visitante="4-3-3")
        _mete_actuacion(almacen, n, 999, "El Nueve", 100, 90,
                        totalShots=tiros, onTargetScoringAttempt=a_puerta,
                        goals=1 if a_puerta >= 2 else 0, keyPass=2)
        # El mismo guion, pero este solo juega 30 minutos contra el bloque bajo.
        minutos = 30 if rival_id == 301 else 90
        _mete_actuacion(almacen, n, 998, "El Suplente", 100, minutos,
                        totalShots=1, onTargetScoringAttempt=1, keyPass=1)

    for n, (presion_local, presion_visitante, posesion) in enumerate(RELLENO, start=10):
        _mete_partido(almacen, n, f"2026-03-{n:02d}", 400 + n, f"Relleno {n}",
                      500 + n, f"Comparsa {n}",
                      presion_local=presion_local, presion_visitante=presion_visitante,
                      posesion_local=posesion)


# ------------------------------------------------------------------ la estadística

@pytest.mark.parametrize("k,lam", [(0, 1.0), (3, 10.0), (5, 2.5), (14, 10.0), (0, 0.4)])
def test_la_poisson_coincide_con_la_cuenta_a_mano(k, lam):
    assert poisson_cdf(k, lam) == pytest.approx(_cdf_a_mano(k, lam), rel=1e-9)


def test_la_poisson_de_cero_es_lo_que_debe_ser():
    assert poisson_cdf(0, 1.0) == pytest.approx(math.exp(-1))


def test_la_poisson_llega_a_uno_y_no_se_pasa():
    assert poisson_cdf(60, 5.0) == pytest.approx(1.0, abs=1e-9)
    assert poisson_cdf(200, 50.0) <= 1.0


def test_la_poisson_no_baja_nunca():
    previo = 0.0
    for k in range(20):
        actual = poisson_cdf(k, 6.0)
        assert actual >= previo
        previo = actual


def test_sin_expectativa_no_hay_nada_que_contrastar():
    assert probabilidad_de_azar(3, 0) == 1.0
    assert poisson_cdf(4, 0) == 1.0


def test_el_contraste_es_de_una_cola_por_el_lado_que_toca():
    # Quedarse muy corto y pasarse mucho son ambos improbables.
    assert probabilidad_de_azar(0, 6.0) < 0.01
    assert probabilidad_de_azar(15, 6.0) < 0.01
    # Acertar la media, no.
    assert probabilidad_de_azar(6, 6.0) > 0.4


def test_marcar_de_menos_se_mide_como_acumulada_y_de_mas_como_cola():
    assert probabilidad_de_azar(3, 10.0) == pytest.approx(_cdf_a_mano(3, 10.0))
    assert probabilidad_de_azar(15, 10.0) == pytest.approx(1 - _cdf_a_mano(14, 10.0))


def test_una_muestra_corta_no_concluye_por_muy_bonito_que_sea_el_numero():
    """Un p de 0,001 con dos partidos sigue siendo dos partidos."""
    assert _veredicto(0.001, partidos=2, minutos=180) == "sin muestra"
    assert _veredicto(0.001, partidos=5, minutos=90) == "sin muestra"
    assert _veredicto(0.001, MINIMO_PARTIDOS, MINIMO_MINUTOS) == "señal"


def test_los_escalones_del_veredicto():
    assert _veredicto(0.04, 6, 540) == "señal"
    assert _veredicto(0.08, 6, 540) == "indicio"
    assert _veredicto(0.30, 6, 540) == "dentro de lo normal"


# ------------------------------------------------------------------ medir sistemas

def test_presionar_mas_da_un_numero_mas_bajo():
    mucho = presion_aproximada({"totalTackle": 20, "interceptionWon": 10, "fouls": 10},
                               {"passes": 400})
    poco = presion_aproximada({"totalTackle": 8, "interceptionWon": 2, "fouls": 2},
                              {"passes": 400})
    assert mucho < poco == 33.33


def test_sin_datos_no_se_inventa_una_presion():
    assert presion_aproximada({}, {"passes": 400}) is None
    assert presion_aproximada({"totalTackle": 20}, {}) is None
    assert presion_aproximada({"totalTackle": 0}, {"passes": 0}) is None


@pytest.mark.parametrize("formacion,defensas", [
    ("4-3-3", 4), ("5-3-2", 5), ("3-4-3", 3), ("4-2-3-1", 4), (None, None), ("raro", None),
])
def test_la_primera_cifra_de_la_formacion_son_los_defensas(formacion, defensas):
    assert _defensas(formacion) == defensas


def test_los_umbrales_salen_de_los_terciles_de_esa_liga(base):
    umbrales = umbrales_de_liga(base, 8)
    assert umbrales["muestras"] == 36
    assert umbrales["presion"] == (10.0, 14.0)
    assert umbrales["posesion"] == (45.0, 60.0)


def test_sin_partidos_suficientes_no_hay_umbrales(base):
    vacio = umbrales_de_liga(base, 999)
    assert vacio["presion"] is None and vacio["posesion"] is None


def test_el_sistema_se_mide_en_el_partido_no_se_supone_del_equipo(base):
    """El mismo rival, dos partidos, dos plantes distintos."""
    _mete_partido(base, 50, "2026-04-01", 100, "Nuestro CF", 301, "Muro CD",
                  presion_local=10.0, presion_visitante=4.0, posesion_local=40,
                  formacion_local="4-3-3", formacion_visitante="4-3-3")
    encerrado = sistema_del_rival(base, 7, 301)
    lanzado = sistema_del_rival(base, 50, 301)
    assert encerrado["presion"] == 22.0 and encerrado["defensas"] == 5
    assert lanzado["presion"] == 4.0 and lanzado["defensas"] == 4


def test_clasificar_es_relativo_a_la_liga_no_absoluto(base):
    """Presionar a 10 es una cosa en una liga y la contraria en otra."""
    sistema = {"presion": 10.0, "posesion": 50, "defensas": 4}
    liga_intensa = {"presion": (4.0, 7.0), "posesion": (45.0, 60.0)}
    liga_pausada = {"presion": (14.0, 20.0), "posesion": (45.0, 60.0)}
    assert clasificar(sistema, liga_intensa)["presion"] == "bloque bajo"
    assert clasificar(sistema, liga_pausada)["presion"] == "presiona alto"


def test_sin_umbrales_se_dice_que_no_se_sabe_en_vez_de_inventar():
    etiquetas = clasificar({"presion": 10.0, "posesion": 50, "defensas": 5},
                           {"presion": None, "posesion": None})
    assert "presion" not in etiquetas and "balon" not in etiquetas
    assert etiquetas["linea"] == "linea de 5"


def test_el_rival_del_guion_sale_clasificado_como_toca(base):
    umbrales = umbrales_de_liga(base, 8)
    etiquetas = {
        rival: clasificar(sistema_del_rival(base, partido, rival), umbrales)
        for partido, rival in ((1, 201), (4, 211), (7, 301))
    }
    assert etiquetas[201]["presion"] == "presiona alto"
    assert etiquetas[211]["presion"] == "presion media"
    assert etiquetas[301]["presion"] == "bloque bajo"
    assert etiquetas[301]["linea"] == "linea de 5"
    assert etiquetas[301]["balon"] == "cede el balon"


def test_el_sistema_habitual_resume_varios_partidos(base):
    habitual = sistema_habitual(base, 301)
    assert habitual["disponible"]
    assert habitual["partidos"] == 3
    assert habitual["formaciones"] == {"5-3-2": 3}
    assert habitual["presion"] == 22.0
    assert habitual["asi_juega"]["presion"] == "bloque bajo"
    assert habitual["asi_juega"]["linea"] == "linea de 5"


def test_de_un_equipo_sin_nada_guardado_no_se_opina(base):
    assert sistema_habitual(base, 77777)["disponible"] is False


# --------------------------------------------------------- el jugador contra eso

def test_agrupa_por_lo_que_se_enfrento(base):
    analisis = jugador_contra_sistema(base, 999, eje="presion")
    assert analisis["disponible"]
    assert analisis["jugador"] == "El Nueve"
    assert set(analisis["grupos"]) == {"presiona alto", "presion media", "bloque bajo"}
    assert analisis["partidos_sin_clasificar"] == 0
    for grupo in analisis["grupos"].values():
        assert grupo["partidos"] == 3 and grupo["minutos"] == 270


def test_todo_va_normalizado_por_noventa_minutos(base):
    analisis = jugador_contra_sistema(base, 999, eje="presion")
    # 15 tiros en 270 minutos son 5 por 90; su media son 30 en 810, o sea 3,33.
    alto = analisis["grupos"]["presiona alto"]
    assert alto["totales"]["tiros"] == 15
    assert alto["por_90"]["tiros"] == pytest.approx(5.0)
    assert analisis["su_media"]["por_90"]["tiros"] == pytest.approx(30 * 90 / 810, abs=1e-3)


def test_desaparecer_contra_el_bloque_bajo_sale_como_senal(base):
    analisis = jugador_contra_sistema(base, 999, eje="presion")
    tiros = analisis["grupos"]["bloque bajo"]["comparado_con_su_media"]["tiros"]
    assert tiros["observado"] == 3
    assert tiros["esperado"] == pytest.approx(10.0)
    assert tiros["p"] == pytest.approx(_cdf_a_mano(3, 10.0), abs=5e-5)
    assert tiros["veredicto"] == "señal"
    assert tiros["diferencia"] < 0


def test_lo_que_cabe_en_el_azar_se_queda_en_lo_normal(base):
    analisis = jugador_contra_sistema(base, 999, eje="presion")
    pases = analisis["grupos"]["presion media"]["comparado_con_su_media"]["pases_clave"]
    # Da dos pases clave en todos los partidos: no hay nada que contar.
    assert pases["veredicto"] == "dentro de lo normal"


def test_las_metricas_continuas_no_se_contrastan_con_poisson(base):
    analisis = jugador_contra_sistema(base, 999, eje="presion")
    xg = analisis["grupos"]["bloque bajo"]["comparado_con_su_media"]["xg"]
    assert xg["veredicto"] == "solo descriptivo"
    assert "p" not in xg


def test_pocos_minutos_en_el_grupo_no_concluyen_aunque_haya_tres_partidos(base):
    """El suplente juega los tres, pero 30 minutos cada uno: no hay muestra."""
    analisis = jugador_contra_sistema(base, 998, eje="presion", minimo_minutos=10)
    grupo = analisis["grupos"]["bloque bajo"]
    assert grupo["partidos"] == 3
    assert grupo["minutos"] == 90 < MINIMO_MINUTOS
    veredictos = {d["veredicto"] for d in grupo["comparado_con_su_media"].values()}
    assert veredictos <= {"sin muestra", "solo descriptivo"}


def test_de_un_jugador_que_no_esta_no_se_dice_nada(base):
    fuera = jugador_contra_sistema(base, 4242)
    assert fuera["disponible"] is False and "barrido" in fuera["nota"]


def test_se_puede_agrupar_por_linea_o_por_balon(base):
    por_linea = jugador_contra_sistema(base, 999, eje="linea")
    assert set(por_linea["grupos"]) == {"linea de 4", "linea de 5"}
    assert por_linea["grupos"]["linea de 4"]["partidos"] == 6

    por_balon = jugador_contra_sistema(base, 999, eje="balon")
    assert por_balon["grupos"]["cede el balon"]["partidos"] == 6


def test_cada_grupo_dice_contra_quien_fue(base):
    analisis = jugador_contra_sistema(base, 999, eje="presion")
    contra = analisis["grupos"]["bloque bajo"]["contra"]
    assert [c["rival"] for c in contra] == ["Muro CD"] * 3
    assert all(c["formacion"] == "5-3-2" for c in contra)


def test_la_respuesta_lleva_escrito_lo_que_no_dice(base):
    analisis = jugador_contra_sistema(base, 999)
    assert "favorito" in analisis["lo_que_no_dice"]
    assert "azar" in analisis["como_leerlo"]


def test_lo_relevante_filtra_y_ordena_por_lo_mas_dificil_de_explicar(base):
    analisis = jugador_contra_sistema(base, 999, eje="presion")
    relevante = lo_relevante(analisis)
    assert relevante, "algo tenía que salir con este guion"
    assert all(f["veredicto"] in {"señal", "indicio"} for f in relevante)
    assert [f["p"] for f in relevante] == sorted(f["p"] for f in relevante)
    assert any(f["contra"] == "bloque bajo" and f["metrica"] == "tiros"
               for f in relevante)


def test_lo_relevante_puede_exigir_senal(base):
    analisis = jugador_contra_sistema(base, 999, eje="presion")
    solo_senal = lo_relevante(analisis, incluir_indicios=False)
    assert all(f["veredicto"] == "señal" for f in solo_senal)
    assert len(solo_senal) <= len(lo_relevante(analisis))


def test_lo_relevante_de_algo_no_disponible_es_una_lista_vacia():
    assert lo_relevante({"disponible": False}) == []


# ------------------------------------------------------------------------ duelo

def test_el_duelo_junta_al_jugador_con_lo_que_suele_plantear_el_rival(base):
    resultado = duelo(base, 999, 301)
    assert resultado["disponible"]
    assert resultado["jugador"] == "El Nueve"
    assert resultado["rival"]["equipo"] == "Muro CD"
    assert resultado["por_eje"]["presion"]["el_rival_es"] == "bloque bajo"
    assert resultado["por_eje"]["linea"]["el_rival_es"] == "linea de 5"

    presion = resultado["por_eje"]["presion"]
    assert presion["encontrado"]
    assert presion["resumen"]["partidos"] == 3
    assert any(f["metrica"] == "tiros" for f in presion["resumen"]["relevante"])


def test_el_duelo_dice_cuando_el_jugador_nunca_se_ha_visto_con_eso(base):
    """Contra un rival que plantea algo que este jugador no ha visto."""
    for pid, fecha in ((60, "2026-05-01"), (61, "2026-05-08"), (62, "2026-05-15")):
        _mete_partido(base, pid, fecha, 600, "Raro FC", 601, "Otro FC",
                      presion_local=4.0, presion_visitante=11.0, posesion_local=70,
                      formacion_local="3-5-2", formacion_visitante="4-4-2")
    resultado = duelo(base, 999, 600)
    assert resultado["disponible"]
    assert resultado["por_eje"]["linea"]["el_rival_es"] == "linea de 3"
    assert resultado["por_eje"]["linea"]["encontrado"] is False
    assert resultado["por_eje"]["linea"]["resumen"] is None


def test_el_duelo_contra_un_desconocido_lo_dice(base):
    assert duelo(base, 999, 88888)["disponible"] is False


def test_el_duelo_avisa_de_hasta_donde_llega(base):
    resultado = duelo(base, 999, 301)
    assert "no lo que va a pasar" in resultado["lo_que_no_dice"]


# ------------------------------------------------------------------- por consola

@pytest.fixture
def db(tmp_path):
    """La misma liga inventada, pero en un fichero, para llamar a la CLI."""
    ruta = tmp_path / "sistemas.db"
    with Almacen(ruta) as almacen:
        _poblar(almacen)
    return str(ruta)


def test_la_consola_cuenta_como_plantea_un_equipo(db, capsys):
    from cancha import cli

    assert cli.main(["sistema", "301", "--db", db]) == 0
    salida = capsys.readouterr().out
    assert "5-3-2" in salida and "bloque bajo" in salida


def test_la_consola_marca_lo_que_se_sale_de_la_media(db, capsys):
    from cancha import cli

    assert cli.main(["contra", "999", "--db", db]) == 0
    salida = capsys.readouterr().out
    assert "Contra bloque bajo" in salida
    assert "señal" in salida
    # Y siempre, debajo, para qué no sirve.
    assert "favorito" in salida


def test_la_consola_saca_el_duelo(db, capsys):
    from cancha import cli

    assert cli.main(["duelo", "999", "301", "--db", db]) == 0
    salida = capsys.readouterr().out
    assert "Muro CD" in salida and "bloque bajo" in salida
    assert "tiros" in salida


def test_la_consola_puede_soltar_el_json(db, capsys):
    from cancha import cli

    assert cli.main(["contra", "999", "--db", db, "--stdout-json"]) == 0
    datos = json.loads(capsys.readouterr().out)
    assert datos["grupos"]["bloque bajo"]["partidos"] == 3


def test_la_consola_se_queja_de_quien_no_conoce(db, capsys):
    from cancha import cli

    assert cli.main(["contra", "Nadie De Nadie", "--db", db]) == 1
    assert "No encuentro" in capsys.readouterr().out


# --------------------------------------------------------- lo que ve la IA

@pytest.fixture
def sesion(db):
    from cancha.cache import MemoryCache
    from cancha.client import SofascoreClient
    from cancha.config import Settings
    from cancha.sesion import Sesion
    from cancha.transport import FakeTransport

    conexion = Sesion(
        cliente=SofascoreClient(Settings(rate_limit=0, retries=0, fallback_base_urls=()),
                                transport=FakeTransport({}), cache=MemoryCache(),
                                sleep=lambda _s: None),
        ruta_almacen=db,
    )
    try:
        yield conexion
    finally:
        conexion.close()


def test_las_tres_herramientas_estan_registradas_y_bien_explicadas():
    from cancha.herramientas import TOOLS

    for nombre in ("sistema_de_equipo", "jugador_contra_sistema", "duelo_jugador_rival"):
        assert nombre in TOOLS, nombre
        # La descripción es lo único que el modelo lee antes de elegir: tiene
        # que decir para qué sirve y, sobre todo, para qué no.
        assert len(TOOLS[nombre].description) > 120


def test_la_herramienta_del_duelo_responde(sesion):
    from cancha.herramientas import ejecutar

    salida = ejecutar("duelo_jugador_rival", {"jugador": "999", "rival": "301"},
                      sesion=sesion)
    assert salida["disponible"]
    assert salida["por_eje"]["presion"]["el_rival_es"] == "bloque bajo"


def test_la_herramienta_puede_devolver_solo_lo_relevante(sesion):
    from cancha.herramientas import ejecutar

    salida = ejecutar("jugador_contra_sistema",
                      {"jugador": "999", "solo_lo_relevante": True}, sesion=sesion)
    assert "grupos" not in salida
    assert salida["hallazgos"] and all(
        h["veredicto"] in {"señal", "indicio"} for h in salida["hallazgos"])
    assert "lo_que_no_dice" in salida


def test_la_herramienta_del_sistema_describe_al_rival(sesion):
    from cancha.herramientas import ejecutar

    salida = ejecutar("sistema_de_equipo", {"equipo": "301"}, sesion=sesion)
    assert salida["asi_juega"]["presion"] == "bloque bajo"


def test_las_herramientas_dicen_a_quien_no_encuentran(sesion):
    from cancha.herramientas import ejecutar

    salida = ejecutar("duelo_jugador_rival",
                      {"jugador": "Nadie De Nadie", "rival": "301"}, sesion=sesion)
    assert "error" in salida
