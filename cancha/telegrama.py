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

**El token y la lista se pueden cambiar sin reiniciar.** El bot mira los
ajustes en cada vuelta, así que ponerle el token desde la pestaña Ajustes
—desde el móvil, sin tocar el ordenador— hace que empiece a escuchar él solo
en veinticinco segundos. Arrancar sin token y no volver a mirar era peor que un
error: escribías al bot y no pasaba nada, sin una línea que lo explicara.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

from .errors import SofascoreError
from .sesion import Sesion
from .tls import SIN_MONTAR

API = "https://api.telegram.org"
#: Telegram corta los mensajes en 4096 caracteres. Se parte un poco antes para
#: dejar sitio al aviso de continuación.
LIMITE = 3900
#: Cuánto espera cada consulta antes de volver vacía. Cuanto más alto, menos
#: peticiones; veinticinco segundos es el equilibrio que recomienda Telegram.
ESPERA = 25
#: Cuánto se espera entre vuelta y vuelta cuando todavía no hay token. No se
#: le puede preguntar nada a Telegram sin token, pero sí mirar si ya lo hay.
ESPERA_SIN_TOKEN = 5
#: Cuántos remitentes sin permiso se recuerdan. Normalmente es uno —tú— pero
#: caben unos pocos por si te equivocas de cuenta.
RECORDAR_VISTOS = 5
#: Dónde quedan apuntados, en la memoria, para que los ajustes los ofrezcan.
NOTA_VISTOS = "telegram_vistos"



class TelegramNoDisponible(SofascoreError):
    """Telegram no contesta, o el token no vale."""


def _pedir_http(url: str, cuerpo: dict | None = None, timeout: float = 60.0,
                contexto: Any = None) -> Any:
    detalle = ""
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    peticion = urllib.request.Request(
        url, data=datos, method="POST" if datos is not None else "GET",
        headers={"Content-Type": "application/json"})
    try:
        respuesta = urllib.request.urlopen(  # noqa: S310
            peticion, timeout=timeout, context=contexto)
    except urllib.error.HTTPError as exc:
        with suppress(Exception):  # el cuerpo es un extra; puede no haberlo
            detalle = exc.read().decode("utf-8", "replace")[:300]
        if exc.code == 401:
            raise TelegramNoDisponible(
                "Telegram dice que el token no vale. Pídele uno a @BotFather en "
                "Telegram: /newbot, y te da algo como 123456:AA....") from exc
        if exc.code == 409:
            # Telegram solo deja un oyente por token. Da un 409 y el bot se
            # queda mudo sin más explicación, que es exactamente lo que parece
            # «no funciona»: casi siempre hay dos cancha abiertos.
            raise TelegramNoDisponible(
                "Hay otro programa escuchando con este mismo token, y Telegram "
                "solo deja uno. Cierra el otro cancha (o el otro `cancha "
                "telegram`) y este empezará a contestar.") from exc
        raise TelegramNoDisponible(f"Telegram ha contestado {exc.code}: {detalle}") from exc
    except OSError as exc:
        from .tls import es_de_certificado, explicar

        # El error de certificado se explica aquí porque es el sitio donde se
        # lee. «No llego a Telegram: [SSL: CERTIFICATE_VERIFY_FAILED]» no dice
        # nada de lo que de verdad pasa, que es que algo en medio está
        # abriendo tu HTTPS.
        if es_de_certificado(exc):
            raise TelegramNoDisponible(
                f"No llego a Telegram. {explicar('api.telegram.org')}") from exc
        raise TelegramNoDisponible(f"No llego a Telegram: {exc}") from exc
    with respuesta:
        return json.loads(respuesta.read().decode("utf-8"))


def _escapar(texto: str) -> str:
    """Lo que hay que hacerle a un nombre de equipo antes de meterlo en HTML.

    Telegram entiende un HTML pequeñito, y un «&» o un «<» sueltos le tumban el
    mensaje entero con un 400. Los nombres vienen de la API —«Brighton & Hove
    Albion»—, así que no son de fiar.
    """
    return (str(texto).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _sin_etiquetas(texto: str) -> str:
    """El mismo texto en plano, para cuando Telegram rechaza el HTML."""
    import re

    limpio = re.sub(r"</?(b|i|u|s|code|pre)>", "", texto)
    return (limpio.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&"))


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
    #: Clave de la nube de Ollama, si la hay. Vacía = el modelo de casa.
    api_key: str = ""
    carpeta_briefings: str = "datos/briefings"
    #: Devuelve los ajustes de ahora mismo. Se consulta en cada vuelta, y es
    #: lo que hace que poner el token desde el móvil valga para algo sin
    #: reiniciar nada. Ver ``refrescar``.
    releer: Callable[[], dict] | None = field(default=None, repr=False)
    #: Las competiciones que se siguen. Sin esto, «qué se juega hoy» traía el
    #: fútbol entero del planeta y «en directo» acababa en Perú sub-15.
    grupos: tuple[str, ...] = ()
    #: Certificados propios, para cuando algo abre tu HTTPS por el camino
    #: (antivirus, proxy de empresa, VPN). Ver :mod:`cancha.tls`.
    ca_bundle: str = ""
    #: No comprobar con quién se habla. Último recurso.
    sin_verificar: bool = False
    #: El token viene de la línea de comandos o del entorno, así que los
    #: ajustes no lo tocan. Sin esto, un ``--token`` se lo comería el primer
    #: ``releer`` que devolviese los ajustes de fábrica, que van vacíos.
    token_fijo: bool = False
    #: Cómo se habla con Telegram. Se sustituye para probar sin red.
    pedir: Callable[[str, dict | None], Any] = field(default=None, repr=False)
    _propia: bool = field(default=False, repr=False)
    _desde: int = field(default=0, repr=False)
    _parando: bool = field(default=False, repr=False)
    _callado: bool = field(default=False, repr=False)
    _ultimo_error: str = field(default="", repr=False)
    _escuchando: bool = field(default=False, repr=False)
    _contexto: Any = field(default=SIN_MONTAR, repr=False)

    def __post_init__(self) -> None:
        if self.pedir is None:
            self.pedir = lambda metodo, cuerpo=None: _pedir_http(
                f"{API}/bot{self.token}/{metodo}", cuerpo,
                timeout=ESPERA + 15 if metodo == "getUpdates" else 60,
                contexto=self._tls())
        if self.sesion is None:
            self.sesion = Sesion()
            self._propia = True

    # --- hablar ---

    def _tls(self):
        """El contexto TLS, montado una vez y rehecho si cambian los ajustes."""
        if self._contexto is SIN_MONTAR:
            from .tls import contexto

            self._contexto = contexto(self.ca_bundle, self.sin_verificar)
        return self._contexto

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

    def _presentarse(self) -> str:
        """Quién soy y dónde escribirme, en una línea. Para el token recién puesto."""
        try:
            quien = self.comprobar()
        except (TelegramNoDisponible, OSError) as exc:
            return f"token puesto, pero Telegram dice: {exc}"
        donde = f" · escríbele en {quien['enlace']}" if quien.get("enlace") else ""
        if not self.permitidos:
            return (f"«{quien['nombre']}» escuchando{donde}. Todavía no contesta a "
                    "nadie: escríbele y te dirá tu identificador de chat.")
        return f"«{quien['nombre']}» escuchando{donde}."

    def enviar(self, chat: int, texto: str) -> None:
        """Manda el texto, partido si hace falta, con negritas si las lleva.

        Solo se pide HTML cuando el texto trae etiquetas puestas por nosotros.
        Y si Telegram lo rechaza —un nombre raro, una etiqueta a medias—, se
        manda en plano en vez de perder el mensaje: el contenido importa más
        que las negritas.
        """
        con_formato = "<b>" in texto or "<i>" in texto
        for trozo in _trozos(texto):
            cuerpo = {"chat_id": chat, "text": trozo, "disable_web_page_preview": True}
            if con_formato:
                cuerpo["parse_mode"] = "HTML"
            try:
                self.pedir("sendMessage", cuerpo)
            except TelegramNoDisponible:
                if not con_formato:
                    raise
                self.pedir("sendMessage", {"chat_id": chat,
                                           "text": _sin_etiquetas(trozo),
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

    def escuchar(self, tandas: int = 0, avisar: Callable[[str], None] | None = None,
                 dormir: Callable[[float], None] = time.sleep) -> int:
        """Se queda escuchando. ``tandas`` limita cuántas vueltas da (0 = siempre).

        Cada vuelta empieza mirando los ajustes (``refrescar``), así que el bot
        se puede quedar aquí sin token —esperando a que lo pongas— y arrancar
        solo cuando aparezca. Eso es a propósito: la alternativa es no arrancar
        el hilo, y entonces poner el token no sirve de nada hasta reiniciar.
        """
        decir = avisar or (lambda _t: None)
        vueltas = 0
        try:
            while True:
                try:
                    self._una_vuelta(decir, dormir)
                except KeyboardInterrupt:
                    raise
                except Exception as exc:  # noqa: BLE001
                    # Nada tumba este hilo. Vive en segundo plano dentro de
                    # `cancha arrancar`, así que morirse aquí es quedarse mudo
                    # sin que nadie se entere: exactamente el fallo que
                    # estamos arreglando, pero por otro camino.
                    self._fallo(decir, f"{type(exc).__name__}: {exc}")
                    dormir(10)
                vueltas += 1
                if tandas and vueltas >= tandas:
                    break
                if self._parando:
                    break
        except KeyboardInterrupt:
            decir("Bot detenido.")
        return vueltas

    def _una_vuelta(self, decir: Callable[[str], None],
                    dormir: Callable[[float], None]) -> None:
        """Una vuelta del bucle: ponerse al día y atender lo que haya llegado."""
        for cambio in self.refrescar():
            decir(f"telegram: {cambio}")
        if not self.token:
            self._escuchando = False
            if not self._callado:
                decir("telegram: esperando un token. Ponlo en Ajustes y "
                      "empiezo a escuchar solo.")
                self._callado = True
            dormir(ESPERA_SIN_TOKEN)
            return
        if self._callado:
            self._callado = False
            decir("telegram: " + self._presentarse())
        self._escuchando = True
        try:
            for atendido in self.una_tanda():
                decir(f"[{atendido['chat']}] {atendido['texto'][:60]}")
        except TelegramNoDisponible as exc:
            self._fallo(decir, str(exc))
            dormir(10)
        else:
            self._ultimo_error = ""

    def _fallo(self, decir: Callable[[str], None], dicho: str) -> None:
        """Apunta un fallo y lo cuenta **una** vez.

        Un token caducado daría seis líneas por minuto y taparía todo lo demás
        en la consola; y el último fallo se queda guardado para poder verlo
        desde la pestaña Ajustes, que es donde se va a mirar.
        """
        self._escuchando = False
        if dicho != self._ultimo_error:
            decir(f"✗ ERROR Telegram: {dicho}")
            self._ultimo_error = dicho

    # --- entender ---

    def atender(self, chat: int, texto: str, quien: str = "") -> str:
        """Contesta a un mensaje. Devuelve lo enviado, para poder probarlo."""
        if not self.permitidos:
            self.apuntar_visto(chat, quien)
            respuesta = (
                "Este bot no tiene lista de permitidos, así que no contesta a nadie.\n\n"
                f"Tu identificador de chat es: {chat}\n\n"
                "Ponlo en la interfaz, en Memoria → Ajustes → «chats permitidos»: "
                "ahí sale con tu nombre al lado para meterlo de un toque, y no hace "
                "falta reiniciar nada. O arráncalo así:\n"
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

    def refrescar(self) -> list[str]:
        """Se pone al día con los ajustes. Devuelve qué ha cambiado, en palabras.

        Un bot que no hace esto obliga a reiniciar el programa para cambiar el
        token o la lista de permitidos, y eso —lo hemos visto— se parece
        demasiado a que el bot esté roto: escribes al bot, el bot no está
        escuchando porque arrancó sin token, y nadie te lo dice.

        Se consulta en cada vuelta del bucle, así que un cambio tarda como
        mucho una espera larga (veinticinco segundos) en notarse.
        """
        if self.releer is None:
            return []
        try:
            frescos = self.releer() or {}
        except Exception:  # noqa: BLE001 - unos ajustes ilegibles no paran el bot
            return []
        cambios = []
        suyo = frescos.get("telegram") or {}
        if not self.token_fijo:
            token = str(suyo.get("token") or "")
            if token != self.token:
                cambios.append("token puesto" if token else "token quitado; me callo")
                self.token = token
                # Un token nuevo se presenta en la vuelta siguiente (quién es el
                # bot y dónde escribirle); uno borrado, al contrario, dice que
                # se queda esperando. Las dos cosas las hace `escuchar`.
                self._callado = bool(token)
        permitidos = _numeros(suyo.get("chats") or ())
        if permitidos != self.permitidos:
            cambios.append("contesta a " + (", ".join(str(c) for c in permitidos)
                                            if permitidos else "nadie"))
            self.permitidos = permitidos
        modelo = str(frescos.get("modelo") or "")
        if modelo and modelo != self.modelo:
            cambios.append(f"modelo {modelo}")
            self.modelo = modelo
        clave = str(frescos.get("ollama_api_key") or "")
        if clave != self.api_key:
            cambios.append("clave de la nube puesta" if clave else "clave de la nube quitada")
            self.api_key = clave
        ligas = tuple(str(x).strip() for x in (frescos.get("ligas") or ()) if str(x).strip())
        if ligas != self.grupos:
            cambios.append("ligas: " + (", ".join(ligas) if ligas else "las de por defecto"))
            self.grupos = ligas
        red = frescos.get("red") or {}
        bundle = str(red.get("ca_bundle") or "")
        flojo = bool(red.get("sin_verificar"))
        if (bundle, flojo) != (self.ca_bundle, self.sin_verificar):
            cambios.append("certificados: " + (
                "sin comprobar con quién hablo (⚠)" if flojo
                else f"los de {bundle}" if bundle else "los del sistema"))
            self.ca_bundle, self.sin_verificar = bundle, flojo
            self._contexto = SIN_MONTAR  # se rehace en la petición siguiente
        return cambios

    def estado(self) -> dict:
        """Si de verdad está escuchando, para poder mirarlo desde la interfaz.

        Es la respuesta a «le escribo al bot y no hace nada»: en vez de tener
        que buscarlo en la consola del ordenador, se ve desde el móvil.
        """
        return {
            "token_puesto": bool(self.token),
            "escuchando": self._escuchando,
            "permitidos": list(self.permitidos),
            "ultimo_error": self._ultimo_error,
        }

    def parar(self) -> None:
        """Que salga del bucle en cuanto termine la vuelta que esté haciendo.

        No se deshace: un bot al que se le ha dicho que pare no vuelve a
        escuchar. Lo contrario —que ``escuchar`` lo rearmara— deja pasar sin
        ruido el caso de pararlo antes de arrancarlo, que es un bucle infinito.
        """
        self._parando = True

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


def _numeros(crudos) -> tuple[int, ...]:
    """Identificadores de chat, vengan como números o como texto."""
    salida = []
    for crudo in crudos or ():
        try:
            salida.append(int(str(crudo).strip()))
        except (TypeError, ValueError):
            continue
    return tuple(salida)


def vistos(almacen) -> list[dict]:
    """Quién ha escrito al bot sin estar en la lista de permitidos."""
    try:
        guardados = json.loads(almacen.nota(NOTA_VISTOS) or "[]")
    except (ValueError, TypeError):
        return []
    return [v for v in guardados if isinstance(v, dict) and v.get("chat")]


# ------------------------------------------------------------------ órdenes

def _ayuda(bot: Bot, _resto: str) -> str:
    ligas = ", ".join(bot.grupos) if bot.grupos else "las de por defecto"
    return (
        "<b>Lo que sé hacer</b>\n\n"
        "<b>El día</b>\n"
        "/hoy — qué se juega hoy, por competición\n"
        "/hoy laliga — una competición entera\n"
        "/hoy 2026-09-22 — otro día\n"
        "/manana — los de mañana\n"
        "/directo — lo que se juega ahora (/directo laliga)\n\n"
        "<b>Un partido</b>\n"
        "/pronostico Girona vs Osasuna — marcador, córners y tarjetas, calculados\n"
        "/previa Girona vs Osasuna — cómo llegan y dónde se hacen daño\n"
        "/dictamen Girona vs Osasuna — el expediente entero a un modelo\n"
        "/seguro — los patrones que se cumplen hoy, con su número\n\n"
        "<b>Quién es quién</b>\n"
        "/equipo Girona — cómo juega, comparado con su liga\n"
        "/jugador Vinicius — forma y rachas\n"
        "/memoria — qué hay guardado y cuándo fue la última guardia\n\n"
        f"<i>Sigo estas competiciones: {_escapar(ligas)}. Se cambian en la "
        "interfaz, en Ajustes.</i>\n"
        "<i>Cualquier otra cosa se la paso al analista, si lo tienes arrancado.</i>")


#: Cuántas competiciones se listan enteras antes de resumir. Un día normal son
#: veinticinco ligas y cien partidos: eso en el móvil no se lee, se scrollea.
LIGAS_ENTERAS = 6
#: Y cuántos partidos de cada una.
PARTIDOS_POR_LIGA = 8


def _hoy(bot: Bot, resto: str, dias: int = 0) -> str:
    """Qué se juega, en las ligas que sigues y a la hora de tu reloj.

    Antes volcaba las veinticinco competiciones del día una detrás de otra
    —cien partidos, con la hora en UTC y sin decirlo—. Ahora manda la fecha o el
    nombre de una liga: con liga, esa liga entera.
    """
    from datetime import datetime, timedelta

    fecha, liga = _fecha_y_liga(resto, dias)
    datos = _herramienta(bot, "agenda_del_dia", _con_grupos(bot, {"fecha": fecha}))
    por_liga = datos.get("por_competicion") or {}
    del datetime, timedelta
    if not por_liga:
        return (f"No hay partidos el {fecha} en las competiciones que sigues.\n"
                "Las eliges en Ajustes → Ligas que sigues.")
    if liga:
        elegidas = {k: v for k, v in por_liga.items() if _parecido(liga, k)}
        if not elegidas:
            return (f"No encuentro «{liga}» entre las {len(por_liga)} competiciones "
                    f"que juegan el {fecha}:\n" + "\n".join(f"  {k}" for k in por_liga))
        por_liga, enteras = elegidas, len(elegidas)
    else:
        enteras = LIGAS_ENTERAS
    zona = datos.get("zona") or "hora local"
    cabeza = [f"⚽ <b>{_escapar(fecha)}</b> · {datos.get('total', 0)} partidos en "
              f"{datos.get('competiciones', len(por_liga))} competiciones",
              f"<i>Horas en {_escapar(zona)}</i>", ""]
    cuerpo: list[str] = []
    # Por importancia, no por número de partidos: ordenar por cantidad abría con
    # diez de la MLS a las dos y media de la mañana y dejaba el Atlético - Real
    # Madrid en tercer lugar.
    from .ligas import relevancia

    ordenadas = sorted(por_liga.items(), key=lambda x: (relevancia(x[0]), x[0]))
    for lista in por_liga.values():
        lista.sort(key=lambda p: p.get("hora_utc") or "99:99")
    for nombre, lista in ordenadas[:enteras]:
        cuerpo.append(f"<b>{_escapar(nombre)}</b>")
        for partido in lista[:PARTIDOS_POR_LIGA]:
            hora = partido.get("hora") or partido.get("hora_utc") or " ?  "
            cuerpo.append(f"  {hora}  {_escapar(partido['partido'])}")
        if len(lista) > PARTIDOS_POR_LIGA:
            cuerpo.append(f"  <i>y {len(lista) - PARTIDOS_POR_LIGA} más</i>")
        cuerpo.append("")
    resto_ligas = ordenadas[enteras:]
    if resto_ligas:
        cuerpo.append("<b>También se juega en</b>")
        for nombre, lista in resto_ligas:
            cuerpo.append(f"  {_escapar(nombre)} ({len(lista)})")
        cuerpo.append("")
        cuerpo.append("<i>Para ver una entera: /hoy y el nombre "
                      "(/hoy laliga, /hoy champions).</i>")
    return "\n".join(cabeza + cuerpo).strip()


def _fecha_y_liga(resto: str, dias: int) -> tuple[str, str]:
    """Del texto de la orden a (fecha, liga). Acepta cualquiera de los dos."""
    from datetime import datetime, timedelta

    dicho = (resto or "").strip()
    fecha = ""
    if len(dicho) >= 10 and dicho[:4].isdigit() and dicho[4] == "-":
        fecha, dicho = dicho[:10], dicho[10:].strip()
    return (fecha or (datetime.now() + timedelta(days=dias)).strftime("%Y-%m-%d"), dicho)


def _parecido(buscado: str, nombre: str) -> bool:
    """¿Se refiere «premier» a «England Premier League»? Sin acentos ni mayúsculas."""
    from .resolve import normalizar

    return normalizar(buscado) in normalizar(nombre)


def _con_grupos(bot: Bot, argumentos: dict) -> dict:
    """Añade las ligas que sigue el bot, si las sigue."""
    if bot.grupos:
        argumentos["grupos"] = ",".join(bot.grupos)
    return argumentos


def _manana(bot: Bot, resto: str) -> str:
    return _hoy(bot, resto, dias=1)


#: Cuántos partidos en directo se enseñan de una vez.
EN_DIRECTO = 15


def _directo(bot: Bot, resto: str) -> str:
    """Lo que se está jugando **en tus competiciones**.

    Sin filtrar, el directo trae el fútbol entero del planeta: en una consulta
    real salieron Perú sub-15, juveniles gallegos y la segunda femenina alemana
    mezclados con LaLiga. Aquí se pide con las ligas que se siguen.
    """
    argumentos = {"limite": 60, "grupos": ",".join(bot.grupos) if bot.grupos else "*"}
    if resto.strip():
        argumentos["liga"] = resto.strip()
    datos = _herramienta(bot, "partidos", argumentos)
    partidos = datos.get("partidos") or []
    if not partidos:
        de_todo = datos.get("de_todo_el_mundo") or 0
        if de_todo:
            return (f"En tus competiciones no se juega nada ahora mismo.\n"
                    f"(Hay {de_todo} partidos en el mundo, pero son de ligas que no "
                    "sigues. Se eligen en Ajustes → Ligas que sigues.)")
        return "Ahora mismo no se juega nada."
    por_liga: dict[str, list] = {}
    for partido in partidos:
        por_liga.setdefault(partido.get("competicion") or "?", []).append(partido)
    lineas = [f"🔴 <b>En juego</b> · {len(partidos)} partidos", ""]
    enseñados = 0
    for liga in sorted(por_liga):
        if enseñados >= EN_DIRECTO:
            break
        lineas.append(f"<b>{_escapar(liga)}</b>")
        for partido in por_liga[liga]:
            if enseñados >= EN_DIRECTO:
                break
            estado = partido.get("estado") or ""
            lineas.append(f"  {_escapar(partido['partido'])}"
                          + (f"  <i>{_escapar(estado)}</i>" if estado else ""))
            enseñados += 1
        lineas.append("")
    if len(partidos) > enseñados:
        lineas.append(f"<i>y {len(partidos) - enseñados} más. Para una liga: "
                      "/directo laliga</i>")
    return "\n".join(lineas).strip()


#: Partidos que se enseñan de cada patrón: los que más se separan del mercado.
POR_PATRON = 5


def _seguro(bot: Bot, resto: str) -> str:
    """Los patrones que se cumplen hoy, uno por patrón.

    Antes salía una ficha por partido, y como un patrón se mide una sola vez
    sobre todo el historial, eran sesenta fichas con la misma frecuencia, los
    mismos casos y el mismo suelo. Lo único que cambiaba era el equipo.
    """
    from .seguro import avisos

    datos = avisos(bot.sesion.almacen, bot.sesion.cliente, fecha=resto or None,
                   grupos=list(bot.grupos) or None)
    if not datos["avisos"]:
        return ("Hoy no se cumple nada que aguante el recuento.\n"
                f"Calibrado con {datos['calibrado_con']} partidos guardados. "
                "Cuantos más barras, más cosas pueden salir aquí.")
    lineas = [f"🎯 <b>Casi seguro</b> · {_escapar(datos['fecha'])}",
              f"<i>Calibrado con {datos['calibrado_con']} partidos de tu memoria</i>", ""]
    for grupo in datos.get("por_patron") or []:
        fuera = (grupo.get("fuera_de_muestra") or {}).get("veredicto") or ""
        marca = {"aguanta": " · aguanta fuera de muestra",
                 "se cae": " · ⚠ SE CAE fuera de muestra"}.get(fuera, "")
        lineas.append(f"<b>{grupo['suelo']:.0%}  {_escapar(grupo['titulo'])}</b>")
        lineas.append(f"      {_escapar(grupo['dice'])}")
        lineas.append(f"      {grupo['frecuencia']:.0%} en {grupo['casos']} casos"
                      f" ({grupo['elevacion']:+.0%} sobre su referencia){marca}")
        lineas.append(f"      <i>Se cumple en {grupo['cuantos_partidos']} partidos "
                      "de hoy; estos son los que más se separan del precio:</i>")
        for partido in grupo["partidos"][:POR_PATRON]:
            hora = partido.get("hora") or partido.get("hora_utc") or ""
            quien = partido["sujeto"] if partido["sujeto"] != "el partido" else ""
            precio = ("sin cuotas" if partido["mercado"] is None else
                      f"mercado {partido['mercado']:.0%} ({partido['mercado_de']}), "
                      f"{partido['diferencia']:+.0%}")
            lineas.append(f"      {hora} {_escapar(partido['partido'])}")
            lineas.append(f"           {_escapar(quien)} · {precio}" if quien
                          else f"           {precio}")
        lineas.append("")
    lineas.append("<i>Ninguna de estas es una apuesta segura: son frecuencias "
                  "contadas sobre tu memoria. La frecuencia y el suelo son del "
                  "patrón —los mismos en todos sus partidos—; lo que cambia es el "
                  "precio de hoy.</i>")
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


def _dictamen(bot: Bot, resto: str) -> str:
    """El expediente entero a un modelo, y su lectura. Lo más caro que hace."""
    if not resto:
        return "Dime qué partido: /dictamen Girona vs Osasuna"
    from .analista import Analista, OllamaNoDisponible
    from .expediente import a_texto, expediente

    datos = expediente(bot.sesion.almacen, resto, cliente=bot.sesion.cliente)
    if not datos.get("disponible"):
        return datos.get("nota", "No hay expediente de ese partido.")
    extra = {"modelo": bot.modelo} if bot.modelo else {}
    if bot.api_key:
        extra["api_key"] = bot.api_key
    try:
        salida = Analista(sesion=bot.sesion, **extra).dictaminar(a_texto(datos))
    except (OllamaNoDisponible, OSError) as exc:
        return f"No he podido pedir el dictamen: {exc}"
    cabeza = (f"🧠 {datos['partido']['local']} - {datos['partido']['visitante']}\n"
              f"({salida['modelo']}, {datos['tamano']['tokens_aprox']} tokens de "
              "expediente)\n\n")
    return cabeza + (salida["respuesta"] or "El modelo no ha dicho nada.")


def _equipo(bot: Bot, resto: str) -> str:
    if not resto:
        return "Dime qué equipo: /equipo Girona"
    datos = _herramienta(bot, "estilo_de_equipo", {"equipo": resto})
    if not datos.get("disponible"):
        return datos.get("nota") or "No tengo nada de ese equipo guardado."
    r = datos["resultados"]
    cuantos = datos["partidos_mirados"]
    lineas = [f"<b>{_escapar(datos['equipo'])}</b> — {_escapar(datos['liga'] or '')}",
              f"{cuantos} partido{'s' if cuantos != 1 else ''} guardado"
              f"{'s' if cuantos != 1 else ''}: {r['racha']}, "
              f"{r['goles_favor']}-{r['goles_contra']} en goles", ""]
    rasgos = datos.get("lo_que_le_distingue") or []
    for rasgo in rasgos:
        lineas.append(f"  · {_escapar(rasgo['rasgo'])} "
                      f"({rasgo['diferencia']:+.0%} sobre su liga)")
    if rasgos:
        lineas.append("")
        lineas.append(f"<i>Medido sobre {cuantos} partidos suyos contra la media de "
                      f"{datos.get('partidos_en_la_media_de_liga', 0)} de su liga.</i>")
    elif datos.get("aviso"):
        # Y esto es lo importante: con un partido no se dice cómo juega nadie.
        # Antes salía «genera peligro (+187%)» de un 2-0 y parecía un retrato.
        lineas.append(f"<i>{_escapar(datos['aviso'])}</i>")
    else:
        lineas.append("No se sale de la media de su liga en nada llamativo.")
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
    if bot.api_key:
        extra["api_key"] = bot.api_key
    try:
        salida = Analista(sesion=bot.sesion, **extra).preguntar(texto)
    except (OllamaNoDisponible, OSError) as exc:
        return _sin_analista(bot, exc)
    return salida.get("respuesta") or "El modelo no ha dicho nada."


def _sin_analista(bot: Bot, exc: Exception) -> str:
    """Por qué no hay analista, y qué escribir para tenerlo.

    El caso que salió en cuanto se usó: «Ollama ha contestado 404: model
    'hermes3' not found». Ollama estaba arrancado y el modelo sin descargar, y
    lo que hacía falta era una línea que decir en el terminal.
    """
    dicho = str(exc)
    if "not found" in dicho and bot.modelo:
        return (f"Ollama está funcionando, pero no tiene el modelo «{bot.modelo}».\n\n"
                f"En el ordenador:\n    ollama pull {bot.modelo}\n\n"
                "Tarda un rato (unos 5 GB) y luego esto ya va. O elige otro en "
                "Ajustes → Analista, que ahí salen los que sí tienes.\n\n"
                "Mientras, las órdenes funcionan igual: /ayuda las lista.")
    return (f"No tengo analista: {dicho}\n\n"
            "Las órdenes no lo necesitan: /ayuda las lista.")


ORDENES: dict[str, Callable[[Bot, str], str]] = {
    "ayuda": _ayuda, "start": _ayuda, "help": _ayuda,
    "hoy": _hoy, "manana": _manana, "mañana": _manana,
    "directo": _directo, "live": _directo,
    "seguro": _seguro, "previa": _previa, "pronostico": _pronostico,
    "dictamen": _dictamen,
    "pronóstico": _pronostico,
    "equipo": _equipo, "jugador": _jugador, "memoria": _memoria,
}


def _herramienta(bot: Bot, nombre: str, argumentos: dict) -> dict:
    from .herramientas import ejecutar

    return ejecutar(nombre, argumentos, sesion=bot.sesion, max_chars=200_000)


__all__ = ["API", "NOTA_VISTOS", "ORDENES", "Bot", "TelegramNoDisponible",
           "vistos"]
