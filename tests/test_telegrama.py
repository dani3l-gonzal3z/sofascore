"""El bot de Telegram, probado sin Telegram.

Se sustituye la única función que habla con la red, igual que en el analista.
Lo que más se mira aquí es quién puede hablarle: un bot es público y contestar
a cualquiera sería enseñarle la memoria entera al primero que pase.
"""

from __future__ import annotations

import pytest

from cancha.sesion import Sesion
from cancha.telegrama import LIMITE, Bot, TelegramNoDisponible, _trozos


class Falso:
    """Se hace pasar por Telegram: apunta lo enviado y devuelve lo que le digas."""

    def __init__(self, actualizaciones=None):
        self.enviados: list[dict] = []
        self.actualizaciones = actualizaciones or []
        self.llamadas: list[str] = []

    def __call__(self, metodo, cuerpo=None):
        self.llamadas.append(metodo)
        if metodo == "getMe":
            return {"ok": True, "result": {"first_name": "cancha", "username": "canchabot"}}
        if metodo == "sendMessage":
            self.enviados.append(cuerpo)
            return {"ok": True}
        if metodo == "getUpdates":
            salida, self.actualizaciones = self.actualizaciones, []
            return {"ok": True, "result": salida}
        return {"ok": True, "result": {}}


def _mensaje(identificador: int, chat: int, texto: str) -> dict:
    return {"update_id": identificador,
            "message": {"chat": {"id": chat}, "text": texto}}


@pytest.fixture
def bot(cliente, tmp_path):
    falso = Falso()
    sesion = Sesion(cliente=cliente, ruta_almacen=str(tmp_path / "t.db"))
    salida = Bot(token="x", permitidos=(42,), sesion=sesion, pedir=falso)
    yield salida, falso
    sesion.close()


# --------------------------------------------------------------- quién entra

def test_sin_lista_de_permitidos_no_contesta_a_nadie(cliente, tmp_path):
    """Un bot es público: sin lista, cualquiera vería tu memoria."""
    falso = Falso()
    sesion = Sesion(cliente=cliente, ruta_almacen=str(tmp_path / "t2.db"))
    solo = Bot(token="x", permitidos=(), sesion=sesion, pedir=falso)
    try:
        respuesta = solo.atender(777, "/memoria")
    finally:
        sesion.close()
    assert "no contesta a nadie" in respuesta
    assert "777" in respuesta, "tiene que decirte tu id para que lo puedas permitir"
    assert "partidos" not in respuesta.lower(), "no ha filtrado nada de la memoria"


def test_a_un_desconocido_no_se_le_cuenta_ni_que_es_esto(bot):
    solo, _ = bot
    respuesta = solo.atender(999, "/memoria")
    assert respuesta == "No tengo nada para ti."


def test_al_permitido_si(bot):
    solo, falso = bot
    respuesta = solo.atender(42, "/memoria")
    assert "partidos" in respuesta
    assert falso.enviados and falso.enviados[-1]["chat_id"] == 42


# ------------------------------------------------------------------ órdenes

def test_la_ayuda_lista_lo_que_sabe_hacer(bot):
    solo, _ = bot
    respuesta = solo.responder("/ayuda")
    for orden in ("/hoy", "/seguro", "/previa", "/equipo", "/jugador", "/memoria"):
        assert orden in respuesta


def test_las_ordenes_valen_con_arroba_y_en_mayusculas(bot):
    """Telegram manda /hoy@mibot en los grupos; y la gente escribe /HOY."""
    solo, _ = bot
    assert "Lo que sé hacer" in solo.responder("/Ayuda@canchabot")


def test_una_orden_desconocida_va_al_analista(bot, monkeypatch):
    solo, _ = bot
    import cancha.telegrama as modulo

    monkeypatch.setattr(modulo, "_analista", lambda _b, t: f"analista dice: {t}")
    assert solo.responder("¿cómo llega el Girona?") == "analista dice: ¿cómo llega el Girona?"


def test_sin_ollama_lo_dice_en_vez_de_callarse(bot, monkeypatch):
    """Que no esté Ollama no puede dejar al bot mudo."""
    import cancha.analista as analista_modulo

    def sin_ollama(*_a, **_k):
        raise analista_modulo.OllamaNoDisponible("No hay nadie escuchando en 11434")

    monkeypatch.setattr(analista_modulo, "_pedir_http", sin_ollama)
    solo, _ = bot
    respuesta = solo.responder("una pregunta cualquiera")
    assert "No tengo analista" in respuesta
    assert "11434" in respuesta
    assert "/ayuda" in respuesta


def test_el_modelo_vacio_no_machaca_el_de_por_defecto(bot, monkeypatch):
    """Pasar modelo=None dejaba al analista sin modelo que pedirle."""
    import cancha.analista as analista_modulo

    pedidos = []

    def apuntar(ruta, cuerpo=None, **_k):
        pedidos.append((cuerpo or {}).get("model"))
        raise analista_modulo.OllamaNoDisponible("da igual")

    monkeypatch.setattr(analista_modulo, "_pedir_http", apuntar)
    solo, _ = bot
    assert solo.modelo == ""
    solo.responder("algo")
    assert pedidos and pedidos[0] == analista_modulo.MODELO_POR_DEFECTO


def test_un_fallo_contestando_no_tumba_el_bot(bot, monkeypatch):
    solo, falso = bot
    monkeypatch.setattr(Bot, "responder",
                        lambda *_a: (_ for _ in ()).throw(RuntimeError("se rompió")))
    respuesta = solo.atender(42, "/hoy")
    assert respuesta.startswith("✗ RuntimeError")
    assert falso.enviados, "el error también se manda, no se traga"


# ------------------------------------------------------------------ la tanda

def test_una_tanda_atiende_y_avanza_el_cursor(bot):
    solo, falso = bot
    falso.actualizaciones = [_mensaje(10, 42, "/memoria"), _mensaje(11, 42, "/ayuda")]
    atendidos = solo.una_tanda()
    assert [a["texto"] for a in atendidos] == ["/memoria", "/ayuda"]
    assert solo._desde == 12, "sin avanzar el cursor se contestaría lo mismo sin parar"
    assert solo.una_tanda() == []


def test_las_actualizaciones_sin_texto_se_saltan(bot):
    """Una foto o alguien entrando al grupo no son una pregunta."""
    solo, falso = bot
    falso.actualizaciones = [{"update_id": 5, "message": {"chat": {"id": 42}}},
                             {"update_id": 6}]
    assert solo.una_tanda() == []
    assert solo._desde == 7


def test_un_token_malo_se_explica(cliente, tmp_path):
    def roto(metodo, cuerpo=None):
        raise TelegramNoDisponible(
            "Telegram dice que el token no vale. Pídele uno a @BotFather")

    sesion = Sesion(cliente=cliente, ruta_almacen=str(tmp_path / "t3.db"))
    solo = Bot(token="malo", sesion=sesion, pedir=roto)
    try:
        with pytest.raises(TelegramNoDisponible, match="BotFather"):
            solo.comprobar()
    finally:
        sesion.close()


# ---------------------------------------------------------------- mensajes largos

def test_un_mensaje_largo_se_parte_porque_telegram_corta_en_4096():
    texto = "\n".join(f"línea {n}" for n in range(2000))
    trozos = _trozos(texto)
    assert len(trozos) > 1
    assert all(len(t) <= LIMITE for t in trozos)
    assert "".join(trozos) == texto, "partir no puede perder ni un carácter"


def test_una_linea_sola_mas_larga_que_el_tope_tambien_se_parte():
    trozos = _trozos("x" * 9000)
    assert all(len(t) <= LIMITE for t in trozos)
    assert "".join(trozos) == "x" * 9000


def test_lo_que_cabe_no_se_parte():
    assert _trozos("corto") == ["corto"]


def test_el_bot_parte_lo_que_envia(bot):
    solo, falso = bot
    solo.enviar(42, "y" * 9000)
    assert len(falso.enviados) == 3
    assert "".join(e["text"] for e in falso.enviados) == "y" * 9000


def test_el_bot_sabe_pronosticar(bot):
    """Es la orden que más se va a usar y la que más fácil se rompe en silencio."""
    solo, _ = bot
    respuesta = solo.responder("/pronostico Real Madrid vs Barcelona")
    assert respuesta.startswith("🔮")
    # Sin memoria de esa liga dice qué hacer, en vez de inventarse un marcador.
    assert "Abastece" in respuesta or "Goles esperados" in respuesta


def test_pronostico_sin_partido_pide_el_partido(bot):
    solo, _ = bot
    assert "Dime qué partido" in solo.responder("/pronostico")


def test_la_ayuda_menciona_el_pronostico(bot):
    solo, _ = bot
    assert "/pronostico" in solo.responder("/ayuda")


# ------------------------------------------------- averiguar el id de chat

def test_quien_escribe_sin_permiso_queda_apuntado(bot):
    """El identificador de chat es un número que nadie se sabe.

    El bot ya te lo contesta por Telegram, pero entonces hay que copiarlo a
    mano de una aplicación a otra. Apuntándolo, la pestaña Ajustes lo ofrece
    en un botón.
    """
    from cancha.telegrama import vistos

    solo, _ = bot
    solo.atender(4242, "hola", quien="Dani G")
    apuntados = vistos(solo.sesion.almacen)
    assert apuntados and apuntados[0]["chat"] == 4242
    assert apuntados[0]["quien"] == "Dani G"


def test_sin_lista_tambien_se_apunta(cliente, tmp_path):
    """Es justo el caso en el que hace falta: todavía no sabes tu número."""
    from cancha.telegrama import vistos

    falso = Falso()
    sesion = Sesion(cliente=cliente, ruta_almacen=str(tmp_path / "v.db"))
    solo = Bot(token="x", permitidos=(), sesion=sesion, pedir=falso)
    try:
        respuesta = solo.atender(777, "hola")
        assert "777" in respuesta
        assert "Ajustes" in respuesta, "tiene que decirte dónde ponerlo"
        assert [v["chat"] for v in vistos(sesion.almacen)] == [777]
    finally:
        sesion.close()


def test_el_mismo_chat_no_se_apunta_dos_veces(bot):
    from cancha.telegrama import vistos

    solo, _ = bot
    solo.atender(4242, "una", quien="Dani")
    solo.atender(4242, "otra", quien="Dani")
    assert len(vistos(solo.sesion.almacen)) == 1


def test_solo_se_recuerdan_unos_pocos(bot):
    from cancha.telegrama import RECORDAR_VISTOS, vistos

    solo, _ = bot
    for n in range(RECORDAR_VISTOS + 4):
        solo.atender(1000 + n, "hola")
    apuntados = vistos(solo.sesion.almacen)
    assert len(apuntados) == RECORDAR_VISTOS
    assert apuntados[0]["chat"] == 1000 + RECORDAR_VISTOS + 3, "el último, primero"


def test_a_un_permitido_no_se_le_apunta(bot):
    from cancha.telegrama import vistos

    solo, _ = bot
    solo.atender(42, "/memoria")
    assert vistos(solo.sesion.almacen) == []


def test_el_nombre_sale_del_mensaje(bot):
    solo, falso = bot
    falso.actualizaciones = [{
        "update_id": 1,
        "message": {"chat": {"id": 555}, "text": "hola",
                    "from": {"first_name": "Dani", "last_name": "G"}}}]
    atendidos = solo.una_tanda()
    assert atendidos[0]["quien"] == "Dani G"


def test_apuntar_no_puede_tumbar_una_respuesta(bot, monkeypatch):
    """Es una comodidad: si la memoria falla, el mensaje se contesta igual."""
    solo, _ = bot

    def roto(*_a, **_k):
        raise RuntimeError("la memoria no está")

    monkeypatch.setattr(type(solo.sesion.almacen), "anotar", roto)
    assert solo.atender(999, "hola") == "No tengo nada para ti."


def test_una_nota_corrupta_no_rompe_los_ajustes(bot):
    from cancha.telegrama import NOTA_VISTOS, vistos

    solo, _ = bot
    solo.sesion.almacen.anotar(NOTA_VISTOS, "{ esto no es json")
    assert vistos(solo.sesion.almacen) == []


# ------------------------------------------------ los ajustes, en caliente
# Esto nace de un fallo que llegó al usuario y que no era un error en pantalla
# sino un silencio: guardó el token en la pestaña Ajustes, le escribió al bot y
# no pasó nada. El hilo del bot no se creaba sin token, así que el token nuevo
# no se miraba hasta reiniciar, y nadie lo decía.

def test_sin_token_no_se_le_pregunta_nada_a_telegram(bot):
    """Antes esto ni se planteaba: sin token no había bucle."""
    solo, falso = bot
    solo.token = ""
    solo.escuchar(tandas=2, dormir=lambda _s: None)
    assert falso.llamadas == [], "no hay a quién preguntar sin token"


def test_el_token_que_aparece_en_los_ajustes_pone_el_bot_a_escuchar(bot):
    """El fallo entero, de una punta a la otra."""
    solo, falso = bot
    solo.token = ""
    guardados = [{"telegram": {"token": "", "chats": []}}]
    solo.releer = lambda: guardados[0]

    solo.escuchar(tandas=1, dormir=lambda _s: None)
    assert falso.llamadas == [], "todavía no hay token"

    guardados[0] = {"telegram": {"token": "123:ABC", "chats": [42]}}
    solo.escuchar(tandas=1, dormir=lambda _s: None)
    assert solo.token == "123:ABC"
    assert solo.permitidos == (42,)
    assert "getUpdates" in falso.llamadas, "ya tiene token: tiene que escuchar"


def test_al_coger_el_token_dice_quien_es_y_donde_escribirle(bot):
    solo, falso = bot
    solo.token = ""
    dicho: list[str] = []
    solo.releer = lambda: {"telegram": {"token": "123:ABC", "chats": []}}
    solo.escuchar(tandas=2, avisar=dicho.append, dormir=lambda _s: None)
    todo = "\n".join(dicho)
    assert "canchabot" in todo, "el enlace del bot es lo que hace falta para escribirle"
    assert "identificador de chat" in todo, "y qué hacer ahora: mandarle un mensaje"


def test_un_token_de_la_linea_de_comandos_no_lo_borran_los_ajustes(bot):
    """`cargar` devuelve los ajustes de fábrica —token vacío— si no hay fichero."""
    solo, falso = bot
    solo.token_fijo = True
    solo.releer = lambda: {"telegram": {"token": "", "chats": []}}
    solo.escuchar(tandas=1, dormir=lambda _s: None)
    assert solo.token == "x"
    assert "getUpdates" in falso.llamadas


def test_quitar_el_token_de_los_ajustes_calla_al_bot(bot):
    solo, falso = bot
    solo.releer = lambda: {"telegram": {"token": "", "chats": []}}
    solo.escuchar(tandas=1, dormir=lambda _s: None)
    assert solo.token == ""
    assert falso.llamadas == []


def test_los_chats_nuevos_valen_sin_reiniciar(bot):
    """El camino normal: el bot te dice tu id y lo pones desde el móvil."""
    solo, falso = bot
    solo.permitidos = ()
    solo.releer = lambda: {"telegram": {"token": "x", "chats": ["42"]}}
    assert solo.refrescar() == ["contesta a 42"]
    assert solo.permitidos == (42,), "los ajustes los guardan como texto a veces"
    assert solo.atender(42, "/memoria") != "No tengo nada para ti."


def test_el_modelo_y_la_clave_de_la_nube_tambien(bot):
    solo, _ = bot
    solo.releer = lambda: {"telegram": {"token": "x", "chats": [42]},
                           "modelo": "qwen3:32b", "ollama_api_key": "k"}
    solo.refrescar()
    assert solo.modelo == "qwen3:32b"
    assert solo.api_key == "k"


def test_unos_ajustes_ilegibles_no_paran_el_bot(bot):
    def revienta():
        raise OSError("el disco dice que no")

    solo, falso = bot
    solo.releer = revienta
    solo.escuchar(tandas=1, dormir=lambda _s: None)
    assert "getUpdates" in falso.llamadas, "sigue con lo que ya tenía"


def test_el_estado_se_puede_mirar_desde_la_interfaz(bot):
    solo, _ = bot
    assert solo.estado()["escuchando"] is False, "todavía no ha dado ni una vuelta"
    solo.escuchar(tandas=1, dormir=lambda _s: None)
    estado = solo.estado()
    assert estado == {"token_puesto": True, "escuchando": True,
                      "permitidos": [42], "ultimo_error": ""}


def test_sin_token_el_estado_lo_dice(bot):
    solo, _ = bot
    solo.token = ""
    solo.escuchar(tandas=1, dormir=lambda _s: None)
    assert solo.estado() == {"token_puesto": False, "escuchando": False,
                             "permitidos": [42], "ultimo_error": ""}


def test_el_mismo_fallo_no_se_repite_cada_diez_segundos(bot):
    def roto(metodo, cuerpo=None):
        raise TelegramNoDisponible("Telegram dice que el token no vale.")

    solo, _ = bot
    solo.pedir = roto
    dicho: list[str] = []
    solo.escuchar(tandas=4, avisar=dicho.append, dormir=lambda _s: None)
    errores = [x for x in dicho if x.startswith("✗")]
    assert len(errores) == 1, f"cuatro vueltas, un error, no cuatro: {dicho}"
    assert solo.estado()["ultimo_error"]


def test_dos_cancha_con_el_mismo_token_se_explica():
    """Telegram da 409 y el bot se queda mudo: es el otro «no funciona»."""
    import urllib.error

    from cancha.telegrama import _pedir_http

    def conflicto(*_a, **_k):
        raise urllib.error.HTTPError("u", 409, "Conflict", {}, None)

    import urllib.request
    original = urllib.request.urlopen
    urllib.request.urlopen = conflicto
    try:
        with pytest.raises(TelegramNoDisponible) as exc:
            _pedir_http("https://api.telegram.org/botx/getUpdates")
    finally:
        urllib.request.urlopen = original
    assert "otro programa escuchando" in str(exc.value)
    assert "Cierra el otro" in str(exc.value)


def test_parar_saca_al_bot_del_bucle(bot):
    solo, _ = bot
    solo.parar()
    assert solo.escuchar(dormir=lambda _s: None) == 1, "una vuelta y fuera"


def test_nada_tumba_el_hilo_del_bot(bot):
    """Morirse en segundo plano es quedarse mudo sin que nadie se entere."""
    solo, _ = bot
    vueltas = {"n": 0}

    def revienta(_metodo, _cuerpo=None):
        vueltas["n"] += 1
        raise RuntimeError("algo con lo que nadie contaba")

    solo.pedir = revienta
    dicho: list[str] = []
    assert solo.escuchar(tandas=3, avisar=dicho.append, dormir=lambda _s: None) == 3
    assert vueltas["n"] == 3, "sigue dando vueltas después del fallo"
    assert [x for x in dicho if "RuntimeError" in x], "y lo cuenta"


def test_lo_que_contesta_no_manda_reiniciar(cliente, tmp_path):
    """Ya no hace falta: los chats permitidos se cogen al vuelo."""
    falso = Falso()
    sesion = Sesion(cliente=cliente, ruta_almacen=str(tmp_path / "t9.db"))
    solo = Bot(token="x", permitidos=(), sesion=sesion, pedir=falso)
    try:
        respuesta = solo.atender(777, "hola")
    finally:
        sesion.close()
    assert "y reinicia cancha" not in respuesta
    assert "no hace falta reiniciar" in respuesta
    assert "777" in respuesta
