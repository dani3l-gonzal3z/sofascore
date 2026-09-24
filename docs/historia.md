# Traerse la historia: años de partidos, no seis por equipo

La memoria se llenaba de dos maneras, y las dos van **partido a partido**: la
guardia nocturna trae los del día siguiente con su contexto, y desde la pantalla
de un partido se piden sus cuarenta.

Con eso no se junta muestra. Para que el perfil de un equipo signifique algo
hacen falta un par de temporadas; para juzgar a un árbitro, más todavía; y para
que la clasificación de los [agentes](agentes.md) ordene a alguien, cincuenta
casos resueltos. A seis partidos por visita, eso son meses.

```bash
cancha historia --plan            # qué costaría, sin pedir un solo partido
cancha historia                   # y ahora sí
cancha historia --anos 5 --grupos grandes --max 5000
```

En la interfaz es **Memoria → Traerse la historia**.

## Mira antes lo que cuesta

`--plan` gasta una petición por liga —su lista de temporadas— y ni una más. Con eso dice cuántas temporadas caen dentro de la ventana y cuántos
partidos y peticiones son, aproximadamente:

```
LaLiga, Premier, Serie A, Bundesliga y Ligue 1 · 15 temporadas · desde 2023-09-21
Con statistics, lineups, incidents, shotmap, odds_featured:
unos 4.500 partidos y 22.695 peticiones.
```

Es una estimación **por arriba**, y conviene mirarla: descubrir a mitad que son
veinte mil peticiones es descubrirlo tarde.

## Qué datos traer, y por qué es lo que más importa

Cada sección es **una petición más por partido**. Con cinco secciones, cuatro mil
partidos son veinte mil peticiones; con dos, ocho mil. Es la perilla que decide
si esto tarda una tarde o tres días.

| Sección | Qué trae | ¿Merece la pena? |
| --- | --- | --- |
| `statistics` | Tiros, posesión, córners, faltas, tarjetas | **Sí.** De aquí sale casi todo lo que se calcula después |
| `incidents` | Goles, tarjetas y cambios con su minuto | Sí, si te importa *cuándo* pasan las cosas |
| `lineups` | Los once, el banquillo y las notas | Solo si vas a mirar jugadores |
| `shotmap` | Cada tiro con su xG y su posición | Caro. Para xG y calidad de tiro |
| `odds_featured` | Las cuotas | Sí: son el listón contra el que se mide todo |

**Sin `statistics` no hay nada que calcular.** Puedes quitarla, y se guardarán
los marcadores, pero entonces la memoria no sirve para casi nada. Los ajustes lo
dicen en voz alta si la quitas.

La lista completa de lo que se puede pedir sale en la interfaz, cada una con lo
que trae, o con `cancha fuentes`.

## Se puede cortar y seguir

Lo que ya está guardado **no se vuelve a pedir**. Eso es lo que hace que esto se
pueda dejar corriendo un rato, cortarlo, y volver a darle mañana sin pagar dos
veces. Con `--max` se pone un tope de peticiones por tanda.

También se para desde la interfaz. Parar no mata el trabajo a mitad: levanta una
bandera que se mira entre partido y partido, así que tarda lo que tarde el que
tenga entre manos y ni un paso más. Matarlo dejaría la memoria escrita a medias.

## Por qué va por temporada y no por equipo

Una petición a la temporada devuelve treinta partidos de **toda** la liga. Yendo
equipo por equipo, cada partido se trae dos veces —una por cada lado— y hay que
pedir veinte calendarios para cubrir lo mismo.

## Lo que no hace

No se inventa lo que la fuente no tiene. Hay partidos viejos y categorías
pequeñas que sencillamente no están con detalle en Sofascore: se piden una vez,
quedan apuntados como tales y no se vuelven a pedir. Salen aparte en el resumen,
como «sin estadísticas», para que no parezca que algo falla.

Y no es instantáneo. Tres años de cinco ligas son varias horas de peticiones. El
plan te lo dice antes; el tope te deja repartirlo.
