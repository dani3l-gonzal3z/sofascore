"""Ejemplo mínimo: un partido, todos sus datos.

    python examples/quickstart.py "Real Madrid vs Barcelona" 2024-10-26

Necesita conexión a internet. Para probarlo sin red, mira `demo_offline.py`.
"""

from __future__ import annotations

import sys

from cancha import MatchNotFound, get_match


def main(argv: list[str]) -> int:
    consulta = argv[1] if len(argv) > 1 else "Real Madrid vs Barcelona"
    fecha = argv[2] if len(argv) > 2 else None

    try:
        partido = get_match(consulta, date=fecha)
    except MatchNotFound as exc:
        print(exc)
        return 1

    evento = partido.event
    print(f"\n{evento.label}")
    print(f"{evento.url}\n")

    posesion = partido.statistic("ballPossession")
    if posesion:
        print(f"Posesión: {posesion['home']} / {posesion['away']}")

    xg = partido.statistic("expectedGoals")
    if xg:
        print(f"xG:       {xg['home']} / {xg['away']}")

    for gol in partido.goals():
        jugador = (gol.get("player") or {}).get("name", "?")
        print(f"  {gol.get('time')}'  {jugador}  [{gol.get('homeScore')}-{gol.get('awayScore')}]")

    print(f"\nSecciones con datos: {', '.join(partido.available())}")
    if partido.locked():
        print(f"Requieren Sofascore Plus: {', '.join(partido.locked())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
