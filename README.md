# Sofascore Framework

Te lo descargas, le dices un partido y te devuelve **todos sus datos**: marcador,
estadísticas, alineaciones, cronología, momento de ataque, cara a cara, forma
previa... Y si tienes **Sofascore Plus**, también las secciones de pago, usando
tu propia sesión.

Lo mismo vale para **equipos, jugadores y competiciones**.

```bash
sofascore match "Real Madrid vs Barcelona" --date 2024-10-26
```

```python
from sofascore import get_match

partido = get_match("Real Madrid vs Barcelona", date="2024-10-26")

print(partido.event.label)                    # Real Madrid 0 - 4 Barcelona (LaLiga, 2024-10-26)
print(partido.statistic("expectedGoals"))     # {'name': 'Goles esperados (xG)', 'home': '1.24', ...}
print(partido.goals())                        # cronología de goles
print(partido.available())                    # secciones con datos
print(partido.locked())                       # secciones que requieren Plus
```

- **Cero dependencias.** Solo biblioteca estándar de Python 3.10+. `pip install`
  y a funcionar; `httpx` y `pandas` son opcionales.
- **Un informe, no veinte llamadas.** No tienes que ir pidiendo alineaciones,
  estadísticas y mapa de tiros por separado: pides el partido y llega todo, en
  paralelo, con el estado de cada sección a la vista.
- **Nada te tumba el informe.** Si una sección falla, no existe para ese deporte
  o está detrás del muro de pago, queda marcada y el resto sigue adelante.
- **Educado con la API.** Límite de peticiones por segundo, reintentos con
  espera creciente y caché en disco (un partido terminado no se vuelve a pedir).
- **Aguanta un bloqueo.** La misma API vive en dos hosts; si el primero
  responde 403, se prueba el otro antes de rendirse.
- **Probado sin red.** 210 tests que corren en menos de un segundo con
  respuestas de ejemplo.

---

## Instalación

```bash
pip install -e .             # instala el comando `sofascore`
pip install curl_cffi        # muy recomendable: ver abajo
pip install -e ".[pandas]"   # además, informe.frames() devuelve DataFrames
pip install -e ".[dev]"      # además, pytest para los tests
```

### Por qué `curl_cffi`

Sofascore está detrás de Cloudflare, y **Cloudflare no mira solo las cabeceras:
mira la huella del handshake TLS**. Una petición de `urllib` con cabeceras de
Chrome canta —el TLS es de Python— y se lleva un `403` por muy perfectas que
sean las cabeceras.

`curl_cffi` habla TLS *como* Chrome, así que la huella cuadra con lo que dicen
las cabeceras. Instalarlo es todo lo que hay que hacer: el framework lo detecta
solo y empieza a usarlo.

```bash
pip install curl_cffi
sofascore doctor        # dice qué transporte usa y si la API contesta
```

No es un capricho de este proyecto: **ninguna** de las librerías que hablan con
esta API usa HTTP normal. `pysofascore` usa este mismo `curl_cffi`, `soccerdata`
usa `tls_requests`, y `ScraperFC` y `sofascore-wrapper` llegan a levantar un
navegador entero. Sigue siendo opcional —sin ella el framework funciona igual
desde una red que no esté bloqueada— pero si ves un `403`, es esto.

Con `--transport` (o `SOFA_TRANSPORT`) eliges a mano: `auto`, `curl`, `httpx`
o `urllib`.

Si al instalar te avisa de que `sofascore.exe` ha quedado en una carpeta *que
no está en el PATH* (habitual en Windows con instalación de usuario), no hace
falta configurar nada: `python -m sofascore` hace exactamente lo mismo.

```bash
python -m sofascore match "Real Madrid vs Barcelona" --date 2024-10-26
```

Y sin instalar nada: copia la carpeta `sofascore/` a tu proyecto y usa
`python -m sofascore ...` desde el directorio que la contiene.

## Cómo se nombra un partido

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
4. el histórico del enfrentamiento (`/event/{id}/h2h/events`), que devuelve la
   serie completa entre esos dos equipos por vieja que sea.

Si aun así ese día no hubo nada que encaje, te lo dice —y con `--debug` te
enseña qué aportó cada vía— antes de darte lo que haya encontrado.

Si dos equipos se cruzan el mismo día en competiciones distintas —un
Barcelona-Madrid de LaLiga y otro de la Liga F, por ejemplo— eliges tú: el
resumen enseña los otros candidatos con su competición. Con `--strict` falla en
vez de elegir; con `sofascore search` los ves todos:

```bash
sofascore search "Betis Sevilla"
```

## La línea de comandos

```bash
sofascore match <consulta> [opciones]     # informe completo de un partido
sofascore team "Real Madrid"              # plantilla, calendario, forma, traspasos
sofascore player "Vinicius Junior"        # ficha, atributos, temporadas
sofascore league laliga                   # clasificación, jornadas, goleadores
sofascore live                            # lo que se está jugando ahora mismo
sofascore today [--date AAAA-MM-DD]       # todos los partidos de un día
sofascore leagues [filtro]                # ligas conocidas con su id
sofascore search <consulta>               # partidos candidatos
sofascore sections [--kind team]          # catálogo de secciones
sofascore login [partido]                 # comprueba tus credenciales Plus
sofascore raw /event/11352550/statistics  # cualquier ruta de la API, tal cual
sofascore doctor                          # qué transporte usa y si la API contesta
sofascore cache [--clear]                 # estado de la caché
```

Opciones más usadas de `match`:

| Opción | Para qué |
| --- | --- |
| `--date AAAA-MM-DD` | Desempatar entre varios cruces |
| `--all` | Pedir todas las secciones del catálogo |
| `--sections statistics,shotmap` | Solo las que te interesan |
| `--no-plus` | Ni intentar las de pago |
| `--json p.json` `--markdown p.md` `--csv carpeta/` | Guardar el resultado |
| `--print statistics` | Volcar una sola sección por pantalla |
| `--stdout-json` | El informe entero en JSON, listo para `jq` |
| `--offline` / `--no-cache` | Solo caché / ignorar caché |
| `--parallel N` | Secciones a la vez (`1` las pide de una en una) |
| `--transport curl` | Forzar transporte (`auto`, `curl`, `httpx`, `urllib`) |
| `--debug` | Contadores de peticiones y ajustes en uso |

```bash
sofascore match 11352550 --all --json partido.json --csv datos/
sofascore match 11352550 --print statistics --quiet | jq '.[0].groups'
```

## Qué trae cada informe

`sofascore sections` lista el catálogo completo. Por defecto vienen:

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

Y si Cloudflare te corta el paso, el error no es un `HTTP 403` pelado: te dice
qué instalar (`Blocked`, que hereda de `HTTPError`, así que quien ya capturaba
`HTTPError` no tiene que cambiar nada).

## Más allá del partido

La misma idea aplicada a equipos, jugadores y competiciones: pides uno y llega
todo lo que hay, con el estado de cada sección a la vista.

```python
from sofascore import get_team, get_player, get_league

madrid = get_team("Real Madrid")
madrid.profile["venue"]["stadium"]["name"]
len(madrid.get("players"))
madrid.get("next_events")

vini = get_player("Vinicius Junior")
vini.get("attributes")          # el radar de atributos
vini.get("transfers")           # historial de traspasos

liga = get_league("laliga")     # temporada en curso si no dices otra
liga.get("standings")
liga.get("top_players")
```

Los nombres se resuelven con el buscador de Sofascore, puntuando los candidatos
por parecido; también valen los ids. Para las ligas hay además un catálogo de
alias que no necesita ni buscar:

```bash
sofascore leagues              # las 37 ligas conocidas con su id
sofascore league champions     # "premier", "mundial", "libertadores"...
```

`sofascore sections --kind team|player|tournament` lista lo que trae cada uno.

## Qué se juega ahora

```bash
sofascore live                       # en directo
sofascore today --date 2024-10-26    # todos los partidos de ese día
```

```python
from sofascore import live_matches, matches_on

for partido in live_matches():
    print(partido.label, partido.status_description)
```

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
sofascore match 11352550 --all --csv datos/
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

## Sofascore Plus

**Antes de nada, un aviso honesto:** casi todo lo que la web enseña detrás del
reclamo de Plus —mapa de tiros, xG por disparo, posiciones medias, mapas de
calor, estadísticas por jugador— **la API lo sirve abierto**. Lo comprobamos
pidiéndolo sin ninguna credencial. Así que probablemente no necesites nada de
esta sección.

**El framework no rompe ni esquiva ningún muro de pago.** Si tienes la
suscripción y alguna sección sí la exige, tu navegador ya recibe esos datos
porque tu sesión está autenticada; aquí simplemente reutilizas *tu* sesión para
pedir lo mismo desde Python. Sin credenciales, esas secciones salen como
`plus_required` y el informe sigue con todo lo demás.

Copia `.env.example` a `.env` y rellena **una** de las tres opciones:

```ini
SOFA_PLUS_COOKIE=          # la cabecera Cookie de tu navegador con sesión iniciada
SOFA_PLUS_TOKEN=           # o un token Bearer de tu cuenta
SOFA_PLUS_COOKIE_FILE=     # o un JSON de cookies exportado del navegador
```

Comprueba que funcionan:

```bash
sofascore login 12437616
# Probando con la sección 'win_probability'...
# ✓ Las credenciales funcionan: se han recibido datos de pago.
```

La sonda es una sección que de verdad requiera suscripción: probar con el mapa
de tiros no diría nada, porque sale `ok` tengas cuenta o no.

Son credenciales personales: no las compartas ni las subas a ningún repositorio
(`.env` está en `.gitignore`). Caducan, así que si un día `login` dice que no
las aceptan, vuelve a copiarlas.

## Usarlo como librería

```python
from sofascore import SofascoreClient, Settings, build_report, resolve_event

# Un cliente reutilizable (comparte caché y límite de peticiones).
cliente = SofascoreClient(Settings.from_env(rate_limit=2))

partido = resolve_event(cliente, "Girona vs Osasuna").event
informe = build_report(cliente, partido, sections=["statistics", "lineups"])

for jugador in informe.players():
    valoracion = jugador.raw.get("statistics", {}).get("rating")
    print(f"{jugador.shirt_number:>2} {jugador.name:<25} {valoracion}")
```

Piezas sueltas, todas intercambiables:

| Módulo | Qué hace |
| --- | --- |
| `config.py` | Ajustes desde entorno y `.env` (prefijo `SOFA_`) |
| `transport.py` | HTTP con `urllib`, con `httpx`, a medida o falso (para tests) |
| `cache.py` | Caché en disco, en memoria o ninguna |
| `ratelimit.py` | Espaciado de peticiones |
| `auth.py` | Tus credenciales de Plus |
| `endpoints.py` | Catálogo declarativo de secciones (partido, equipo, jugador, liga) |
| `catalog.py` | Ligas conocidas, códigos de estado y claves de estadística |
| `client.py` | Peticiones, reintentos, cambio de host, errores tipados |
| `resolve.py` | De «un partido» a un id de evento |
| `report.py` | La mecánica común: secciones, estados, paralelismo |
| `match.py` | El informe de un partido |
| `entities.py` | Los informes de equipo, jugador y competición |
| `frames.py` | Tablas y `DataFrame` |
| `export.py` | JSON, Markdown y CSV |
| `cli.py` | La línea de comandos |

### Añadir una sección nueva

Es una línea en `endpoints.py`; no hay que tocar el cliente:

```python
Section("mi_seccion", "/event/{event_id}/lo-que-sea",
        "Qué trae esta sección.", unwrap="clave", default=False)
```

### Otro deporte

El catálogo está pensado para fútbol, pero la API comparte estructura. Cambia el
deporte de las búsquedas con `--sport basketball` (o `SOFA_SPORT`); las secciones
que no existan aparecerán como `unavailable` en vez de romper nada. Las que sí
son de otro deporte (`point_by_point`, `innings`...) se piden solas cuando el
partido lo es.

### Si te bloquean

Lo primero es `pip install curl_cffi` (ver [arriba](#por-qué-curl_cffi)), que
resuelve el caso normal. El framework se prueba además con los dos hosts de la
API antes de rendirse, y si aun así te responden 403 te lo dice con la salida
escrita en el propio error, no con un `HTTP 403` a secas.

Si ni con eso, el transporte es enchufable y no hace falta tocar nada más —aquí
con `curl_cffi` a mano, pero vale igual `playwright` o un proxy tuyo:

```python
from curl_cffi import requests as cr
from sofascore import SofascoreClient
from sofascore.transport import CallableTransport

sesion = cr.Session(impersonate="chrome")
cliente = SofascoreClient(transport=CallableTransport(
    lambda m, url, h: (lambda r: (r.status_code, r.content))(sesion.request(m, url, headers=h))
))
```

`curl_cffi`, `playwright` o lo que prefieras son dependencias tuyas: el
framework sigue sin necesitar ninguna.

## Errores

Todos heredan de `SofascoreError`, así que un solo `except` te cubre:

```python
from sofascore import MatchNotFound, PlusRequired, RateLimited, SofascoreError

try:
    partido = get_match("Equipo Inventado")
except MatchNotFound as exc:
    print(exc)   # explica cómo afinar la consulta
except SofascoreError as exc:
    print(f"algo ha fallado: {exc}")
```

## Desarrollo

```bash
python -m pytest                  # 210 tests, sin red
python examples/demo_offline.py   # el informe completo con datos de ejemplo
python examples/entidades.py      # equipos, jugadores y ligas (necesita red)
```

Los tests usan `FakeTransport` y respuestas guardadas en `tests/fixtures/`:
nada sale a internet, así que corren igual de rápido con o sin conexión.

## De dónde salen las rutas

La API que usa la web de Sofascore no está documentada. Las rutas de este
framework están **contrastadas una a una** con las librerías públicas que llevan
años hablando con ella: [`ScraperFC`](https://pypi.org/project/ScraperFC/),
[`soccerdata`](https://pypi.org/project/soccerdata/),
[`sofascore-wrapper`](https://pypi.org/project/sofascore-wrapper/),
[`sofascrape`](https://pypi.org/project/sofascrape/) y
[`pysofascore`](https://pypi.org/project/pysofascore/). Cuando una ruta aparece
en varias de ellas, es la que funciona de verdad.

De ese repaso salieron tres cosas que aquí ya están puestas:

- la **probabilidad de victoria** cuelga de `/event/{id}/graph/win-probability`,
  no de `/event/{id}/win-probability`;
- el **catálogo de ligas** (nombre → id de competición) y la tabla de **códigos
  de estado** (`100` = *Ended*, `7` = *2nd half*...);
- las **claves de estadística** que devuelve la API — 110 de jugador y las
  habituales de equipo—, que es lo que hace posible `partido.suggest()`.

Si alguna ruta cambiara, la sección saldría como `unavailable` en el resumen en
vez de romper el informe, y corregirla es una línea en `endpoints.py`.

## Comparado con otras librerías

Si lo que quieres es sacar datos de varias fuentes y ponerte a analizar cuanto
antes, `soccerdata` y `ScraperFC` están más rodados: cubren FBref, Understat,
WhoScored, Transfermarkt y más, y llevan años de parches.

Este framework hace tres cosas que no encontré en ellos:

1. **Un informe, no un wrapper.** Los demás te dan `get_lineups(id)`,
   `get_statistics(id)`... y tú ensamblas. Aquí dices el partido y llegan las 30
   secciones a la vez, cada una con su estado.
2. **Sofascore Plus.** Ninguno contempla autenticación: todos asumen acceso
   anónimo. Aquí, si tienes la suscripción, pones tu sesión y esas secciones
   dejan de salir bloqueadas.
3. **Cero dependencias.** `pysofascore` arrastra `scrapling` y `curl_cffi`;
   `sofascore-wrapper` levanta un Chromium con Playwright; `soccerdata` y
   `ScraperFC` traen pandas y compañía. Esto funciona con la biblioteca estándar.

## Aviso

Proyecto **no oficial**, sin relación con Sofascore. Usa su API pública igual
que lo haría un navegador y está pensado para uso personal y análisis propio.
Respeta sus condiciones de servicio, no subas el límite de peticiones sin
motivo y no redistribuyas datos que no sean tuyos. Las credenciales de Plus son
tuyas y solo tuyas: el framework las usa para pedir *tus* datos, nunca para
saltarse una suscripción que no tengas.
