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
    "evolucion_de_equipo",
    "SI UN EQUIPO HA CAMBIADO su forma de jugar: sus últimos partidos frente a "
    "los de antes, dimensión a dimensión (posesión, presión, juego en largo, "
    "lo que concede...) y si ha cambiado de dibujo. Contesta a '¿cómo están "
    "jugando ahora?' y a '¿el nuevo entrenador ha cambiado algo?'. Con "
    "muestras cortas: mira contra quién fueron esos partidos antes de "
    "concluir.",
    {
        "equipo": {"type": "string", "description": "Nombre o id del equipo."},
        "ultimos": {"type": "integer",
                    "description": "Cuántos partidos son 'ahora' (por defecto 5)."},
        "anteriores": {"type": "integer",
                       "description": "Cuántos partidos son 'antes' (por defecto 10)."},
    },
    ["equipo"],
)
def _evolucion_de_equipo(sesion, equipo: str, ultimos: int = 5, anteriores: int = 10):
    from ..perfiles import evolucion_de_estilo

    equipo_id, nombre = _equipo(sesion, equipo)
    if equipo_id is None:
        return {"error": f"No encuentro el equipo '{equipo}'."}
    return evolucion_de_estilo(sesion.almacen, equipo_id, ultimos=ultimos,
                               anteriores=anteriores)


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
    "briefing_del_dia",
    "EL REPASO DIARIO ENTERO en una llamada: todos los partidos del día en las "
    "competiciones que importan, y de cada uno cómo llegan los dos equipos, si "
    "han cambiado su forma de jugar, quién lleva racha, qué le pasa a sus "
    "jugadores contra el sistema que van a tener enfrente, lo que dice el "
    "mercado y cómo pita el árbitro. Empieza por aquí cuando te pidan 'qué hay "
    "hoy'. Si ya se generó ese día, devuelve el guardado sin volver a calcular.",
    {
        "fecha": {"type": "string", "description": "AAAA-MM-DD (por defecto, hoy)."},
        "grupos": {"type": "string",
                   "description": "Grupos separados por comas: grandes, uefa, europeas, "
                                  "americas, arabia."},
        "recalcular": {"type": "boolean",
                       "description": "Volver a generarlo aunque exista el de ese día."},
    },
)
def _briefing_del_dia(sesion, fecha: str | None = None, grupos: str | None = None,
                      recalcular: bool = False):
    from datetime import datetime, timezone

    from ..briefing import briefing, cargar, guardar

    dia = fecha or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not recalcular and not grupos:
        guardado = cargar(dia)
        if guardado:
            return guardado
    datos = briefing(sesion.almacen, sesion.cliente, fecha=dia,
                     grupos=grupos.split(",") if grupos else None)
    if not grupos:
        guardar(datos)
    return datos


@herramienta(
    "estado_de_la_memoria",
    "Qué hay guardado en la memoria local: cuántos partidos, de qué "
    "competiciones y de cuándo es el último barrido. Míralo si alguna de las "
    "otras herramientas dice que no tiene datos: probablemente falte barrer.",
    {},
)
def _estado_de_la_memoria(sesion):
    return sesion.almacen.resumen()


@herramienta(
    "expediente_partido",
    "TODO LO DE UN PARTIDO DE UNA VEZ: pronóstico calculado, cómo juega cada "
    "equipo comparado con su liga, los cruces, los últimos partidos de los dos, "
    "el historial entre ellos, el árbitro, el mercado y los patrones medidos. "
    "Una sola llamada en vez de ocho. Úsala cuando te pidan analizar un partido "
    "entero; para una cosa concreta, la herramienta concreta. Trae 'texto' ya "
    "escrito y ordenado: léelo y ata cabos, no recalcules nada.",
    {
        "partido": {"type": "string", "description": "Id, URL o 'Equipo A vs Equipo B'."},
        "ultimos": {"type": "integer",
                    "description": "Partidos anteriores por equipo (por defecto 6)."},
    },
    ["partido"],
)
def _expediente_partido(sesion, partido: str, ultimos: int = 6):
    from ..expediente import a_texto, expediente

    datos = expediente(sesion.almacen, partido, cliente=sesion.cliente, ultimos=ultimos)
    datos["texto"] = a_texto(datos)
    return datos


@herramienta(
    "pronostico_partido",
    "EL PRONÓSTICO, YA CALCULADO. Marcador exacto con su probabilidad, 1X2, "
    "más/menos goles, marcan los dos, córners y tarjetas, todo salido de la "
    "memoria con fuerzas de ataque y defensa sobre xG y una Poisson. **Usa "
    "estos números tal cual y no calcules ni estimes ninguno por tu cuenta**: "
    "si te piden un marcador, el que va primero en 'marcadores' es el más "
    "probable, y su probabilidad es la que pone. Trae también lo que dice el "
    "mercado, y cuando coinciden hay que decirlo: no hay nada que ganar ahí. "
    "Si contesta que falta muestra, eso es la respuesta; usa abastecer_partido "
    "y vuelve.",
    {
        "partido": {"type": "string", "description": "Id, URL o 'Equipo A vs Equipo B'."},
        "ultimos": {"type": "integer",
                    "description": "Partidos de cada equipo a mirar (por defecto 10)."},
    },
    ["partido"],
)
def _pronostico_partido(sesion, partido: str, ultimos: int = 10):
    from ..pronostico import pronostico

    return pronostico(sesion.almacen, partido, cliente=sesion.cliente, ultimos=ultimos)


@herramienta(
    "abastecer_partido",
    "TRAE Y GUARDA todo lo que hace falta para analizar un partido: los últimos "
    "de cada equipo por separado, lo que han jugado entre ellos y lo que ha "
    "pitado el árbitro, con estadísticas, alineaciones, tiros y cuotas. Úsala "
    "cuando otra herramienta diga que no hay datos de ese partido, en vez de "
    "contestar que la memoria está vacía. Cuesta minuto y medio la primera vez "
    "y casi nada las siguientes, porque lo guardado no se vuelve a pedir. Con "
    "'solo_plan' dice qué pediría y cuánto costaría sin pedir nada.",
    {
        "partido": {"type": "string", "description": "Id, URL o 'Equipo A vs Equipo B'."},
        "ultimos": {"type": "integer",
                    "description": "Partidos anteriores de cada equipo (por defecto 10)."},
        "solo_plan": {"type": "boolean",
                      "description": "Solo decir qué haría falta y qué costaría."},
        "maximo": {"type": "integer",
                   "description": "Tope de peticiones. 0 o sin poner, sin tope."},
    },
    ["partido"],
)
def _abastecer_partido(sesion, partido: str, ultimos: int = 10,
                       solo_plan: bool = False, maximo: int = 0):
    from ..abastecer import abastecer, planear

    if solo_plan:
        plan = planear(sesion.cliente, sesion.almacen, partido, ultimos=ultimos)
        return plan.cuentas(sesion.almacen)
    return abastecer(sesion.cliente, sesion.almacen, partido, ultimos=ultimos,
                     maximo_peticiones=maximo)


@herramienta(
    "sistema_de_equipo",
    "CON QUÉ PLANTEA un equipo: dibujo más repetido, posesión, cuánto presiona "
    "y qué concede, con una etiqueta relativa a SU liga ('bloque bajo', "
    "'presiona alto', 'línea de 5'). Se mide partido a partido y luego se "
    "resume, no se supone del escudo. Úsala antes de preguntar cómo le va a un "
    "jugador contra ese rival.",
    {
        "equipo": {"type": "string", "description": "Nombre o id del equipo."},
        "ultimos": {"type": "integer",
                    "description": "Cuántos partidos suyos mirar (por defecto 8)."},
    },
    ["equipo"],
)
def _sistema_de_equipo(sesion, equipo: str, ultimos: int = 8):
    from ..sistemas import sistema_habitual

    equipo_id, nombre = _equipo(sesion, equipo)
    if equipo_id is None:
        return {"error": f"No encuentro el equipo '{equipo}'."}
    return sistema_habitual(sesion.almacen, equipo_id, ultimos=ultimos)


@herramienta(
    "jugador_contra_sistema",
    "CÓMO RINDE un jugador SEGÚN A QUÉ SE ENFRENTA: agrupa sus partidos por el "
    "sistema que le puso delante el rival (presión alta / media / bloque bajo, "
    "línea de 4 o de 5, quién domina el balón) y compara cada grupo con la "
    "media del propio jugador. Cada diferencia lleva su prueba de Poisson: "
    "'señal' es difícil de explicar por azar, 'sin muestra' significa que hay "
    "menos de 3 partidos o 180 minutos y no se debe concluir nada. NO lo "
    "presentes como una predicción: parte de lo que se ve es el contexto (a un "
    "bloque bajo se le juega sobre todo siendo favorito).",
    {
        "jugador": {"type": "string", "description": "Nombre o id del jugador."},
        "eje": {"type": "string", "enum": ["presion", "linea", "balon"],
                "description": "Por qué se agrupa: presión del rival, línea "
                               "defensiva o dominio del balón."},
        "solo_lo_relevante": {
            "type": "boolean",
            "description": "Si es cierto, devuelve solo lo que pasa el filtro "
                           "estadístico en vez de todas las métricas."},
        "solo": {"type": "string", "enum": ["favorito", "no_favorito"],
                 "description": "Restringir a los partidos en que su equipo era "
                                "(o no era) favorito según el mercado."},
    },
    ["jugador"],
)
def _jugador_contra_sistema(sesion, jugador: str, eje: str = "presion",
                            solo_lo_relevante: bool = False, solo: str | None = None):
    from ..comandos.memoria import _jugador_id
    from ..sistemas import jugador_contra_sistema, lo_relevante

    jugador_id, nombre = _jugador_id(sesion.almacen, jugador, sesion.cliente)
    if jugador_id is None:
        return {"error": f"No encuentro al jugador '{jugador}'."}
    analisis = jugador_contra_sistema(sesion.almacen, jugador_id, eje=eje, solo=solo)
    if solo_lo_relevante and analisis.get("disponible"):
        return {
            "jugador": analisis["jugador"], "eje": eje,
            "su_media": analisis["su_media"]["por_90"],
            "hallazgos": lo_relevante(analisis),
            "como_leerlo": analisis["como_leerlo"],
            "lo_que_no_dice": analisis["lo_que_no_dice"],
        }
    return analisis


@herramienta(
    "duelo_jugador_rival",
    "QUÉ LE PASA A UN JUGADOR contra lo que SUELE PLANTEAR un rival concreto. "
    "Junta las dos anteriores: mide con qué juega ese rival y busca qué ha "
    "hecho el jugador las veces que se ha medido a algo así, por los tres ejes "
    "(presión, línea, balón). Es la herramienta para 'cómo se le puede dar a X "
    "el partido contra Y'. Si dice que no se ha medido nunca a eso, dilo: es "
    "más útil que rellenar el hueco.",
    {
        "jugador": {"type": "string", "description": "Nombre o id del jugador."},
        "rival": {"type": "string", "description": "Nombre o id del equipo rival."},
    },
    ["jugador", "rival"],
)
def _duelo_jugador_rival(sesion, jugador: str, rival: str):
    from ..comandos.memoria import _jugador_id
    from ..sistemas import duelo

    jugador_id, _ = _jugador_id(sesion.almacen, jugador, sesion.cliente)
    if jugador_id is None:
        return {"error": f"No encuentro al jugador '{jugador}'."}
    rival_id, _ = _equipo(sesion, rival)
    if rival_id is None:
        return {"error": f"No encuentro el equipo '{rival}'."}
    return duelo(sesion.almacen, jugador_id, rival_id)


@herramienta(
    "sistema_o_contexto",
    "¿ES EL SISTEMA O ES EL CONTEXTO? Repite jugador_contra_sistema dos veces: "
    "solo con los partidos en que su equipo era favorito según el mercado, y "
    "solo con los que no. Un hallazgo que sale en los dos es del sistema; uno "
    "que solo sale siendo favorito es casi seguro el contexto (a un bloque bajo "
    "se le juega sobre todo siendo favorito). Úsala antes de afirmar que a un "
    "jugador 'se le da mal' un tipo de rival.",
    {
        "jugador": {"type": "string", "description": "Nombre o id del jugador."},
        "eje": {"type": "string", "enum": ["presion", "linea", "balon"],
                "description": "Por qué se agrupa (por defecto, presion)."},
    },
    ["jugador"],
)
def _sistema_o_contexto(sesion, jugador: str, eje: str = "presion"):
    from ..comandos.memoria import _jugador_id
    from ..sistemas import desglose_por_favorito

    jugador_id, _ = _jugador_id(sesion.almacen, jugador, sesion.cliente)
    if jugador_id is None:
        return {"error": f"No encuentro al jugador '{jugador}'."}
    return desglose_por_favorito(sesion.almacen, jugador_id, eje=eje)


@herramienta(
    "casi_seguro",
    "QUÉ SE REPITE CASI SIEMPRE, con el número medido detrás. Cuenta cada patrón "
    "(el favorito que no ganó y vuelve a serlo, el que marca en todos, más de 2,5 "
    "goles, córners, tarjetas del árbitro...) sobre el historial guardado y "
    "devuelve la frecuencia, el SUELO de confianza de Wilson y la ELEVACIÓN sobre "
    "su patrón de referencia. Lee siempre la elevación: si es casi cero, el "
    "patrón es la tasa base disfrazada y NO debes presentarlo como hallazgo. "
    "Nada aquí llega al 99 %; si alguien te pide una apuesta segura, esto es lo "
    "que hay y conviene decirlo con su número de casos.",
    {
        "fecha": {"type": "string", "description": "AAAA-MM-DD (por defecto, hoy)."},
        "grupos": {"type": "string", "description": "Competiciones, separadas por comas."},
        "calibrar": {"type": "boolean",
                     "description": "Devolver la tabla de patrones medidos en vez de "
                                    "los avisos de hoy."},
        "umbral": {"type": "number",
                   "description": "Suelo mínimo para avisar (0.65 por defecto)."},
    },
)
def _casi_seguro(sesion, fecha: str | None = None, grupos: str | None = None,
                 calibrar: bool = False, umbral: float = 0.65):
    from ..seguro import avisos
    from ..seguro import calibrar as calibrar_patrones

    if calibrar:
        return calibrar_patrones(sesion.almacen)
    return avisos(sesion.almacen, sesion.cliente, fecha=fecha,
                  grupos=grupos.split(",") if grupos else None, umbral=umbral)
