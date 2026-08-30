"""Lo que solo se puede contestar teniendo memoria.

El resto de herramientas miran un partido. Estas miran **muchos**, que es de
donde salen las cosas que de verdad interesan a un análisis: cómo juega un
equipo, si un jugador lleva un mes sin aparecer, cómo pita el árbitro
designado.

Todas leen de :mod:`cancha.almacen` y ninguna sale a la red, así que son
inmediatas. Lo que sí necesitan es que alguien haya hecho un barrido antes; si
no, lo dicen en vez de devolver un informe vacío.
"""

from __future__ import annotations

from .base import herramienta


def _equipo(sesion, consulta: str):
    from ..comandos.memoria import _equipo_id

    return _equipo_id(sesion.almacen, consulta, sesion.cliente)


@herramienta(
    "estilo_de_equipo",
    "CÓMO JUEGA un equipo, no cómo le ha ido: posesión, verticalidad, presión, "
    "juego por fuera, dependencia del balón parado... todo comparado con la "
    "media de SU liga, que es lo único que hace significativo un número. "
    "Devuelve los rasgos en los que se sale de lo normal. Necesita un barrido "
    "previo (`cancha barrido`).",
    {
        "equipo": {"type": "string", "description": "Nombre o id del equipo."},
        "ultimos": {"type": "integer",
                    "description": "Cuántos partidos recientes mirar (por defecto 6)."},
    },
    ["equipo"],
)
def _estilo_de_equipo(sesion, equipo: str, ultimos: int = 6):
    from ..perfiles import estilo_de_equipo

    equipo_id, nombre = _equipo(sesion, equipo)
    if equipo_id is None:
        return {"error": f"No encuentro el equipo '{equipo}' ni en la memoria ni buscando."}
    return estilo_de_equipo(sesion.almacen, equipo_id, ultimos=ultimos)


@herramienta(
    "forma_de_jugador",
    "CÓMO ESTÁ un jugador y qué RACHAS lleva: cuántos partidos sin marcar, sin "
    "tirar entre palos, sin ser titular, o cuántos seguidos marcando. Las "
    "rachas solo cuentan partidos que jugó, no los que pasó en el banquillo. "
    "Es lo que no se ve mirando un partido suelto.",
    {
        "jugador": {"type": "string", "description": "Nombre o id del jugador."},
        "ultimas": {"type": "integer",
                    "description": "Cuántas actuaciones mirar (por defecto 6)."},
    },
    ["jugador"],
)
def _forma_de_jugador(sesion, jugador: str, ultimas: int = 6):
    from ..comandos.memoria import _jugador_id
    from ..perfiles import forma_de_jugador

    jugador_id, nombre = _jugador_id(sesion.almacen, jugador, sesion.cliente)
    if jugador_id is None:
        return {"error": f"No encuentro al jugador '{jugador}'."}
    return forma_de_jugador(sesion.almacen, jugador_id, ultimas=ultimas)


@herramienta(
    "perfil_de_arbitro",
    "CÓMO PITA un árbitro: tarjetas, penaltis y faltas por partido, y cómo "
    "reparte entre local y visitante. Sale de contar sus partidos guardados, no "
    "de un endpoint —Sofascore no publica uno— así que cuantos más partidos "
    "barridos, más fiable; con menos de diez lo dice.",
    {
        "arbitro": {"type": "string", "description": "Nombre del árbitro."},
        "ultimos": {"type": "integer", "description": "Cuántos partidos suyos mirar."},
    },
    ["arbitro"],
)
def _perfil_de_arbitro(sesion, arbitro: str, ultimos: int = 20):
    from ..perfiles import perfil_de_arbitro

    return perfil_de_arbitro(sesion.almacen, arbitro, ultimos=ultimos)


@herramienta(
    "previa_de_partido",
    "TODO LO QUE SE SABE de un partido antes de jugarse, junto: cómo llegan y "
    "cómo juegan los dos equipos, en qué se pueden hacer daño, qué jugadores "
    "llevan racha (buena o mala) y cómo pita el árbitro designado. Es la "
    "herramienta con la que empezar cuando te pidan analizar un partido futuro.",
    {
        "partido": {"type": "string", "description": "Id, URL o 'Equipo A vs Equipo B'."},
        "ultimos": {"type": "integer", "description": "Partidos recientes por equipo."},
        "jugadores": {"type": "integer",
                      "description": "Cuántos jugadores destacar por equipo."},
    },
    ["partido"],
)
def _previa_de_partido(sesion, partido: str, ultimos: int = 6, jugadores: int = 4):
    from ..previa import previa

    return previa(sesion.almacen, partido, cliente=sesion.cliente,
                  ultimos=ultimos, jugadores_por_equipo=jugadores)


@herramienta(
    "agenda_del_dia",
    "QUÉ SE JUEGA un día en las competiciones que importan (las cinco grandes "
    "europeas, UEFA, MLS, Arabia y varias europeas menores). Es por donde "
    "empieza un repaso diario: de aquí salen los partidos sobre los que luego "
    "pedir la previa.",
    {
        "fecha": {"type": "string", "description": "AAAA-MM-DD (por defecto, hoy)."},
        "grupos": {"type": "string",
                   "description": "Grupos separados por comas: grandes, uefa, "
                                  "europeas, americas, arabia."},
    },
)
def _agenda_del_dia(sesion, fecha: str | None = None, grupos: str | None = None):
    from ..barrido import agenda

    partidos = agenda(sesion.cliente, fecha, grupos.split(",") if grupos else None)
    por_liga: dict[str, list] = {}
    for evento in partidos:
        por_liga.setdefault(evento.tournament or "?", []).append({
            "id": evento.id,
            "partido": f"{evento.home} - {evento.away}",
            "hora_utc": evento.kickoff.strftime("%H:%M") if evento.kickoff else None,
            "arbitro": evento.referee or None,
        })
    return {"fecha": fecha or "hoy", "total": len(partidos), "por_competicion": por_liga}


@herramienta(
    "estado_de_la_memoria",
    "Qué hay guardado en la memoria local: cuántos partidos, de qué "
    "competiciones y de cuándo es el último barrido. Míralo si alguna de las "
    "otras herramientas dice que no tiene datos: probablemente falte barrer.",
    {},
)
def _estado_de_la_memoria(sesion):
    return sesion.almacen.resumen()
