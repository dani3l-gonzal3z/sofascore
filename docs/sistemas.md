# Jugador contra sistema

Es la pregunta más interesante que se le puede hacer a estos datos y la más
fácil de contestar mal. Casi cualquier herramienta te dirá «contra bloque bajo
rinde 0,18 de xG» a partir de dos partidos, y eso no es un dato: es ruido con
formato de dato.

```bash
cancha sistema "Getafe"              # con qué plantea un equipo
cancha contra "Vinicius"             # cómo rinde según lo que le pongan delante
cancha duelo "Vinicius" "Getafe"     # las dos cosas juntas
```

Necesitan un [barrido](memoria.md) previo: leen de la memoria local, no salen a
la red.

## Los tres cuidados

Todo lo de esta página se sostiene sobre tres decisiones que no son opcionales.
Si alguna se cae, los números siguen saliendo y dejan de significar algo.

### Uno: el sistema se mide, no se supone

No vale decir «el Getafe es bloque bajo». Cada partido se caracteriza por lo que
pasó **en ese partido** —formación, presión, posesión—, porque el mismo equipo
no juega igual en casa que fuera, ni contra el primero que contra el último.

La presión se aproxima al estilo del PPDA: pases que concede el defensor por
cada acción defensiva suya (entradas + interceptaciones + faltas). **Cuanto más
bajo, más presiona.** La aproximación está en que el PPDA de verdad solo cuenta
las acciones en campo rival y aquí no hay reparto por zonas: sirve para ordenar
equipos entre sí, no para comparar con cifras publicadas por ahí.

La línea sale de la primera cifra de la formación guardada (`5-3-2` → línea de
cinco), que es el motivo por el que la memoria guarda las alineaciones.

### Dos: se compara contra su liga, no contra un número absoluto

Presionar alto en la Premier no es lo mismo que en la Segunda. Los cortes salen
de los **terciles de la propia competición**, contando todos los partidos
guardados de esa liga. Un equipo que concede 10 pases por acción defensiva es
«bloque bajo» en una liga intensa y «presiona alto» en una pausada, y así sale
etiquetado.

Si no hay muestra suficiente para calcular los terciles (menos de doce
observaciones), no se etiqueta. No hay umbral absoluto de reserva.

### Tres: si no hay muestra, se dice

Todo va normalizado por 90 minutos, todo lleva su número de partidos, y las
diferencias se contrastan contra el azar con una **prueba de Poisson de una
cola**: si el jugador tira 3 veces donde su propia media esperaría 10, la
pregunta es cuánto de improbable era eso.

| Veredicto | Qué significa |
| --- | --- |
| `señal` | p < 0,05 — difícil de explicar por azar |
| `indicio` | p < 0,10 — sugerente, no concluyente |
| `dentro de lo normal` | cabe en lo que explica la suerte |
| `sin muestra` | menos de 3 partidos o 180 minutos: no se concluye nada |
| `solo descriptivo` | métrica continua (xG, xA, toques): no se contrasta |

`sin muestra` gana siempre. Un p de 0,001 con dos partidos sigue siendo dos
partidos.

## Con qué plantea un equipo

```bash
cancha sistema "Getafe" --ultimos 8
```
```
Getafe — 8 partidos mirados

  Dibujo:    5-3-2 (6), 5-4-1 (2)
  Posesión:  38.4%
  Presión:   16.2 pases concedidos por acción defensiva
  Concede:   1.05 xG · 9.4 tiros por partido

  Así juega, comparado con su liga
    · linea    linea de 5
    · presion  bloque bajo
    · balon    cede el balon
```

## Cómo rinde un jugador según lo que le pongan delante

```bash
cancha contra "Vinicius" --eje presion
```

`--eje` decide por qué se agrupa:

| Eje | Grupos |
| --- | --- |
| `presion` | presiona alto · presion media · bloque bajo |
| `linea` | linea de 3 · linea de 4 · linea de 5 |
| `balon` | domina el balon · reparte · cede el balon |

```
El Nueve — agrupado por la presión del rival
  9 partidos, 810 minutos en total

  Contra bloque bajo  (3 partidos, 270 min, nota 7.0)
    tiros             !!   1.00 /90  (su media  3.33, -2.33)  p=0.010
    tiros_a_puerta    !!   0.00 /90  (su media  1.67, -1.67)  p=0.007
    goles                  0.00 /90  (su media  0.67, -0.67)  p=0.135

  Lo que se sale de su propia media
    · contra bloque bajo: tiros_a_puerta 0.0/90 frente a 1.667 (señal, p=0.0067)
    · contra bloque bajo: tiros 1.0/90 frente a 3.333 (señal, p=0.0103)
```

`!!` es señal, `!` indicio, `?` sin muestra. Cada grupo se compara con **la
media del propio jugador**, no con la de otros: la pregunta no es si es bueno,
es si se le da distinto según a qué se enfrente.

Con `--metricas tiros,regates,duelos_ganados` se elige qué enseñar, y con
`--stdout-json` sale todo lo calculado.

## El duelo

```bash
cancha duelo "Vinicius" "Getafe"
```

Junta las dos cosas: mide con qué suele plantear el rival y busca qué ha hecho
el jugador las veces que se ha medido a algo así, por los tres ejes.

```
El Nueve contra el sistema de Muro CD

  Muro CD en sus últimos 3 partidos: 5-3-2 (3)
  30.0% de posesión · presión 22.0 · concede 1.23 xG

  Como linea: linea de 5
    3 partidos, 270 min, nota 7.0
    · tiros_a_puerta: 0.0/90 frente a su media de 1.667 (señal, p=0.0067)
    Contra: Muro CD (2026-02-09), Muro CD (2026-02-08), Muro CD (2026-02-07)
```

Cuando el jugador no se ha medido nunca a lo que plantea ese rival, lo dice.
Eso es más útil que rellenar el hueco con un número.

## Lo que esto no dice

Va escrito en cada respuesta, y conviene repetirlo aquí:

- **Hay sesgo de selección.** Un jugador se enfrenta a bloques bajos sobre todo
  cuando su equipo es favorito, y a presiones altas cuando no lo es. Parte de lo
  que se vea es el contexto del partido y no él.
- **Describe lo que ha pasado, no lo que va a pasar.** Con seis u ocho partidos
  por grupo, hasta una «señal» puede ser una racha.
- **Los tiros de un partido no son sucesos independientes**, así que la Poisson
  es una vara honesta para separar «pasa algo» de «han sido seis partidos», no
  una prueba de hipótesis con todas las de la ley.
- **La presión es una aproximación**, por lo de las zonas.

## Desde Python

```python
from cancha.almacen import Almacen
from cancha.sistemas import duelo, jugador_contra_sistema, lo_relevante

with Almacen("datos/cancha.db") as memoria:
    analisis = jugador_contra_sistema(memoria, 754465, eje="presion")
    for hallazgo in lo_relevante(analisis):
        print(hallazgo["contra"], hallazgo["metrica"], hallazgo["veredicto"])

    print(duelo(memoria, 754465, 2825))
```

## Para la IA

Tres herramientas, ninguna sale a la red: `sistema_de_equipo`,
`jugador_contra_sistema` (con `solo_lo_relevante` para que no le lleguen cien
números) y `duelo_jugador_rival`. Ver [Para una IA local](ia.md).
