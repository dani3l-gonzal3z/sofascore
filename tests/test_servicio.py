"""Los comandos de dejarlo funcionando, ejecutados de verdad.

Este fichero nace de un fallo que llegó al usuario: `cancha arrancar` leía las
opciones de `args` en vez de resolverlas contra los ajustes, y como los valores
por defecto del parser son None —para que puedan ganar los ajustes—, al
servidor le llegaba `puerto=None` y reventaba al abrir el puerto.

Había ochocientas ochenta y nueve pruebas y ninguna ejecutaba el comando que
se usa todos los días. Estas lo ejecutan.
"""

from __future__ import annotations

import json

import pytest

from cancha import cli
from cancha.ajustes import guardar


@pytest.fixture
def llamadas(monkeypatch, cliente):
    """Deja arrancar el comando pero sin abrir puertos ni hilos de verdad."""
    import cancha.web as web
    from cancha.comandos import comun

    apuntadas: dict = {}

    def arrancar_de_mentira(aplicacion, **kwargs):
        apuntadas["arrancar"] = kwargs
        apuntadas["app"] = aplicacion
        aplicacion.close()
        return 0

    monkeypatch.setattr(web, "arrancar", arrancar_de_mentira)
    monkeypatch.setattr(comun, "construir_cliente", lambda _a: cliente)
    return apuntadas


def _ajustes(tmp_path, **cambios) -> str:
    from cancha.ajustes import cargar, poner

    datos = cargar("/no/existe")
    for clave, valor in cambios.items():
        datos = poner(datos, clave.replace("__", "."), valor)
    ruta = tmp_path / "ajustes.json"
    guardar(datos, ruta)
    return str(ruta)


# ------------------------------------------------------------------ arrancar

def test_arrancar_coge_el_puerto_de_los_ajustes(tmp_path, llamadas):
    """Este es el fallo exacto que llegó al usuario: puerto=None."""
    ruta = _ajustes(tmp_path, web__puerto=9123, memoria=str(tmp_path / "m.db"))
    assert cli.main(["arrancar", "--ajustes", ruta, "--sin-guardia", "--sin-bot"]) == 0
    assert llamadas["arrancar"]["puerto"] == 9123
    assert isinstance(llamadas["arrancar"]["puerto"], int)


def test_ninguna_opcion_le_llega_al_servidor_en_None(tmp_path, llamadas):
    """La red de seguridad: si algo vuelve a quedarse sin resolver, se ve aquí."""
    ruta = _ajustes(tmp_path, memoria=str(tmp_path / "m2.db"))
    cli.main(["arrancar", "--ajustes", ruta, "--sin-guardia", "--sin-bot"])
    for nombre, valor in llamadas["arrancar"].items():
        assert valor is not None, f"arrancar ha recibido {nombre}=None"


def test_la_linea_de_comandos_gana_a_los_ajustes_al_arrancar(tmp_path, llamadas):
    ruta = _ajustes(tmp_path, web__puerto=9123, memoria=str(tmp_path / "m3.db"))
    cli.main(["arrancar", "--ajustes", ruta, "--port", "9999",
              "--sin-guardia", "--sin-bot"])
    assert llamadas["arrancar"]["puerto"] == 9999


def test_la_clave_y_los_briefings_salen_de_los_ajustes(tmp_path, llamadas):
    ruta = _ajustes(tmp_path, web__clave="secreta", memoria=str(tmp_path / "m4.db"),
                    briefings=str(tmp_path / "bfs"))
    cli.main(["arrancar", "--ajustes", ruta, "--sin-guardia", "--sin-bot"])
    aplicacion = llamadas["app"]
    assert aplicacion.clave == "secreta"
    assert aplicacion.carpeta_briefings == str(tmp_path / "bfs")


def test_el_ajuste_de_wifi_decide_el_host(tmp_path, llamadas):
    ruta = _ajustes(tmp_path, web__lan=False, memoria=str(tmp_path / "m5.db"))
    cli.main(["arrancar", "--ajustes", ruta, "--sin-guardia", "--sin-bot"])
    assert llamadas["arrancar"]["host"] == "127.0.0.1"

    ruta = _ajustes(tmp_path, web__lan=True, memoria=str(tmp_path / "m6.db"))
    cli.main(["arrancar", "--ajustes", ruta, "--sin-guardia", "--sin-bot"])
    assert llamadas["arrancar"]["host"] == "0.0.0.0"


def test_solo_local_gana_aunque_los_ajustes_digan_wifi(tmp_path, llamadas):
    ruta = _ajustes(tmp_path, web__lan=True, memoria=str(tmp_path / "m7.db"))
    cli.main(["arrancar", "--ajustes", ruta, "--solo-local",
              "--sin-guardia", "--sin-bot"])
    assert llamadas["arrancar"]["host"] == "127.0.0.1"


def test_al_arrancar_se_dice_la_hora_de_verdad_de_la_guardia(tmp_path, llamadas,
                                                             capsys, monkeypatch):
    """«cada día a las None» era el síntoma visible del mismo fallo."""
    import cancha.guardia as guardia

    monkeypatch.setattr(guardia, "vigilar", lambda *a, **k: None)
    ruta = _ajustes(tmp_path, guardia__hora="02:30", memoria=str(tmp_path / "m8.db"))
    cli.main(["arrancar", "--ajustes", ruta, "--sin-bot"])
    salida = capsys.readouterr().out
    assert "a las 02:30" in salida
    assert "None" not in salida, "algo se ha quedado sin resolver"


def test_la_guardia_apagada_en_los_ajustes_no_se_pone_en_marcha(tmp_path, llamadas,
                                                                capsys):
    ruta = _ajustes(tmp_path, guardia__activa=False, memoria=str(tmp_path / "m9.db"))
    cli.main(["arrancar", "--ajustes", ruta, "--sin-bot"])
    assert "apagada en tus ajustes" in capsys.readouterr().out


def test_las_ligas_elegidas_se_enseñan_al_arrancar(tmp_path, llamadas, capsys):
    ruta = _ajustes(tmp_path, ligas=["grandes", "uefa"],
                    memoria=str(tmp_path / "m10.db"))
    cli.main(["arrancar", "--ajustes", ruta, "--sin-guardia", "--sin-bot"])
    assert "grandes, uefa" in capsys.readouterr().out


def test_sin_ligas_elegidas_se_dice_que_es_todo(tmp_path, llamadas, capsys):
    ruta = _ajustes(tmp_path, memoria=str(tmp_path / "m11.db"))
    cli.main(["arrancar", "--ajustes", ruta, "--sin-guardia", "--sin-bot"])
    assert "todo el catálogo" in capsys.readouterr().out


def test_la_pagina_recibe_el_modelo_y_el_fichero_de_ajustes(tmp_path, llamadas):
    """Sin esto, la pestaña Ajustes de la interfaz editaría otro fichero."""
    ruta = _ajustes(tmp_path, modelo="qwen2.5:7b", memoria=str(tmp_path / "m12.db"))
    cli.main(["arrancar", "--ajustes", ruta, "--sin-guardia", "--sin-bot"])
    aplicacion = llamadas["app"]
    assert aplicacion.modelo == "qwen2.5:7b"
    assert aplicacion.ruta_ajustes == ruta


# ------------------------------------------------------------------- guardia

def test_guardia_una_vez_usa_los_ajustes(tmp_path, monkeypatch, cliente):
    import cancha.guardia as guardia
    from cancha.comandos import comun

    monkeypatch.setattr(comun, "construir_cliente", lambda _a: cliente)
    recogidos: dict = {}
    monkeypatch.setattr(guardia, "preparar_dia",
                        lambda *a, **k: recogidos.update(k) or {})
    ruta = _ajustes(tmp_path, guardia__partidos=3, ligas=["grandes"],
                    memoria=str(tmp_path / "g.db"),
                    briefings=str(tmp_path / "gb"))
    assert cli.main(["guardia", "--una-vez", "--ajustes", ruta]) == 0
    assert recogidos["abastecer_partidos"] == 3
    assert recogidos["grupos"] == ["grandes"]
    assert recogidos["carpeta_briefings"] == str(tmp_path / "gb")


def test_un_fichero_de_ajustes_roto_avisa_y_arranca_igual(tmp_path, llamadas, capsys):
    """Si esto tumbara el arranque no podrías ni entrar a arreglarlo."""
    ruta = tmp_path / "roto.json"
    ruta.write_text("{ esto no es json", encoding="utf-8")
    assert cli.main(["arrancar", "--ajustes", str(ruta), "--sin-guardia",
                     "--sin-bot"]) == 0
    salida = capsys.readouterr().out
    assert "No he podido leer" in salida
    assert llamadas["arrancar"]["puerto"] == 8765, "ha seguido con lo de fábrica"


# --------------------------------------------------------------------- ajustes

def test_el_comando_ajustes_guarda_y_lo_enseña(tmp_path, capsys):
    ruta = str(tmp_path / "aj.json")
    assert cli.main(["ajustes", "--ajustes", ruta, "guardia.hora=01:45",
                     "modelo=qwen2.5:7b"]) == 0
    salida = capsys.readouterr().out
    assert "Guardado en" in salida
    guardado = json.loads((tmp_path / "aj.json").read_text(encoding="utf-8"))
    assert guardado["guardia"]["hora"] == "01:45"
    assert guardado["modelo"] == "qwen2.5:7b"


def test_un_ajuste_inventado_no_se_guarda_y_se_explica(tmp_path, capsys):
    ruta = str(tmp_path / "aj2.json")
    assert cli.main(["ajustes", "--ajustes", ruta, "guardia.horita=01:45"]) == 2
    assert "guardia.hora" in capsys.readouterr().out
    assert not (tmp_path / "aj2.json").exists()


def test_sin_igual_no_es_un_cambio(tmp_path, capsys):
    ruta = str(tmp_path / "aj3.json")
    assert cli.main(["ajustes", "--ajustes", ruta, "guardia.hora"]) == 2
    assert "clave=valor" in capsys.readouterr().out


def test_ajustes_ligas_lista_lo_que_se_puede_elegir(capsys):
    assert cli.main(["ajustes", "--ligas"]) == 0
    salida = capsys.readouterr().out
    assert "grandes" in salida and "Spain La Liga" in salida
    assert "laliga" in salida, "los alias también, que son lo que se escribe"


def test_la_guardia_no_comparte_cliente_con_la_web(tmp_path, monkeypatch, cliente):
    """Compartirlo le descontaba a la guardia lo que pidieras desde la página.

    El tope de la guardia se mide con el contador de peticiones de su cliente.
    Si fuera el mismo que usa el servidor web, abrir una previa desde el móvil
    le gastaría presupuesto y se cortaría sola sin motivo. Antes esto se
    comprobaba leyendo el código fuente, que es lo que se hace cuando no
    tienes cómo ejecutarlo; ahora se ejecuta.
    """
    import threading

    import cancha.guardia as guardia
    import cancha.web as web
    from cancha.client import SofascoreClient
    from cancha.comandos import comun
    from cancha.config import Settings
    from cancha.transport import FakeTransport

    hechos = []

    def cliente_nuevo(_args):
        nuevo = SofascoreClient(Settings(rate_limit=0, retries=0, cache_ttl=0,
                                         fallback_base_urls=()),
                                transport=FakeTransport({}), sleep=lambda _s: None)
        hechos.append(nuevo)
        return nuevo

    recibido = {}
    listo = threading.Event()

    def vigilar_de_mentira(cli, _almacen, **_k):
        recibido["cliente"] = cli
        listo.set()

    monkeypatch.setattr(comun, "construir_cliente", cliente_nuevo)
    monkeypatch.setattr(guardia, "vigilar", vigilar_de_mentira)
    aplicaciones = {}
    monkeypatch.setattr(web, "arrancar",
                        lambda app, **k: aplicaciones.update(app=app) or 0)

    ruta = _ajustes(tmp_path, memoria=str(tmp_path / "hilo.db"))
    cli.main(["arrancar", "--ajustes", ruta, "--sin-bot"])
    assert listo.wait(5), "la guardia no ha llegado a arrancar"

    del_web = aplicaciones["app"].sesion.cliente
    assert recibido["cliente"] is not del_web, "la guardia usa el cliente de la web"
    assert len(hechos) >= 2, "tiene que haberse construido uno para cada cosa"
    aplicaciones["app"].close()


# -------------------------------------------------------------------- el bot
# Otro fallo que llegó al usuario, y de los peores: uno silencioso. Guardó el
# token del bot en la pestaña Ajustes, le escribió por Telegram y no pasó nada.
# El hilo del bot solo se creaba si había token al arrancar, así que el token
# nuevo no lo miraba nadie hasta reiniciar.

def test_el_bot_se_levanta_aunque_todavia_no_haya_token(tmp_path, llamadas):
    ruta = _ajustes(tmp_path, memoria=str(tmp_path / "bot1.db"))
    assert cli.main(["arrancar", "--ajustes", ruta, "--sin-guardia"]) == 0
    bot = llamadas["app"].bot
    assert bot is not None, "sin hilo, poner el token en Ajustes no sirve de nada"
    assert bot.releer is not None, "y tiene que volver a mirar los ajustes"
    assert bot.releer()["telegram"]["token"] == ""
    bot.parar()
    bot.close()


def test_el_bot_coge_el_token_que_se_guarde_despues(tmp_path, llamadas):
    """El camino del usuario, entero: arrancar sin token y ponerlo desde el móvil."""
    from cancha.ajustes import cargar, guardar, poner

    ruta = _ajustes(tmp_path, memoria=str(tmp_path / "bot2.db"))
    cli.main(["arrancar", "--ajustes", ruta, "--sin-guardia"])
    bot = llamadas["app"].bot
    try:
        assert bot.token == ""
        # Esto es lo que hace la pestaña Ajustes al darle a Guardar.
        guardar(poner(poner(cargar(ruta), "telegram.token", "123:ABC"),
                      "telegram.chats", "4242"), ruta)
        assert bot.refrescar() == ["token puesto", "contesta a 4242"]
        assert bot.token == "123:ABC"
        assert bot.permitidos == (4242,)
    finally:
        bot.parar()
        bot.close()


def test_con_sin_bot_no_hay_bot(tmp_path, llamadas):
    ruta = _ajustes(tmp_path, memoria=str(tmp_path / "bot3.db"))
    cli.main(["arrancar", "--ajustes", ruta, "--sin-guardia", "--sin-bot"])
    assert llamadas["app"].bot is None


def test_un_token_de_la_linea_de_comandos_manda(tmp_path, llamadas, monkeypatch):
    ruta = _ajustes(tmp_path, memoria=str(tmp_path / "bot4.db"))
    import cancha.telegrama as telegrama

    monkeypatch.setattr(telegrama.Bot, "comprobar",
                        lambda self: {"nombre": "cancha", "enlace": None})
    cli.main(["arrancar", "--ajustes", ruta, "--sin-guardia", "--token", "123:ABC"])
    bot = llamadas["app"].bot
    try:
        assert bot.token == "123:ABC"
        assert bot.token_fijo, "los ajustes vacíos no pueden borrar un --token"
        assert bot.refrescar() == []
        assert bot.token == "123:ABC"
    finally:
        bot.parar()
        bot.close()
