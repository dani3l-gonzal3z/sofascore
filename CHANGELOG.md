# Cambios

Lo que ha ido pasando, de lo nuevo a lo viejo. Las versiones siguen
[versionado semántico](https://semver.org/lang/es/), con la salvedad de que
hasta el 1.0 la API puede moverse.

## 0.6.0

Cuatro cosas: todo el fútbol que importa, lo que casi siempre pasa contado en
vez de supuesto, un analista que vive en tu máquina y una interfaz rehecha.

### Novedades

- **71 competiciones, masculinas y femeninas.** Las cinco grandes europeas en
  los dos géneros, la Champions femenina, las segundas y las nórdicas, MLS,
  USL, NWSL, Liga MX y Liga MX Femenil, CONCACAF, y Sudamérica entera desde
  Brasil hasta Venezuela. Los ids de Sofascore no se adivinan y no me los he
  inventado: los que no estaban contrastados **se descubren solos** la primera
  vez que hay red, comprobando país, deporte y género antes de guardar
  ninguno. Lo que no convence no se guarda, porque un id equivocado no falla:
  barre otra competición en silencio. `cancha ligas`, `--descubrir`,
  `--faltan`. La memoria sube a esquema v4 con la tabla de ligas.
- **Casi seguro** (`cancha seguro`): la corazonada de «si el Madrid perdió, el
  siguiente lo gana», contada. Doce patrones medidos sobre el historial con su
  frecuencia, su suelo de Wilson y —la cifra que decide— su **elevación sobre
  el patrón de referencia**. Si los favoritos ganan el 84 % y los favoritos que
  pincharon ganan el 61 %, no hay reacción: hay tasa base, y se dice con esas
  palabras. Ver [docs/seguro.md](docs/seguro.md).
- **El analista local** (`cancha analista "…"`): habla con Ollama —Hermes 3 por
  defecto, afinado para llamar funciones— y le da las 42 herramientas. Cada
  paso se ve: qué preguntó, cuánto le contestaron y qué concluye. Las
  instrucciones le prohíben estimar cifras y le obligan a respetar los
  veredictos de «sin muestra» y «es la tasa base». Con `pip install
  "cancha[langchain]"` hay además un adaptador a `create_agent` de LangChain
  1.x en `cancha.agentes.langchain`.
- **La interfaz, rehecha.** Identidad propia —papel de periódico en claro,
  césped de noche en oscuro, Archivo para los marcadores— y cinco pestañas:
  Hoy, Casi seguro, Analista, Buscar y Memoria. Los partidos del día vienen
  **plegados en una línea** con lo que decide si te interesan (mercado, forma,
  insignias) y se abren **donde están**, sin cambiar de página; la previa se
  pide al abrirlos, no antes. El analista responde en streaming con sus pasos a
  la vista. Tema claro, oscuro o automático.

### Arreglos

- Una tabla ancha estiraba la rejilla entera y la página se desplazaba a lo
  ancho en el móvil. Las rejillas pasan a `minmax(0, 1fr)` y la tabla se
  desliza dentro de su caja.
- `/api/analista` ya no se cae si Ollama no está: cualquier fallo se convierte
  en una respuesta que la página puede explicar.

### Lo que no se ha podido comprobar

Desde donde se escribió esto no hay red hacia Sofascore, así que **el
descubridor de competiciones no se ha ejercitado contra la API real**: su
lógica está probada con respuestas de mentira, incluidas las trampas (Liga F
frente a LaLiga, Bundesliga alemana frente a austriaca). La primera ejecución
con red es la prueba: `cancha ligas --descubrir` y luego `cancha ligas`.
Tampoco había un Ollama al que preguntar: el bucle del analista está probado
con un Ollama de mentira que devuelve respuestas guionizadas.

## 0.5.0

El framework se pidió por consola y por una IA. Ahora también se mira: hay una
interfaz, y lo que enseña sale de más sitios.

### Novedades

- **Interfaz** (`cancha web`): un servidor de la biblioteca estándar sirviendo
  una página y una API JSON encima de las mismas herramientas que ve la IA. Se
  instala como app en Windows (Edge o Chrome → Instalar) y en iOS (Safari →
  Añadir a pantalla de inicio) con `--lan`. Seis pestañas: Hoy, Partido,
  Equipo, Jugador, Duelo y Memoria, con el barrido corriendo en segundo plano.
- **Briefing** (`cancha briefing`): el documento de la mañana. Todos los
  partidos del día con cómo llegan los dos, si han cambiado, quién lleva racha,
  qué le pasa a sus jugadores contra el sistema del rival, el mercado y el
  árbitro. En Markdown y JSON, uno por día; `--barrer` barre antes.
- **Quién era favorito** (`cancha/cuotas.py`): las cuotas se guardan en la
  memoria (esquema v3, migración automática) y se convierten a probabilidades
  sin el margen de la casa. Con eso, `cancha contra X --desglose` y la
  herramienta `sistema_o_contexto` hacen el análisis dos veces —siendo
  favorito y sin serlo— y dicen, hallazgo por hallazgo, si es el sistema o el
  contexto. Es la comprobación que la versión anterior solo podía prometer.
- **Si un equipo ha cambiado** (`cancha estilo X --evolucion`): sus últimos
  partidos frente a los de antes, dimensión a dimensión, más el dibujo.
- **Tres fuentes más.** football-data.co.uk (resultados y cuotas de cierre
  desde 1993; `cancha cuotas` rellena la memoria con ellas), ESPN (agenda
  independiente, clasificación, resumen y **noticias**: `cancha noticias
  laliga`) y, si están instaladas, **ScraperFC** y **soccerdata** para FBref,
  Transfermarkt, Capology y SoFIFA a través de sus lectores, con nuestra
  interfaz. Extras `cancha[scraperfc]` y `cancha[soccerdata]`.
- **Nueve herramientas más para la IA** (41 en total): `briefing_del_dia`,
  `sistema_o_contexto`, `evolucion_de_equipo`, `noticias`, `agenda_espn`,
  `historial_de_liga`, `rellenar_cuotas`, `datos_externos` y el parámetro
  `solo` en `jugador_contra_sistema`.

### Arreglos

- `_numero(3.5)` devolvía 3: `int()` trunca sin avisar. Una línea de 3,5 goles
  se convertía en 3.
- El emparejado por nombres aceptaba «Girona - Osasuna» como «Sevilla -
  Osasuna» con un lado exacto y el otro cualquiera. Ahora los dos lados
  tienen que parecerse.
- La previa guardaba las cuotas de un partido por jugar antes de guardar su
  cabecera, y la clave foránea lo rechazaba.
- La conexión de SQLite deja de estar atada al hilo que la abrió, que es lo
  que necesita un servidor con un hilo por petición.

### Lo que no se ha podido comprobar

Las fuentes nuevas están escritas contra el formato que documentan
`soccerdata` y los propios sitios, pero desde donde se escribieron no había red
hacia ellos. La primera ejecución real es la prueba.

## 0.4.0

La memoria ya guardaba muchos partidos. Lo que faltaba era la pregunta que
justifica guardarlos: **cómo rinde un jugador según a qué se enfrenta**.

### Novedades

- **Jugador contra sistema** (`cancha/sistemas.py`, `cancha contra`,
  `cancha duelo`, `cancha sistema`): agrupa los partidos de un jugador por el
  sistema que le puso delante el rival y compara cada grupo con la media del
  propio jugador. Con tres cuidados que son el módulo entero:
  - **el sistema se mide, no se supone**: se caracteriza cada partido por lo
    que pasó en él —formación, presión al estilo del PPDA, posesión—, porque el
    mismo equipo no plantea igual en casa que fuera;
  - **se compara contra su liga**: los cortes salen de los terciles de la propia
    competición, así que «presiona alto» significa alto *para ahí*, y si no hay
    muestra para calcularlos no se etiqueta;
  - **si no hay muestra, se dice**: todo por 90 minutos, y cada diferencia
    contrastada contra el azar con una Poisson de una cola. Por debajo de tres
    partidos o 180 minutos el veredicto es `sin muestra`, por bonito que sea el
    número.
- **La memoria guarda las alineaciones** (esquema v2): sin la formación no hay
  línea de cinco que valga. Las bases viejas se migran solas al abrirlas; nadie
  tiene que repetir un barrido de una semana porque el esquema creció.
- **Tres herramientas más para la IA** (32 en total): `sistema_de_equipo`,
  `jugador_contra_sistema` —con `solo_lo_relevante`, para que al modelo le
  lleguen los hallazgos y no cien números— y `duelo_jugador_rival`.
- **[Documentación](docs/sistemas.md)** de todo esto, incluido un apartado
  entero de lo que **no** dice: el sesgo de selección (a los bloques bajos se
  les juega sobre todo siendo favorito) está escrito también en cada respuesta.

### Arreglos

- **El barrido se caía con un 404**: la ruta global de partidos del día
  (`/sport/football/scheduled-events/{fecha}`) ha dejado de existir. Ahora se
  intenta y, si no está, se pide competición por competición, que es más lento
  pero funciona.
- **`--rate 0` no llegaba a las fuentes**: cada una imponía su propio ritmo
  pasara lo que pasara, así que la opción existía y no hacía nada ahí. De paso,
  la batería de tests baja de dieciséis segundos a menos de tres.
- **ClubElo no contestaba nunca**: con el transporte que imita a Chrome se
  quedaba en treinta segundos y cero bytes por http y por https. Es una API
  pública que sirve CSV, sin anti-bot que sortear, así que ahora se le habla
  con `urllib`. De paso, cada fuente puede pedir el transporte que le convenga.

## 0.3.0

El framework sabía traer los datos de **un** partido. Ahora se acuerda de
muchos, que es lo que hace falta para analizar de verdad: un dato suelto no
dice nada sin saber qué es normal en esa liga o en ese jugador.

### Novedades

- **Memoria local** (`cancha/almacen.py`): una base SQLite —biblioteca
  estándar— con partidos, estadísticas, actuaciones de jugadores, tiros e
  incidencias. Guardar es idempotente, así que un barrido se puede cortar y
  reanudar sin romper nada.
- **Barrido** (`cancha barrido`): la agenda del día en 25 competiciones (las
  cinco grandes, UEFA, MLS, Arabia, y varias europeas y americanas) y, de cada
  equipo que juega, sus últimos partidos con detalle. El primero es caro; los
  siguientes casi no, porque solo entra lo nuevo.
- **Estilo de equipo** (`cancha estilo`): posesión, verticalidad, juego por
  fuera, dependencia del balón parado, presión… todo **comparado con la media
  de su liga**, y esa media se calcula sin contar al propio equipo.
- **Forma y rachas de jugador** (`cancha forma`): cuántos partidos lleva sin
  marcar, sin tirar entre palos o sin ser titular. Las rachas solo cuentan
  partidos jugados, no los que pasó en el banquillo.
- **Perfil de árbitro** (`cancha arbitro`): tarjetas, penaltis y faltas por
  partido, y cómo reparte entre local y visitante. Sale de contar sus partidos
  guardados; Sofascore no publica un endpoint para esto.
- **Previa** (`cancha previa`): todo junto sobre un partido por jugar, incluido
  dónde se pueden hacer daño.
- **Seis herramientas más para la IA** (29 en total), ninguna de las cuales
  sale a la red: leen de la memoria. Con `agenda_del_dia` y `previa_de_partido`
  se escribe un repaso diario entero.

### Arreglos

- **ClubElo se pedía por HTTP plano** y se quedaba colgado quince segundos sin
  recibir un byte. Ahora se intenta primero por HTTPS, con el HTTP de reserva.
  El mecanismo es general: cualquier fuente puede declarar raíces alternativas
  y su propio timeout.
- Cuando una fuente no contestaba, el aviso culpaba a cómo hubieras escrito el
  nombre del equipo. Ahora distingue «no encontrado» de «no ha contestado».
- El orden en que la IA ve las herramientas ya no depende del orden de los
  imports, que cualquier formateador reordena sin avisar.

### Verificado contra la API real

**Understat funciona.** Se escribió a ciegas, leyendo el código de
`soccerdata`, y en la primera ejecución real dio 1.41–2.52 de xG donde
Sofascore daba 1.46–2.58: los dos modelos coinciden dentro de 0.06.

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
