"""El briefing: lo que un analista querría tener encima de la mesa a las ocho.

Es la tarea diaria de la que salió todo lo demás: mirar qué se juega hoy en
las ligas que importan y, de cada partido, saber cómo llegan los dos, cómo
juegan, si han cambiado, quién lleva racha, qué le pasa a sus jugadores contra
el sistema que van a tener enfrente, qué dice el mercado y quién pita.

Nada de esto es nuevo: :mod:`cancha.previa`, :mod:`cancha.sistemas` y
:mod:`cancha.perfiles` ya lo contestan por separado. Aquí se junta en un
documento por día, en Markdown para leerlo y en JSON para que una IA lo
tenga entero en una sola llamada.

    cancha briefing                  # hoy, en datos/briefings/AAAA-MM-DD.md
    cancha briefing --barrer         # barre primero y luego lo escribe

Se apoya en la memoria: sin barrido, cada partido sale con «haz un barrido» en
vez de con un análisis, que es lo honesto.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .almacen import Almacen
from .barrido import agenda
from .client import SofascoreClient
from .models import Event
from .perfiles import evolucion_de_estilo
from .previa import previa
from .sistemas import duelo

CARPETA_POR_DEFECTO = "datos/briefings"


def briefing(
    almacen: Almacen,
    cliente: SofascoreClient,
    fecha: str | None = None,
    grupos: list[str] | None = None,
    ultimos: int = 6,
    jugadores: int = 3,
    duelos_por_equipo: int = 2,
    avisar: Callable[[str], None] | None = None,
    puede_seguir: Callable[[], bool] | None = None,
) -> dict:
    """Todo lo que se sabe de todos los partidos de un día.

    Esto **tarda**: un día normal son doscientos y pico partidos, y de cada uno
    se monta la previa entera, la evolución de estilo de los dos equipos y los
    duelos de sus jugadores a seguir. Son miles de peticiones y varios minutos.

    Por eso `avisar` va contando por dónde va y `puede_seguir` deja cortarlo: un
    briefing a medias con ochenta partidos hechos vale mucho más que nada, así
    que lo que se lleve hecho se guarda igual y queda dicho que está incompleto.
    """
    decir = avisar or (lambda _t: None)
    sigue = puede_seguir or (lambda: True)
    dia = fecha or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    decir(f"Buscando lo que se juega el {dia}…")
    eventos = agenda(cliente, dia, grupos)
    decir(f"{len(eventos)} partidos. Ahora, uno a uno: cómo llegan, si han "
          "cambiado y qué les pasa a sus jugadores contra el rival de hoy.")

    partidos, completo = [], True
    for numero, evento in enumerate(eventos, 1):
        if not sigue():
            decir(f"Parado a petición tuya, con {len(partidos)} de {len(eventos)} "
                  "hechos. Lo hecho se guarda.")
            completo = False
            break
        partidos.append(_partido(almacen, cliente, evento, ultimos, jugadores,
                                 duelos_por_equipo))
        # Cada diez, no cada uno: doscientas líneas no son un progreso, son ruido.
        if numero % 10 == 0 or numero == len(eventos):
            decir(f"{numero}/{len(eventos)} · {evento.home.name} - {evento.away.name}")

    competiciones = sorted({p["partido"]["competicion"] for p in partidos})
    return {
        "fecha": dia,
        "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "partidos": partidos,
        "competiciones": competiciones,
        "total": len(partidos),
        "de_cuantos": len(eventos),
        "completo": completo,
        "memoria": almacen.resumen(),
        "que_lleva": QUE_LLEVA,
        "lo_que_no_dice": (
            "Esto describe cómo llegan, no quién va a ganar. Las rachas son "
            "rachas, los hallazgos contra un sistema son de muestras cortas y el "
            "mercado es una previsión, no un resultado."
        ),
    }


#: Qué trae cada partido del briefing y de dónde sale cada cosa. Está aquí, y
#: viaja dentro del propio briefing, porque «¿con qué ha calculado esto?» es la
#: primera pregunta razonable ante un número, y no tener respuesta a mano
#: convierte un análisis en un horóscopo.
QUE_LLEVA = [
    {"apartado": "Cómo llega cada equipo",
     "sale_de": "cancha.previa",
     "con_que": "Los últimos partidos guardados de cada uno, de la memoria. No "
                "se piden a la fuente: si no has barrido, sale corto y lo dice.",
     "muestra": "«ultimos», 6 por defecto"},
    {"apartado": "Cómo juega, comparado con su liga",
     "sale_de": "cancha.perfiles",
     "con_que": "Las estadísticas de esos partidos contra la media de su "
                "competición en la memoria. Por eso una liga con pocos partidos "
                "guardados da «sin media de liga con la que comparar todavía»."},
    {"apartado": "Si ha cambiado",
     "sale_de": "cancha.perfiles.evolucion_de_estilo",
     "con_que": "Compara sus partidos recientes con los de antes y solo cuenta "
                "lo que se mueve más de lo que se movería por azar."},
    {"apartado": "Jugador contra sistema",
     "sale_de": "cancha.sistemas.duelo",
     "con_que": "Cómo rinde cada jugador a seguir contra equipos que plantean lo "
                "mismo que el rival de hoy, con su prueba de significación. Solo "
                "entra lo que la pasa: un briefing con cien números no se lee."},
    {"apartado": "Lo que dice el mercado",
     "sale_de": "las cuotas guardadas",
     "con_que": "Las cuotas de la fuente, convertidas a probabilidad quitándoles "
                "el margen de la casa. Es una previsión, no un resultado."},
    {"apartado": "El árbitro",
     "sale_de": "cancha.perfiles",
     "con_que": "Sus partidos en la memoria: tarjetas y faltas por partido "
                "contra la media. Sin árbitro designado todavía, se dice."},
]


def _partido(almacen: Almacen, cliente: SofascoreClient, evento: Event,
             ultimos: int, jugadores: int, duelos_por_equipo: int) -> dict:
    datos = previa(almacen, evento, cliente=cliente, ultimos=ultimos,
                   jugadores_por_equipo=jugadores)
    datos["partido"]["hora_utc"] = evento.kickoff.strftime("%H:%M") if evento.kickoff else None
    datos["partido"]["local_id"] = evento.home.id
    datos["partido"]["visitante_id"] = evento.away.id

    datos["evolucion"] = {}
    for lado, equipo in (("local", evento.home), ("visitante", evento.away)):
        if equipo.id:
            evolucion = evolucion_de_estilo(almacen, equipo.id)
            datos["evolucion"][lado] = (
                evolucion.get("lo_que_ha_cambiado", []) if evolucion.get("disponible") else [])

    datos["duelos"] = _duelos(almacen, evento, datos.get("jugadores") or {}, duelos_por_equipo)
    return datos


def _duelos(almacen: Almacen, evento: Event, a_seguir: dict, cuantos: int) -> list[dict]:
    """Qué le pasa a los jugadores a seguir contra lo que plantea el rival de hoy.

    Solo entra lo que ha pasado el filtro estadístico: un briefing con cien
    números es un briefing que nadie lee.
    """
    salida = []
    for lado, rival in (("local", evento.away), ("visitante", evento.home)):
        if not rival.id:
            continue
        for jugador in (a_seguir.get(lado) or [])[:cuantos]:
            resultado = duelo(almacen, jugador["jugador_id"], rival.id)
            if not resultado.get("disponible"):
                continue
            for eje, bloque in (resultado.get("por_eje") or {}).items():
                resumen = bloque.get("resumen") or {}
                for hallazgo in resumen.get("relevante") or []:
                    salida.append({
                        "jugador": resultado["jugador"],
                        "jugador_id": jugador["jugador_id"],
                        "rival": rival.name,
                        "eje": eje,
                        "el_rival_es": bloque["el_rival_es"],
                        "metrica": hallazgo["metrica"],
                        "por_90": hallazgo["por_90"],
                        "su_media": hallazgo["su_media"],
                        "partidos": hallazgo["partidos"],
                        "veredicto": hallazgo["veredicto"],
                        "p": hallazgo["p"],
                    })
    salida.sort(key=lambda h: h["p"])
    return salida


# ------------------------------------------------------------------ markdown

def a_markdown(datos: dict) -> str:
    """El briefing como documento: por competición, un bloque por partido."""
    lineas = [f"# Briefing del {datos['fecha']}", ""]
    memoria = datos.get("memoria") or {}
    lineas.append(
        f"{datos['total']} partidos en {len(datos['competiciones'])} competiciones · "
        f"memoria con {memoria.get('partidos', 0)} partidos "
        f"(último barrido: {memoria.get('ultimo_barrido', 'nunca')})")
    lineas.append("")
    if not datos["partidos"]:
        lineas.append("No hay partidos ese día en las competiciones elegidas.")
        return "\n".join(lineas) + "\n"

    por_liga: dict[str, list[dict]] = {}
    for partido in datos["partidos"]:
        por_liga.setdefault(partido["partido"]["competicion"] or "Otros", []).append(partido)

    for liga in sorted(por_liga):
        lineas += [f"## {liga}", ""]
        for partido in por_liga[liga]:
            lineas += _bloque_partido(partido)
    lineas += ["---", "", f"_{datos['lo_que_no_dice']}_", ""]
    return "\n".join(lineas) + "\n"


def _bloque_partido(datos: dict) -> list[str]:
    p = datos["partido"]
    hora = f"{p['hora_utc']} UTC · " if p.get("hora_utc") else ""
    lineas = [f"### {p['local']} - {p['visitante']}", "",
              f"{hora}{p.get('sede') or ''}".strip(" ·"), ""]

    mercado = datos.get("mercado") or {}
    if mercado.get("disponible"):
        probs = mercado["probabilidades"]
        lineas.append(f"**Mercado:** {probs.get('local', 0):.0%} · {probs.get('empate', 0):.0%} "
                      f"· {probs.get('visitante', 0):.0%} — {mercado['favorito']['lectura']}")
        lineas.append("")

    for lado in ("local", "visitante"):
        estilo = (datos.get("equipos") or {}).get(lado) or {}
        nombre = p[lado]
        if not estilo.get("disponible"):
            lineas += [f"**{nombre}:** {estilo.get('nota', 'sin datos en la memoria')}", ""]
            continue
        r = estilo["resultados"]
        lineas.append(f"**{nombre}** — {estilo['partidos_mirados']} últimos: {r['racha']}, "
                      f"{r['goles_favor']}-{r['goles_contra']}")
        for rasgo in estilo.get("lo_que_le_distingue", [])[:4]:
            lineas.append(f"- {rasgo['rasgo']} ({rasgo['cuanto']})")
        for cambio in (datos.get("evolucion") or {}).get(lado) or []:
            lineas.append(f"- ha cambiado: {cambio['lectura']} ({cambio['cambio']})")
        for jugador in (datos.get("jugadores") or {}).get(lado) or []:
            if jugador.get("rachas"):
                lineas.append(f"- {jugador['jugador']}: {', '.join(jugador['rachas'])}")
        lineas.append("")

    cruces = datos.get("donde_se_hacen_dano") or []
    if cruces:
        lineas.append("**Dónde se pueden hacer daño**")
        lineas += [f"- {c['aviso']}" for c in cruces]
        lineas.append("")

    duelos = datos.get("duelos") or []
    if duelos:
        lineas.append("**Jugador contra sistema**")
        for d in duelos[:6]:
            lineas.append(
                f"- {d['jugador']} contra {d['el_rival_es']} ({d['rival']}): "
                f"{d['metrica']} {d['por_90']}/90 frente a su media de {d['su_media']} "
                f"— {d['veredicto']}, {d['partidos']} partidos")
        lineas.append("")

    arbitro = datos.get("arbitro") or {}
    if arbitro.get("disponible"):
        por = arbitro["por_partido"]
        lineas.append(f"**Árbitro:** {arbitro['arbitro']} — {por['amarillas']} amarillas, "
                      f"{por['penaltis']} penaltis y {por['faltas']} faltas por partido "
                      f"({arbitro['partidos_mirados']} partidos)")
    elif arbitro.get("nota"):
        lineas.append(f"**Árbitro:** {arbitro['nota']}")
    lineas.append("")
    return lineas


def guardar(datos: dict, carpeta: str | Path = CARPETA_POR_DEFECTO) -> dict[str, Path]:
    """Escribe el briefing en Markdown y en JSON, uno por día."""
    destino = Path(carpeta)
    destino.mkdir(parents=True, exist_ok=True)
    markdown = destino / f"{datos['fecha']}.md"
    fichero_json = destino / f"{datos['fecha']}.json"
    markdown.write_text(a_markdown(datos), encoding="utf-8")
    fichero_json.write_text(json.dumps(datos, ensure_ascii=False, indent=1, default=str),
                            encoding="utf-8")
    return {"markdown": markdown, "json": fichero_json}


def guardados(carpeta: str | Path = CARPETA_POR_DEFECTO) -> list[str]:
    """Las fechas de los briefings que hay escritos, de la más reciente atrás."""
    destino = Path(carpeta)
    if not destino.is_dir():
        return []
    return sorted((f.stem for f in destino.glob("*.json")), reverse=True)


def cargar(fecha: str, carpeta: str | Path = CARPETA_POR_DEFECTO) -> dict[str, Any] | None:
    fichero = Path(carpeta) / f"{fecha}.json"
    if not fichero.is_file():
        return None
    return json.loads(fichero.read_text(encoding="utf-8"))


__all__ = ["CARPETA_POR_DEFECTO", "QUE_LLEVA", "a_markdown", "briefing", "cargar",
           "guardar", "guardados"]
