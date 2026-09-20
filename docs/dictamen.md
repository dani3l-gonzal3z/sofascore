# Dictamen: el expediente entero a un modelo grande

Hay dos maneras de usar un modelo en esto, y no compiten: hacen cosas distintas.

El **analista** ([IA y analista](analista.md)) trabaja a cachitos. Le preguntas
algo, él pide una herramienta, lee lo que sale, pide otra. Es lo correcto para un
modelo de 8B en tu ordenador: no le cabe más en la cabeza, y así acierta con lo
que pide.

El **dictamen** es lo contrario: se monta el expediente **completo** del partido
—todo, calculado— y se le manda de una vez, en una sola llamada y sin
herramientas. Porque lo que quieres de un modelo grande no es que sepa qué pedir,
sino que **vea todo a la vez y ate cabos**: que se dé cuenta de que el equipo que
mejor llega es el que peor defiende los córners, y que enfrente hay alguien que
vive de eso.

```bash
cancha dictamen "Girona vs Osasuna"
cancha dictamen "Girona vs Osasuna" --solo-expediente   # sin modelo: mira qué se manda
```

En la interfaz es la tarjeta **Dictamen**, y en el bot `/dictamen Girona vs
Osasuna`.

## Qué lleva el expediente

El documento está escrito como un informe y no como un volcado, a propósito: un
modelo grande lee mejor —y se inventa menos— cuando lo que recibe lleva
**cabecera fechada**, **clave de lectura**, **índice** y **apartados numerados**.
Empieza así:

```
EXPEDIENTE DE PARTIDO — Real Madrid vs Barcelona
Competición: LaLiga · Fecha: 2026-09-20 16:15 (14:15 UTC)
Sede: Santiago Bernabéu · Árbitro designado: César Soto Grado
Preparado por cancha el 2026-09-20 09:31 CEST con 4.218 partidos en memoria

CÓMO LEER ESTE DOCUMENTO
- n=X es el número de partidos sobre los que está medida esa cifra…
```

La clave de lectura define `n=`, «suelo», «sobre su liga» y «fuera de muestra»
**dentro del propio documento**, al lado de los números. Eso no se arregla en las
instrucciones: un modelo que no sabe qué es un suelo de Wilson se inventa la
interpretación, y la inventa con aplomo.

Lo monta `cancha/expediente.py`, y estos son sus apartados, numerados para que se
puedan citar:

| Apartado | Qué |
| --- | --- |
| 1. Ficha del partido | Equipos, competición, fecha, sede y árbitro |
| 2. Pronóstico calculado | El método en una línea, marcador más probable con su probabilidad, 1X2, goles, córners y tarjetas ([Pronóstico](pronostico.md)) |
| 3. Mercado | Lo que implican las cuotas, y el recordatorio de que sabe cosas que el documento no ([Sistemas y cuotas](sistemas.md)) |
| 4. Perfil de los dos equipos | En qué se sale cada uno de la media de su liga —con `n=` de las dos partes—, los cruces entre lo que uno hace y el otro concede, y cuatro jugadores a seguir |
| 5. Últimos partidos | Los seis de cada equipo y los seis entre ellos, uno a uno |
| 6. Árbitro | Su perfil de tarjetas comparado con su liga |
| 7. Patrones medidos | Con su muestra, su suelo y su veredicto fuera de muestra ([Casi seguro](seguro.md)) |
| 8. Límites de este expediente | Lo que no contiene, y por tanto no se puede afirmar |

El **mercado va en su propio apartado** y no dentro del pronóstico: es lo primero
que hay que contrastar, y antes desaparecía del documento cuando no había
pronóstico que calcular.

Cuando un equipo no tiene muestra para ser retratado, el apartado 4 lo dice con
esas palabras —`SIN MUESTRA PARA RETRATARLO`— en vez de decir que «no se sale de
la media en nada llamativo», que es una afirmación distinta y no medida.

Y cierra con un apartado que importa tanto como los demás: **«Lo que este
expediente NO sabe»** —alineaciones, lesiones, si el partido se juega a algo, el
tiempo— para que el modelo no rellene esos huecos por su cuenta.

**Los números van ya calculados.** El expediente no trae datos en bruto para que
el modelo los promedie: trae las cuentas hechas, con su muestra al lado. El
modelo pone el razonamiento; la aritmética la pone Python. Es la línea de
siempre de este proyecto, y con un modelo grande importa **más**, no menos: se
equivoca con más aplomo.

## El encargo

Las instrucciones que van delante (`INSTRUCCIONES_DICTAMEN`, en
`cancha/analista.py`) están escritas como un encargo profesional, con cinco
bloques: **ROL**, **ENTRADA** (qué recibe y qué significa la notación),
**MÉTODO** (en qué orden mirar los apartados), **REGLAS QUE NO SE NEGOCIAN** y
**FORMATO DE SALIDA**. A un modelo grande al que solo se le dice «analiza esto»
le sale una redacción; con un encargo sale un informe.

El formato de salida está fijado, y es lo que se recibe siempre:

```
**Lectura**                                    3 o 4 frases
**En qué me apoyo**                            3 a 5 puntos, cada uno con su n
**Dónde el cálculo y el mercado no coinciden** 1 a 3 puntos, con las dos cifras
**Qué me haría cambiar de opinión**            2 o 3 puntos concretos
**Confianza**                                  alta / media / baja, y por qué
```

De las siete reglas, las que hacen el trabajo:

- todos los números salen del expediente, y si una cifra no está escrita, no se
  dice;
- se mira la muestra antes de afirmar: «7 goles en 3 partidos» son tres
  partidos;
- **el mercado es un rival serio**: donde el pronóstico y la cuota coinciden no
  hay nada que ganar, y donde no coinciden, lo más probable sigue siendo que se
  equivoque el pronóstico;
- y **no da consejos de apuesta**: describe lo que dicen los números y dónde se
  separan del precio. La decisión no es del modelo.

## La nube de Ollama

Un expediente son del orden de **3.500 caracteres, unos 900 tokens** por
partido. Medido: 2.263 caracteres con un partido sin historia detrás, y unos 1.100
más cuando la memoria ya tiene los seis anteriores de cada equipo y los seis
cruces —que es como se usa—. En un 8B de casa entra, pero un 8B no saca de ahí lo
que saca un modelo grande. Para eso está la clave de la nube.

```bash
cancha ajustes ollama_api_key=...          # o en Ajustes, desde el móvil
cancha dictamen "Girona vs Osasuna" --modelo gpt-oss:120b-cloud
```

El nombre del modelo es el que use Ollama en la nube: míralo en su web, porque el
catálogo cambia y aquí no se inventa ninguno.

La clave se pide en [ollama.com](https://ollama.com) → Settings → API keys. El
protocolo es **el mismo** que el de casa (`/api/chat`), así que no hay un camino
nuevo: cambia la URL a `https://ollama.com` y la clave va en la cabecera
`Authorization`. Con clave puesta, `ollama` (la URL local) se ignora.

> **Con clave, el expediente de cada partido SALE de tu ordenador.**
>
> Es la única parte de todo esto que no es local. Son datos de fútbol públicos
> —nada tuyo—, pero conviene saberlo, y por eso va dicho también en la interfaz
> cada vez. Sin clave, el expediente no sale de tu máquina.

Lo que se manda es el texto del expediente y nada más: ni tu memoria, ni tus
ajustes, ni la clave dentro del cuerpo de la petición. Y se manda **una vez por
dictamen**, no una por herramienta: el coste es una llamada.

Antes de gastar, se puede ver exactamente qué se manda:

```bash
cancha dictamen "Girona vs Osasuna" --solo-expediente
```

La respuesta trae el tamaño en caracteres y tokens aproximados, y los tokens que
Ollama dice haber cobrado (`prompt_eval_count` y `eval_count`). En la interfaz
sale al lado del dictamen, con el expediente entero dentro de un plegable.

## Qué esperar

Un dictamen no es un pronóstico mejor. El pronóstico —el marcador, los córners,
las tarjetas— lo calcula Python y es el mismo con nube y sin ella. Lo que añade
el modelo es la **lectura**: qué de todo eso importa en este partido, qué se
contradice y qué habría que mirar antes de hacerle caso.

Y sigue valiendo lo de siempre: el marcador más probable de un partido de fútbol
ronda el 10-12 %. Un modelo grande escribe mejor esa frase, pero no la cambia.

---

[← Volver al índice](../README.md)
