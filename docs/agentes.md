# Agentes: varios analistas compitiendo, y una tabla que dice cuál acierta

Hasta aquí había **un** analista. Las mismas instrucciones para todo el mundo, el
mismo acceso a los mismos datos, y una respuesta en prosa: se leía, se creía o no
se creía, y ahí moría.

Un agente es ese mismo analista pero con nombre y con carácter: sus
instrucciones, su modelo, su presupuesto de vueltas y —lo que de verdad los
diferencia— **a qué datos llega**. Uno que solo pueda mirar árbitros y tarjetas
no escribe distinto que otro que lo mire todo: piensa distinto, porque no sabe lo
mismo.

Y hay una condición que lo cambia todo: **un agente está obligado a terminar
dando probabilidades**. Con eso, lo que dice entra en [el registro](registro.md)
con su nombre al lado y se mide con la misma vara que todo lo demás. Entonces ya
no hace falta opinar sobre quién analiza mejor:

```bash
cancha agentes                                    # los que tienes
cancha agente el-esceptico "Girona vs Osasuna"    # que uno lo analice
cancha clasificacion                              # quién acierta más
```

En la interfaz es la pestaña **Agentes**, y en el partido, la tarjeta «Que lo
vea…». En el bot, `/agentes`, `/agente` y `/clasificacion`.

## Contra quién compiten

En la tabla no están solo los agentes. Hay dos concursantes fijos, y sin ellos la
clasificación no significaría nada:

| Concursante | Qué es |
| --- | --- |
| `calculo` | El Poisson encogido que ya calculaba el [pronóstico](pronostico.md) |
| `mercado` | Las probabilidades implícitas de las cuotas, apuntadas gratis |

El mercado es el listón. Es bueno, es difícil de batir, y coronar al mejor de
varios agentes sin saber si alguno le gana es coronar al mejor de varios malos.

## Cómo se crea uno

En la pestaña **Agentes → Quiénes son**, o a mano en `datos/agentes.json`:

```json
{
  "el-del-arbitro": {
    "nombre": "El del árbitro",
    "instrucciones": "Mira el partido por donde casi nadie lo mira: quién pita…",
    "modelo": "",
    "vueltas": 5,
    "crudo": "tabla",
    "herramientas": ["perfil_de_arbitro", "pronostico_partido", "casi_seguro"],
    "temperatura": 0.2,
    "activo": true
  }
}
```

| Campo | Qué hace |
| --- | --- |
| `instrucciones` | Su forma de mirar un partido. Es lo único imprescindible: sin esto es el analista de siempre con otro nombre |
| `modelo` | Vacío = el de los ajustes. Puede ser uno de la nube |
| `vueltas` | Cuántas veces puede parar a pedir datos. Cada una es una llamada al modelo, así que esto es el presupuesto |
| `crudo` | Con cuánto detalle arranca su expediente: `todo`, `tabla` o `no` |
| `herramientas` | A cuáles de las 45 llega. Vacío = a todas |
| `temperatura` | Cuánto se le deja improvisar |

El nombre corto tiene que ser minúsculas, números y guiones, **sin tildes**. No
es una manía: ese nombre viaja por el terminal, por una petición y hasta la base
de datos, que compara byte a byte. `calculo` y `mercado` están cogidos.

Vienen tres de ejemplo —el escéptico, el del crudo y el del árbitro— y están
escritos para que se noten en la tabla. Si dos agentes aciertan exactamente lo
mismo, es que eran el mismo agente.

## Lo que hace un agente cuando lo pones a analizar

1. Se le monta el expediente con el detalle que lleve configurado.
2. Se le deja **pedir por su cuenta** lo que vea que le falta, con las
   herramientas a las que llegue, hasta agotar sus vueltas.
3. Se le exige acabar con un bloque de números: el 1X2, más de 2,5, ambos
   marcan, córners, tarjetas y un marcador.
4. Su análisis se guarda con el partido —para siempre, como los
   [dictámenes](dictamen.md)— y sus probabilidades entran en el registro a su
   nombre.

Si no da los números, se le piden **una** vez más, a secas. Si vuelve a fallar,
el análisis se guarda igual y se marca que no puntúa: se lee, pero no se puede
comparar con nadie. Insistir en bucle cuesta dinero y no convence a un modelo que
no sabe hacerlo.

Y que eso le pase a menudo a un agente es, en sí mismo, información sobre él.

## La clasificación, y por qué no ordena por lo que parece

```
#  quién                 casos   ventaja   brier  dist.mdo  h.antes
1  el-esceptico             80    +0.04%  0.2610     0.006        0
2  el mercado               80    +0.00%  0.2614     0.000       14
3  el cálculo               80    -1.47%  0.2761     0.066       14
4  el-del-crudo             80    -2.20%  0.2834     0.104        0
```

**No ordena por acierto.** Es la cifra que mejor se vende y la que menos informa:
depende de qué partidos predijiste, y una muestra llena de favoritos claros
halaga a todo el mundo.

**Y tampoco por el Brier a secas**, que es el error que nadie ve: el Brier
depende de la **dificultad** de los casos. Dos agentes que han opinado de
partidos distintos no son comparables aunque los dos tengan un Brier.

Lo que ordena es la **ventaja sobre el mercado**: cuánto mejor es su Brier que el
de las cuotas *en esos mismos partidos*. Así la dificultad se cancela y lo que
queda es el agente. Positivo es ganarle al precio, y es raro.

Con menos de 50 casos resueltos, un agente **sale en la tabla pero sin puesto**.
Con veinte predicciones, el orden es casi todo azar.

### Las dos columnas que deciden si la tabla significa algo

**`dist.mdo`** es la distancia media entre lo que dice y lo que decía el precio.
Esto no lo pide nadie y es lo más valioso de la tabla: el expediente **le enseña
las cuotas**, así que un agente puede limitarse a repetirlas y salir clasificado
arriba. Con una distancia de 0,01, lo que la tabla mide no es quién analiza
mejor: es quién copia mejor. Y cuando pasa, la tabla lo dice.

En el ejemplo de arriba, el que va primero es exactamente eso.

**`h.antes`** es con cuánta antelación predice. Es un desnivel de fábrica: el
cálculo se apunta en la guardia de las tres de la mañana y un agente se corre a
mano, a lo mejor media hora antes del saque. El que llega más tarde sabe más
cosas —quién juega, cómo se ha movido la cuota—, así que tiene **más
información, no más talento**. Cuando la diferencia pasa de seis horas, la tabla
avisa de que eso no es una comparación limpia.

### Dos, cara a cara

```bash
cancha clasificacion --comparar el-esceptico calculo
```

Compara solo los sucesos sobre los que han opinado **los dos**. Es la única
comparación que no arrastra la diferencia de dificultad.

## Lo que esto no es

Un agente no es un oráculo. Que uno vaya primero con sesenta predicciones quiere
decir que ha ido mejor en sesenta predicciones, y sesenta predicciones son pocas.
La tabla trae intervalos y mínimos precisamente porque la tentación de leerla
como un veredicto es enorme.

Tampoco es un sistema de apuestas. Aquí no hay unidades, ni ROI, ni consejos:
hay probabilidades apuntadas antes del partido y medidas después.

Y el coste es real: un agente con seis vueltas son seis llamadas al modelo. En
local eso es tiempo; con una clave de la nube puesta, es dinero. Por eso se
ejecutan a mano y no cada noche.

## Qué viene después, y con qué condición

La idea siguiente es que cada agente pueda tener **su propio código** —un fichero
de Python que calcule lo que a él le interese y se lo meta en el expediente—. Se
va a hacer, pero con una condición escrita antes de empezar para no moverla
después: un agente con código se registra como **dos** concursantes, con y sin
él, y si el que lleva código no le gana al pelado con muestra suficiente, **la
conclusión es que la idea no sirve** y se queda lo de ahora.

Lo primero que se mira, y puede que ahí se acabe la discusión, es en cuántos
partidos la respuesta **cambia** siquiera. Si el agente dice lo mismo con código
y sin él, el código es decoración y ninguna muestra va a demostrar nada.
