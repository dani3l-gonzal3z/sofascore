# La memoria: analizar muchos partidos, no uno

Un partido suelto no contesta las preguntas que importan. «42% de posesión» no
significa nada sin saber cuánto promedia esa liga, y «tres partidos sin marcar»
no es igual para quien tira ocho veces por partido que para quien no tira.

Para eso hace falta algo que el framework no tenía: **acordarse**.

```bash
cancha barrido                    # trae los partidos del día y el historial de quien juega
cancha memoria                    # qué hay guardado
cancha previa "Girona vs Osasuna" # todo lo que se sabe antes de jugarse
```

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
| `grandes` | Las cinco grandes europeas |
| `uefa` | Champions, Europa League y Conference |
| `europeas` | Eredivisie, Primeira Liga, Süper Lig, segundas divisiones… |
| `americas` | MLS, Liga MX, Argentina, Libertadores, Perú |
| `arabia` | Saudi Pro League |

Sin `--grupos` entran todos: 25 competiciones.

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
