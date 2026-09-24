"""¿Está todo listo? Cada pieza, probada de verdad, con lo que hay que hacer.

Todo lo que habla con el exterior —Sofascore, Ollama, Telegram, Betfair, The Odds
API— se ha escrito leyendo su documentación y probado con respuestas fabricadas.
La primera vez que se usa contra lo de verdad es cuando aparecen las sorpresas:
un formato que no era el que decía la documentación, un modelo que no sabe pedir
herramientas, un bot que no es administrador del canal.

Esto las busca todas de una vez, en el orden en que dependen unas de otras, y de
cada una dice qué ha visto y qué hacer:

    cancha listo

Tres comprobaciones no son de «¿contesta?» sino de «¿contesta **lo que creemos**?»:

* **las cuotas**: se piden las de un partido de hoy y se mira qué mercados trae de
  verdad, y si entre ellos está el marcador exacto;
* **las temporadas**: el recorrido del que depende `cancha historia`;
* **el modelo de casa pidiendo una herramienta**: de eso dependen los agentes, el
  reparto entre dos modelos y la charla de cada partido. Un modelo que no sabe
  pedirlas contesta igual de bien escrito, pero inventándose los datos.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any

OK, AVISO, MAL, APAGADO = "ok", "aviso", "mal", "sin configurar"
ICONOS = {OK: "✓", AVISO: "⚠", MAL: "✗", APAGADO: "·"}


def _pieza(nombre: str, estado: str, detalle: str, arreglo: str = "", **extra) -> dict:
    return {"nombre": nombre, "estado": estado, "detalle": detalle,
            "arreglo": arreglo, **extra}


# ------------------------------------------------------------------ la memoria

def memoria(almacen) -> dict:
    from .almacen import VERSION_ESQUEMA

    try:
        integridad = almacen.consulta("PRAGMA quick_check")[0]
        cuenta = {tabla: almacen.consulta(f"SELECT COUNT(*) AS n FROM {tabla}")[0]["n"]
                  for tabla in ("partidos", "estadisticas", "cuotas_mercado", "predicciones",
                                "picks", "dictamenes", "charlas")}
    except Exception as exc:  # noqa: BLE001
        return _pieza("Memoria", MAL, f"No se puede leer: {exc}",
                      "Cierra lo que la esté usando y vuelve a abrir.")
    if list(integridad.values())[0] != "ok":
        return _pieza("Memoria", MAL, "SQLite dice que el fichero está dañado.",
                      "Haz una copia del fichero antes de nada y avísame.")
    con_cuotas = almacen.consulta(
        "SELECT COUNT(DISTINCT partido_id) AS n FROM cuotas_mercado")[0]["n"]
    detalle = (f"esquema v{VERSION_ESQUEMA} · {cuenta['partidos']} partidos · "
               f"{con_cuotas} con cuotas · {cuenta['predicciones']} predicciones · "
               f"{cuenta['picks']} picks")
    if cuenta["partidos"] < 500:
        return _pieza("Memoria", AVISO, detalle,
                      "Con tan pocos partidos casi nada tiene muestra. Tráete historia: "
                      "cancha historia --plan y luego cancha historia.", cuenta=cuenta)
    return _pieza("Memoria", OK, detalle, cuenta=cuenta)


# ------------------------------------------------------------------ Sofascore

def sofascore(cliente, almacen) -> list[dict]:
    """La agenda, las cuotas de verdad y el recorrido de temporadas."""
    from .errors import SofascoreError

    piezas = []
    hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        eventos = cliente.scheduled_events(hoy)
    except SofascoreError as exc:
        return [_pieza("Sofascore", MAL, f"No contesta: {exc}",
                       "Mira `cancha doctor` y, si habla de certificados, "
                       "`cancha doctor --tls`.")]
    futbol = [e for e in eventos if (e.get("status") or {}).get("type") == "notstarted"]
    piezas.append(_pieza("Sofascore", OK, f"{len(eventos)} partidos hoy en la agenda."))

    # Las cuotas: ¿qué mercados trae de verdad?
    from .mercados import de_sofascore

    mercados, con_exacto, probados = set(), False, 0
    for crudo in futbol[:6]:
        for seccion in ("odds", "odds_featured"):
            with suppress(SofascoreError):
                filas = de_sofascore(cliente.section(seccion, crudo["id"], ttl=600))
                probados += seccion == "odds"
                mercados |= {f["mercado"] for f in filas}
                con_exacto = con_exacto or any(f["mercado"] == "marcador" for f in filas)
                if filas:
                    break
        if mercados and con_exacto:
            break
    if not mercados:
        piezas.append(_pieza(
            "Cuotas de Sofascore", AVISO if probados else MAL,
            f"{probados} partidos probados y ninguno trae cuotas legibles.",
            "Puede ser que a esta hora no haya mercados abiertos. Si sigue igual con "
            "partidos de mañana, el formato ha cambiado: avísame con `cancha raw "
            "/event/<id>/odds/1/all`."))
    else:
        piezas.append(_pieza(
            "Cuotas de Sofascore", OK if con_exacto else AVISO,
            f"Mercados que trae: {', '.join(sorted(mercados))}.",
            "" if con_exacto else
            "No trae marcador exacto. Para compararlo con el nuestro hace falta Betfair "
            "(Ajustes → Cuotas): su clave es gratuita.",
            mercados=sorted(mercados)))

    # Las temporadas: de esto depende `cancha historia`.
    from .barrido import ligas_de

    ligas = ligas_de(None, almacen)
    if ligas:
        liga_id, nombre = next(iter(ligas.items()))
        try:
            temporadas = cliente.seasons(liga_id)
            pagina = (cliente.season_events(liga_id, temporadas[0]["id"], 0)
                      if temporadas else [])
            piezas.append(_pieza(
                "Temporadas (para `historia`)", OK if pagina else AVISO,
                f"{nombre}: {len(temporadas)} temporadas, {len(pagina)} partidos en la "
                "primera página.",
                "" if pagina else "La temporada en curso aún no tiene partidos jugados; "
                                  "prueba `cancha historia --plan`."))
        except (SofascoreError, KeyError, IndexError) as exc:
            piezas.append(_pieza("Temporadas (para `historia`)", MAL, str(exc),
                                 "Sin esto `cancha historia` no puede traer nada: avísame."))
    return piezas


# ------------------------------------------------------------------ Ollama

def ollama(ajustes: dict, pedir: Callable | None = None) -> list[dict]:
    """El de casa: si está, si tiene el modelo, y si sabe pedir una herramienta."""
    from .analista import MODELO_POR_DEFECTO, Analista
    from .herramientas import esquemas

    modelo = ajustes.get("modelo") or MODELO_POR_DEFECTO
    opciones = {"pedir": pedir} if pedir else {}
    if ajustes.get("ollama"):
        opciones["url"] = ajustes["ollama"]
    analista = Analista(modelo=modelo, **opciones)
    try:
        return _ollama(analista, modelo, esquemas)
    finally:
        analista.close()


def _ollama(analista, modelo: str, esquemas: Callable) -> list[dict]:
    estado = analista.comprobar()
    if not estado.get("disponible"):
        return [_pieza("Ollama (en tu máquina)", MAL, estado.get("nota") or "No contesta.",
                       estado.get("como") or "Arranca Ollama.")]
    if not estado.get("instalado"):
        return [_pieza("Ollama (en tu máquina)", MAL, estado.get("nota") or "",
                       f"ollama pull {modelo}")]
    piezas = [_pieza("Ollama (en tu máquina)", OK,
                     f"{modelo} instalado ({len(estado.get('modelos') or [])} modelos).")]

    herramienta = next(e for e in esquemas() if e["name"] == "estado_de_la_memoria")
    try:
        respuesta = analista.pedir("/api/chat", {
            "model": modelo, "stream": False, "options": {"temperature": 0},
            "messages": [{"role": "user", "content":
                          "Usa la herramienta estado_de_la_memoria para saber qué hay "
                          "guardado. No contestes nada sin usarla."}],
            "tools": [{"type": "function", "function": {
                "name": herramienta["name"], "description": herramienta["description"],
                "parameters": herramienta["input_schema"]}}]}) or {}
    except Exception as exc:  # noqa: BLE001
        piezas.append(_pieza("…pidiendo herramientas", MAL, str(exc),
                             "El modelo está pero no ha contestado a una pregunta "
                             "sencilla: mira que no se haya quedado sin memoria."))
        return piezas

    pedidas = [((c.get("function") or {}).get("name"))
               for c in (respuesta.get("message") or {}).get("tool_calls") or []]
    if "estado_de_la_memoria" in pedidas:
        piezas.append(_pieza("…pidiendo herramientas", OK,
                             "Ha pedido la herramienta como tenía que hacerlo."))
    else:
        piezas.append(_pieza(
            "…pidiendo herramientas", MAL,
            "Ha contestado sin pedir la herramienta. Con este modelo, los agentes, el "
            "chat de cada partido y el reparto entre dos modelos contestarán bien "
            "escrito pero inventándose los datos.",
            "Usa un modelo que sepa llamar funciones: hermes3, qwen2.5 o llama3.1."))
    return piezas


def nube(ajustes: dict, contexto: Any = None) -> dict:
    from .analista import URL_NUBE, OllamaNoDisponible, _pedir_http

    clave = ajustes.get("ollama_api_key") or ""
    if not clave:
        return _pieza("Ollama en la nube", APAGADO, "Sin clave.",
                      "Solo hace falta para dictámenes grandes o para el modelo director.")
    try:
        datos = _pedir_http(f"{URL_NUBE}/api/tags", None, timeout=30.0, api_key=clave,
                            contexto=contexto)
    except (OllamaNoDisponible, OSError) as exc:
        return _pieza("Ollama en la nube", MAL, str(exc),
                      "Revisa la clave en Ajustes: es la de «API keys», no la SSH.")
    return _pieza("Ollama en la nube", OK,
                  f"La clave vale: {len((datos or {}).get('models') or [])} modelos.")


# ------------------------------------------------------------------ Telegram

def telegram(ajustes: dict, pedir: Callable | None = None) -> list[dict]:
    """El token, a quién contesta, y si puede escribir en los canales de picks."""
    from .telegrama import Bot, TelegramNoDisponible

    suyo = ajustes.get("telegram") or {}
    if not suyo.get("token"):
        return [_pieza("Telegram", APAGADO, "Sin token.",
                       "Pídele uno a @BotFather y ponlo en Ajustes → Telegram.")]
    red = ajustes.get("red") or {}
    bot = Bot(token=suyo["token"], ca_bundle=red.get("ca_bundle") or "",
              sin_verificar=bool(red.get("sin_verificar")),
              **({"pedir": pedir} if pedir else {}))
    try:
        yo = bot.pedir("getMe", None).get("result") or {}
    except TelegramNoDisponible as exc:
        return [_pieza("Telegram", MAL, str(exc))]
    piezas = [_pieza("Telegram", OK if suyo.get("chats") else AVISO,
                     f"@{yo.get('username')} · contesta a {len(suyo.get('chats') or [])} "
                     "chats.",
                     "" if suyo.get("chats") else
                     "No contesta a nadie todavía: escríbele y apunta tu chat en Ajustes.")]
    for nivel in ("gratis", "premium"):
        canal = suyo.get(f"canal_{nivel}")
        if not canal:
            continue
        try:
            miembro = bot.pedir("getChatMember", {"chat_id": canal,
                                                  "user_id": yo.get("id")}).get("result") or {}
            admin = miembro.get("status") in ("administrator", "creator")
            piezas.append(_pieza(f"Canal {nivel}", OK if admin else MAL,
                                 f"{canal}: el bot es {miembro.get('status')}.",
                                 "" if admin else "Hazlo administrador del canal, o no podrá "
                                                  "publicar el boletín."))
        except TelegramNoDisponible as exc:
            piezas.append(_pieza(f"Canal {nivel}", MAL, f"{canal}: {exc}",
                                 "Comprueba el id del canal (-100…) o su @nombre."))
    return piezas


# ------------------------------------------------------------ casas de fuera

def casas(ajustes: dict, contexto: Any = None) -> list[dict]:
    from .sources.casas import Betfair, CasaNoDisponible, TheOddsApi

    cuotas = ajustes.get("cuotas") or {}
    piezas = []
    bf = cuotas.get("betfair") or {}
    if not bf.get("clave_app"):
        piezas.append(_pieza("Betfair", APAGADO, "Sin clave.",
                             "Es la única fuente con marcador exacto casi sin margen: "
                             "developer.betfair.com, clave retrasada gratuita."))
    else:
        try:
            Betfair(bf.get("clave_app"), bf.get("usuario", ""), bf.get("contrasena", ""),
                    bf.get("jurisdiccion", "com"), contexto=contexto).entrar()
            piezas.append(_pieza("Betfair", OK, "Entra."))
        except CasaNoDisponible as exc:
            piezas.append(_pieza("Betfair", MAL, str(exc)))
    oa = cuotas.get("the_odds_api") or {}
    if not oa.get("clave"):
        piezas.append(_pieza("The Odds API", APAGADO, "Sin clave."))
    else:
        try:
            casa = TheOddsApi(oa["clave"], contexto=contexto)
            deportes = casa._pedir(f"{casa.raiz}/sports/?apiKey={oa['clave']}")
            futbol = [d for d in deportes or [] if str(d.get("key", "")).startswith("soccer")]
            piezas.append(_pieza("The Odds API", OK, f"Vale: {len(futbol)} competiciones "
                                                     "de fútbol disponibles."))
        except CasaNoDisponible as exc:
            piezas.append(_pieza("The Odds API", MAL, str(exc)))
    return piezas


# ------------------------------------------------------------ lo que hay hecho

def estado(almacen) -> list[dict]:
    """La guardia, el backtest y los picks: lo que ya está funcionando solo."""
    from .picks import mezcla_guardada

    piezas = []
    ultima = almacen.nota("ultima_guardia")
    if not ultima:
        piezas.append(_pieza("Guardia", AVISO, "No ha pasado nunca.",
                             "`cancha arrancar` la deja trabajando cada noche; "
                             "`cancha guardia --una-vez` la prueba ahora."))
    else:
        piezas.append(_pieza("Guardia", OK, f"Última vuelta: {ultima[:16]}."))
    mezcla = mezcla_guardada(almacen)
    if not mezcla:
        piezas.append(_pieza("Backtest", AVISO, "Sin hacer: los picks salen del modelo a "
                                                "secas, sin validar.",
                             "Trae historia y haz `cancha backtest`."))
    else:
        piezas.append(_pieza("Backtest", OK if mezcla.get("veredicto") == "aporta" else AVISO,
                             f"{mezcla.get('veredicto')} · peso {mezcla.get('peso', 0):.0%} · "
                             f"{mezcla.get('partidos')} partidos.",
                             "" if mezcla.get("peso") else
                             "Con peso cero no hay picks: es lo honesto con este modelo."))
    return piezas


# --------------------------------------------------------------- todo junto

def comprobar(almacen, cliente, ajustes: dict, con_red: bool = True,
              avisar: Callable[[dict], None] | None = None, cerrojo: Any = None) -> dict:
    """Todas las piezas, en el orden en que dependen unas de otras.

    ``cerrojo`` es el del servidor web: se coge solo para lo que lee la memoria,
    nunca mientras se espera a Ollama o a Telegram, que pueden tardar un minuto.
    """
    from contextlib import nullcontext

    from .tls import contexto

    candado = cerrojo or nullcontext()

    decir = avisar or (lambda _p: None)
    piezas: list[dict] = []
    red = ajustes.get("red") or {}
    tls = contexto(red.get("ca_bundle") or None, bool(red.get("sin_verificar")))

    def apuntar(salida):
        for pieza in salida if isinstance(salida, list) else [salida]:
            piezas.append(pieza)
            decir(pieza)

    with candado:
        apuntar(memoria(almacen))
    if con_red:
        def con_la_memoria():
            with candado:
                return sofascore(cliente, almacen)

        for paso in (con_la_memoria, lambda: ollama(ajustes),
                     lambda: nube(ajustes, tls), lambda: telegram(ajustes),
                     lambda: casas(ajustes, tls)):
            try:
                apuntar(paso())
            except Exception as exc:  # noqa: BLE001 - una pieza no para la lista
                apuntar(_pieza("(comprobación)", MAL, f"{type(exc).__name__}: {exc}"))
    with candado:
        apuntar(estado(almacen))
    malas = [p for p in piezas if p["estado"] == MAL]
    return {"piezas": piezas, "malas": len(malas),
            "avisos": sum(1 for p in piezas if p["estado"] == AVISO),
            "listo": not malas, "con_red": con_red}


def texto(datos: dict) -> list[str]:
    lineas = []
    for pieza in datos["piezas"]:
        lineas.append(f"{ICONOS[pieza['estado']]} {pieza['nombre']:<30} {pieza['detalle']}")
        if pieza.get("arreglo") and pieza["estado"] != OK:
            lineas.append(f"  {'':<30} → {pieza['arreglo']}")
    if not datos["listo"]:
        final = (f"{datos['malas']} cosa{'s' if datos['malas'] != 1 else ''} que arreglar "
                 "antes de fiarse de nada.")
    elif datos["avisos"]:
        final = (f"Nada roto. {datos['avisos']} aviso{'s' if datos['avisos'] != 1 else ''}"
                 " que conviene mirar.")
    else:
        final = "Todo listo."
    if not datos.get("con_red", True):
        final += " (Sin probar lo de fuera: quítale --sin-red.)"
    lineas += ["", final]
    return lineas


def linea(pieza: dict) -> str:
    """Una pieza en una línea, para ir contándolas según salen."""
    return f"{ICONOS[pieza['estado']]} {pieza['nombre']}: {pieza['detalle']}"


__all__ = ["APAGADO", "AVISO", "MAL", "OK", "comprobar", "linea", "texto"]
