"""Comandos sobre los propios datos: grabarlos, mirarlos y diagnosticar."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

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
    from ..diagnostico import diagnostico

    if args.tls:
        return _doctor_tls(args)
    cliente = comun.construir_cliente(args)
    try:
        d = diagnostico(cliente, cache_dir=args.cache_dir, con_red=True)
        imprimir("Transportes disponibles:")
        for t in d["transportes"]:
            imprimir(f"  {'✓' if t['disponible'] else '·'} {t['nombre']:<8} {t['para_que']}")
        imprimir(f"\nPython: {d['python']}")
        imprimir(f"En uso: {d['en_uso']}")
        if d.get("aviso"):
            imprimir(f"  ⚠  {d['aviso']}")
        imprimir(f"Credenciales Plus: {d['credenciales']}")
        imprimir(f"Certificados: {d['tls']['lectura']}")
        cache = d["cache"]
        imprimir(f"Caché: {cache.get('respuestas', 0)} respuestas "
                 f"({cache.get('kib', 0)} KiB) en {cache.get('carpeta', '—')}"
                 if cache["activa"] else f"Caché: {cache['nota']}")

        imprimir("\nProbando contra la API...")
        for prueba in d["api"]:
            icono = ("✓" if prueba["ok"] else
                     "🚫" if prueba["http"] in (401, 403) else "✗")
            estado = f"HTTP {prueba['http']}" if prueba["http"] else prueba["lectura"]
            imprimir(f"  {icono} {prueba['base']} — {estado}")
        return 0
    finally:
        cliente.close()


def cmd_listo(args: argparse.Namespace) -> int:
    """``cancha listo``: cada pieza, probada de verdad, y qué hacer si falla."""
    from .. import ajustes as modulo_ajustes
    from ..almacen import Almacen
    from ..listo import ICONOS, comprobar, texto

    guardados = modulo_ajustes.cargar(getattr(args, "ajustes", None))
    almacen = Almacen(args.db or "datos/cancha.db")
    cliente = None if args.sin_red else comun.construir_cliente(args)

    def al_vuelo(pieza: dict) -> None:
        if not args.json:
            imprimir(f"{ICONOS[pieza['estado']]} {pieza['nombre']}…")

    try:
        datos = comprobar(almacen, cliente, guardados, con_red=not args.sin_red,
                          avisar=al_vuelo)
    finally:
        almacen.close()
        if cliente is not None:
            cliente.close()
    if args.json:
        imprimir(json.dumps(datos, ensure_ascii=False, indent=2, default=str))
    else:
        imprimir("")
        for linea in texto(datos):
            imprimir(linea)
    return 0 if datos["listo"] else 1


def _doctor_tls(args: argparse.Namespace) -> int:
    """``cancha doctor --tls``: quién está abriendo tu HTTPS, si es que alguien.

    Es la respuesta a un error que no se entiende solo —«self-signed certificate
    in certificate chain»— y que además no parece lo que es: parece que la API
    o Telegram estén rotos, cuando lo que pasa es que hay algo en medio de tu
    propio ordenador.
    """
    from ..diagnostico import probar_tls
    from ..tls import explicar

    ajustes = comun.construir_cliente(args).settings
    for host in (args.host or "api.telegram.org,api.sofascore.com").split(","):
        d = probar_tls(host.strip(), ajustes)
        imprimir("")
        imprimir(f"  {host.strip()}")
        imprimir(f"    python        {d['python']}")
        imprimir(f"    certificados  {d['lectura']}")
        if d["interceptado"] is None:
            imprimir(f"    ⚠  {d['nota']}")
            continue
        if not d["interceptado"]:
            imprimir(f"    ✓  {d['nota']}")
            continue
        imprimir(f"    🚫 {d['nota']}")
        imprimir("")
        # Ya viene partido: volver a partirlo aquí descolocaba la numeración.
        for linea in explicar(host.strip(), ancho=68).splitlines():
            imprimir(f"    {linea}")
    imprimir("")
    return 0


def cmd_cache(args: argparse.Namespace) -> int:
    from ..diagnostico import estado_cache, limpiar_cache

    if args.clear:
        d = limpiar_cache(args.cache_dir)
        imprimir(f"Borrados {d['borrados']} ficheros de {d['carpeta']}")
        return 0
    d = estado_cache(args.cache_dir)
    if not d["activa"]:
        imprimir(d["nota"])
        return 0
    imprimir(f"{d['respuestas']} respuestas en caché ({d['kib']} KiB) en {d['carpeta']}")
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
    from ..sources import disponibles

    imprimir("\nLibrerías externas (se usan si están instaladas):\n")
    for nombre, info in disponibles().items():
        marca = "✓" if info["instalado"] else "·"
        version = f" {info['version']}" if info.get("version") else ""
        imprimir(f"  {marca} {nombre}{version}")
        for linea in envolver(info["aporta"], 70):
            imprimir(f"      {linea}")
        if not info["instalado"]:
            imprimir(f"      {info['instalar']}")
    imprimir("\nJúntalas todas sobre un partido con: cancha contexto <partido>")
    return 0


def cmd_noticias(args: argparse.Namespace) -> int:
    """Los titulares de una liga (o de un equipo), de ESPN."""
    from ..sources import ESPN

    fuente = ESPN()
    try:
        noticias = fuente.noticias(args.liga, cuantas=args.limit, equipo=args.equipo)
        if args.stdout_json:
            imprimir(json.dumps(noticias, ensure_ascii=False, indent=2, default=str))
            return 0
        if not noticias:
            imprimir("Sin noticias" + (f" que mencionen a {args.equipo}." if args.equipo else "."))
            return 0
        for noticia in noticias:
            fecha = (noticia.get("fecha") or "")[:10]
            imprimir(f"{fecha}  {noticia['titulo']}")
            for linea in envolver(noticia.get("resumen") or "", 72):
                imprimir(f"            {linea}")
            if noticia.get("enlace"):
                imprimir(f"            {noticia['enlace']}")
            imprimir("")
        return 0
    finally:
        fuente.close()


def cmd_cuotas(args: argparse.Namespace) -> int:
    """Rellena las cuotas de la memoria con las de cierre de football-data.co.uk."""
    from ..almacen import Almacen
    from ..sources import rellenar_cuotas

    almacen = Almacen(args.db or "datos/cancha.db")
    try:
        imprimir("Rellenando cuotas desde football-data.co.uk…")
        resumen = rellenar_cuotas(almacen, liga_id=args.liga_id, maximo=args.max,
                                  avisar=None if args.quiet else imprimir)
        imprimir(f"\nRellenados {resumen['rellenados']} de {resumen['candidatos']} candidatos · "
                 f"sin cobertura: {resumen['sin_cobertura']} · "
                 f"no encontrados: {resumen['no_encontrados']}")
        for fallo in resumen["fallos"][:5]:
            imprimir(f"    {fallo}")
        return 0
    finally:
        almacen.close()


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
    p_doctor.add_argument("--tls", action="store_true",
                          help="Mira si algo está abriendo tu HTTPS por el camino "
                               "(antivirus, proxy de empresa, VPN) y dice quién es.")
    p_doctor.add_argument("--host", help="Qué hosts probar con --tls, separados por comas.")
    p_doctor.set_defaults(func=cmd_doctor)

    p_listo = sub.add_parser(
        "listo", parents=[comun],
        help="¿Está todo listo? Prueba cada pieza de verdad y dice qué arreglar.",
        description="Memoria, Sofascore (y qué cuotas trae de verdad), el recorrido de "
                    "temporadas, Ollama y si tu modelo sabe pedir herramientas, la "
                    "nube, Telegram y sus canales, Betfair y The Odds API, la guardia "
                    "y el backtest. Sale con 1 si algo está mal.")
    p_listo.add_argument("--db", help="Fichero de la memoria (por defecto: datos/cancha.db).")
    p_listo.add_argument("--sin-red", action="store_true",
                         help="Solo lo que no sale de tu máquina: memoria, guardia, backtest.")
    p_listo.add_argument("--json", action="store_true", help="Volcar el JSON.")
    p_listo.set_defaults(func=cmd_listo)

    p_cache = sub.add_parser("cache", help="Estado de la caché.")
    p_cache.add_argument("--clear", action="store_true", help="Vacía la caché.")
    p_cache.add_argument("--cache-dir", help="Carpeta de la caché.")
    p_cache.set_defaults(func=cmd_cache)

    p_fuentes = sub.add_parser("fuentes", help="Qué fuentes de datos hay y qué aporta cada una.")
    p_fuentes.set_defaults(func=cmd_fuentes)

    p_noticias = sub.add_parser("noticias", parents=[comun],
                                help="Titulares de una liga o de un equipo (ESPN).")
    p_noticias.add_argument("liga", help="'laliga', 'premier', 'mls'... o el código de ESPN.")
    p_noticias.add_argument("--equipo", help="Solo las que mencionen a este equipo.")
    p_noticias.add_argument("--limit", type=int, default=15, help="Cuántas.")
    p_noticias.add_argument("--stdout-json", action="store_true")
    p_noticias.set_defaults(func=cmd_noticias)

    p_cuotas = sub.add_parser(
        "cuotas", parents=[comun],
        help="Rellena las cuotas de los partidos guardados (football-data.co.uk).",
        description="Pone quién era favorito a los partidos barridos sin cuotas, para "
                    "que el desglose por favorito funcione con todo lo guardado.")
    p_cuotas.add_argument("--db", help="Fichero de la memoria.")
    p_cuotas.add_argument("--liga-id", type=int, help="Solo esa competición (id de Sofascore).")
    p_cuotas.add_argument("--max", type=int, default=0, help="Tope de partidos a rellenar.")
    p_cuotas.add_argument("--quiet", action="store_true")
    p_cuotas.set_defaults(func=cmd_cuotas)
