# Cómo se nombra un partido

Las cuatro formas valen, elige la que te resulte más cómoda:

| Forma | Ejemplo |
| --- | --- |
| Nombres de los equipos | `"Real Madrid vs Barcelona"` (`vs`, `-`, `x`, `contra`...) |
| Con fecha para desempatar | `--date 2024-10-26` |
| URL de Sofascore | `https://www.sofascore.com/.../#id:11352550` |
| Id del evento | `11352550` |

**La fecha es una condición, no una sugerencia.** Si dices `--date`, no se elige
nada de otro día. Para encontrarlo se prueban cuatro vías, en este orden y
parando en cuanto aparece:

1. el buscador de Sofascore;
2. los partidos programados de ese día;
3. el calendario de los equipos, **retrocediendo páginas** según lo antigua que
   sea la fecha (una página son ~30 partidos: un cruce de hace dos temporadas
   queda muy atrás);
4. el histórico del enfrentamiento (`/event/{customId}/h2h/events`), que
   devuelve la serie completa entre esos dos equipos por vieja que sea. Esa
   ruta pide el **código** del partido (`xNbsDNb`), no el id numérico: con el
   id responde 404.

Si aun así ese día no hubo nada que encaje, te lo dice —y con `--debug` te
enseña qué aportó cada vía— antes de darte lo que haya encontrado.

Si dos equipos se cruzan el mismo día en competiciones distintas —un
Barcelona-Madrid de LaLiga y otro de la Liga F, por ejemplo— eliges tú: el
resumen enseña los otros candidatos con su competición. Con `--strict` falla en
vez de elegir; con `cancha search` los ves todos:

```bash
cancha search "Betis Sevilla"
```

## Qué trae cada informe

`cancha sections` lista el catálogo completo. Por defecto vienen:

| Sección | Contenido |
| --- | --- |
| `event` | Marcador, estado, competición, sede, árbitro, asistencia |
| `statistics` | Posesión, tiros, pases, duelos, xG... por periodo |
| `lineups` | Titulares, suplentes, dorsales, formación, valoraciones |
| `incidents` | Goles, tarjetas, cambios, VAR, penaltis |
| `momentum` | Presión/momento de ataque minuto a minuto |
| `best_players` | Mejores jugadores según Sofascore |
| `managers` | Entrenadores |
| `h2h` | Balance histórico entre los dos equipos |
| `pregame_form` | Forma y clasificación antes del partido |

Bajo demanda (`--sections` o `--all`): `votes`, `h2h_events`, `team_streaks`,
`odds`, `odds_featured`, `winning_odds`, `highlights`, `comments`,
`tv_channels`, `standings`.

Y las avanzadas: `shotmap` (xG por disparo), `average_positions`,
`team_heatmap`, `player_statistics`, `heatmaps`. **La web las enseña bajo el
reclamo de Sofascore Plus, pero la API las sirve abiertas** —comprobado
pidiéndolas sin credenciales— así que las tienes igual.

Solo dos siguen marcadas como de pago, y por prudencia más que por certeza:
`win_probability` y `ai_insights`. Si resulta que también son abiertas, saldrán
`ok` igual: el ámbito es una pista, la respuesta de la API es la que manda.

Hay además secciones que solo existen en su deporte y que se piden solas cuando
toca: `point_by_point` y `tennis_power` (tenis), `innings` (críquet),
`esports_games`. En un partido de fútbol ni se intentan.

Cada sección termina en uno de estos estados, y lo verás en el resumen:

| Estado | Significado |
| --- | --- |
| `ok` | Datos recibidos |
| `empty` | La sección existe pero no tiene contenido (partido sin jugar, por ejemplo) |
| `plus_required` | Hace falta Sofascore Plus y no hay credenciales válidas |
| `unavailable` | Ese partido o deporte no tiene esa sección |
| `error` | Fallo de red o de la API |

Un `unavailable` no significa que la ruta esté mal. `tv_channels` solo existe
en partidos por jugar, `win_probability` no la tienen todos los deportes ni
todos los partidos, y `cuptree` solo existe donde hay eliminatorias: en una
liga regular devuelve 404 y es lo correcto.

Y si Cloudflare te corta el paso, el error no es un `HTTP 403` pelado: te dice
qué instalar (`Blocked`, que hereda de `HTTPError`, así que quien ya capturaba
`HTTPError` no tiene que cambiar nada).

## Tablas y pandas

Todo lo del informe sale también en forma de tabla, listo para analizar:

```python
partido = get_match(11352550, sections=["all"])

partido.tables()      # listas de diccionarios, sin instalar nada
partido.frames()      # DataFrames de pandas (pip install "sofascore-framework[pandas]")
```

Las tablas son `partido`, `estadisticas`, `incidencias`, `alineaciones`,
`valoraciones`, `tiros`, `momento` y `posiciones_medias`. Las que ese partido no
tenga, simplemente no aparecen. Lo mismo escrito a disco:

```bash
cancha match 11352550 --all --csv datos/
```

Y unos cuantos atajos para lo que se mira siempre:

```python
partido.goals()                  # goles en orden
partido.cards()                  # tarjetas
partido.substitutions()          # cambios
partido.ratings()                # jugadores por valoración, de mayor a menor
partido.shots()                  # disparos con xG (si tienes Plus)
partido.statistic("expectedGoals")
partido.statistic_keys()         # qué estadísticas trae este partido
partido.suggest("expectedGoal")  # ['expectedGoals'] — la errata típica
```

---

[← Volver al índice](../README.md)
