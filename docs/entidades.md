# Más allá del partido

La misma idea aplicada a equipos, jugadores y competiciones: pides uno y llega
todo lo que hay, con el estado de cada sección a la vista.

```python
from cancha import get_team, get_player, get_league

madrid = get_team("Real Madrid")
madrid.profile["venue"]["stadium"]["name"]
len(madrid.get("players"))
madrid.get("next_events")

vini = get_player("Vinicius Junior")
vini.get("attributes")          # el radar de atributos
vini.get("transfers")           # historial de traspasos
vini.get("season_statistics")   # la temporada entera: goles, xG, pases...

liga = get_league("laliga")     # temporada en curso si no dices otra
liga.get("standings")
liga.get("top_players")
```

Los nombres se resuelven con el buscador de Sofascore, puntuando los candidatos
por parecido; también valen los ids. Para las ligas hay además un catálogo de
alias que no necesita ni buscar:

```bash
cancha leagues              # las 37 ligas conocidas con su id
cancha league champions     # "premier", "mundial", "libertadores"...
```

Las estadísticas de temporada de un jugador necesitan saber *de qué* liga y
temporada, y eso no lo sabes de antemano. Como el informe ya trae el índice de
temporadas del jugador, de ahí se saca la más reciente y se piden en una
segunda tanda, sin que tengas que averiguar ningún id.

`cancha sections --kind team|player|tournament` lista lo que trae cada uno.

## Qué se juega ahora

```bash
cancha live                          # en directo, agrupado por competición
cancha live --league laliga          # solo una competición
cancha live --filter "Arsenal"       # por equipo o competición
cancha today --date 2024-10-26       # todos los partidos de ese día
```

Un `live` sin filtrar son 150 partidos entre amistosos, ligas juveniles y
femeninas de medio mundo, así que salen **agrupados por competición** y te dice
cuántos se ha dejado fuera. `--league` usa el catálogo de ligas conocidas (y
filtra por id, que es exacto); `--filter` busca texto libre en equipos y
competición.

```python
from cancha import live_matches, matches_on

for partido in live_matches():
    print(partido.label, partido.status_description)
```

---

[← Volver al índice](../README.md)
