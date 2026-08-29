"""Comandos sobre los propios datos: grabarlos, mirarlos y diagnosticar."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..cache import DiskCache
from ..config import Settings
from ..errors import SofascoreError
from . import comun
from .comun import envolver, imprimir

#: Lo que se graba para que los tests de contrato tengan de todo.
GUION_DE_GRABACION = (
    ("partido, todas las secciones", "match", ["--all", "--players", "6", "--quiet"]),
    ("equipo", "team", ["--all"]),
    ("jugador", "player", ["--all"]),
    ("competición", "league", ["--all"]),
)


def cmd_grabar(args: argparse.Namespace) -> int:
    """Guarda respuestas reales de la API para que los tests las usen.

    Los tests de este proyecto se han escrito siempre contra respuestas de
    ejemplo inventadas, y eso dejó pasar fallos de verdad. Esto graba lo que la
    API responde para poder comprobar que el código no da por supuesto nada que
    no esté.
    """
    from ..grabacion import resumen

    destino = Path(args.carpeta)
    imprimir(f"Grabando en {destino}\n")
    imprimir("Se guarda SOLO la respuesta, nunca la petición: tu cookie de Plus")
    imprimir("no acaba en ningún fichero.\n")

    plan = [
        ("partido", ["match", args.partido, "--all", "--players", "4", "--quiet"]),
    ]
    if args.equipo:
        plan.append(("equipo", ["team", args.equipo, "--all"]))
    if args.jugador:
        plan.append(("jugador", ["player", args.jugador, "--all"]))
    if args.liga:
        plan.append(("competición", ["league", args.liga, "--all"]))
    if args.fuentes:
        plan.append(("otras fuentes", ["contexto", args.partido]))

    # Se importa aquí y no arriba: cli monta los comandos, así que importarlo
    # desde un comando en la cabecera sería una pescadilla mordiéndose la cola.
    from ..cli import main

    fallos = 0
    for etiqueta, orden in plan:
        imprimir(f"  · {etiqueta}: cancha {' '.join(orden[:2])} …")
        completa = [*orden, "--record", str(destino)]
        if getattr(args, "date", None) and orden[0] == "match":
            completa += ["--date", args.date]
        try:
            codigo = main(completa)
            if codigo != 0:
                fallos += 1
                imprimir(f"      (terminó con código {codigo})")
        except SofascoreError as exc:
            fallos += 1
            imprimir(f"      falló: {exc}")

    datos = resumen(destino)
    imprimir(f"\n{datos.get('grabaciones', 0)} respuestas guardadas.")
    if datos.get("grabaciones"):
        imprimir("\nAhora los tests de contrato ya tienen con qué trabajar:")
        imprimir("    python -m pytest tests/test_contrato.py -v")
    if fallos:
        imprimir(f"\n{fallos} parte(s) no se pudieron grabar; el resto sí.")
    return 0


def cmd_grabaciones(args: argparse.Namespace) -> int:
    """Qué hay grabado."""
    from ..grabacion import resumen

    datos = resumen(args.carpeta)
    if not datos.get("grabaciones"):
        imprimir(f"No hay nada grabado en {args.carpeta}.")
        imprimir("Grábalo con: cancha grabar <partido>")
        return 0
    imprimir(f"{datos['grabaciones']} respuestas en {args.carpeta}")
    imprimir(f"Grabadas entre {datos['desde']} y {datos['hasta']}\n")
    for ruta in datos["rutas"]:
        imprimir(f"  {ruta}")
    return 0


def cmd_raw(args: argparse.Namespace) -> int:
    cliente = comun.construir_cliente(args)
    try:
        datos = cliente.raw(args.ruta)
        imprimir(json.dumps(datos, ensure_ascii=False, indent=2, default=str))
        return 0
    finally:
        cliente.close()


def cmd_doctor(args: argparse.Namespace) -> int:
    """Dice con qué está pidiendo y si Sofascore le contesta."""
    from ..transport import AUTO_ORDER, transport_disponible

    imprimir("Transportes disponibles:")
    for nombre in AUTO_ORDER:
        marca = "✓" if transport_disponible(nombre) else "·"
        extra = {
            "curl": "curl_cffi — imita el TLS de Chrome, atraviesa el anti-bot",
            "httpx": "httpx — HTTP/2 y conexiones reutilizadas",
            "urllib": "biblioteca estándar, siempre está",
        }[nombre]
        imprimir(f"  {marca} {nombre:<8} {extra}")

    cliente = comun.construir_cliente(args)
    try:
        elegido = type(cliente.transport).__name__
        imprimir(f"\nEn uso: {elegido}")
        if elegido == "UrllibTransport":
            imprimir("  ⚠  Sofascore suele responder 403 a urllib. `pip install curl_cffi`")
        imprimir(f"Credenciales Plus: {cliente.credentials.describe()}")

        imprimir("\nProbando contra la API...")
        for base in cliente.settings.base_urls():
            try:
                respuesta = cliente.transport.request(
                    "GET", f"{base}/sport/football/events/live", cliente._headers()
                )
                estado = f"HTTP {respuesta.status}"
                icono = "✓" if respuesta.ok else ("🚫" if respuesta.status in (401, 403) else "✗")
            except SofascoreError as exc:
                estado, icono = str(exc), "✗"
            imprimir(f"  {icono} {base} — {estado}")
        return 0
    finally:
        cliente.close()


def cmd_cache(args: argparse.Namespace) -> int:
    ajustes = Settings.from_env(cache_dir=Path(args.cache_dir) if args.cache_dir else None)
    cache = DiskCache(ajustes.cache_dir)
    if args.clear:
        imprimir(f"Borrados {cache.clear()} ficheros de {ajustes.cache_dir}")
    else:
        ficheros = list(Path(ajustes.cache_dir).rglob("*.json")) if ajustes.cache_dir else []
        tamano = sum(f.stat().st_size for f in ficheros) / 1024
        imprimir(f"{len(ficheros)} respuestas en caché ({tamano:.1f} KiB) en {ajustes.cache_dir}")
    return 0


# -------------------------------------------------------------------------- parser


def cmd_fuentes(args: argparse.Namespace) -> int:
    """Qué fuentes hay además de Sofascore."""
    from ..sources import FUENTES, construir

    imprimir("Fuente principal:\n")
    imprimir("  sofascore    Partidos, equipos, jugadores y competiciones.")
    imprimir(f"\nOtras {len(FUENTES)} fuentes:\n")
    for nombre in sorted(FUENTES):
        fuente = construir(nombre)
        imprimir(f"  {nombre}")
        for linea in envolver(fuente.descripcion, 74):
            imprimir(f"      {linea}")
        imprimir(f"      {fuente.base_url} · {fuente.rate_limit}/s · caché {fuente.ttl // 3600} h")
    imprimir("\nJúntalas todas sobre un partido con: cancha contexto <partido>")
    return 0


def registrar(sub, comun, informe, listado) -> None:
    """Añade los subcomandos de esta familia al parser."""
    p_grabar = sub.add_parser(
        "grabar", parents=[comun],
        help="Guarda respuestas reales de la API para los tests.",
        description="Los tests se escribieron contra respuestas inventadas. "
                    "Esto graba las de verdad para poder comprobar el código "
                    "contra ellas.",
    )
    p_grabar.add_argument("partido", help="Id, URL o 'Equipo A vs Equipo B'.")
    p_grabar.add_argument("--date", help="Fecha del partido (AAAA-MM-DD).")
    p_grabar.add_argument("--carpeta", default="tests/fixtures/reales",
                          help="Dónde guardarlo (por defecto: tests/fixtures/reales).")
    p_grabar.add_argument("--equipo", default="Real Madrid", help="Equipo del que grabar la ficha.")
    p_grabar.add_argument("--jugador", default="Vinicius Junior", help="Jugador del que grabarla.")
    p_grabar.add_argument("--liga", default="laliga", help="Competición de la que grabarla.")
    p_grabar.add_argument("--fuentes", action="store_true",
                          help="Grabar también Understat y ClubElo.")
    p_grabar.set_defaults(func=cmd_grabar)

    p_grabaciones = sub.add_parser("grabaciones", help="Qué respuestas hay grabadas.")
    p_grabaciones.add_argument("--carpeta", default="tests/fixtures/reales")
    p_grabaciones.set_defaults(func=cmd_grabaciones)

    p_raw = sub.add_parser("raw", parents=[comun], help="Pide una ruta cualquiera de la API.")
    p_raw.add_argument("ruta", help="P. ej. /event/11352550/statistics")
    p_raw.set_defaults(func=cmd_raw)

    p_doctor = sub.add_parser("doctor", parents=[comun],
                              help="Comprueba el transporte y si la API contesta.")
    p_doctor.set_defaults(func=cmd_doctor)

    p_cache = sub.add_parser("cache", help="Estado de la caché.")
    p_cache.add_argument("--clear", action="store_true", help="Vacía la caché.")
    p_cache.add_argument("--cache-dir", help="Carpeta de la caché.")
    p_cache.set_defaults(func=cmd_cache)

    p_fuentes = sub.add_parser("fuentes", help="Qué fuentes de datos hay y qué aporta cada una.")
    p_fuentes.set_defaults(func=cmd_fuentes)
