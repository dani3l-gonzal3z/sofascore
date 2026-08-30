# Cambios

Lo que ha ido pasando, de lo nuevo a lo viejo. Las versiones siguen
[versionado semántico](https://semver.org/lang/es/), con la salvedad de que
hasta el 1.0 la API puede moverse.

## 0.2.0

El paquete se llamaba `sofascore` y hablaba solo con Sofascore. Ahora se llama
**`cancha`**, habla con tres fuentes y trae una capa pensada para que una IA
analice partidos por su cuenta. **El nombre viejo sigue funcionando** —`import
sofascore`, `python -m sofascore` y el comando `sofascore`— y no hay planes de
quitarlo.

### Novedades

- **Para una IA local.** 23 herramientas con su esquema JSON y descripciones
  escritas para que un modelo sepa cuándo usar cada una, más un **servidor MCP**
  (`cancha mcp`) sin dependencias. Las respuestas vienen recortadas para no
  llenarle el contexto, y un fallo llega como dato legible en vez de excepción.
- **Métricas calculadas** (`cancha analisis`): puntos esperados a partir del xG
  de cada disparo —convolución exacta, no una aproximación de Poisson—, calidad
  de tiro, carrera de xG minuto a minuto, desglose por situación y aportación
  por jugador. Son las cuentas que un modelo hace mal.
- **Otras fuentes**: Understat (un segundo modelo de xG) y ClubElo (fuerza real
  de un club). Y `cancha contexto`, que **cruza las fuentes** sobre un mismo
  partido: los dos modelos de xG con su diferencia calculada y el Elo de ambos
  equipos. El emparejado lo hace el framework, que es lo que `soccerdata` y
  `ScraperFC` dejan en tus manos.
- **Equipos, jugadores y competiciones**: 28 secciones nuevas con la misma
  mecánica que los partidos, y `cancha team|player|league`.
- **Grabar respuestas reales** (`cancha grabar`) y reproducirlas sin red
  (`--replay`), con tests de contrato que comprueban que la API devuelve lo que
  el código supone.
- **Sesión de análisis**: ocho preguntas seguidas sobre un partido pasan de 25
  peticiones a 11.
- **Transporte con huella TLS de Chrome** (`curl_cffi`, opcional), que es lo
  único que atraviesa el anti-bot de Cloudflare. Se elige solo si está
  instalado.
- **Integración continua**: los tests en Python 3.10–3.13 sobre Linux, Windows y
  macOS, más un trabajo que comprueba que se puede vivir sin dependencias.
- Comandos nuevos: `analisis`, `contexto`, `fuentes`, `grabar`, `grabaciones`,
  `cookie`, `doctor`, `mcp`, `tools`, `live`, `today`, `leagues`.
- Tablas y `DataFrame` (`informe.tables()` / `informe.frames()`), catálogo de 37
  ligas, códigos de estado y 110 claves de estadística.

### Arreglos

Todos salieron de ejecutarlo contra la API de verdad:

- `/h2h/events` pide el **`customId`** del partido, no el id numérico. Con el id
  devuelve 404 siempre, y esa ruta era además la última vía para encontrar un
  cruce antiguo: llevaba dos rondas sin hacer nada, en silencio.
- La **probabilidad de victoria** cuelga de `/event/{id}/graph/win-probability`,
  no de `/event/{id}/win-probability`.
- **`--date` no filtraba**: se pedía un partido de 2024 y salía uno de 2026 con
  los mismos equipos. La fecha era una penalización blanda cuando el usuario la
  da como condición dura.
- **No se llegaba a partidos de hace temporadas**: solo se pedía la primera
  página del calendario del equipo, los ~30 partidos más recientes.
- **Lo de «Plus» era casi todo mentira**: `shotmap`, `heatmaps`,
  `average_positions` y `player_statistics` los sirve la API abiertos.
  Marcarlos como de pago hacía que `--no-plus` se saltara datos gratis.
- El **CSV de incidencias salía del final al principio** y los cambios de
  jugador aparecían sin nadie, porque en un cambio la API no usa la clave
  `player`.
- `--debug` solo existía en `match`; los demás comandos fallaban con
  «unrecognized arguments».
- `live` devolvía 150 partidos en una lista plana empezando por amistosos y
  ligas sub-12. Ahora van agrupados por competición y se pueden filtrar.
- Las **estadísticas de temporada de un jugador** pedían dos ids que nadie sabe
  de antemano; ahora se deducen del propio informe.
- `cancha login` sondeaba con una sección que da 404 en muchos partidos, así que
  no decía nada de tus credenciales.
- **ClubElo se pedía por HTTP plano** y se quedaba colgado quince segundos sin
  recibir un byte. Ahora se intenta primero por HTTPS, con el HTTP de reserva y
  más paciencia. Y cuando una fuente no contesta, el aviso ya no culpa a cómo
  hayas escrito el nombre del equipo.

### Cambios internos

- `tools.py` (839 líneas) y `cli.py` (898) repartidos en paquetes por familias;
  `cli.py` queda en 56 líneas. El README, en nueve páginas bajo `docs/`.
- Las variables de entorno aceptan `CANCHA_` además de `SOFA_`.
- La carpeta de caché pasa a `.cancha-cache`.
- Un fixture corta la red en los tests: uno que intente salir a internet falla
  al instante y con nombre, en vez de colgar la suite.
- De 101 tests a 398.

## 0.1.0

La primera versión: le dices un partido de Sofascore y te devuelve todos sus
datos. Catálogo declarativo de secciones, resolución de partidos por nombre,
caché en disco, límite de peticiones, exportación a JSON, Markdown y CSV, y
soporte para tus propias credenciales de Sofascore Plus. Sin dependencias.
