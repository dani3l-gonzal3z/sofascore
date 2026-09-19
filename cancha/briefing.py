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
) -> dict:
    """Todo lo que se sabe de todos los partidos de un día."""
    dia = fecha or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    eventos = agenda(cliente, dia, grupos)
    partidos = [_partido(almacen, cliente, evento, ultimos, jugadores, duelos_por_equipo)
                for evento in eventos]
    competiciones = sorted({p["partido"]["competicion"] for p in partidos})
    return {
        "fecha": dia,
        "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "partidos": partidos,
        "competiciones": competiciones,
        "total": len(partidos),
        "memoria": almacen.resumen(),
        "lo_que_no_dice": (
            "Esto describe cómo llegan, no quién va a ganar. Las rachas son "
            "rachas, los hallazgos contra un sistema son de muestras cortas y el "
            "mercado es una previsión, no un resultado."
        ),
    }


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


__all__ = ["briefing", "a_markdown", "guardar", "guardados", "cargar", "CARPETA_POR_DEFECTO"]
