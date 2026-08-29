"""Exportar el informe: JSON completo, Markdown legible y CSV tabulados."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .match import MatchReport

# --------------------------------------------------------------------------- JSON

def to_json(informe: MatchReport, ruta: str | Path | None = None, indent: int = 2) -> str:
    """Serializa el informe entero. Si hay ``ruta``, además lo guarda."""
    texto = json.dumps(informe.to_dict(), ensure_ascii=False, indent=indent, default=str)
    if ruta:
        destino = Path(ruta)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(texto, encoding="utf-8")
    return texto


# ----------------------------------------------------------------------- Markdown

def _tabla_estadisticas(informe: MatchReport) -> list[str]:
    bloques = informe.get("statistics") or []
    if not bloques:
        return []
    lineas: list[str] = []
    for bloque in bloques:
        periodo = bloque.get("period", "ALL")
        lineas.append(f"### Estadísticas ({periodo})\n")
        lineas.append(f"| Estadística | {informe.event.home} | {informe.event.away} |")
        lineas.append("| --- | ---: | ---: |")
        for grupo in bloque.get("groups", []) or []:
            for item in grupo.get("statisticsItems", []) or []:
                lineas.append(
                    f"| {item.get('name', '')} | {item.get('home', '')} | {item.get('away', '')} |"
                )
        lineas.append("")
    return lineas


def _cronologia(informe: MatchReport) -> list[str]:
    if not informe.get("incidents"):
        return []
    lineas = ["### Cronología\n"]
    for incidencia in informe.incidents():
        tipo = incidencia.get("incidentType", "")
        if tipo in {"period", "injuryTime"}:
            continue
        minuto = incidencia.get("time")
        anadido = incidencia.get("addedTime")
        reloj = f"{minuto}'" + (f"+{anadido}" if anadido else "") if minuto is not None else "—"
        jugador = _nombre(incidencia, "player", "playerIn")
        sale = _nombre(incidencia, "playerOut")
        if sale:
            jugador = f"{jugador} ← {sale}" if jugador else f"sale {sale}"
        asistencia = _nombre(incidencia, "assist1")
        if asistencia:
            jugador = f"{jugador} (asist. {asistencia})"
        detalle = incidencia.get("incidentClass") or incidencia.get("text") or ""
        marcador = ""
        if incidencia.get("homeScore") is not None:
            marcador = f" [{incidencia['homeScore']}-{incidencia.get('awayScore')}]"
        lineas.append(f"- **{reloj}** {tipo} {detalle} {jugador}{marcador}".rstrip())
    lineas.append("")
    return lineas


def _alineaciones(informe: MatchReport) -> list[str]:
    alineaciones = informe.get("lineups")
    if not alineaciones:
        return []
    lineas = ["### Alineaciones\n"]
    for lado, equipo in (("home", informe.event.home), ("away", informe.event.away)):
        bloque = alineaciones.get(lado) or {}
        formacion = bloque.get("formation", "")
        lineas.append(f"**{equipo}**" + (f" — {formacion}" if formacion else ""))
        titulares, suplentes = [], []
        for entrada in bloque.get("players", []) or []:
            jugador = entrada.get("player", {})
            dorsal = entrada.get("shirtNumber") or jugador.get("jerseyNumber") or ""
            nombre = f"{dorsal} {jugador.get('name', '')}".strip()
            (suplentes if entrada.get("substitute") else titulares).append(nombre)
        lineas.append("- Titulares: " + ", ".join(titulares))
        if suplentes:
            lineas.append("- Suplentes: " + ", ".join(suplentes))
        lineas.append("")
    return lineas


def to_markdown(informe: MatchReport, ruta: str | Path | None = None) -> str:
    """Informe legible para humanos."""
    evento = informe.event
    lineas = [
        f"# {evento.home} {evento.scoreline} {evento.away}",
        "",
        f"- **Competición:** {evento.tournament}"
        + (f" · {evento.season_name}" if evento.season_name else "")
        + (f" · jornada {evento.round}" if evento.round else ""),
        f"- **Fecha:** {evento.kickoff.isoformat() if evento.kickoff else 'desconocida'}",
        f"- **Estado:** {evento.status_description or evento.status_type}",
    ]
    if evento.venue:
        ciudad = f" ({evento.city})" if evento.city else ""
        lineas.append(f"- **Estadio:** {evento.venue}{ciudad}")
    if evento.referee:
        lineas.append(f"- **Árbitro:** {evento.referee}")
    if evento.attendance:
        lineas.append(f"- **Asistencia:** {evento.attendance}")
    lineas += [f"- **Ficha:** {evento.url}", ""]

    lineas += _tabla_estadisticas(informe)
    lineas += _cronologia(informe)
    lineas += _alineaciones(informe)

    lineas.append("### Secciones\n")
    for nombre, resultado in informe.sections.items():
        marca = {"ok": "✓", "empty": "·", "plus_required": "🔒", "unavailable": "–", "error": "✗"}
        lineas.append(
            f"- {marca.get(resultado.status, '?')} `{nombre}` — {resultado.status}"
            + (f" ({resultado.error})" if resultado.error else "")
        )
    if nota := informe.meta.get("nota_plus"):
        lineas += ["", f"> {nota}"]

    texto = "\n".join(lineas) + "\n"
    if ruta:
        destino = Path(ruta)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(texto, encoding="utf-8")
    return texto


# ---------------------------------------------------------------------------- CSV

def _filas_estadisticas(informe: MatchReport) -> list[dict]:
    filas = []
    for bloque in informe.get("statistics") or []:
        periodo = bloque.get("period", "ALL")
        for grupo in bloque.get("groups", []) or []:
            for item in grupo.get("statisticsItems", []) or []:
                filas.append({
                    "periodo": periodo,
                    "grupo": grupo.get("groupName", ""),
                    "clave": item.get("key", ""),
                    "estadistica": item.get("name", ""),
                    "local": item.get("home", ""),
                    "visitante": item.get("away", ""),
                    "local_valor": item.get("homeValue", ""),
                    "visitante_valor": item.get("awayValue", ""),
                })
    return filas


def _nombre(incidencia: dict, *claves: str) -> str:
    """Primer nombre de jugador que aparezca en esas claves de la incidencia.

    La API mete al jugador en una clave distinta según el tipo de incidencia
    (``player`` en un gol o una tarjeta, entrante y saliente en un cambio), así
    que se prueban varias y se coge la que haya.
    """
    for clave in claves:
        valor = incidencia.get(clave)
        if isinstance(valor, dict) and valor.get("name"):
            return valor["name"]
    return ""


def _filas_incidencias(informe: MatchReport) -> list[dict]:
    # En orden: la API las devuelve del final al principio, y una cronología
    # que va hacia atrás no es una cronología.
    return [
        {
            "minuto": i.get("time", ""),
            "anadido": i.get("addedTime", ""),
            "tipo": i.get("incidentType", ""),
            "clase": i.get("incidentClass", ""),
            "equipo": "" if i.get("isHome") is None else ("local" if i["isHome"] else "visitante"),
            "jugador": _nombre(i, "player", "playerIn"),
            "jugador_sale": _nombre(i, "playerOut"),
            "asistencia": _nombre(i, "assist1"),
            "marcador_local": i.get("homeScore", ""),
            "marcador_visitante": i.get("awayScore", ""),
        }
        for i in informe.incidents()
    ]


def _filas_alineaciones(informe: MatchReport) -> list[dict]:
    filas = []
    for jugador in informe.players():
        estadisticas = (jugador.raw or {}).get("statistics") or {}
        filas.append({
            "jugador_id": jugador.id,
            "jugador": jugador.name,
            "equipo_id": jugador.team_id,
            "posicion": jugador.position,
            "dorsal": jugador.shirt_number or "",
            "suplente": jugador.substitute,
            "minutos": estadisticas.get("minutesPlayed", ""),
            "valoracion": estadisticas.get("rating", ""),
        })
    return filas


def _filas_tiros(informe: MatchReport) -> list[dict]:
    return [
        {
            "jugador": (t.get("player") or {}).get("name", ""),
            "equipo": "local" if t.get("isHome") else "visitante",
            "minuto": t.get("time", ""),
            "tipo": t.get("shotType", ""),
            "situacion": t.get("situation", ""),
            "parte_cuerpo": t.get("bodyPart", ""),
            "xg": t.get("xg", ""),
            "xgot": t.get("xgot", ""),
        }
        for t in informe.get("shotmap") or []
    ]


def _filas_partido(informe: MatchReport) -> list[dict]:
    """Una sola fila con la cabecera del partido: para juntar muchos partidos."""
    cabecera = informe.event.to_dict()
    local = cabecera.pop("home", {})
    visitante = cabecera.pop("away", {})
    for lado, datos in (("local", local), ("visitante", visitante)):
        for campo, valor in (datos or {}).items():
            cabecera[f"{lado}_{campo}"] = valor
    return [cabecera]


def _filas_momento(informe: MatchReport) -> list[dict]:
    return [
        {"minuto": p.get("minute", ""), "valor": p.get("value", "")}
        for p in informe.get("momentum") or []
        if isinstance(p, dict)
    ]


def _filas_posiciones(informe: MatchReport) -> list[dict]:
    filas = []
    for lado in ("home", "away"):
        for entrada in (informe.get("average_positions") or {}).get(lado, []) or []:
            jugador = entrada.get("player") or {}
            filas.append({
                "equipo": "local" if lado == "home" else "visitante",
                "jugador_id": jugador.get("id", ""),
                "jugador": jugador.get("name", ""),
                "x": entrada.get("averageX", ""),
                "y": entrada.get("averageY", ""),
                "toques": entrada.get("pointsCount", ""),
            })
    return filas


def _filas_valoraciones(informe: MatchReport) -> list[dict]:
    return informe.ratings()


TABLAS = {
    "partido": _filas_partido,
    "estadisticas": _filas_estadisticas,
    "incidencias": _filas_incidencias,
    "alineaciones": _filas_alineaciones,
    "tiros": _filas_tiros,
    "valoraciones": _filas_valoraciones,
    "momento": _filas_momento,
    "posiciones_medias": _filas_posiciones,
}


def to_csv_dir(informe: MatchReport, directorio: str | Path) -> list[Path]:
    """Escribe un CSV por tabla disponible. Devuelve los ficheros creados."""
    destino = Path(directorio)
    destino.mkdir(parents=True, exist_ok=True)
    creados: list[Path] = []
    for nombre, constructor in TABLAS.items():
        filas = constructor(informe)
        if not filas:
            continue
        ruta = destino / f"{nombre}.csv"
        with ruta.open("w", encoding="utf-8", newline="") as fichero:
            escritor = csv.DictWriter(fichero, fieldnames=list(filas[0].keys()))
            escritor.writeheader()
            escritor.writerows(filas)
        creados.append(ruta)
    return creados
