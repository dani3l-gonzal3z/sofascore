"""Comandos de tus credenciales: sacar la cookie y comprobarla."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..auth import cookie_desde_navegador
from ..endpoints import SECTIONS
from ..match import build_report
from ..resolve import resolve_event
from . import comun
from .comun import imprimir


def cmd_login(args: argparse.Namespace) -> int:
    cliente = comun.construir_cliente(args)
    try:
        imprimir(f"Credenciales: {cliente.credentials.describe()}")
        if not args.consulta:
            imprimir("Pasa un partido (`cancha login <id|URL|equipos>`) para comprobarlas "
                      "de verdad contra una sección de pago.")
            return 0
        # La sonda tiene que ser una sección que de verdad requiera suscripción.
        # El mapa de tiros no sirve: la API lo da abierto, así que saldría "ok"
        # tengas cuenta o no, y no diría nada de tus credenciales.
        sondas = [n for n, s in SECTIONS.items() if s.requires_plus]
        if not sondas:
            imprimir("No hay ninguna sección de pago en el catálogo con la que probar.")
            return 0

        resolucion = resolve_event(cliente, args.consulta, date=args.date)
        imprimir(f"Partido de prueba: {resolucion.event.label}\n")

        # Se prueban todas hasta que una responda algo concluyente: varias de
        # ellas no existen en todos los partidos, y un 404 no dice nada de tus
        # credenciales.
        sin_conclusion = []
        for sonda in sondas:
            informe = build_report(
                cliente, resolucion.event, sections=[sonda], include_plus=True
            )
            estado = informe.sections[sonda].status
            if estado == "ok":
                imprimir(f"✓ Las credenciales funcionan: '{sonda}' ha traído datos de pago.")
                return 0
            if estado == "plus_required":
                imprimir(f"🔒 Sofascore ha rechazado las credenciales en '{sonda}' "
                          "(faltan o han caducado).")
                return 1
            sin_conclusion.append(f"{sonda} ({estado})")

        imprimir("· Sin conclusión: ninguna sección de pago existe en este partido — "
                  + ", ".join(sin_conclusion) + ".")
        imprimir("  Prueba con un partido reciente o en juego: `cancha live` te da ids.")
        return 0
    finally:
        cliente.close()


def _guardar_en_dotenv(clave: str, valor: str, ruta: str = ".env") -> str:
    """Escribe ``clave=valor`` en el ``.env``, respetando lo que ya hubiera."""
    fichero = Path(ruta)
    lineas = fichero.read_text(encoding="utf-8").splitlines() if fichero.is_file() else []
    salida, sustituida = [], False
    for linea in lineas:
        if linea.strip().startswith(f"{clave}="):
            salida.append(f"{clave}={valor}")
            sustituida = True
        else:
            salida.append(linea)
    if not sustituida:
        salida.append(f"{clave}={valor}")
    fichero.write_text("\n".join(salida) + "\n", encoding="utf-8")
    return "actualizada" if sustituida else "añadida"


def cmd_cookie(args: argparse.Namespace) -> int:
    """Saca la cookie de lo que copies del navegador y la deja lista."""
    if args.file:
        texto = Path(args.file).read_text(encoding="utf-8", errors="replace")
    else:
        imprimir("Pega aquí lo copiado del navegador y termina con Ctrl+Z y Enter")
        imprimir("(en Linux/Mac, Ctrl+D):\n")
        texto = sys.stdin.read()

    cookie = cookie_desde_navegador(texto)
    if not cookie:
        imprimir("\nNo he encontrado ninguna cookie en lo que has pegado.")
        imprimir("Vale cualquiera de estas tres cosas:")
        imprimir("  · botón derecho sobre una petición → Copiar como cURL")
        imprimir("  · botón derecho sobre una petición → Copiar como PowerShell")
        imprimir("  · lo que devuelva document.cookie en la consola")
        return 1

    trozos = [t for t in cookie.split(";") if t.strip()]
    imprimir(f"\n✓ Cookie encontrada: {len(trozos)} valores, {len(cookie)} caracteres.")

    if args.save:
        estado = _guardar_en_dotenv("SOFA_PLUS_COOKIE", cookie, args.env)
        imprimir(f"  Línea SOFA_PLUS_COOKIE {estado} en {args.env}.")
        imprimir("\nCompruébalo con: cancha login <id de un partido reciente>")
    else:
        imprimir("\nPega esta línea en tu .env (o repite con --save y te la escribo yo):\n")
        imprimir(f"SOFA_PLUS_COOKIE={cookie}")
    return 0


def registrar(sub, comun, informe, listado) -> None:
    """Añade los subcomandos de esta familia al parser."""
    p_login = sub.add_parser("login", parents=[comun],
                             help="Comprueba tus credenciales de Sofascore Plus.")
    p_login.add_argument("consulta", nargs="?", help="Partido con el que probarlas.")
    p_login.add_argument("--date", help="Fecha (AAAA-MM-DD).")
    p_login.set_defaults(func=cmd_login)

    p_cookie = sub.add_parser(
        "cookie",
        help="Saca tu cookie de Sofascore de lo que copies del navegador.",
        description="Pega lo que te dé el navegador al copiar una petición "
                    "(cURL o PowerShell) y te deja la línea para el .env.",
    )
    p_cookie.add_argument("--file", help="Leerlo de un fichero en vez de pegarlo.")
    p_cookie.add_argument("--save", action="store_true", help="Escribirla en el .env.")
    p_cookie.add_argument("--env", default=".env", help="Ruta del .env (por defecto: .env).")
    p_cookie.set_defaults(func=cmd_cookie)
