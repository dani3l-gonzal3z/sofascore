"""Lo que hay más allá de un partido: equipos, jugadores y competiciones.

    python examples/entidades.py                 # Real Madrid, Vinicius y LaLiga
    python examples/entidades.py "Liverpool" "Mohamed Salah" "premier"

Necesita conexión a internet.
"""

from __future__ import annotations

import sys

from cancha import SofascoreError, get_league, get_player, get_team


def main(argv: list[str]) -> int:
    equipo = argv[1] if len(argv) > 1 else "Real Madrid"
    jugador = argv[2] if len(argv) > 2 else "Vinicius Junior"
    liga = argv[3] if len(argv) > 3 else "laliga"

    try:
        informe = get_team(equipo)
        print(f"\n== {informe.name} ==")
        ficha = informe.profile
        print(f"  estadio: {((ficha.get('venue') or {}).get('stadium') or {}).get('name', '?')}")
        plantilla = informe.get("players") or []
        print(f"  plantilla: {len(plantilla)} jugadores")
        for evento in (informe.get("next_events") or [])[:3]:
            print(f"  próximo: {evento.get('homeTeam', {}).get('name')} - "
                  f"{evento.get('awayTeam', {}).get('name')}")

        informe = get_player(jugador)
        print(f"\n== {informe.name} ==")
        ficha = informe.profile
        print(f"  posición: {ficha.get('position', '?')} · "
              f"dorsal: {ficha.get('jerseyNumber', '?')}")
        atributos = (informe.get("attributes") or {}).get("averageAttributeOverviews") or []
        if atributos:
            print(f"  atributos: {atributos[0]}")

        informe = get_league(liga)
        print(f"\n== {informe.name} ==")
        for tabla in informe.get("standings") or []:
            for fila in (tabla.get("rows") or [])[:5]:
                print(f"  {fila.get('position'):>2}. {fila['team']['name']:<20} "
                      f"{fila.get('points')} pts")
            break
    except SofascoreError as exc:
        print(f"error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
