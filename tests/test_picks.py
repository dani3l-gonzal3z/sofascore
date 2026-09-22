"""Los picks: una regla fija, el precio al que se dio y un historial que no se toca.

Lo que se prueba es lo que hace esto vendible sin mentir: que la regla elige lo
que dice que elige y rechaza lo que dice que rechaza, que el precio apuntado no
se puede cambiar después, y que el historial calcula el rendimiento al precio
tomado —con su intervalo y su CLV— en vez de un acierto suelto.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cancha.almacen import Almacen
from cancha.mercados import con_probabilidades
from cancha.picks import (
    MINIMO_PARA_VENDER,
    REGLA,
    apuntar,
    boletin,
    candidatos,
    historial,
    resolver,
)

SAQUE = datetime(2026, 9, 26, 19, 0, tzinfo=timezone.utc).timestamp()


@pytest.fixture
def base():
    with Almacen(":memory:") as almacen:
        almacen._conexion.execute(
            "INSERT INTO partidos (id, local, visitante, fecha, momento) "
            "VALUES (1, 'Girona', 'Osasuna', '2026-09-26', ?)", (SAQUE,))
        almacen._conexion.commit()
        yield almacen


def _pronostico(local=0.55, mas25=0.52, partidos=10) -> dict:
    return {"disponible": True, "goles": {
        "1x2": {"local": local, "empate": 0.25, "visitante": 1 - local - 0.25},
        "mas_de": {"2.5": mas25}, "ambos_marcan": 0.5,
        "fuerzas": {"local": {"partidos": partidos}, "visitante": {"partidos": partidos}}}}


def _cuotas(base, local=2.10, empate=3.4, visitante=3.6, mas=1.95, menos=1.90,
            casa="bet365", extra=()):
    filas = [{"casa": casa, "mercado": "1x2", "linea": "", "seleccion": s, "cuota": c}
             for s, c in (("local", local), ("empate", empate), ("visitante", visitante))]
    filas += [{"casa": casa, "mercado": "goles", "linea": "2.5", "seleccion": s, "cuota": c}
              for s, c in (("mas", mas), ("menos", menos))]
    filas += list(extra)
    base.guardar_mercados(1, con_probabilidades(filas), fuente="prueba")


# --------------------------------------------------------------------- la regla

def test_pasa_lo_que_tiene_valor_y_se_separa_del_mercado(base):
    """Nosotros 55 % al local, el mercado ~46 % a cuota 2,10: valor de +15 %."""
    _cuotas(base)
    local = next(c for c in candidatos(base, 1, _pronostico()) if c["suceso"] == "Gana el local")
    assert local["pasa"], local["por_que_no"]
    assert local["valor"] == pytest.approx(0.55 * 2.10 - 1, abs=1e-3)


def test_con_muestra_corta_no_hay_pick(base):
    _cuotas(base)
    local = next(c for c in candidatos(base, 1, _pronostico(partidos=3))
                 if c["suceso"] == "Gana el local")
    assert not local["pasa"]
    assert any("muestra corta" in m for m in local["por_que_no"])


def test_una_cuota_demasiado_baja_no_es_pick_aunque_tenga_valor(base):
    """Por debajo de 1,50 el margen se come la ventaja posible."""
    _cuotas(base, local=1.35, empate=4.8, visitante=8.0)
    local = next(c for c in candidatos(base, 1, _pronostico(local=0.85))
                 if c["suceso"] == "Gana el local")
    assert not local["pasa"]
    assert any("fuera de" in m for m in local["por_que_no"])


def test_sin_separarse_del_mercado_no_hay_pick(base):
    """Valor sin separación suele ser un precio raro de una casa, no una opinión."""
    _cuotas(base, local=2.30)
    cerca = next(c for c in candidatos(base, 1, _pronostico(local=0.46))
                 if c["suceso"] == "Gana el local")
    assert not cerca["pasa"]


def test_un_mercado_con_mucho_margen_no_vale(base):
    _cuotas(base, local=1.80, empate=3.0, visitante=3.0)
    local = next(c for c in candidatos(base, 1, _pronostico(local=0.70))
                 if c["suceso"] == "Gana el local")
    assert any("cobra" in m for m in local["por_que_no"])


def test_el_menos_de_es_el_complemento_de_nuestro_mas_de(base):
    _cuotas(base)
    menos = next(c for c in candidatos(base, 1, _pronostico(mas25=0.30))
                 if c["suceso"] == "Menos de 2,5 goles")
    assert menos["prob_nuestra"] == pytest.approx(0.70)
    assert menos["mercado"] == "mas_2_5" and menos["seleccion"] == "no"


def test_la_cuota_del_pick_es_la_mejor_apostable_y_no_la_de_la_bolsa(base):
    """El precio medio de Betfair es la referencia, pero no se puede apostar a él."""
    extra = [{"casa": "betfair-exchange", "mercado": "1x2", "linea": "", "seleccion": s,
              "cuota": c} for s, c in (("local", 2.40), ("empate", 3.5), ("visitante", 3.9))]
    extra += [{"casa": "pinnacle", "mercado": "1x2", "linea": "", "seleccion": s,
               "cuota": c} for s, c in (("local", 2.18), ("empate", 3.45), ("visitante", 3.7))]
    _cuotas(base, extra=extra)
    local = next(c for c in candidatos(base, 1, _pronostico()) if c["suceso"] == "Gana el local")
    assert local["cuota"] == 2.18 and local["casa"] == "pinnacle"


# ------------------------------------------------------------------ apuntarlos

def _dia(pick):
    return {"fecha": "2026-09-26", "regla": REGLA["version"],
            "gratis": [pick], "premium": [pick]}


def _pick(cuota=2.10, mercado="1x2", seleccion="local"):
    return {"partido_id": 1, "suceso": "Gana el local", "mercado": mercado,
            "seleccion": seleccion, "prob_nuestra": 0.55, "prob_mercado": 0.46,
            "cuota": cuota, "casa": "bet365", "valor": 0.155}


def test_el_precio_apuntado_no_se_puede_cambiar_despues(base):
    """Un historial que se puede reescribir no vale nada, y uno de pago menos."""
    assert apuntar(base, _dia(_pick(cuota=2.10)))["apuntados"] == 2
    assert apuntar(base, _dia(_pick(cuota=2.60)))["apuntados"] == 0
    cuotas = {f["cuota"] for f in base.consulta("SELECT cuota FROM picks")}
    assert cuotas == {2.10}


def _jugado(base, local, visitante):
    base._conexion.execute(
        "UPDATE partidos SET goles_local = ?, goles_visitante = ?, estado = 'finished' "
        "WHERE id = 1", (local, visitante))
    base._conexion.commit()


def test_un_acierto_gana_la_cuota_menos_uno(base):
    apuntar(base, _dia(_pick(cuota=2.10)))
    _jugado(base, 2, 0)
    resolver(base)
    fila = base.consulta("SELECT * FROM picks WHERE nivel = 'gratis'")[0]
    assert fila["acerto"] == 1 and fila["beneficio"] == pytest.approx(1.10)


def test_un_fallo_pierde_la_unidad(base):
    apuntar(base, _dia(_pick()))
    _jugado(base, 0, 1)
    resolver(base)
    assert base.consulta("SELECT beneficio FROM picks")[0]["beneficio"] == -1.0


def test_la_cuota_de_cierre_sale_de_la_ultima_foto_antes_del_saque(base):
    """Dado a 2,10 y cerrado a 1,95: el mercado se movió hacia nosotros."""
    apuntar(base, _dia(_pick(cuota=2.10)))
    _cuotas(base, local=1.95)
    base._conexion.execute("UPDATE cuotas_mercado SET horas_antes = 0.5")
    base._conexion.commit()
    _jugado(base, 1, 0)
    resolver(base)
    assert base.consulta("SELECT cuota_cierre FROM picks")[0]["cuota_cierre"] == 1.95


# ---------------------------------------------------------------- el historial

def _sembrar(base, resultados):
    for n, (acerto, cuota, cierre) in enumerate(resultados):
        base._conexion.execute(
            """INSERT INTO picks (fecha, nivel, partido_id, mercado, seleccion,
               prob_nuestra, cuota, resuelto, acerto, beneficio, cuota_cierre)
               VALUES (?, 'gratis', 1, '1x2', ?, 0.5, ?, 1, ?, ?, ?)""",
            (f"2026-09-{n % 28 + 1:02d}", f"s{n}", cuota, acerto,
             cuota - 1 if acerto else -1.0, cierre))
    base._conexion.commit()


def test_el_historial_da_el_rendimiento_al_precio_tomado(base):
    _sembrar(base, [(1, 2.0, 1.9), (0, 2.0, 2.1), (1, 2.5, 2.3), (0, 2.0, 2.0)])
    h = historial(base, "gratis")
    assert h["picks"] == 4 and h["aciertos"] == 2
    assert h["unidades"] == pytest.approx(1.0 + 1.5 - 2)
    assert h["rendimiento"] == pytest.approx(0.125)


def test_el_intervalo_dice_que_cuarenta_picks_no_demuestran_nada(base):
    _sembrar(base, [(1, 2.2, 2.0)] * 22 + [(0, 2.2, 2.3)] * 18)
    h = historial(base, "gratis")
    assert h["intervalo"][0] < 0 < h["intervalo"][1], "el cero cabe"
    assert "no demuestra nada" in h["lectura"]


def test_la_peor_racha_se_cuenta(base):
    _sembrar(base, [(1, 2.0, None)] + [(0, 2.0, None)] * 5 + [(1, 2.0, None)])
    assert historial(base, "gratis")["peor_racha"] == pytest.approx(-5.0)


def test_el_clv_cuenta_cuantas_veces_el_mercado_vino_hacia_nosotros(base):
    """Es lo que mejor predice si esto va a ganar, mucho antes que el acierto."""
    _sembrar(base, [(0, 2.0, 1.8), (0, 2.0, 1.9), (1, 2.0, 2.2)])
    h = historial(base, "gratis")
    assert h["gana_al_cierre"] == pytest.approx(2 / 3, abs=1e-3)


def test_sin_picks_se_dice(base):
    assert historial(base, "premium")["picks"] == 0


# ------------------------------------------------------------------ el boletín

def test_un_dia_sin_pick_se_dice_y_no_se_inventa_uno():
    texto = boletin({"fecha": "2026-09-26", "gratis": [], "premium": []}, "gratis")
    assert "no hay pick" in texto
    assert "mayor de edad" in texto


def test_el_boletin_lleva_la_cuota_y_el_historial():
    pick = {**_pick(), "partido": "Girona - Osasuna", "hora_utc": "19:00"}
    texto = boletin({"fecha": "2026-09-26", "gratis": [pick], "premium": [pick]},
                    "gratis", {"picks": 12, "aciertos": 7, "unidades": 1.4,
                               "rendimiento": 0.117})
    assert "2.1" in texto and "Girona - Osasuna" in texto
    assert "12 picks" in texto
    assert f"menos de {MINIMO_PARA_VENDER}" in texto, "y que con doce no se demuestra nada"


# ------------------------------------------------------------ bot y canales

class _Telegram:
    def __init__(self):
        self.enviados = []

    def __call__(self, metodo, cuerpo=None):
        if metodo == "sendMessage":
            self.enviados.append(cuerpo)
        return {"ok": True, "result": {}}


def test_cada_nivel_se_publica_en_su_canal_con_su_historial(tmp_path):
    from cancha.sesion import Sesion
    from cancha.telegrama import Bot

    falso = _Telegram()
    sesion = Sesion(ruta_almacen=str(tmp_path / "b.db"))
    bot = Bot(token="x", permitidos=(1,), sesion=sesion, pedir=falso,
              canal_gratis="@gratis", canal_premium="@premium")
    pick = {**_pick(), "partido": "Girona - Osasuna", "hora_utc": "19:00"}
    otro = {**_pick(cuota=1.9), "partido": "Betis - Celta", "suceso": "Empate"}
    publicados = bot.publicar_picks(
        {"fecha": "2026-09-26", "gratis": [pick], "premium": [pick, otro]},
        {"gratis": {"picks": 3, "aciertos": 2, "unidades": 1.2, "rendimiento": 0.4}})
    sesion.close()
    assert publicados == ["gratis", "premium"]
    por_canal = {e["chat_id"]: e["text"] for e in falso.enviados}
    assert "Betis" not in por_canal["@gratis"], "el gratis lleva uno solo"
    assert "Betis" in por_canal["@premium"]
    assert "3 picks" in por_canal["@gratis"] and "3 picks" not in por_canal["@premium"]


def test_sin_canales_no_se_publica_nada(tmp_path):
    from cancha.sesion import Sesion
    from cancha.telegrama import Bot

    falso = _Telegram()
    sesion = Sesion(ruta_almacen=str(tmp_path / "b.db"))
    bot = Bot(token="x", permitidos=(1,), sesion=sesion, pedir=falso)
    assert bot.publicar_picks({"fecha": "x", "gratis": [], "premium": []}) == []
    sesion.close()
    assert falso.enviados == []


def test_los_canales_se_cogen_al_vuelo_de_los_ajustes(tmp_path):
    from cancha.sesion import Sesion
    from cancha.telegrama import Bot

    sesion = Sesion(ruta_almacen=str(tmp_path / "b.db"))
    bot = Bot(token="x", sesion=sesion, pedir=_Telegram(), releer=lambda: {
        "telegram": {"token": "x", "canal_gratis": "@g", "canal_premium": ""}})
    cambios = bot.refrescar()
    sesion.close()
    assert bot.canal_gratis == "@g"
    assert any("canal gratis" in c for c in cambios)


def test_el_pick_apuntado_es_el_que_se_ensena(base):
    """Recalcularlo daría otro precio: enseñar ese sería enseñar algo distinto de
    lo que se juzga después."""
    from cancha.picks import apuntados

    apuntar(base, _dia(_pick(cuota=2.10)))
    dia = apuntados(base, "2026-09-26")
    assert dia["apuntado"] is True
    assert dia["gratis"][0]["cuota"] == 2.10
    assert apuntados(base, "2026-09-27") is None


def test_la_guardia_apunta_los_picks_y_los_publica(monkeypatch, tmp_path):
    """El precio queda apuntado antes del saque, y el bot los manda a sus canales."""
    import cancha.picks as modulo
    from cancha import guardia

    dia = {"fecha": "2026-09-26", "regla": "regla-1",
           "gratis": [_pick()], "premium": [_pick()], "casi": [], "nota": ""}
    monkeypatch.setattr(modulo, "del_dia", lambda *a, **k: dia)
    visto = {}

    def publicar(d, historiales):
        visto["dia"], visto["historiales"] = d, historiales
        return ["gratis"]

    # Solo el paso de los picks: el resto de la guardia ya tiene sus pruebas.
    for nombre in ("barrer",):
        monkeypatch.setattr("cancha.barrido." + nombre, lambda *a, **k: {
            "guardados": 0, "peticiones": 0})
    # `agenda` se importa en varios módulos al cargarlos: se sustituye en todos,
    # o esta prueba depende de qué otra haya cargado antes el briefing.
    monkeypatch.setattr("cancha.barrido.agenda", lambda *a, **k: [])
    monkeypatch.setattr("cancha.briefing.agenda", lambda *a, **k: [])

    class Cliente:
        class stats:
            requests = 0

    with Almacen(str(tmp_path / "g.db")) as almacen:
        almacen._conexion.execute(
            "INSERT INTO partidos (id, local, visitante, fecha) "
            "VALUES (1, 'Girona', 'Osasuna', '2026-09-26')")
        almacen._conexion.commit()
        resumen = guardia.preparar_dia(Cliente(), almacen, fecha="2026-09-26",
                                       abastecer_partidos=0,
                                       carpeta_briefings=str(tmp_path / "br"),
                                       publicar=publicar)
        assert resumen["picks"]["apuntados"] == 2
        assert almacen.consulta("SELECT COUNT(*) AS n FROM picks")[0]["n"] == 2
    assert visto["dia"] is dia
    assert set(visto["historiales"]) == {"gratis", "premium"}
