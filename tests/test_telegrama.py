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
    assert solo.responder("/Ayuda@canchabot").startswith("Lo que sé hacer")


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
