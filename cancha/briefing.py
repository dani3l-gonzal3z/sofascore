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
        "portada": portada(almacen, dia, partidos),
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
    {"apartado": "Nuestro pronóstico",
     "sale_de": "cancha.pronostico",
     "con_que": "Fuerzas de ataque y defensa de cada equipo sobre xG (o goles si no "
                "hay xG), encogidas hacia la media cuando hay poca muestra, y una "
                "Poisson con la corrección de Dixon-Coles para los marcadores bajos.",
     "muestra": "al menos los partidos de «muestra» de cada equipo"},
    {"apartado": "Contra el mercado",
     "sale_de": "cancha.mercados",
     "con_que": "De cada suceso, la casa que menos cobra, con su probabilidad sin "
                "margen. Se marca donde nos separamos más de cinco puntos: ahí o "
                "sabemos algo o, más a menudo, el mercado sabe algo que nosotros no."},
    {"apartado": "Pick",
     "sale_de": "cancha.picks",
     "con_que": "La regla fija (cuota, valor, separación, muestra y margen). Si "
                "ningún suceso del partido la pasa, no hay pick."},
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

    # Lo que faltaba, y era lo más útil para decidir: nuestro pronóstico, lo que
    # dice el mercado de cada cosa al lado, y si el partido tiene pick. Antes el
    # briefing contaba cómo llegaban los equipos pero no qué se esperaba del
    # partido ni dónde no estábamos de acuerdo con las casas.
    from .mercados import frente_al_mercado
    from .picks import candidatos
    from .pronostico import pronostico

    try:
        pron = pronostico(almacen, evento, cliente=cliente)
    except Exception as exc:  # noqa: BLE001 - un partido no tumba el briefing
        pron = {"disponible": False, "nota": str(exc)}
    datos["pronostico"] = _resumen_pronostico(pron)
    try:
        datos["frente_al_mercado"] = frente_al_mercado(almacen, evento.id, pron)
        datos["candidatos"] = [c for c in candidatos(almacen, evento.id, pron)
                               if c["pasa"]][:1]
    except Exception as exc:  # noqa: BLE001
        datos["frente_al_mercado"] = {"disponible": False, "nota": str(exc)}
        datos["candidatos"] = []
    for candidato in datos["candidatos"]:
        candidato["partido"] = f"{evento.home.name} - {evento.away.name}"
        candidato["hora_utc"] = datos["partido"].get("hora_utc")
    return datos


def _resumen_pronostico(pron: dict) -> dict:
    """Lo del pronóstico que cabe en un briefing: los números y su muestra."""
    if not pron.get("disponible"):
        return {"disponible": False, "nota": pron.get("nota") or "sin muestra"}
    g = pron["goles"]
    fuerzas = g.get("fuerzas") or {}
    return {
        "disponible": True,
        "1x2": g["1x2"], "esperados": g.get("esperados"),
        "marcadores": g.get("marcadores", [])[:5],
        "mas_2_5": (g.get("mas_de") or {}).get("2.5"),
        "ambos_marcan": g.get("ambos_marcan"),
        "corners_mas_9_5": ((pron.get("corners") or {}).get("mas_de") or {}).get("9.5"),
        "tarjetas_mas_3_5": ((pron.get("tarjetas") or {}).get("mas_de") or {}).get("3.5"),
        "muestra": min((fuerzas.get(lado) or {}).get("partidos") or 0
                       for lado in ("local", "visitante")),
        "medido_en": g.get("medido_en"),
    }


def portada(almacen, dia: str, partidos: list[dict]) -> dict:
    """Lo primero que se lee: lo de ayer, los picks y dónde discrepamos.

    En ese orden a propósito. Empezar el día viendo si lo de ayer salió es más
    honesto que empezar prometiendo lo de hoy, y es lo que hace creíble lo que
    viene después.
    """
    picks = sorted((c for p in partidos for c in p.get("candidatos") or []),
                   key=lambda c: -c["valor"])
    discrepancias = []
    for p in partidos:
        nombre = f"{p['partido']['local']} - {p['partido']['visitante']}"
        for s in (p.get("frente_al_mercado") or {}).get("sucesos") or []:
            if s.get("discrepa"):
                discrepancias.append({**s, "partido": nombre})
    discrepancias.sort(key=lambda s: -abs(s["diferencia"]))
    return {"ayer": _ayer(almacen, dia), "pick": picks[:1], "picks": picks,
            "discrepancias": discrepancias[:8]}


def _ayer(almacen, dia: str) -> dict:
    """Cómo salió el día anterior: sus picks, y el cálculo contra el mercado."""
    from datetime import date, timedelta

    from .registro import balance

    try:
        antes = (date.fromisoformat(dia) - timedelta(days=1)).isoformat()
    except ValueError:
        return {}
    picks = almacen.consulta(
        """SELECT k.*, m.local || ' - ' || m.visitante AS partido FROM picks k
           LEFT JOIN partidos m ON m.id = k.partido_id
           WHERE k.fecha = ? AND k.nivel = 'premium' ORDER BY k.valor DESC""", (antes,))
    registro = balance(almacen, desde=antes, hasta=antes, autor="calculo", mercado="1x2")
    return {
        "fecha": antes,
        "picks": [{"partido": f["partido"], "suceso": f["suceso"], "cuota": f["cuota"],
                   "resuelto": bool(f["resuelto"]), "acerto": f["acerto"],
                   "beneficio": f["beneficio"]} for f in picks],
        "unidades": round(sum(f["beneficio"] or 0 for f in picks if f["resuelto"]), 2),
        "registro": {"casos": registro.get("casos", 0), "brier": registro.get("brier"),
                     "contra_el_mercado": (registro.get("contra_el_mercado") or {})
                     .get("lectura")},
    }


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

    lineas += _texto_portada(datos.get("portada") or {})

    por_liga: dict[str, list[dict]] = {}
    for partido in datos["partidos"]:
        por_liga.setdefault(partido["partido"]["competicion"] or "Otros", []).append(partido)

    for liga in sorted(por_liga):
        lineas += [f"## {liga}", ""]
        for partido in por_liga[liga]:
            lineas += _bloque_partido(partido)
    lineas += ["---", "", f"_{datos['lo_que_no_dice']}_", ""]
    return "\n".join(lineas) + "\n"


def _texto_portada(portada: dict) -> list[str]:
    """Lo de ayer, los picks y las discrepancias, antes que ningún partido."""
    if not portada:
        return []
    lineas = []
    ayer = portada.get("ayer") or {}
    if ayer.get("picks"):
        lineas += [f"## Lo de ayer ({ayer['fecha']})", ""]
        for pick in ayer["picks"]:
            estado = ("pendiente" if not pick["resuelto"]
                      else "✅ acertado" if pick["acerto"] else "❌ fallado")
            lineas.append(f"- {pick['partido']}: {pick['suceso']} a {pick['cuota']} — "
                          f"{estado}")
        lineas += [f"- **{ayer['unidades']:+.2f} unidades** en el día", ""]
    elif (ayer.get("registro") or {}).get("casos"):
        lineas += [f"## Lo de ayer ({ayer['fecha']})", "",
                   f"{ayer['registro']['casos']} predicciones de 1X2 resueltas. "
                   f"{ayer['registro'].get('contra_el_mercado') or ''}".strip(), ""]

    lineas += ["## El pick del día", ""]
    if portada.get("pick"):
        pick = portada["pick"][0]
        lineas += [f"**{pick['partido']}** — {pick['suceso']} a **{pick['cuota']}** "
                   f"({pick['casa']})",
                   f"Nosotros {pick['prob_nuestra']:.0%} · mercado "
                   f"{pick['prob_mercado']:.0%} · valor {pick['valor']:+.0%}", ""]
        if len(portada.get("picks") or []) > 1:
            lineas += ["**Los demás que pasan la regla:**"]
            for pick in portada["picks"][1:]:
                lineas.append(f"- {pick['partido']}: {pick['suceso']} a {pick['cuota']} "
                              f"(valor {pick['valor']:+.0%})")
            lineas.append("")
    else:
        lineas += ["Hoy nada pasa la regla, así que no hay pick. Un día sin pick no es "
                   "un fallo: es lo que hace creíble el día que sí lo hay.", ""]

    if portada.get("discrepancias"):
        lineas += ["## Dónde no estamos de acuerdo con el mercado", "",
                   "_Lo más probable es que el mercado sepa algo que nosotros no; las "
                   "que además tienen valor ya están arriba como picks._", ""]
        for s in portada["discrepancias"]:
            lineas.append(f"- {s['partido']}: {s['suceso']} — nosotros "
                          f"{s['nuestra']:.0%}, mercado {s['mercado']:.0%} "
                          f"({s['diferencia']:+.0%})")
        lineas.append("")
    return lineas + ["---", ""]


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

    pron = datos.get("pronostico") or {}
    if pron.get("disponible"):
        uno = pron["1x2"]
        lineas.append(f"**Nuestro pronóstico:** {uno['local']:.0%} · {uno['empate']:.0%} · "
                      f"{uno['visitante']:.0%} — goles esperados "
                      f"{(pron.get('esperados') or {}).get('local')}-"
                      f"{(pron.get('esperados') or {}).get('visitante')} · marcadores "
                      + ", ".join(f"{m['marcador']} ({m['probabilidad']:.0%})"
                                  for m in pron.get("marcadores", [])[:3])
                      + f" · muestra {pron.get('muestra')} partidos")
        lineas.append("")
    elif pron:
        lineas += [f"**Nuestro pronóstico:** {pron.get('nota')}", ""]

    frente = datos.get("frente_al_mercado") or {}
    discrepa = [s for s in frente.get("sucesos") or [] if s.get("discrepa")]
    if discrepa:
        lineas.append("**Contra el mercado:** " + "; ".join(
            f"{s['suceso']} nosotros {s['nuestra']:.0%}, mercado {s['mercado']:.0%}"
            for s in discrepa))
        lineas.append("")
    for candidato in datos.get("candidatos") or []:
        lineas += [f"**Pick:** {candidato['suceso']} a {candidato['cuota']} "
                   f"({candidato['casa']}), valor {candidato['valor']:+.0%}", ""]

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
