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
    AUTOR_CALCULO,
    MINIMO_PARA_JUZGAR,
    VERSION_MODELO,
    anotar,
    balance,
    brier,
    calibracion,
    comparar,
    log_loss,
    resolver,
    tabla,
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
    mercados = {(f["mercado"], f["seleccion"]) for f in filas
                if f["autor"] == AUTOR_CALCULO}
    assert ("1x2", "local") in mercados
    assert ("marcador", "2-1") in mercados
    assert ("mas_2_5", "si") in mercados
    assert all(f["version"] == VERSION_MODELO for f in filas
               if f["autor"] == AUTOR_CALCULO)
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
    # Seis del cálculo y tres del mercado, que ahora también concursa.
    assert salida["resueltas"] == 9
    filas = {(f["mercado"], f["seleccion"]): f
             for f in base.consulta(
                 "SELECT * FROM predicciones WHERE autor='calculo'")}
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
    assert salida["sin_jugar_todavia"] == 9


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

    datos = balance(base, autor=AUTOR_CALCULO)
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

    contra = balance(base, autor=AUTOR_CALCULO)["contra_el_mercado"]
    assert contra["casos"] == 15, "los tres resultados del 1X2 de cinco partidos"
    assert contra["brier_nuestro"] is not None
    assert contra["brier_del_mercado"] is not None
    assert "mercado" in contra["lectura"]


def test_se_puede_mirar_un_solo_mercado(base):
    anotar(base, _evento(1), _pronostico())
    _acabado(base, 1, 2, 1)
    resolver(base)
    solo = balance(base, mercado="1x2", autor=AUTOR_CALCULO)
    assert solo["casos"] == 3
    assert list(solo["por_mercado"]) == ["1x2"]


def test_el_texto_se_lee_de_un_vistazo(base):
    anotar(base, _evento(1), _pronostico())
    _acabado(base, 1, 2, 1)
    resolver(base)
    lineas = "\n".join(texto(balance(base, autor=AUTOR_CALCULO)))
    assert "Calibración" in lineas
    assert "Brier" in lineas and "0.25" in lineas
    assert "Acierto" in lineas
    assert "indicio, no un juicio" in lineas, "con 6 casos no se juzga nada"


# ------------------------------------------------- el mercado, como uno más

def test_el_mercado_se_apunta_como_concursante(base):
    """Es gratis —las cuotas ya están— y es el listón contra el que se mide todo."""
    salida = anotar(base, _evento(1), _pronostico())
    assert salida["del_mercado"] == 3, "el 1X2 del mercado"

    suyas = base.consulta("SELECT * FROM predicciones WHERE autor='mercado'"
                          " ORDER BY seleccion")
    assert [f["seleccion"] for f in suyas] == ["empate", "local", "visitante"]
    assert [f["probabilidad"] for f in suyas] == [0.27, 0.50, 0.23]
    assert all(f["version"] == "cuotas" for f in suyas)


def test_sin_cuotas_el_mercado_no_concursa(base):
    pronostico = _pronostico()
    pronostico["mercado"] = {"disponible": False}
    salida = anotar(base, _evento(1), pronostico)
    assert salida["del_mercado"] == 0
    assert base.consulta("SELECT * FROM predicciones WHERE autor='mercado'") == []


def test_el_mercado_no_se_apunta_una_vez_por_cada_agente(base):
    """Tres agentes opinando del mismo partido no son tres mercados."""
    anotar(base, _evento(1), _pronostico())
    for quien in ("agente-a", "agente-b"):
        anotar(base, _evento(1), _pronostico(), autor=quien,
               probabilidades={"1x2": {"local": 0.6, "empate": 0.2, "visitante": 0.2}})
    assert len(base.consulta("SELECT * FROM predicciones WHERE autor='mercado'")) == 3


def test_un_agente_apunta_sus_numeros(base):
    salida = anotar(base, _evento(1), _pronostico(), autor="el-escéptico",
                    probabilidades={"1x2": {"local": 0.62, "empate": 0.22,
                                            "visitante": 0.16},
                                    "mas_2_5": 0.48,
                                    "marcador": {"marcador": "2-0",
                                                 "probabilidad": 0.09}})
    assert salida["guardadas"] == 5
    suyas = {(f["mercado"], f["seleccion"]): f["probabilidad"]
             for f in base.consulta(
                 "SELECT * FROM predicciones WHERE autor='el-escéptico'")}
    assert suyas[("1x2", "local")] == 0.62
    assert suyas[("marcador", "2-0")] == 0.09
    # Y se queda con el precio del mercado de ese momento, para poder medir CLV.
    fila = base.consulta("SELECT prob_mercado FROM predicciones"
                         " WHERE autor='el-escéptico' AND seleccion='local'")[0]
    assert fila["prob_mercado"] == 0.50


def test_lo_que_no_es_una_probabilidad_no_entra(base):
    """Una fila con un 1,4 envenena la calibración de todo el registro."""
    anotar(base, _evento(1), _pronostico(), autor="el-roto",
           probabilidades={"1x2": {"local": 1.4, "empate": "mucho",
                                   "visitante": -0.2},
                           "mas_2_5": None})
    assert base.consulta("SELECT * FROM predicciones WHERE autor='el-roto'") == []


def test_un_numero_imposible_no_se_convierte_en_uno_razonable(base):
    """Un 1,4 suelto no es «1,4 %»: es un disparate, y se tira."""
    from cancha.registro import _probabilidad, _son_porcentajes

    assert _probabilidad(1.4) is None
    assert _probabilidad(0.55) == 0.55
    assert _son_porcentajes({"local": 55, "empate": 25, "visitante": 20}) is True
    assert _son_porcentajes({"local": 0.55, "empate": 0.25, "visitante": 0.2}) is False
    assert _son_porcentajes({"local": 1.4}) is False


def test_un_porcentaje_se_entiende_igual(base):
    """Los modelos escriben 55 tanto como 0.55, y las dos cosas son lo mismo."""
    anotar(base, _evento(1), _pronostico(), autor="el-de-los-porcentajes",
           probabilidades={"1x2": {"local": 55, "empate": 25, "visitante": 20}})
    suyas = {f["seleccion"]: f["probabilidad"] for f in base.consulta(
        "SELECT * FROM predicciones WHERE autor='el-de-los-porcentajes'")}
    assert suyas == {"local": 0.55, "empate": 0.25, "visitante": 0.20}


# ------------------------------------------------------------ la clasificación

def _sembrar(base, autor, aciertos, probabilidad, desde=1, prob_mercado=0.5,
             horas_antes=None):
    """Unas cuantas predicciones ya resueltas de un autor, a mano."""
    for numero in range(desde, desde + aciertos[0] + aciertos[1]):
        acerto = 1 if numero < desde + aciertos[0] else 0
        base._conexion.execute(
            "INSERT OR IGNORE INTO partidos (id,fecha) VALUES (?,?)",
            (numero, "2026-09-20"))
        base._conexion.execute(
            """INSERT OR IGNORE INTO predicciones
               (partido_id,fecha,autor,mercado,seleccion,probabilidad,prob_mercado,
                horas_antes,resuelto,acerto) VALUES (?,?,?,?,?,?,?,?,1,?)""",
            (numero, "2026-09-20", autor, "1x2", "local", probabilidad,
             prob_mercado, horas_antes, acerto))
    base._conexion.commit()


def test_la_tabla_ordena_por_la_ventaja_sobre_el_mercado(base):
    """Un Brier bueno se consigue prediciendo solo partidos fáciles."""
    # El bueno: dice 0.8 y acierta 8 de 10, con el mercado en 0.5.
    _sembrar(base, "el-bueno", (8, 2), 0.8, desde=1)
    # El malo: dice 0.8 y acierta 3 de 10, con el mismo mercado.
    _sembrar(base, "el-malo", (3, 7), 0.8, desde=1)

    datos = tabla(base, minimo=5)
    orden = [f["autor"] for f in datos["clasificacion"]]
    assert orden[0] == "el-bueno", datos
    assert orden[-1] == "el-malo"
    bueno = datos["clasificacion"][0]
    assert bueno["ventaja_sobre_el_mercado"] > 0, "le gana al mercado"
    assert bueno["casos_comparables"] == 10
    assert bueno["desvio_de_calibracion"] is not None


def test_quien_no_tiene_muestra_no_entra_en_la_tabla(base):
    _sembrar(base, "el-veterano", (30, 20), 0.6, desde=1)
    _sembrar(base, "el-novato", (3, 1), 0.6, desde=100)

    datos = tabla(base, minimo=50)
    assert [f["autor"] for f in datos["clasificacion"]] == ["el-veterano"]
    assert [f["autor"] for f in datos["todavia_sin_muestra"]] == ["el-novato"]
    assert str(datos["minimo"]) in datos["como_leerlo"]


def test_quien_no_se_puede_comparar_con_el_mercado_va_al_final(base):
    """No haber podido medirse no es una ventaja."""
    _sembrar(base, "con-mercado", (6, 4), 0.6, desde=1)
    for numero in range(200, 210):
        base._conexion.execute(
            "INSERT OR IGNORE INTO partidos (id,fecha) VALUES (?,?)",
            (numero, "2026-09-20"))
        base._conexion.execute(
            """INSERT INTO predicciones (partido_id,fecha,autor,mercado,seleccion,
               probabilidad,resuelto,acerto) VALUES (?,?,?,?,?,?,1,1)""",
            (numero, "2026-09-20", "sin-mercado", "1x2", "local", 0.6))
    base._conexion.commit()

    orden = [f["autor"] for f in tabla(base, minimo=5)["clasificacion"]]
    assert orden[-1] == "sin-mercado"


# ------------------------------------------------- comparar dos, de verdad

def test_comparar_solo_mira_lo_que_han_predicho_los_dos(base):
    """Comparar dos balances sueltos es comparar dos exámenes distintos."""
    _sembrar(base, "con-cuaderno", (9, 1), 0.85, desde=1)
    _sembrar(base, "sin-cuaderno", (9, 1), 0.60, desde=1)
    # Y uno de ellos, además, un partido fácil que el otro no vio.
    _sembrar(base, "sin-cuaderno", (1, 0), 0.99, desde=500)

    salida = comparar(base, "con-cuaderno", "sin-cuaderno")
    assert salida["casos"] == 10, "solo los diez que vieron los dos"
    assert salida["gana"] == "con-cuaderno", salida
    assert salida["diferencia"] > 0
    assert "indicio, no un juicio" in salida["lectura"], "diez casos no juzgan nada"


def test_comparar_sin_nada_en_comun_lo_dice(base):
    _sembrar(base, "uno", (5, 0), 0.7, desde=1)
    _sembrar(base, "otro", (5, 0), 0.7, desde=300)
    salida = comparar(base, "uno", "otro")
    assert salida["casos"] == 0
    assert "no han predicho todavía nada en común" in salida["nota"]


def test_la_tabla_marca_a_quien_solo_repite_el_precio(base):
    """El expediente le enseña las cuotas, así que copiarlas es la trampa fácil.

    Y sale muy bien en la tabla: el mercado es difícil de batir, así que quien lo
    repite acaba arriba. Sin esta columna, la clasificación mediría quién copia
    mejor con toda la apariencia de medir quién analiza mejor.
    """
    _sembrar(base, "el-copion", (6, 4), 0.505, prob_mercado=0.5)
    _sembrar(base, "el-suyo", (6, 4), 0.72, prob_mercado=0.5)

    datos = tabla(base, minimo=5)
    por_autor = {f["autor"]: f for f in datos["clasificacion"]}
    assert por_autor["el-copion"]["distancia_al_mercado"] < 0.02
    assert por_autor["el-suyo"]["distancia_al_mercado"] > 0.2
    assert any("copion" in aviso and "repitiendo" in aviso
               for aviso in datos["avisos"]), datos["avisos"]


def test_la_tabla_avisa_cuando_uno_predice_mucho_mas_tarde(base):
    """Quien habla media hora antes del saque sabe más, no acierta más.

    Es un desnivel de fábrica: el cálculo se apunta en la guardia de las tres de
    la mañana y un agente se corre a mano. Premiarlo por eso sería premiar el
    reloj.
    """
    _sembrar(base, "el-madrugador", (6, 4), 0.7, horas_antes=14.0)
    _sembrar(base, "el-tardon", (6, 4), 0.7, horas_antes=0.4)

    datos = tabla(base, minimo=5)
    por_autor = {f["autor"]: f for f in datos["clasificacion"]}
    assert por_autor["el-madrugador"]["horas_antes_media"] == 14.0
    assert por_autor["el-tardon"]["horas_antes_media"] == 0.4
    assert any("comparación limpia" in aviso for aviso in datos["avisos"]), datos


def test_sin_desnivel_ni_copia_la_tabla_no_inventa_avisos(base):
    """Un aviso que sale siempre deja de leerse."""
    _sembrar(base, "el-uno", (6, 4), 0.72, prob_mercado=0.5, horas_antes=12.0)
    _sembrar(base, "el-otro", (5, 5), 0.66, prob_mercado=0.5, horas_antes=11.0)
    assert tabla(base, minimo=5)["avisos"] == []


def test_el_texto_de_la_tabla_no_finge_numeros_que_no_hay(base):
    """Un guion es honesto; un cero en su sitio sería mentira."""
    from cancha.registro import texto_tabla

    _sembrar(base, "el-solo", (6, 4), 0.7, prob_mercado=None)
    lineas = "\n".join(texto_tabla(tabla(base, minimo=5)))
    assert "el-solo" in lineas
    assert "—" in lineas


def test_el_texto_de_la_tabla_aparta_a_quien_no_tiene_muestra(base):
    from cancha.registro import texto_tabla

    _sembrar(base, "el-hecho", (30, 20), 0.7)
    _sembrar(base, "el-nuevo", (2, 1), 0.7, desde=500)
    lineas = "\n".join(texto_tabla(tabla(base, minimo=50)))
    assert "Todavía sin muestra" in lineas
    assert "le faltan 47" in lineas
