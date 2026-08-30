"""La previa: todo lo que se sabe de un partido antes de que se juegue.

Es donde converge lo demás. Coge un partido por jugar y responde a las
preguntas que uno se hace mirando el calendario:

* ¿cómo llegan los dos, y cómo juegan?
* ¿en qué se van a hacer daño? (lo que uno hace bien contra lo que el otro
  defiende mal)
* ¿quién está en racha y quién lleva un mes sin aparecer?
* ¿quién pita, y cómo pita?

Todo sale de la memoria (:mod:`cancha.almacen`), así que **no sirve de nada sin
un barrido antes**. Lo dice claramente en vez de devolver un informe vacío.
"""

from __future__ import annotations

from typing import Any

from .almacen import Almacen
from .client import SofascoreClient
from .models import Event
from .perfiles import estilo_de_equipo, forma_de_jugador, perfil_de_arbitro
from .resolve import resolve_event

#: Cruces que merece la pena señalar: lo que uno hace mucho contra lo que el
#: otro concede mucho. Cada uno es (dimensión propia, clave concedida, lectura).
CRUCES = [
    ("corners", "cornerKicks", "vive del córner y enfrente conceden muchos"),
    ("centros", "accurateCross", "ataca por fuera y enfrente les entran los centros"),
    ("toques_en_area", "touchesInOppBox", "se mete en el área y enfrente les entran"),
    ("tiros", "totalShotsOnGoal", "tira mucho y enfrente les tiran mucho"),
    ("pases_largos", "accurateLongBalls", "juega en largo y enfrente lo sufren"),
]


def _equipo_de(evento: Event, lado: str):
    return evento.home if lado == "local" else evento.away


def previa(
    almacen: Almacen,
    partido: str | int | Event,
    cliente: SofascoreClient | None = None,
    ultimos: int = 6,
    jugadores_por_equipo: int = 4,
) -> dict:
    """Todo lo que se sabe de un partido, junto y ordenado."""
    evento = partido if isinstance(partido, Event) else _resolver(almacen, partido, cliente)
    if evento is None:
        return {"disponible": False,
                "nota": "No encuentro ese partido ni en la memoria ni en la API."}

    salida: dict[str, Any] = {
        "partido": {
            "id": evento.id,
            "local": evento.home.name,
            "visitante": evento.away.name,
            "fecha": evento.date,
            "competicion": evento.tournament,
            "sede": evento.venue,
            "estado": evento.status_description or evento.status_type,
        },
        "equipos": {},
        "jugadores": {},
    }

    for lado in ("local", "visitante"):
        equipo = _equipo_de(evento, lado)
        if not equipo.id:
            continue
        estilo = estilo_de_equipo(almacen, equipo.id, ultimos=ultimos)
        salida["equipos"][lado] = estilo
        salida["jugadores"][lado] = _a_seguir(
            almacen, equipo.id, cuantos=jugadores_por_equipo, ultimos=ultimos)

    salida["donde_se_hacen_dano"] = _cruces(salida["equipos"])
    salida["arbitro"] = (
        perfil_de_arbitro(almacen, evento.referee) if evento.referee
        else {"disponible": False, "nota": "El partido todavía no tiene árbitro designado."}
    )
    salida["memoria"] = _cobertura(salida)
    return salida


def _resolver(almacen: Almacen, partido: str | int,
              cliente: SofascoreClient | None) -> Event | None:
    """Busca el partido primero en la memoria y solo si no está, en la API."""
    if str(partido).isdigit():
        filas = almacen.consulta("SELECT * FROM partidos WHERE id = ?", (int(partido),))
        if filas:
            return _evento_desde_fila(filas[0])
    if cliente is None:
        return None
    return resolve_event(cliente, partido).event


def _evento_desde_fila(fila: dict) -> Event:
    """Reconstruye lo justo de un partido guardado para poder describirlo."""
    return Event.from_api({
        "id": fila["id"],
        "customId": fila.get("custom_id"),
        "startTimestamp": fila.get("momento"),
        "referee": {"name": fila.get("arbitro")} if fila.get("arbitro") else None,
        "venue": {"stadium": {"name": fila.get("sede")}} if fila.get("sede") else None,
        "status": {"type": fila.get("estado")},
        "tournament": {"name": fila.get("liga"),
                       "uniqueTournament": {"id": fila.get("liga_id")}},
        "season": {"id": fila.get("temporada_id")},
        "homeTeam": {"id": fila.get("local_id"), "name": fila.get("local")},
        "awayTeam": {"id": fila.get("visitante_id"), "name": fila.get("visitante")},
        "homeScore": {"current": fila.get("goles_local")},
        "awayScore": {"current": fila.get("goles_visitante")},
    })


def _a_seguir(almacen: Almacen, equipo_id: int, cuantos: int, ultimos: int) -> list[dict]:
    """Los jugadores del equipo que dan de qué hablar.

    No los mejores: los que llevan una racha, para bien o para mal. Un
    delantero con cinco partidos sin rematar entre palos cuenta más que uno que
    lleva haciendo lo mismo de siempre.
    """
    habituales = almacen.consulta(
        """SELECT a.jugador_id, a.jugador, COUNT(*) AS partidos, AVG(a.minutos) AS minutos
           FROM actuaciones a JOIN partidos p ON p.id = a.partido_id
           WHERE a.equipo_id = ? AND a.minutos > 0
           GROUP BY a.jugador_id ORDER BY partidos DESC, minutos DESC LIMIT 14""",
        (equipo_id,),
    )
    con_algo, sin_nada = [], []
    for fila in habituales:
        forma = forma_de_jugador(almacen, fila["jugador_id"], ultimas=ultimos)
        if not forma.get("disponible"):
            continue
        resumen = {
            "jugador": forma["jugador"],
            "jugador_id": forma["jugador_id"],
            "partidos": forma["partidos_mirados"],
            "rating_medio": forma["rating_medio"],
            "por_partido": forma["por_partido"],
            "rachas": [r["racha"] for r in forma["rachas"]],
        }
        (con_algo if forma["rachas"] else sin_nada).append(resumen)
    return (con_algo + sin_nada)[:cuantos]


def _cruces(equipos: dict) -> list[dict]:
    """Dónde lo que uno hace bien coincide con lo que el otro defiende mal."""
    salida = []
    for atacante, defensor in (("local", "visitante"), ("visitante", "local")):
        uno, otro = equipos.get(atacante), equipos.get(defensor)
        if not (uno and otro and uno.get("disponible") and otro.get("disponible")):
            continue
        for dimension, clave_concedida, lectura in CRUCES:
            propio = (uno.get("dimensiones") or {}).get(dimension) or {}
            if propio.get("diferencia", 0) < 0.15:
                continue
            concede = (otro.get("concede") or {})
            # 'concede' solo trae unas pocas claves; para el resto se mira la
            # media de lo que le hacen, que está en las dimensiones del rival.
            del concede
            salida.append({
                "quien": uno["equipo"],
                "contra": otro["equipo"],
                "aviso": f"{uno['equipo']} {lectura}",
                "cuanto": propio.get("diferencia"),
                "dimension": dimension,
                "clave": clave_concedida,
            })
    salida.sort(key=lambda c: -(c.get("cuanto") or 0))
    return salida[:5]


def _cobertura(salida: dict) -> dict:
    """Con cuánta memoria se ha montado esto: sin ella, no vale nada."""
    equipos = salida.get("equipos") or {}
    partidos = sum((e.get("partidos_mirados") or 0) for e in equipos.values()
                   if isinstance(e, dict))
    faltan = [lado for lado, e in equipos.items()
              if isinstance(e, dict) and not e.get("disponible")]
    return {
        "partidos_usados": partidos,
        "sin_datos": faltan,
        "consejo": ("Haz un barrido antes: `cancha barrido`."
                    if faltan or partidos < 4 else None),
    }


def texto(datos: dict, ancho: int = 76) -> list[str]:
    """La previa en líneas, para leerla en el terminal."""
    import textwrap

    if not datos.get("disponible", True):
        return [datos.get("nota", "No hay previa.")]

    p = datos["partido"]
    lineas = [f"{p['local']} - {p['visitante']}   ({p['competicion']}, {p['fecha']})"]
    if p.get("sede"):
        lineas.append(f"{p['sede']}")
    lineas.append("")

    for lado in ("local", "visitante"):
        estilo = (datos["equipos"] or {}).get(lado)
        if not estilo:
            continue
        if not estilo.get("disponible"):
            lineas += [f"{lado.upper()}: {estilo.get('nota')}", ""]
            continue
        r = estilo["resultados"]
        lineas.append(f"{estilo['equipo']}  ({estilo['partidos_mirados']} últimos: "
                      f"{r['racha']}, {r['goles_favor']}-{r['goles_contra']})")
        for rasgo in estilo["lo_que_le_distingue"][:4]:
            lineas.append(f"    · {rasgo['rasgo']:<34} {rasgo['cuanto']}")
        if estilo.get("aviso"):
            lineas += textwrap.wrap(f"    {estilo['aviso']}", ancho)
        jugadores = (datos["jugadores"] or {}).get(lado) or []
        for jugador in jugadores:
            if jugador["rachas"]:
                lineas.append(f"    {jugador['jugador']}: {', '.join(jugador['rachas'])}")
        lineas.append("")

    cruces = datos.get("donde_se_hacen_dano") or []
    if cruces:
        lineas.append("Dónde se pueden hacer daño")
        for cruce in cruces:
            lineas.append(f"    · {cruce['aviso']}")
        lineas.append("")

    arbitro = datos.get("arbitro") or {}
    if arbitro.get("disponible"):
        por = arbitro["por_partido"]
        lineas.append(f"Árbitro: {arbitro['arbitro']} "
                      f"({arbitro['partidos_mirados']} partidos vistos)")
        lineas.append(f"    {por['amarillas']} amarillas, {por['rojas']} rojas, "
                      f"{por['penaltis']} penaltis y {por['faltas']} faltas por partido")
        if arbitro.get("aviso"):
            lineas += textwrap.wrap(f"    {arbitro['aviso']}", ancho)
    elif arbitro.get("nota"):
        lineas.append(f"Árbitro: {arbitro['nota']}")

    consejo = (datos.get("memoria") or {}).get("consejo")
    if consejo:
        lineas += ["", consejo]
    return lineas


__all__ = ["previa", "texto", "CRUCES"]
