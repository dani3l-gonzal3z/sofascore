"""El registro: apuntar antes, resolver después, y poder juzgarlo.

Lo que se comprueba aquí es lo que hace que esto valga algo: que una predicción
se escriba **antes** del partido y no se pueda reescribir, que se resuelva sola
con el resultado, y que lo que se publique sea calibración y Brier antes que el
acierto, que es la cifra que más engaña.
"""

from __future__ import annotations

import pytest

from cancha.almacen import Almacen
from cancha.models import Event
from cancha.registro import (
    MINIMO_PARA_JUZGAR,
    VERSION_MODELO,
    anotar,
    balance,
    brier,
    calibracion,
    log_loss,
    resolver,
    texto,
)


@pytest.fixture
def base():
    with Almacen(":memory:") as almacen:
        yield almacen


def _evento(identificador: int, fecha: str = "2026-09-20") -> Event:
    from datetime import datetime, timezone

    momento = int(datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc).timestamp())
    return Event.from_api({
        "id": identificador, "startTimestamp": momento,
        "tournament": {"name": "LaLiga", "uniqueTournament": {"id": 8}},
        "homeTeam": {"id": 100, "name": "Local FC"},
        "awayTeam": {"id": 200, "name": "Visitante CF"},
    })


def _pronostico(local=0.55, empate=0.25, visitante=0.20) -> dict:
    return {
        "disponible": True,
        "goles": {
            "1x2": {"local": local, "empate": empate, "visitante": visitante},
            "mas_de": {"2.5": 0.52}, "ambos_marcan": 0.58,
            "marcadores": [{"marcador": "2-1", "probabilidad": 0.11}],
            "esperados": {"local": 1.6, "visitante": 1.1},
        },
        "mercado": {"disponible": True,
                    "mercado": {"local": 0.50, "empate": 0.27, "visitante": 0.23}},
    }


def _acabado(base, identificador, local, visitante, fecha="2026-09-20"):
    """El partido, ya jugado. Con el mismo UPSERT que usa el programa.

    Y esto importa: con `INSERT OR REPLACE` la fila se borra y se vuelve a
    escribir, y el `ON DELETE CASCADE` de la tabla se lleva por delante las
    predicciones de ese partido. El barrido guarda los partidos una y otra vez,
    así que un REPLACE ahí dentro borraría el registro cada noche.
    """
    base._conexion.execute(
        """INSERT INTO partidos
           (id,fecha,liga_id,liga,local_id,local,visitante_id,visitante,
            goles_local,goles_visitante,estado)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET
               goles_local=excluded.goles_local,
               goles_visitante=excluded.goles_visitante,
               estado=excluded.estado""",
        (identificador, fecha, 8, "LaLiga", 100, "Local FC", 200, "Visitante CF",
         local, visitante, "finished"))
    base._conexion.commit()


# ------------------------------------------------------------------ apuntar

def test_apuntar_guarda_una_prediccion_por_suceso(base):
    """Cada una es un sí/no con su probabilidad: así se puede calibrar."""
    salida = anotar(base, _evento(1), _pronostico())
    assert salida["guardadas"] == 6, salida
    filas = base.consulta("SELECT * FROM predicciones ORDER BY mercado, seleccion")
    mercados = {(f["mercado"], f["seleccion"]) for f in filas}
    assert ("1x2", "local") in mercados
    assert ("marcador", "2-1") in mercados
    assert ("mas_2_5", "si") in mercados
    assert all(f["version"] == VERSION_MODELO for f in filas)
    assert all(f["resuelto"] == 0 for f in filas)


def test_la_prediccion_guarda_el_precio_del_mercado_de_ese_momento(base):
    """Sin esto no hay CLV: no se sabe contra qué se predijo."""
    anotar(base, _evento(1), _pronostico())
    fila = base.consulta(
        "SELECT * FROM predicciones WHERE mercado='1x2' AND seleccion='local'")[0]
    assert fila["probabilidad"] == 0.55
    assert fila["prob_mercado"] == 0.50


def test_no_se_puede_reescribir_una_prediccion(base):
    """Un historial que se puede reescribir no vale nada."""
    anotar(base, _evento(1), _pronostico(local=0.55))
    segunda = anotar(base, _evento(1), _pronostico(local=0.99))
    assert segunda["guardadas"] == 0
    assert segunda["ya_estaban"] == 6
    fila = base.consulta(
        "SELECT * FROM predicciones WHERE mercado='1x2' AND seleccion='local'")[0]
    assert fila["probabilidad"] == 0.55, "la primera es la que cuenta"


def test_sin_pronostico_no_se_apunta_nada(base):
    salida = anotar(base, _evento(1), {"disponible": False, "nota": "faltan partidos"})
    assert salida["guardadas"] == 0
    assert "faltan" in salida["nota"]


# ----------------------------------------------------------------- resolver

def test_resolver_puntua_lo_que_ya_se_ha_jugado(base):
    anotar(base, _evento(1), _pronostico())
    _acabado(base, 1, 2, 1)                      # gana el local, 3 goles, marcan los dos

    salida = resolver(base)
    assert salida["resueltas"] == 6
    filas = {(f["mercado"], f["seleccion"]): f
             for f in base.consulta("SELECT * FROM predicciones")}
    assert filas[("1x2", "local")]["acerto"] == 1
    assert filas[("1x2", "empate")]["acerto"] == 0
    assert filas[("1x2", "visitante")]["acerto"] == 0
    assert filas[("mas_2_5", "si")]["acerto"] == 1, "2+1 = 3 goles"
    assert filas[("ambos_marcan", "si")]["acerto"] == 1
    assert filas[("marcador", "2-1")]["acerto"] == 1
    assert filas[("1x2", "local")]["valor_real"] == "2-1"


def test_un_partido_sin_jugar_se_queda_esperando(base):
    anotar(base, _evento(1), _pronostico())
    salida = resolver(base)
    assert salida["resueltas"] == 0
    assert salida["sin_jugar_todavia"] == 6


def test_resolver_dos_veces_no_cambia_nada(base):
    anotar(base, _evento(1), _pronostico())
    _acabado(base, 1, 2, 1)
    resolver(base)
    assert resolver(base)["resueltas"] == 0, "ya estaban resueltas"


def test_guardar_el_partido_otra_vez_no_borra_sus_predicciones(base):
    """El barrido guarda los partidos cada noche: si eso borrara el registro,
    el registro no existiría."""
    anotar(base, _evento(1), _pronostico())
    antes = base.consulta("SELECT COUNT(*) AS n FROM predicciones")[0]["n"]

    acabado = _evento(1)
    acabado.home_score.current, acabado.away_score.current = 2, 1
    acabado.status_type = "finished"
    base.guardar_evento(acabado)
    base._conexion.commit()

    assert base.consulta("SELECT COUNT(*) AS n FROM predicciones")[0]["n"] == antes
    assert resolver(base)["resueltas"] == antes, "y se pueden resolver"


def test_los_corners_se_resuelven_con_la_estadistica(base):
    pronostico = _pronostico()
    pronostico["corners"] = {"disponible": True, "mas_de": {"9.5": 0.44}}
    anotar(base, _evento(1), pronostico)
    _acabado(base, 1, 1, 1)
    base._conexion.execute(
        """INSERT INTO estadisticas (partido_id,periodo,clave,local,visitante)
           VALUES (?,?,?,?,?)""", (1, "ALL", "cornerKicks", 7, 4))
    base._conexion.commit()

    resolver(base)
    fila = base.consulta("SELECT * FROM predicciones WHERE mercado='corners'")[0]
    assert fila["acerto"] == 1, "11 córners pasan de 9.5"
    assert fila["valor_real"] == "11"


# ------------------------------------------------------------------ las cuentas

def test_brier_es_el_error_cuadratico():
    casos = [{"probabilidad": 0.7, "acerto": 1}, {"probabilidad": 0.3, "acerto": 0}]
    assert brier(casos) == pytest.approx((0.09 + 0.09) / 2)


def test_log_loss_castiga_equivocarse_con_aplomo():
    seguro_y_mal = [{"probabilidad": 0.99, "acerto": 0}]
    dudoso_y_mal = [{"probabilidad": 0.55, "acerto": 0}]
    assert log_loss(seguro_y_mal) > log_loss(dudoso_y_mal) * 5


def test_la_calibracion_dice_si_un_70_es_un_70():
    casos = [{"probabilidad": 0.7, "acerto": 1} for _ in range(7)]
    casos += [{"probabilidad": 0.7, "acerto": 0} for _ in range(3)]
    tramo = next(t for t in calibracion(casos) if t["tramo"] == "60%-80%")
    assert tramo["dijiste"] == pytest.approx(0.7)
    assert tramo["paso"] == pytest.approx(0.7)
    assert abs(tramo["desvio"]) < 0.001, "perfectamente calibrado"
    assert tramo["casos"] == 10


# ------------------------------------------------------------------- balance

def test_el_balance_sin_nada_lo_dice_en_vez_de_fingir(base):
    datos = balance(base)
    assert datos["casos"] == 0
    assert "Todavía no hay" in datos["nota"]


def test_el_balance_pone_la_calibracion_antes_que_el_acierto(base):
    for numero in range(1, 13):
        anotar(base, _evento(numero), _pronostico())
        _acabado(base, numero, 2, 1)
    resolver(base)

    datos = balance(base)
    assert datos["casos"] == 72
    assert datos["calibracion"], "la calibración es lo primero que hay que mirar"
    assert datos["brier"] is not None
    assert datos["brier_de_no_saber_nada"] == 0.25, "la referencia, siempre al lado"
    assert 0 <= datos["acierto"] <= 1
    assert datos["acierto_suelo"] <= datos["acierto"] <= datos["acierto_techo"]
    # Y el aviso de muestra, que es lo que impide leerlo como un juicio.
    assert datos["suficiente"] is (datos["casos"] >= MINIMO_PARA_JUZGAR)
    assert "no dice" not in datos["como_leerlo"]
    assert "ROI" in datos["lo_que_no_dice"], "aquí no se mide dinero"


def test_el_balance_compara_con_el_mercado_donde_se_puede(base):
    for numero in range(1, 6):
        anotar(base, _evento(numero), _pronostico())
        _acabado(base, numero, 2, 1)
    resolver(base)

    contra = balance(base)["contra_el_mercado"]
    assert contra["casos"] == 15, "los tres resultados del 1X2 de cinco partidos"
    assert contra["brier_nuestro"] is not None
    assert contra["brier_del_mercado"] is not None
    assert "mercado" in contra["lectura"]


def test_se_puede_mirar_un_solo_mercado(base):
    anotar(base, _evento(1), _pronostico())
    _acabado(base, 1, 2, 1)
    resolver(base)
    solo = balance(base, mercado="1x2")
    assert solo["casos"] == 3
    assert list(solo["por_mercado"]) == ["1x2"]


def test_el_texto_se_lee_de_un_vistazo(base):
    anotar(base, _evento(1), _pronostico())
    _acabado(base, 1, 2, 1)
    resolver(base)
    lineas = "\n".join(texto(balance(base)))
    assert "Calibración" in lineas
    assert "Brier" in lineas and "0.25" in lineas
    assert "Acierto" in lineas
    assert "indicio, no un juicio" in lineas, "con 6 casos no se juzga nada"
