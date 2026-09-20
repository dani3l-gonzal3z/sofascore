"""Un bot de Telegram: preguntarle desde la calle, con el ordenador en casa.

El QR resuelve el móvil en la misma wifi. Esto resuelve el resto: el ordenador
se queda encendido en casa haciendo el trabajo, y tú preguntas desde donde
estés sin abrir un puerto ni contratar nada. Telegram hace de puente, y el
puente lo abre tu ordenador hacia fuera —no hay nada que apuntar a tu casa.

Sin dependencias: la API de Telegram es HTTP con JSON y ``urllib`` sobra. Se
usa *long polling*, que es pedirle a Telegram «avísame cuando haya algo» y
quedarse esperando hasta veinticinco segundos. Ni webhooks ni IP pública.

**Quién puede hablarle.** Un bot es público: cualquiera que dé con su nombre
puede escribirle. Por eso hace falta una lista de chats permitidos y, si no la
hay, el bot **no contesta nada**: responde a quien escriba diciéndole su
identificador de chat para que lo pongas en la lista, y ahí se queda. Un bot
sin lista que conteste a cualquiera es un agujero por el que se ve tu memoria
entera.

    cancha telegram --token 123:ABC --chat 987654321
    cancha telegram --token 123:ABC            # dice quién te escribe y no contesta
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .errors import SofascoreError
from .sesion import Sesion

API = "https://api.telegram.org"
#: Telegram corta los mensajes en 4096 caracteres. Se parte un poco antes para
#: dejar sitio al aviso de continuación.
LIMITE = 3900
#: Cuánto espera cada consulta antes de volver vacía. Cuanto más alto, menos
#: peticiones; veinticinco segundos es el equilibrio que recomienda Telegram.
ESPERA = 25
#: Cuántos remitentes sin permiso se recuerdan. Normalmente es uno —tú— pero
#: caben unos pocos por si te equivocas de cuenta.
RECORDAR_VISTOS = 5
#: Dónde quedan apuntados, en la memoria, para que los ajustes los ofrezcan.
NOTA_VISTOS = "telegram_vistos"


class TelegramNoDisponible(SofascoreError):
    """Telegram no contesta, o el token no vale."""


def _pedir_http(url: str, cuerpo: dict | None = None, timeout: float = 60.0) -> Any:
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    peticion = urllib.request.Request(
        url, data=datos, method="POST" if datos is not None else "GET",
        headers={"Content-Type": "application/json"})
    try:
        respuesta = urllib.request.urlopen(peticion, timeout=timeout)  # noqa: S310
    except urllib.error.HTTPError as exc:
        detalle = exc.read().decode("utf-8", "replace")[:300]
        if exc.code == 401:
            raise TelegramNoDisponible(
                "Telegram dice que el token no vale. Pídele uno a @BotFather en "
                "Telegram: /newbot, y te da algo como 123456:AA....") from exc
        raise TelegramNoDisponible(f"Telegram ha contestado {exc.code}: {detalle}") from exc
    except OSError as exc:
        raise TelegramNoDisponible(f"No llego a Telegram: {exc}") from exc
    with respuesta:
        return json.loads(respuesta.read().decode("utf-8"))


def _trozos(texto: str, limite: int = LIMITE) -> list[str]:
    """Parte un texto largo por saltos de línea, sin cortar palabras a lo bruto."""
    if len(texto) <= limite:
        return [texto]
    salida, actual = [], ""
    for linea in texto.splitlines(keepends=True):
        while len(linea) > limite:            # una línea sola más larga que el tope
            salida.append(linea[:limite])
            linea = linea[limite:]
        if len(actual) + len(linea) > limite:
            salida.append(actual)
            actual = linea
        else:
            actual += linea
    if actual:
        salida.append(actual)
    return salida


@dataclass
class Bot:
    """El bot: escucha, entiende cuatro órdenes y contesta con datos."""

    token: str = ""
    #: Quién puede hablarle. Vacío significa que no contesta a nadie.
    permitidos: tuple[int, ...] = ()
    sesion: Sesion | None = None
    modelo: str = ""
    carpeta_briefings: str = "datos/briefings"
    #: Cómo se habla con Telegram. Se sustituye para probar sin red.
    pedir: Callable[[str, dict | None], Any] = field(default=None, repr=False)
    _propia: bool = field(default=False, repr=False)
    _desde: int = field(default=0, repr=False)

    def __post_init__(self) -> None:
        if self.pedir is None:
            self.pedir = lambda metodo, cuerpo=None: _pedir_http(
                f"{API}/bot{self.token}/{metodo}", cuerpo,
                timeout=ESPERA + 15 if metodo == "getUpdates" else 60)
        if self.sesion is None:
            self.sesion = Sesion()
            self._propia = True

    # --- hablar ---

    def comprobar(self) -> dict:
        """Quién soy, según Telegram. Lo primero que hay que poder responder."""
        datos = self.pedir("getMe", None)
        if not datos.get("ok"):
            raise TelegramNoDisponible(f"Telegram dice: {datos}")
        yo = datos["result"]
        return {"disponible": True, "nombre": yo.get("first_name"),
                "usuario": yo.get("username"),
                "enlace": f"https://t.me/{yo.get('username')}" if yo.get("username") else None,
                "permitidos": list(self.permitidos)}

    def enviar(self, chat: int, texto: str) -> None:
        for trozo in _trozos(texto):
            self.pedir("sendMessage", {"chat_id": chat, "text": trozo,
                                       "disable_web_page_preview": True})

    # --- escuchar ---

    def una_tanda(self) -> list[dict]:
        """Pide los mensajes nuevos y los contesta. Devuelve lo que ha atendido."""
        datos = self.pedir("getUpdates", {"offset": self._desde, "timeout": ESPERA})
        if not datos.get("ok"):
            raise TelegramNoDisponible(f"Telegram dice: {datos}")
        atendidos = []
        for actualizacion in datos.get("result") or []:
            self._desde = max(self._desde, actualizacion.get("update_id", 0) + 1)
            mensaje = actualizacion.get("message") or actualizacion.get("edited_message")
            if not mensaje:
                continue
            datos_chat = mensaje.get("chat") or {}
            chat = datos_chat.get("id")
            texto = (mensaje.get("text") or "").strip()
            if chat is None or not texto:
                continue
            quien = " ".join(x for x in (
                (mensaje.get("from") or {}).get("first_name"),
                (mensaje.get("from") or {}).get("last_name"),
            ) if x) or datos_chat.get("title") or ""
            atendidos.append({"chat": chat, "texto": texto, "quien": quien})
            self.atender(chat, texto, quien)
        return atendidos

    def escuchar(self, tandas: int = 0, avisar: Callable[[str], None] | None = None) -> int:
        """Se queda escuchando. ``tandas`` limita cuántas vueltas da (0 = siempre)."""
        decir = avisar or (lambda _t: None)
        vueltas = 0
        try:
            while True:
                try:
                    for atendido in self.una_tanda():
                        decir(f"[{atendido['chat']}] {atendido['texto'][:60]}")
                except TelegramNoDisponible as exc:
                    decir(f"✗ ERROR Telegram: {exc}")
                    import time

                    time.sleep(10)
                vueltas += 1
                if tandas and vueltas >= tandas:
                    break
        except KeyboardInterrupt:
            decir("Bot detenido.")
        return vueltas

    # --- entender ---

    def atender(self, chat: int, texto: str, quien: str = "") -> str:
        """Contesta a un mensaje. Devuelve lo enviado, para poder probarlo."""
        if not self.permitidos:
            self.apuntar_visto(chat, quien)
            respuesta = (
                "Este bot no tiene lista de permitidos, así que no contesta a nadie.\n\n"
                f"Tu identificador de chat es: {chat}\n\n"
                "Ponlo en la interfaz, en Memoria → Ajustes → «chats permitidos», "
                "y reinicia cancha. O arráncalo así:\n"
                f"    cancha telegram --token ... --chat {chat}")
            self.enviar(chat, respuesta)
            return respuesta
        if chat not in self.permitidos:
            # A un desconocido no se le cuenta nada, ni siquiera qué es esto.
            # Pero se apunta, porque casi siempre eres tú desde otra cuenta.
            self.apuntar_visto(chat, quien)
            self.enviar(chat, "No tengo nada para ti.")
            return "No tengo nada para ti."

        try:
            respuesta = self.responder(texto)
        except SofascoreError as exc:
            respuesta = f"✗ {exc}"
        except Exception as exc:  # noqa: BLE001 - el bot no se cae por una pregunta
            respuesta = f"✗ {type(exc).__name__}: {exc}"
        self.enviar(chat, respuesta)
        return respuesta

    def responder(self, texto: str) -> str:
        """De un mensaje a una respuesta en texto. Aquí no se habla con Telegram."""
        orden, _, resto = texto.partition(" ")
        orden = orden.lower().lstrip("/").split("@")[0]
        resto = resto.strip()
        manejador = ORDENES.get(orden)
        if manejador:
            return manejador(self, resto)
        # Sin orden reconocida, es una pregunta para el analista.
        return _analista(self, texto)

    def apuntar_visto(self, chat: int, quien: str = "") -> None:
        """Deja constancia de quién ha escrito sin estar en la lista.

        Es lo que convierte «pon tu identificador de chat» —un número que nadie
        se sabe— en un botón en los ajustes. El bot ya te lo contesta por
        Telegram, pero entonces tienes que copiarlo a mano de una aplicación a
        otra; así aparece solo en la pestaña Ajustes.

        Si la memoria no está o falla, no pasa nada: esto es una comodidad, no
        puede tumbar la respuesta a un mensaje.
        """
        try:
            almacen = self.sesion.almacen
            vistos = [v for v in json.loads(almacen.nota(NOTA_VISTOS) or "[]")
                      if isinstance(v, dict) and v.get("chat") != chat]
            vistos.insert(0, {"chat": chat, "quien": quien})
            almacen.anotar(NOTA_VISTOS,
                           json.dumps(vistos[:RECORDAR_VISTOS], ensure_ascii=False))
        except Exception:  # noqa: BLE001 - una comodidad no tumba una respuesta
            pass

    def close(self) -> None:
        if self._propia and self.sesion:
            self.sesion.close()


def vistos(almacen) -> list[dict]:
    """Quién ha escrito al bot sin estar en la lista de permitidos."""
    try:
        guardados = json.loads(almacen.nota(NOTA_VISTOS) or "[]")
    except (ValueError, TypeError):
        return []
    return [v for v in guardados if isinstance(v, dict) and v.get("chat")]


# ------------------------------------------------------------------ órdenes

def _ayuda(bot: Bot, _resto: str) -> str:
    return (
        "Lo que sé hacer:\n\n"
        "/hoy — los partidos de hoy\n"
        "/manana — los de mañana\n"
        "/seguro — lo que casi siempre pasa, de hoy\n"
        "/previa <equipos> — la previa de un partido\n"
        "/pronostico <equipos> — marcador, córners y tarjetas, calculados\n"
        "/equipo <nombre> — cómo juega, comparado con su liga\n"
        "/jugador <nombre> — forma y rachas\n"
        "/memoria — qué hay guardado y cuándo fue la última guardia\n"
        "/directo — lo que se está jugando ahora\n\n"
        "Y cualquier otra cosa se la paso al analista local, si lo tienes "
        "arrancado.")


def _hoy(bot: Bot, resto: str, dias: int = 0) -> str:
    from datetime import datetime, timedelta

    fecha = resto or (datetime.now() + timedelta(days=dias)).strftime("%Y-%m-%d")
    datos = _herramienta(bot, "agenda_del_dia", {"fecha": fecha})
    por_liga = datos.get("por_competicion") or {}
    if not por_liga:
        return f"No hay partidos el {fecha} en las competiciones que sigues."
    lineas = [f"⚽ {fecha}", ""]
    for liga in sorted(por_liga):
        lineas.append(liga)
        for partido in por_liga[liga]:
            lineas.append(f"  {partido.get('hora_utc') or '  ?  '}  {partido['partido']}")
        lineas.append("")
    return "\n".join(lineas).strip()


def _manana(bot: Bot, resto: str) -> str:
    return _hoy(bot, resto, dias=1)


def _directo(bot: Bot, _resto: str) -> str:
    datos = _herramienta(bot, "partidos", {"limite": 40})
    partidos = datos.get("partidos") or []
    if not partidos:
        return "Ahora mismo no se juega nada."
    lineas = ["🔴 En juego", ""]
    for partido in partidos:
        lineas.append(f"  {partido['partido']}  ({partido.get('estado') or ''})")
    return "\n".join(lineas)


def _seguro(bot: Bot, resto: str) -> str:
    from .seguro import avisos

    datos = avisos(bot.sesion.almacen, bot.sesion.cliente, fecha=resto or None)
    if not datos["avisos"]:
        return ("Hoy no se cumple nada que aguante el recuento.\n"
                f"Calibrado con {datos['calibrado_con']} partidos guardados.")
    lineas = [f"🎯 Casi seguro · {datos['fecha']}", ""]
    for aviso in datos["avisos"][:12]:
        fuera = (aviso.get("fuera_de_muestra") or {}).get("veredicto") or ""
        marca = {"aguanta": " · aguanta después", "se cae": " · ⚠ SE CAE después"}.get(fuera, "")
        lineas.append(f"{aviso['suelo']:.0%}  {aviso['partido']}")
        lineas.append(f"      {aviso['sujeto']}: {aviso['dice']}")
        lineas.append(f"      {aviso['frecuencia']:.0%} en {aviso['casos']} casos"
                      f" ({aviso['elevacion']:+.0%} sobre su referencia){marca}")
        lineas.append("")
    lineas.append("Ninguna de estas es una apuesta segura: son frecuencias contadas.")
    return "\n".join(lineas)


def _previa(bot: Bot, resto: str) -> str:
    if not resto:
        return "Dime qué partido: /previa Girona vs Osasuna"
    from .previa import previa, texto

    datos = previa(bot.sesion.almacen, resto, cliente=bot.sesion.cliente)
    return "\n".join(texto(datos))


def _pronostico(bot: Bot, resto: str) -> str:
    if not resto:
        return "Dime qué partido: /pronostico Girona vs Osasuna"
    from .pronostico import pronostico
    from .pronostico import texto as texto_pronostico

    datos = pronostico(bot.sesion.almacen, resto, cliente=bot.sesion.cliente)
    return "🔮 " + "\n".join(texto_pronostico(datos, ancho=48))


def _equipo(bot: Bot, resto: str) -> str:
    if not resto:
        return "Dime qué equipo: /equipo Girona"
    datos = _herramienta(bot, "estilo_de_equipo", {"equipo": resto})
    if not datos.get("disponible"):
        return datos.get("nota") or "No tengo nada de ese equipo guardado."
    r = datos["resultados"]
    lineas = [f"{datos['equipo']} — {datos['liga']}",
              f"{datos['partidos_mirados']} partidos: {r['racha']}, "
              f"{r['goles_favor']}-{r['goles_contra']}", ""]
    for rasgo in datos.get("lo_que_le_distingue") or []:
        lineas.append(f"  · {rasgo['rasgo']} ({rasgo['cuanto']})")
    if not datos.get("lo_que_le_distingue"):
        lineas.append("  No se sale de la media de su liga en nada llamativo.")
    return "\n".join(lineas)


def _jugador(bot: Bot, resto: str) -> str:
    if not resto:
        return "Dime qué jugador: /jugador Vinicius"
    datos = _herramienta(bot, "forma_de_jugador", {"jugador": resto})
    if not datos.get("disponible"):
        return datos.get("nota") or "No tengo nada de ese jugador guardado."
    pp = datos.get("por_partido") or {}
    lineas = [f"{datos['jugador']}",
              f"{datos['partidos_mirados']} partidos · nota {datos.get('rating_medio')}",
              f"Por partido: {pp.get('goles')} goles, {pp.get('tiros')} tiros, "
              f"{pp.get('xg')} xG", ""]
    for racha in datos.get("rachas") or []:
        lineas.append(f"  · {racha['racha']}")
    return "\n".join(lineas)


def _memoria(bot: Bot, _resto: str) -> str:
    datos = bot.sesion.almacen.resumen()
    lineas = [
        f"📚 {datos['partidos']} partidos ({datos['con_estadisticas']} con estadísticas)",
        f"Del {datos['desde']} al {datos['hasta']}",
        f"{datos['actuaciones']} actuaciones · {datos['tiros']} tiros",
        f"Último barrido: {datos['ultimo_barrido'] or 'nunca'}",
    ]
    guardia = bot.sesion.almacen.nota("ultima_guardia")
    if guardia:
        lineas.append(f"Última guardia: {guardia} "
                      f"(preparó el {bot.sesion.almacen.nota('ultima_guardia_fecha')})")
    return "\n".join(lineas)


def _analista(bot: Bot, texto: str) -> str:
    """Lo que no es una orden se lo pasamos al modelo local, si lo hay."""
    from .analista import Analista, OllamaNoDisponible

    # Solo se pasa `modelo` si hay uno: mandar None machacaría el de por
    # defecto del dataclass y el analista se quedaría sin modelo que pedir.
    extra = {"modelo": bot.modelo} if bot.modelo else {}
    try:
        salida = Analista(sesion=bot.sesion, **extra).preguntar(texto)
    except (OllamaNoDisponible, OSError) as exc:
        return (f"No tengo analista: {exc}\n\n"
                "Prueba con una orden concreta. /ayuda las lista.")
    return salida.get("respuesta") or "El modelo no ha dicho nada."


ORDENES: dict[str, Callable[[Bot, str], str]] = {
    "ayuda": _ayuda, "start": _ayuda, "help": _ayuda,
    "hoy": _hoy, "manana": _manana, "mañana": _manana,
    "directo": _directo, "live": _directo,
    "seguro": _seguro, "previa": _previa, "pronostico": _pronostico,
    "pronóstico": _pronostico,
    "equipo": _equipo, "jugador": _jugador, "memoria": _memoria,
}


def _herramienta(bot: Bot, nombre: str, argumentos: dict) -> dict:
    from .herramientas import ejecutar

    return ejecutar(nombre, argumentos, sesion=bot.sesion, max_chars=200_000)


__all__ = ["API", "NOTA_VISTOS", "ORDENES", "Bot", "TelegramNoDisponible",
           "vistos"]
