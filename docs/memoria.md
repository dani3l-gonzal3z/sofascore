# La memoria: analizar muchos partidos, no uno

Un partido suelto no contesta las preguntas que importan. «42% de posesión» no
significa nada sin saber cuánto promedia esa liga, y «tres partidos sin marcar»
no es igual para quien tira ocho veces por partido que para quien no tira.

Para eso hace falta algo que el framework no tenía: **acordarse**.

```bash
cancha barrido                    # trae los partidos del día y el historial de quien juega
cancha memoria                    # qué hay guardado
cancha previa "Girona vs Osasuna" # todo lo que se sabe antes de jugarse
cancha previa "Girona vs Osasuna" --abastecer   # …y trae antes lo que falte
```

## Dos maneras de llenarla

**El barrido** es al por mayor: todo lo que se juega hoy y el historial de
quien juega. **El abastecimiento** es al detalle: un partido concreto y todo lo
que cuesta entenderlo. El primero se lanza una vez al día; el segundo, cuando
te interesa un partido y la memoria no llega.

## Abastecer un partido

```bash
cancha previa "Girona vs Osasuna" --plan        # qué haría falta y qué costaría
cancha previa "Girona vs Osasuna" --abastecer   # traerlo y guardarlo
```

Trae, con detalle completo y guardado: los **últimos diez de cada equipo por
separado**, los que han **jugado entre ellos**, y los del **árbitro**. Unos
cuarenta partidos, seis peticiones cada uno: unas 240, minuto y medio al ritmo
por defecto de tres por segundo.

Antes de pedir nada dice lo que va a costar, porque decidir a ciegas cuánto le
vas a pedir a un servidor ajeno no es decidir:

```
Girona - Osasuna
  hacen falta 38 partidos: 10 del local, 10 del visitante, 3 entre ellos, 15 de Jesús Gil
  ya están 12; faltan 26 (~156 peticiones)
```

### Por qué no crece exponencialmente

Es la pregunta natural —«cuarenta partidos por análisis»— y la respuesta es que
**se satura**. Los últimos diez del Girona son también los últimos diez de
media LaLiga, así que el segundo análisis de la misma competición ya encuentra
la mitad hecho, y el décimo casi todo. Simulando una liga de veinte equipos,
partido a partido:

| Análisis | Pide | Nuevos | Ya estaban | Coste en peticiones |
| --- | --- | --- | --- | --- |
| 1.º | 20 | 20 | 0 | 120 |
| 4.º | 21 | 8 | 13 | 48 |
| 12.º | 19 | 3 | 16 | 18 |
| 40.º | 20 | 1 | 19 | 6 |

Cuarenta análisis de una liga dejan 245 de sus 380 partidos guardados, y el
último ha costado una sexta parte que el primero. Una memoria que crece
exponencialmente es una memoria rota; esta hace lo contrario, que es su trabajo.

### Lo que ocupa

Un partido con todo el detalle —estadísticas por periodo, los veintidós con sus
números, los tiros, las incidencias y las cuotas— son unos **35 KiB**. Medido,
no estimado:

| Lo que guardes | Partidos | En disco |
| --- | --- | --- |
| Un análisis | 40 | 1,4 MiB |
| Diez análisis | 400 | 14 MiB |
| Una temporada de las cinco grandes | 3.800 | 131 MiB |
| Diez temporadas | 38.000 | 1,3 GiB |

El disco no es el límite. El límite es la paciencia con el ritmo de peticiones,
y por eso importa que la segunda vez no cueste.

### Mirar el futuro, no

Al traer «los últimos diez» se cortan por la fecha del partido que se analiza,
en el origen. Meter en la memoria un partido posterior y luego promediarlo como
si fuera historia previa es la manera más silenciosa de construir un análisis
que acierta en el pasado y falla en el futuro. Hay un test que lo vigila.

## El barrido

Dos movimientos: la agenda del día en las competiciones que te importen (una
petición para todo el fútbol del mundo, y el filtro se hace en local), y de cada
equipo que juega, sus últimos partidos con el detalle completo.

**El primer barrido es caro** —un par de miles de peticiones para las ligas
grandes, unos veinte minutos al ritmo por defecto—. Los siguientes casi no
cuestan, porque solo entra lo nuevo. Y se puede cortar por donde sea: al
reanudar sigue donde lo dejó, porque lo que decide qué pedir es lo que hay en la
base, no un contador.

```bash
cancha barrido --grupos grandes --max 200    # para probar sin gastar la mañana
cancha barrido --date 2026-08-31 --ultimos 8
```

| Grupo | Qué incluye |
| --- | --- |
| `grandes` / `grandes_f` | Las cinco grandes europeas, ellos y ellas |
| `uefa` / `uefa_f` | Champions, Europa League, Conference y la Champions femenina |
| `europeas` / `europeas_f` | Segundas, Países Bajos, Portugal, Turquía, nórdicas… |
| `usa` / `usa_f` | MLS, USL, Liga MX, CONCACAF, NWSL, Liga MX Femenil |
| `sudamerica` / `sudamerica_f` | Brasil, Argentina, Colombia, Chile, Uruguay, Libertadores… |
| `arabia` | Saudi Pro League |

Atajos: `femenino`, `masculino`, `europa`, `america`, `todo`. Sin `--grupos`
entra el catálogo entero: **71 competiciones**, y el primer barrido es largo.

Los ids de Sofascore no se adivinan, así que las competiciones que no venían
contrastadas **se descubren solas** la primera vez que hay red: se buscan, se
comprueba que el país, el deporte y el género coinciden, y solo entonces se
guardan. Lo que no convence no se guarda —un id equivocado no falla, barre otra
liga en silencio—. `cancha ligas --faltan` dice lo que queda.

La memoria es una base **SQLite** en `datos/cancha.db` —biblioteca estándar, ni
un paquete más— y está en el `.gitignore`: es tuya y se reconstruye sola.

## Cómo juega un equipo

```bash
cancha estilo "Girona"
```
```
Girona — LaLiga
  6 últimos partidos (2026-08-02 → 2026-08-30): GEPGGE, 11-7

  Lo que le distingue de su liga
    · tiene el balón                    +22% sobre la media de su liga
    · no juega en largo                 -31% sobre la media de su liga
    · se mete en el área                +19% sobre la media de su liga

  Concede por partido: 1.42 xG · 13.1 tiros · 2.1 ocasiones claras
```

Lo importante es el «sobre la media de su liga». Y esa media se calcula **sin
contar al propio equipo**: comparar a alguien contra un promedio en el que él
pesa suaviza justo lo que se quiere ver.

## Si ha cambiado

```bash
cancha estilo "Girona" --evolucion
```

Sus últimos cinco partidos frente a los diez de antes, dimensión a dimensión,
más el dibujo y lo que concede. Un equipo que ha pasado de tener el balón a
esperar atrás sale aquí antes de que lo diga nadie. Con muestras tan cortas
solo se menciona un cambio del 20 % o más, y la respuesta avisa de que puede
ser el calendario.

## Cómo está un jugador

```bash
cancha forma "Vinicius Junior"
```

Devuelve minutos, nota media y lo que de verdad interesa: las **rachas**.
Cuántos partidos lleva sin marcar, sin tirar entre palos, sin ser titular, o
cuántos seguidos marcando. Una racha solo cuenta partidos que jugó: no tiene
sentido decir que lleva cinco sin marcar si en tres se quedó en el banquillo.

## Cómo pita el árbitro

```bash
cancha arbitro "César Soto Grado"
```

Tarjetas, penaltis y faltas por partido, y cómo reparte entre local y
visitante. Sale de **contar sus partidos guardados**, no de un endpoint:
Sofascore no publica uno y ninguna de las librerías que hablan con su API lo
usa. Con menos de diez partidos te avisa de que es una anécdota, no un patrón.

## La previa

```bash
cancha previa "Girona vs Osasuna"
```

Junta todo lo anterior sobre un partido por jugar: cómo llegan y cómo juegan los
dos, en qué se pueden hacer daño (lo que uno hace mucho contra lo que el otro
concede), quién lleva racha y cómo pita el árbitro designado.

## El briefing

```bash
cancha briefing                 # hoy, en datos/briefings/AAAA-MM-DD.md y .json
cancha briefing --barrer        # barre primero y luego lo escribe
cancha briefing --date 2026-09-20 --grupos grandes,uefa
```

Es la tarea diaria de la que salió todo esto: qué se juega hoy y, de cada
partido, cómo llegan los dos, cómo juegan, si han cambiado, quién lleva racha,
qué le pasa a sus jugadores contra el sistema que van a tener enfrente, lo que
dice el mercado y quién pita. En Markdown para leerlo y en JSON para que una IA
lo tenga entero en una llamada (`briefing_del_dia`). Solo entra lo que ha
pasado el filtro estadístico: un briefing con cien números es un briefing que
nadie lee.

Para que salga solo a las ocho, en Windows (Programador de tareas):

```
schtasks /Create /SC DAILY /ST 08:00 /TN cancha-briefing ^
  /TR "cmd /c cd /d C:\ruta\al\proyecto && cancha briefing --barrer --quiet"
```

Y la [interfaz](interfaz.md) lo enseña en la pestaña Hoy.

## Para la IA

Seis herramientas nuevas: `estilo_de_equipo`, `forma_de_jugador`,
`perfil_de_arbitro`, `previa_de_partido`, `agenda_del_dia` y
`estado_de_la_memoria`. Ninguna sale a la red —leen de la base— así que son
inmediatas.

Un repaso diario se escribe solo con ellas: `agenda_del_dia` para saber qué se
juega, y `previa_de_partido` sobre cada uno.

## Lo que hay que saber

- **Sin barrido no hay nada.** Todas las herramientas de esta página lo dicen en
  vez de devolver un informe vacío.
- **Los rasgos son descripciones, no predicciones.** Que un equipo tenga más el
  balón que su liga es un hecho; que eso vaya a decidir el partido del sábado es
  una opinión, y el framework no la tiene.
- **Un jugador con mala racha es un jugador con mala racha.** Si eso le hace
  esforzarse más o menos es una hipótesis tuya: aquí solo se ve la racha.

## Y con esto, la pregunta buena

Todo lo anterior es contexto. La pregunta por la que merece la pena guardar
tantos partidos es **cómo rinde un jugador según a qué se enfrenta**, y tiene
página propia: [Jugador contra sistema](sistemas.md).

```bash
cancha duelo "Vinicius" "Getafe"
```

---

[← Volver al índice](../README.md)

## Pensando en un modelo, algún día

Guardar todo para poder entrenar algo más adelante es razonable, y la memoria
está montada para que sirva. Lo que hace falta para que sirva de verdad no es
volumen, es **disciplina temporal**: cada fila tiene que poder leerse *como se
veía antes del partido*, o el modelo aprenderá del futuro y acertará
maravillosamente en los datos de entrenamiento.

Lo que ya está:

- Cada partido lleva su `momento`, así que se puede reconstruir qué se sabía en
  cualquier fecha.
- Los partidos terminados no cambian: lo guardado es lo que pasó.
- Las cuotas llevan `visto_en` y `horas_antes`, porque una de apertura y una de
  cierre no valen lo mismo y antes se sobrescribían sin dejar rastro. Para
  entrenar, la de cierre es la buena: ya ha absorbido alineaciones y bajas.
- La separación `Antes` / `Despues` de `cancha.seguro`, que hace
  **estructuralmente imposible** que una condición previa mire el resultado.

Lo que faltaría el día que se quiera hacer:

- Un exportador de conjunto de datos: una fila por partido con sus rasgos
  previos y el desenlace, construido solo con lo anterior al saque.
- Validación hacia delante, no partición al azar. La partición por fecha de
  `cancha seguro --calibrar` es el mismo principio en pequeño.
- Y la parte incómoda: el mercado ya es un modelo, y es bueno. Cualquier cosa
  que se entrene aquí hay que medirla **contra la cuota de cierre**, no contra
  acertar o no. Batir al azar es fácil; batir a Pinnacle es otra conversación.

Nada de esto cambia lo que hay que hacer hoy, que es guardar bien.
