"""Las cuentas ya hechas, para que el modelo no las haga a ojo.

Puntos esperados, calidad de tiro, carrera de xG y aportación por jugador. Lo
calcula :mod:`cancha.analisis`; aquí solo se envuelve para la IA.
"""

from __future__ import annotations

from .base import herramienta


@herramienta(
    "analisis_partido",
    "LAS CUENTAS YA HECHAS. No devuelve filas para que las sumes: devuelve los "
    "números calculados, que es lo que un modelo hace mal. Trae puntos "
    "esperados (¿ganó el que mereció?), calidad de tiro (¿tres ocasiones claras "
    "o quince chutes de lejos?), la carrera de xG minuto a minuto, el desglose "
    "por situación de juego, quién generó el peligro y la comparación entre las "
    "dos partes. Úsala en cuanto te pidan valorar un partido; no rehagas tú "
    "estas cuentas.",
    {
        "partido": {"type": "string", "description": "Id, URL o 'Equipo A vs Equipo B'."},
        "fecha": {"type": "string", "description": "AAAA-MM-DD, para desambiguar."},
        "cada": {"type": "integer",
                 "description": "Minutos por tramo en la carrera de xG (por defecto 15)."},
    },
    ["partido"],
)
def _analisis_partido(sesion, partido: str, fecha: str | None = None, cada: int = 15):
    from ..analisis import analisis_completo

    evento = sesion.evento(partido, fecha)
    informe = sesion.informe(evento, ["statistics", "shotmap", "incidents",
                                                      "lineups"])
    return analisis_completo(informe, cada=cada)


@herramienta(
    "puntos_esperados",
    "¿Ganó el que mereció? Calcula, a partir del xG de cada disparo, la "
    "probabilidad de victoria, empate y derrota, y los puntos que merecía cada "
    "equipo. Es una convolución exacta sobre los tiros, no una estimación a "
    "ojo: no intentes reproducirla tú.",
    {
        "partido": {"type": "string", "description": "Id, URL o 'Equipo A vs Equipo B'."},
        "fecha": {"type": "string", "description": "AAAA-MM-DD, para desambiguar."},
    },
    ["partido"],
)
def _puntos_esperados(sesion, partido: str, fecha: str | None = None):
    from ..analisis import puntos_esperados

    evento = sesion.evento(partido, fecha)
    return puntos_esperados(sesion.informe(evento, ["shotmap"]))


@herramienta(
    "carrera_xg",
    "El xG acumulado de cada equipo minuto a minuto: cuándo se generó el "
    "peligro, no solo cuánto. Dice además quién manda en xG y desde qué minuto "
    "dejó de perder esa ventaja. Un 2.5 hecho en diez minutos finales no es el "
    "mismo partido que un 2.5 repartido.",
    {
        "partido": {"type": "string", "description": "Id, URL o 'Equipo A vs Equipo B'."},
        "cada": {"type": "integer", "description": "Minutos por tramo (1 para el detalle)."},
    },
    ["partido"],
)
def _carrera_xg(sesion, partido: str, cada: int = 5):
    from ..analisis import carrera_xg

    evento = sesion.evento(partido)
    return carrera_xg(sesion.informe(evento, ["shotmap"]), cada=cada)


@herramienta(
    "aportacion_jugadores",
    "Quién generó el peligro de verdad: xG disparado, goles, asistencias y "
    "valoración, por jugador y ordenado por xG. Más informativo que la nota, "
    "que premia el partido completo.",
    {
        "partido": {"type": "string", "description": "Id, URL o 'Equipo A vs Equipo B'."},
        "minimo_xg": {"type": "number",
                      "description": "Deja fuera a quien no llegue a este xG (por defecto 0.05)."},
    },
    ["partido"],
)
def _aportacion_jugadores(sesion, partido: str, minimo_xg: float = 0.05):
    from ..analisis import aportacion_jugadores

    evento = sesion.evento(partido)
    informe = sesion.informe(evento, ["shotmap", "incidents", "lineups"])
    return aportacion_jugadores(informe, minimo_xg=minimo_xg)


