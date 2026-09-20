"""Dejarlo funcionando: el arranque de cada día, la guardia y el bot.

Tres comandos que van juntos:

* ``cancha arrancar`` — lo que abres por la mañana o dejas por la noche. Mira
  que todo esté en su sitio, levanta la interfaz, la guardia y el bot, y te
  dice por dónde entrar. Es un solo proceso: se cierra con Ctrl+C y se lleva
  todo por delante.
* ``cancha guardia`` — solo la guardia nocturna, para quien la quiera aparte o
  en el programador de tareas de Windows.
* ``cancha telegram`` — solo el bot.

Lo que más cuidado lleva aquí no es el código, son los mensajes de error: esto
es lo que arranca alguien a las once de la noche, y si algo falla tiene que
poder leerse de un vistazo y decir qué hacer, no volcar una traza.
"""

from __future__ import annotations

import argparse
import json
import os
import threading

from .. import ajustes as modulo_ajustes
from . import comun
from .comun import envolver, imprimir


def _ajustes(args: argparse.Namespace) -> dict:
    """Los ajustes guardados, avisando si el fichero está roto."""
    cargados = modulo_ajustes.cargar(getattr(args, "ajustes", None))
    if cargados.get("_error"):
        _problema(cargados["_error"], "Bórralo o arréglalo y vuelve a arrancar.")
    for problema in modulo_ajustes.revisar(cargados):
        imprimir(f"  ⚠ {problema}")
    return cargados


def _ligas(args: argparse.Namespace, guardados: dict) -> list[str] | None:
    """Las ligas: las de la línea de comandos si las hay, si no las guardadas."""
    if getattr(args, "grupos", None):
        return args.grupos.split(",")
    return modulo_ajustes.grupos_de(guardados)


#: Variables de entorno, para no tener que escribir el token cada vez.
ENV_TOKEN = "CANCHA_TELEGRAM_TOKEN"
ENV_CHAT = "CANCHA_TELEGRAM_CHAT"


def _problema(titulo: str, *consejos: str) -> None:
    """Un error tal como se quiere leer a las once de la noche: qué pasa y qué hacer."""
    imprimir("")
    imprimir(f"  ✗ {titulo}")
    for consejo in consejos:
        for numero, linea in enumerate(envolver(consejo, 70)):
            imprimir(("    → " if numero == 0 else "      ") + linea)
    imprimir("")


def _chats(args: argparse.Namespace, guardados: dict | None = None) -> tuple[int, ...]:
    crudo = (args.chat or os.environ.get(ENV_CHAT, "")
             or ((guardados or {}).get("telegram", {}).get("chats") or []))
    if isinstance(crudo, str):
        crudo = [x for x in crudo.replace(";", ",").split(",") if x.strip()]
    salida = []
    for trozo in crudo or []:
        try:
            salida.append(int(str(trozo).strip()))
        except ValueError:
            _problema(f"«{trozo}» no es un identificador de chat.",
                      "Es un número, como 987654321. Arranca el bot sin --chat y "
                      "escríbele: te dirá el tuyo.")
    return tuple(salida)


# ------------------------------------------------------------------- guardia

def cmd_guardia(args: argparse.Namespace) -> int:
    """Prepara el día siguiente cada noche, sola."""
    from ..almacen import Almacen
    from ..guardia import preparar_dia, vigilar

    guardados = _ajustes(args)
    suya = guardados["guardia"]
    valor = modulo_ajustes.valor

    cliente = comun.construir_cliente(args)
    almacen = Almacen(valor(args, "db", guardados["memoria"]))
    grupos = _ligas(args, guardados)
    registro = None if args.sin_registro else valor(args, "registro", suya["registro"])
    briefings = valor(args, "briefings", guardados["briefings"])
    comunes = {
        "grupos": grupos,
        "ultimos": valor(args, "ultimos", suya["ultimos"]),
        "abastecer_partidos": valor(args, "partidos", suya["partidos"]),
        "maximo_peticiones": valor(args, "max", suya["max"]),
        "carpeta_briefings": briefings,
    }
    try:
        if args.una_vez:
            from ..guardia import Diario

            diario = Diario(ruta=registro)
            try:
                preparar_dia(cliente, almacen, fecha=args.date, diario=diario, **comunes)
            finally:
                diario.cerrar()
            return 0
        vigilar(cliente, almacen,
                a_las=valor(args, "a_las", suya["hora"]),
                dias_vista=valor(args, "dias", suya["dias"]),
                registro=registro, ahora=args.ahora,
                releer=lambda: modulo_ajustes.cargar(getattr(args, "ajustes", None)),
                **comunes)
        return 0
    finally:
        almacen.close()
        cliente.close()


# ------------------------------------------------------------------ telegram

def cmd_telegram(args: argparse.Namespace) -> int:
    """El bot, para preguntarle desde fuera de casa."""
    from ..sesion import Sesion
    from ..telegrama import Bot, TelegramNoDisponible

    guardados = _ajustes(args)
    token = (args.token or os.environ.get(ENV_TOKEN, "")
             or (guardados["telegram"]["token"] or ""))
    if not token:
        _problema("Falta el token del bot.",
                  "Abre Telegram, habla con @BotFather, manda /newbot y te dará "
                  "uno como 123456:AAE... Luego: cancha telegram --token 123456:AAE...",
                  f"O guárdalo en la variable de entorno {ENV_TOKEN} y no lo "
                  "vuelvas a escribir.")
        return 2

    cliente = comun.construir_cliente(args)
    sesion = Sesion(cliente=cliente,
                    ruta_almacen=modulo_ajustes.valor(args, "db", guardados["memoria"]))
    bot = Bot(token=token, permitidos=_chats(args, guardados), sesion=sesion,
              modelo=args.modelo or guardados["modelo"] or "")
    try:
        quien = bot.comprobar()
    except TelegramNoDisponible as exc:
        _problema(str(exc), "Comprueba el token y que este ordenador tenga internet.")
        sesion.close()
        return 2

    imprimir(f"Bot «{quien['nombre']}» en marcha.")
    if quien.get("enlace"):
        imprimir(f"  Escríbele aquí: {quien['enlace']}")
    if not bot.permitidos:
        imprimir("")
        imprimir("  ⚠ Sin lista de permitidos: NO va a contestar a nadie.")
        imprimir("    Escríbele desde tu Telegram y te dirá tu identificador de chat;")
        imprimir("    luego arráncalo con --chat <ese número>.")
    else:
        imprimir(f"  Contesta a: {', '.join(str(c) for c in bot.permitidos)}")
    imprimir("Ctrl+C para parar.")
    try:
        bot.escuchar(avisar=imprimir)
        return 0
    finally:
        bot.close()


# ------------------------------------------------------------------- ajustes

def cmd_ajustes(args: argparse.Namespace) -> int:
    """Ver y cambiar lo que se decide una vez: hora, ligas, modelo, puerto."""
    from ..ligas import CATALOGO, GRUPOS

    if args.ligas:
        imprimir("Grupos (valen en --grupos y en el ajuste «ligas»):\n")
        for grupo, nombres in GRUPOS.items():
            imprimir(f"  {grupo:<14} {len(nombres)} competiciones")
        imprimir("\nAtajos:  todo · masculino · femenino · europa · america\n")
        imprimir("Competiciones sueltas (vale el nombre o cualquier alias):\n")
        for competicion in CATALOGO:
            alias = f"  ({', '.join(competicion.alias)})" if competicion.alias else ""
            imprimir(f"  {competicion.nombre}{alias}")
        return 0

    guardados = modulo_ajustes.cargar(args.ajustes)
    if guardados.get("_error"):
        _problema(guardados["_error"])

    if args.cambios:
        for cambio in args.cambios:
            if "=" not in cambio:
                _problema(f"«{cambio}» no es un cambio.",
                          "Se escribe clave=valor, por ejemplo guardia.hora=02:30.")
                return 2
            clave, _, crudo = cambio.partition("=")
            try:
                guardados = modulo_ajustes.poner(guardados, clave, crudo)
            except modulo_ajustes.AjusteDesconocido as exc:
                _problema(str(exc))
                return 2
        problemas = modulo_ajustes.revisar(guardados)
        for problema in problemas:
            imprimir(f"  ⚠ {problema}")
        destino = modulo_ajustes.guardar(guardados, args.ajustes)
        imprimir(f"Guardado en {destino}.")
        imprimir("")

    imprimir(json.dumps(modulo_ajustes.sin_secretos(
        {k: v for k, v in guardados.items() if not k.startswith("_")}),
        ensure_ascii=False, indent=2))
    if not args.cambios:
        imprimir("")
        imprimir("Para cambiar algo:  cancha ajustes guardia.hora=02:30 modelo=qwen2.5:7b")
        imprimir("Las ligas que hay:  cancha ajustes --ligas")
    return 0


# ------------------------------------------------------------------ arrancar

def cmd_arrancar(args: argparse.Namespace) -> int:
    """Todo junto: comprobación, interfaz, guardia y bot, en un proceso."""
    from ..diagnostico import diagnostico
    from ..guardia import puede_impedir_suspension
    from ..sesion import Sesion
    from ..web import Servidor, arrancar

    imprimir("")
    imprimir("  cancha — arrancando")
    imprimir("")

    # Todo lo que se puede configurar se resuelve aquí arriba y una sola vez.
    # Leerlo de `args` más abajo es lo que hacía este comando antes, y como los
    # valores por defecto del parser son None para que ganen los ajustes, lo
    # que llegaba al servidor era None: reventaba al abrir el puerto.
    guardados = _ajustes(args)
    valor = modulo_ajustes.valor
    suya = guardados["guardia"]
    opciones = {
        "memoria": valor(args, "db", guardados["memoria"]),
        "briefings": valor(args, "briefings", guardados["briefings"]),
        "hora": valor(args, "a_las", suya["hora"]),
        "dias": valor(args, "dias", suya["dias"]),
        "registro": valor(args, "registro", suya["registro"]),
        "ultimos": valor(args, "ultimos", suya["ultimos"]),
        "partidos": valor(args, "partidos", suya["partidos"]),
        "max": valor(args, "max", suya["max"]),
        "puerto": valor(args, "port", guardados["web"]["puerto"]),
        "clave": valor(args, "clave", guardados["web"]["clave"]) or "",
        "grupos": _ligas(args, guardados),
        "modelo": args.modelo or guardados["modelo"] or "",
    }

    cliente = comun.construir_cliente(args)
    sesion = Sesion(cliente=cliente, ruta_almacen=opciones["memoria"])

    # 1. Lo que puede estar mal, dicho antes de que se note.
    estado = diagnostico(cliente)
    if estado.get("aviso"):
        _problema("Vas a llevarte muchos 403 de Sofascore.", estado["aviso"])
    memoria = sesion.almacen.resumen()
    imprimir(f"  memoria      {memoria['partidos']} partidos, "
             f"{memoria['con_estadisticas']} con estadísticas")
    imprimir(f"  transporte   {estado.get('en_uso', '?')}")
    imprimir(f"  credenciales {estado.get('credenciales', '?')}")
    imprimir("  ligas        " + (", ".join(opciones["grupos"]) if opciones["grupos"]
                                  else "todo el catálogo"))
    if not memoria["partidos"]:
        imprimir("")
        imprimir("  La memoria está vacía. La guardia la llenará esta noche, o")
        imprimir("  puedes empezar ya con:  cancha guardia --una-vez")

    # 2. La guardia, en segundo plano.
    if not args.sin_guardia and suya.get("activa", True):
        def correr_guardia() -> None:
            from ..almacen import Almacen as AlmacenHilo
            from ..guardia import vigilar

            # Todo propio: memoria y **cliente**. Compartir el cliente con el
            # servidor web tenía dos problemas, y el sutil es el peor: el tope
            # de la guardia se mide con el contador de peticiones del cliente,
            # así que cada cosa que pidieras desde la página se le descontaría
            # a la guardia y se cortaría sola sin motivo.
            propio = AlmacenHilo(opciones["memoria"])
            suyo = comun.construir_cliente(args)
            try:
                vigilar(suyo, propio, a_las=opciones["hora"],
                        dias_vista=opciones["dias"], grupos=opciones["grupos"],
                        ultimos=opciones["ultimos"],
                        abastecer_partidos=opciones["partidos"],
                        maximo_peticiones=opciones["max"],
                        carpeta_briefings=opciones["briefings"],
                        registro=opciones["registro"], en_pantalla=False,
                        releer=lambda: modulo_ajustes.cargar(
                            getattr(args, "ajustes", None)))
            finally:
                propio.close()
                suyo.close()

        threading.Thread(target=correr_guardia, daemon=True, name="guardia").start()
        imprimir(f"  guardia      cada día a las {opciones['hora']}, prepara el día "
                 f"+{opciones['dias']} · registro en {opciones['registro']}")
        if puede_impedir_suspension():
            imprimir("               el equipo no se suspenderá mientras trabaje "
                     "(la pantalla sí se apaga)")
        else:
            imprimir("               ⚠ no sé impedir la suspensión en este sistema:")
            imprimir("                 si el equipo se duerme, la guardia se duerme")
            imprimir("                 con él. Desactívala en los ajustes de energía.")
    elif not suya.get("activa", True):
        imprimir("  guardia      apagada en tus ajustes")

    # 3. El bot, si hay token.
    token = (args.token or os.environ.get(ENV_TOKEN, "")
             or guardados["telegram"]["token"] or "")
    if token and not args.sin_bot:
        from ..telegrama import Bot, TelegramNoDisponible

        # Sesión propia, igual que la guardia: el bot vive en su hilo y
        # compartir la conexión de SQLite con las peticiones de la web es una
        # carrera esperando a pasar. Cada uno la suya, y que SQLite haga su
        # trabajo, que para eso está en modo WAL.
        bot = Bot(token=token, permitidos=_chats(args, guardados),
                  sesion=Sesion(cliente=comun.construir_cliente(args),
                                ruta_almacen=opciones["memoria"]),
                  modelo=opciones["modelo"])
        try:
            quien = bot.comprobar()
            threading.Thread(target=bot.escuchar, daemon=True, name="telegram").start()
            imprimir(f"  telegram     «{quien['nombre']}»"
                     + (f" · {quien['enlace']}" if quien.get("enlace") else ""))
            if not bot.permitidos:
                imprimir("               ⚠ sin chats permitidos: no contestará a "
                         "nadie (escríbele y te dirá tu id)")
        except TelegramNoDisponible as exc:
            _problema(f"El bot de Telegram no arranca: {exc}",
                      "El resto sigue funcionando; arréglalo cuando quieras.")
    elif not token:
        imprimir("  telegram     apagado (sin token; ponlo en Ajustes, o con "
                 f"--token o {ENV_TOKEN})")

    # 4. La interfaz, que es la que se queda en primer plano.
    aplicacion = Servidor(sesion=sesion, clave=opciones["clave"],
                          carpeta_briefings=opciones["briefings"],
                          modelo=opciones["modelo"], ollama=guardados["ollama"],
                          ruta_ajustes=getattr(args, "ajustes", None))
    a_la_red = guardados["web"]["lan"] and not args.solo_local
    host = "0.0.0.0" if a_la_red else "127.0.0.1"
    imprimir("")
    try:
        return arrancar(aplicacion, host=host, puerto=opciones["puerto"],
                        abrir=args.abrir, avisar=imprimir, qr=not args.sin_qr,
                        color=not args.sin_color)
    except OSError as exc:
        _problema(f"No he podido abrir el puerto {opciones['puerto']}: {exc}",
                  "Casi siempre es que ya hay otro cancha abierto. Ciérralo, o "
                  f"arranca este con --port {opciones['puerto'] + 1}.")
        sesion.close()
        return 2


# -------------------------------------------------------------------- parser

def registrar(sub, comun_p, informe, listado) -> None:
    """Añade los comandos de dejarlo funcionando."""
    # Todo por defecto a None a propósito: así se distingue «no lo has dicho»
    # de «lo has dicho y coincide con lo de fábrica», y los ajustes guardados
    # pueden ganar sin pisar lo que sí has escrito tú.
    de_fabrica = modulo_ajustes.POR_DEFECTO
    guardia_base = argparse.ArgumentParser(add_help=False)
    guardia_base.add_argument("--ajustes", help=f"Fichero de ajustes (por defecto: "
                                                f"{modulo_ajustes.RUTA_POR_DEFECTO}).")
    guardia_base.add_argument("--a-las", help="Hora local de la guardia. Por defecto, la "
                                              "de tus ajustes (de fábrica, "
                                              f"{de_fabrica['guardia']['hora']}).")
    guardia_base.add_argument("--dias", type=int,
                              help="Qué día preparar: 1 es mañana.")
    guardia_base.add_argument("--grupos", help="Ligas o grupos, separados por comas. Por "
                                               "defecto, los de tus ajustes.")
    guardia_base.add_argument("--partidos", type=int,
                              help="Cuántos partidos abastecer a fondo. 0 para ninguno.")
    guardia_base.add_argument("--max", type=int,
                              help="Tope de peticiones por vuelta (0 = sin tope).")
    guardia_base.add_argument("--registro", help="Dónde se escribe lo que va haciendo.")
    guardia_base.add_argument("--briefings", help="Carpeta de los briefings.")
    guardia_base.add_argument("--db", help="Fichero de la memoria.")

    p_guardia = sub.add_parser(
        "guardia", parents=[comun_p, guardia_base],
        help="Deja el ordenador preparando el día siguiente cada noche.",
        description="Cada noche a su hora: barre el día que viene, abastece sus "
                    "partidos, escribe el briefing y calibra «casi seguro». Por la "
                    "mañana está todo. En Windows le pide al sistema que no se "
                    "suspenda mientras trabaja, porque si el equipo se duerme el "
                    "proceso se duerme con él.",
    )
    p_guardia.add_argument("--ahora", action="store_true",
                           help="Hacer una vuelta al arrancar, sin esperar a la hora.")
    p_guardia.add_argument("--una-vez", action="store_true",
                           help="Una vuelta y salir. Para el programador de tareas.")
    p_guardia.add_argument("--date", help="Preparar esta fecha concreta (AAAA-MM-DD).")
    p_guardia.add_argument("--ultimos", type=int,
                           help="Partidos recientes por equipo en el barrido.")
    p_guardia.add_argument("--sin-registro", action="store_true",
                           help="No escribir el fichero de registro.")
    p_guardia.set_defaults(func=cmd_guardia)

    bot_base = argparse.ArgumentParser(add_help=False)
    bot_base.add_argument("--token", help=f"Token del bot (o la variable {ENV_TOKEN}).")
    bot_base.add_argument("--chat", action="append",
                          help="Identificador de chat permitido. Se puede repetir. "
                               f"También vale la variable {ENV_CHAT}.")
    bot_base.add_argument("--modelo", help="Modelo de Ollama para las preguntas libres.")

    p_telegram = sub.add_parser(
        "telegram", parents=[comun_p, bot_base],
        help="Un bot para preguntarle desde el móvil, estés donde estés.",
        description="El ordenador se queda en casa haciendo el trabajo y tú "
                    "preguntas por Telegram. No hace falta abrir ningún puerto: es "
                    "tu ordenador quien llama a Telegram. Sin --chat no contesta a "
                    "nadie, y con razón: un bot es público.",
    )
    p_telegram.add_argument("--db", help="Fichero de la memoria.")
    p_telegram.set_defaults(func=cmd_telegram)

    p_ajustes = sub.add_parser(
        "ajustes",
        help="Ver y cambiar la hora de la guardia, las ligas, el modelo…",
        description="Lo que se decide una vez y no se vuelve a escribir. Vive en "
                    "datos/ajustes.json y se puede tocar también desde la pestaña "
                    "Ajustes de la interfaz, incluido el móvil. Lo que escribas en la "
                    "línea de comandos gana a lo guardado, y lo guardado a lo de "
                    "fábrica.")
    p_ajustes.add_argument("cambios", nargs="*",
                           help="clave=valor. Ej: guardia.hora=02:30 modelo=qwen2.5:7b")
    p_ajustes.add_argument("--ajustes", help="Otro fichero de ajustes.")
    p_ajustes.add_argument("--ligas", action="store_true",
                           help="Listar los grupos y competiciones que se pueden elegir.")
    p_ajustes.set_defaults(func=cmd_ajustes)

    p_arrancar = sub.add_parser(
        "arrancar", parents=[comun_p, guardia_base, bot_base],
        help="Todo a la vez: la interfaz, la guardia nocturna y el bot.",
        description="Lo que se abre y se deja. Comprueba que esté todo en su "
                    "sitio, levanta la interfaz en la wifi con su QR, pone la "
                    "guardia a preparar el día siguiente y, si le das token, el "
                    "bot de Telegram. Ctrl+C lo cierra todo.",
    )
    p_arrancar.add_argument("--port", type=int, help="Puerto de la interfaz.")
    p_arrancar.add_argument("--solo-local", action="store_true",
                            help="No abrir la interfaz a la wifi.")
    p_arrancar.add_argument("--clave", help="Clave para la interfaz (recomendable con wifi).")
    p_arrancar.add_argument("--abrir", action="store_true", help="Abrir el navegador.")
    p_arrancar.add_argument("--sin-qr", action="store_true", help="No dibujar el QR.")
    p_arrancar.add_argument("--sin-color", action="store_true", help="QR sin colores ANSI.")
    p_arrancar.add_argument("--sin-guardia", action="store_true", help="No poner la guardia.")
    p_arrancar.add_argument("--sin-bot", action="store_true", help="No arrancar el bot.")
    p_arrancar.set_defaults(func=cmd_arrancar)
