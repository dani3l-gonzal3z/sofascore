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
import os
import threading

from ..guardia import ABASTECER_POR_DEFECTO, HORA_POR_DEFECTO, REGISTRO_POR_DEFECTO
from . import comun
from .comun import envolver, imprimir

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


def _chats(args: argparse.Namespace) -> tuple[int, ...]:
    crudo = args.chat or os.environ.get(ENV_CHAT, "")
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

    cliente = comun.construir_cliente(args)
    almacen = Almacen(args.db or "datos/cancha.db")
    grupos = args.grupos.split(",") if args.grupos else None
    try:
        if args.una_vez:
            from ..guardia import Diario

            diario = Diario(ruta=None if args.sin_registro else args.registro)
            try:
                preparar_dia(cliente, almacen, fecha=args.date, grupos=grupos,
                             ultimos=args.ultimos, abastecer_partidos=args.partidos,
                             maximo_peticiones=args.max,
                             carpeta_briefings=args.briefings or "datos/briefings",
                             diario=diario)
            finally:
                diario.cerrar()
            return 0
        vigilar(cliente, almacen, a_las=args.a_las, dias_vista=args.dias,
                grupos=grupos, ultimos=args.ultimos, abastecer_partidos=args.partidos,
                maximo_peticiones=args.max,
                carpeta_briefings=args.briefings or "datos/briefings",
                registro=None if args.sin_registro else args.registro,
                ahora=args.ahora)
        return 0
    finally:
        almacen.close()
        cliente.close()


# ------------------------------------------------------------------ telegram

def cmd_telegram(args: argparse.Namespace) -> int:
    """El bot, para preguntarle desde fuera de casa."""
    from ..sesion import Sesion
    from ..telegrama import Bot, TelegramNoDisponible

    token = args.token or os.environ.get(ENV_TOKEN, "")
    if not token:
        _problema("Falta el token del bot.",
                  "Abre Telegram, habla con @BotFather, manda /newbot y te dará "
                  "uno como 123456:AAE... Luego: cancha telegram --token 123456:AAE...",
                  f"O guárdalo en la variable de entorno {ENV_TOKEN} y no lo "
                  "vuelvas a escribir.")
        return 2

    cliente = comun.construir_cliente(args)
    sesion = Sesion(cliente=cliente, ruta_almacen=args.db or "datos/cancha.db")
    bot = Bot(token=token, permitidos=_chats(args), sesion=sesion, modelo=args.modelo or "")
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


# ------------------------------------------------------------------ arrancar

def cmd_arrancar(args: argparse.Namespace) -> int:
    """Todo junto: comprobación, interfaz, guardia y bot, en un proceso."""
    from ..diagnostico import diagnostico
    from ..sesion import Sesion
    from ..web import Servidor, arrancar

    imprimir("")
    imprimir("  cancha — arrancando")
    imprimir("")

    cliente = comun.construir_cliente(args)
    sesion = Sesion(cliente=cliente, ruta_almacen=args.db or "datos/cancha.db")

    # 1. Lo que puede estar mal, dicho antes de que se note.
    estado = diagnostico(cliente)
    if estado.get("aviso"):
        _problema("Vas a llevarte muchos 403 de Sofascore.", estado["aviso"])
    memoria = sesion.almacen.resumen()
    imprimir(f"  memoria      {memoria['partidos']} partidos, "
             f"{memoria['con_estadisticas']} con estadísticas")
    imprimir(f"  transporte   {estado.get('en_uso', '?')}")
    imprimir(f"  credenciales {estado.get('credenciales', '?')}")
    if not memoria["partidos"]:
        imprimir("")
        imprimir("  La memoria está vacía. La guardia la llenará esta noche, o")
        imprimir("  puedes empezar ya con:  cancha guardia --una-vez")

    hilos = []

    # 2. La guardia, en segundo plano.
    if not args.sin_guardia:
        def correr_guardia() -> None:
            from ..almacen import Almacen as AlmacenHilo
            from ..guardia import vigilar

            # Todo propio: memoria y **cliente**. Compartir el cliente con el
            # servidor web tenía dos problemas, y el sutil es el peor: el tope
            # de la guardia se mide con el contador de peticiones del cliente,
            # así que cada cosa que pidieras desde la página se le descontaría
            # a la guardia y se cortaría sola sin motivo.
            propio = AlmacenHilo(args.db or "datos/cancha.db")
            suyo = comun.construir_cliente(args)
            try:
                vigilar(suyo, propio, a_las=args.a_las, dias_vista=args.dias,
                        grupos=args.grupos.split(",") if args.grupos else None,
                        abastecer_partidos=args.partidos, maximo_peticiones=args.max,
                        carpeta_briefings=args.briefings or "datos/briefings",
                        registro=args.registro, en_pantalla=False)
            finally:
                propio.close()
                suyo.close()

        hilo = threading.Thread(target=correr_guardia, daemon=True, name="guardia")
        hilo.start()
        hilos.append(hilo)
        from ..guardia import puede_impedir_suspension

        imprimir(f"  guardia      cada día a las {args.a_las}, prepara el día "
                 f"+{args.dias} · registro en {args.registro}")
        if puede_impedir_suspension():
            imprimir("               el equipo no se suspenderá mientras trabaje "
                     "(la pantalla sí se apaga)")
        else:
            imprimir("               ⚠ no sé impedir la suspensión en este sistema:")
            imprimir("                 si el equipo se duerme, la guardia se duerme")
            imprimir("                 con él. Desactívala en los ajustes de energía.")

    # 3. El bot, si hay token.
    token = args.token or os.environ.get(ENV_TOKEN, "")
    if token and not args.sin_bot:
        from ..telegrama import Bot, TelegramNoDisponible

        bot = Bot(token=token, permitidos=_chats(args), sesion=sesion,
                  modelo=args.modelo or "")
        try:
            quien = bot.comprobar()
            hilo = threading.Thread(target=lambda: bot.escuchar(), daemon=True,
                                    name="telegram")
            hilo.start()
            hilos.append(hilo)
            imprimir(f"  telegram     «{quien['nombre']}»"
                     + (f" · {quien['enlace']}" if quien.get("enlace") else ""))
            if not bot.permitidos:
                imprimir("               ⚠ sin --chat: no contestará a nadie "
                         "(escríbele y te dirá tu id)")
        except TelegramNoDisponible as exc:
            _problema(f"El bot de Telegram no arranca: {exc}",
                      "El resto sigue funcionando; arréglalo cuando quieras.")
    elif not token:
        imprimir("  telegram     apagado (sin token; --token o "
                 f"{ENV_TOKEN} para encenderlo)")

    # 4. La interfaz, que es la que se queda en primer plano.
    aplicacion = Servidor(sesion=sesion, clave=args.clave or "",
                          carpeta_briefings=args.briefings or "datos/briefings")
    host = "127.0.0.1" if args.solo_local else "0.0.0.0"
    imprimir("")
    try:
        return arrancar(aplicacion, host=host, puerto=args.port, abrir=args.abrir,
                        avisar=imprimir, qr=not args.sin_qr, color=not args.sin_color)
    except OSError as exc:
        _problema(f"No he podido abrir el puerto {args.port}: {exc}",
                  "Casi siempre es que ya hay otro cancha abierto. Ciérralo, o "
                  f"arranca este con --port {args.port + 1}.")
        sesion.close()
        return 2


# -------------------------------------------------------------------- parser

def registrar(sub, comun_p, informe, listado) -> None:
    """Añade los comandos de dejarlo funcionando."""
    guardia_base = argparse.ArgumentParser(add_help=False)
    guardia_base.add_argument("--a-las", default=HORA_POR_DEFECTO,
                              help=f"Hora local de la guardia (por defecto {HORA_POR_DEFECTO}).")
    guardia_base.add_argument("--dias", type=int, default=1,
                              help="Qué día preparar: 1 es mañana (por defecto).")
    guardia_base.add_argument("--grupos", help="Grupos de competiciones, separados por comas.")
    guardia_base.add_argument("--partidos", type=int, default=ABASTECER_POR_DEFECTO,
                              help=f"Cuántos partidos abastecer a fondo (por defecto "
                                   f"{ABASTECER_POR_DEFECTO}). 0 para ninguno.")
    guardia_base.add_argument("--max", type=int, default=0,
                              help="Tope de peticiones por vuelta (0 = sin tope).")
    guardia_base.add_argument("--registro", default=REGISTRO_POR_DEFECTO,
                              help="Dónde se escribe lo que va haciendo.")
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
    p_guardia.add_argument("--ultimos", type=int, default=6,
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

    p_arrancar = sub.add_parser(
        "arrancar", parents=[comun_p, guardia_base, bot_base],
        help="Todo a la vez: la interfaz, la guardia nocturna y el bot.",
        description="Lo que se abre y se deja. Comprueba que esté todo en su "
                    "sitio, levanta la interfaz en la wifi con su QR, pone la "
                    "guardia a preparar el día siguiente y, si le das token, el "
                    "bot de Telegram. Ctrl+C lo cierra todo.",
    )
    p_arrancar.add_argument("--port", type=int, default=8765, help="Puerto de la interfaz.")
    p_arrancar.add_argument("--solo-local", action="store_true",
                            help="No abrir la interfaz a la wifi.")
    p_arrancar.add_argument("--clave", help="Clave para la interfaz (recomendable con wifi).")
    p_arrancar.add_argument("--abrir", action="store_true", help="Abrir el navegador.")
    p_arrancar.add_argument("--sin-qr", action="store_true", help="No dibujar el QR.")
    p_arrancar.add_argument("--sin-color", action="store_true", help="QR sin colores ANSI.")
    p_arrancar.add_argument("--sin-guardia", action="store_true", help="No poner la guardia.")
    p_arrancar.add_argument("--sin-bot", action="store_true", help="No arrancar el bot.")
    p_arrancar.set_defaults(func=cmd_arrancar)
