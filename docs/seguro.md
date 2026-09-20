# Casi seguro

```bash
cancha seguro                  # qué se cumple hoy, y con qué número detrás
cancha seguro --calibrar       # la tabla entera de patrones medidos
```

La intuición de la que sale esto es buena: *«si el Madrid perdió el último, es
rarísimo que pierda el siguiente»*. El problema es el número. Nadie sabe si eso
es el 99 %, el 80 % o exactamente lo mismo que pasa siempre, porque nadie lo ha
contado.

Aquí se cuenta.

## Cómo se cuenta

Un **patrón** es una condición que se puede ver antes del partido y un
desenlace que se ve después. Se recorre todo el historial guardado y se publican
tres cifras juntas:

| Cifra | Qué es |
| --- | --- |
| **Frecuencia** | Lo que pasó, con su número de casos |
| **Suelo** | Lo que esa muestra permite defender (Wilson al 95 %) |
| **Elevación** | Cuánto se separa de su patrón de referencia |
| **Después** | Si se cumplió también en la parte del historial con la que no se midió |

**La elevación es la importante.** Si los favoritos ganan el 84 % y los
favoritos que pincharon ganan el 61 %, no hay reacción: hay tasa base, y el
módulo lo dice con esas palabras.

El suelo hace falta porque la frecuencia sola engaña: **8 de 8 es el 100 % y no
significa el 100 %**, significa «entre el 68 % y el 100 %». Con 30 casos el
suelo sube al 89 %; con 300, al 99 %. Es lo que separa un patrón de una racha.

Para que un patrón se publique tiene que pasar tres filtros: **30 casos**
mínimo, un **suelo por encima del 65 %** y una **elevación de al menos el 5 %**
sobre su referencia.

### La comprobación fuera de muestra

Los tres filtros protegen del azar, pero no de lo otro: que el patrón se haya
medido sobre los mismos partidos que lo hicieron parecer bueno. Contra eso, el
historial se parte **por fecha** —el 70 % más viejo y el 30 % más nuevo— y la
misma cuenta se hace dos veces.

| Veredicto | Qué significa |
| --- | --- |
| **aguanta** | El número se mantiene en la parte nueva, que no participó en medirlo |
| **se cae** | Cae más de lo que esa muestra puede explicar: se apoyaba en lo viejo |
| **sin muestra** | Menos de 12 casos después del corte: no alcanza para comprobar nada |

El corte es por fecha y no al azar a propósito: partir al azar dejaría partidos
posteriores en la mitad con la que se mide, y entonces comprobar el patrón en la
otra mitad no comprobaría nada.

Es lo más barato que se puede hacer contra el riesgo de haberle puesto nombre al
ruido, y lo más difícil de discutir. Un patrón que dice **aguanta** no es una
promesa; es lo único de aquí que no se eligió a sí mismo.

## Los patrones

| Patrón | Qué pregunta |
| --- | --- |
| La reacción del favorito | Era favorito, no ganó, y hoy vuelve a serlo: ¿gana? |
| El favorito no pierde | Sale de favorito: ¿evita la derrota? |
| El favorito claro gana | El mercado le da un 65 % o más: ¿gana? |
| El rebote tras la derrota | Perdió el último: ¿evita perder hoy? |
| El que marca siempre | Marcó en sus seis últimos: ¿marca hoy? |
| El que no marca | Lleva tres sin marcar: ¿sigue sin marcar? |
| El que gana todo | Ganó los cuatro últimos: ¿gana el quinto? |
| Los dos marcan | Los dos vienen de partidos con goles de ambos |
| Más de 2,5 / menos de 3,5 goles | Según lo que promedian entre los dos |
| Más de 9,5 córners | Los dos sacan y conceden muchos |
| Más de 3,5 amarillas | Pita un árbitro que promedia casi cinco |

Añadir uno es escribir una condición, un desenlace y —si hace falta— con qué
otro patrón hay que compararlo. Está en `cancha/seguro.py`.

## Lo que sale de verdad

Una calibración real tiene esta pinta:

```
PATRÓN                    CASOS   FREC   SUELO    BASE    ELEV  VEREDICTO
el_que_marca_siempre        130    90%     84%     55%    +35%  casi seguro
favorito_no_pierde          289    87%     83%     54%    +33%  casi seguro
racha_de_cuatro             151    88%     82%     87%     +1%  es la tasa base
reaccion_del_favorito        51    61%     47%     84%    -23%  poco
```

Las dos últimas líneas son el motivo de que esto exista. «El que gana todo» y
«la reacción del favorito» son justo las dos corazonadas que todo el mundo
tiene, y el recuento dice que una no añade nada sobre ser favorito y la otra va
en contra.

## Un patrón, no una ficha por partido

Un patrón se mide **una sola vez** sobre todo el historial. Así que cuando se
cumple en sesenta partidos del día, la frecuencia, los casos, la elevación y el
suelo son los mismos en los sesenta: lo único propio de cada partido es que la
condición se cumple, y el precio que le pone el mercado hoy.

Eso se enseñaba por partido, y salían sesenta fichas idénticas en las que solo
cambiaba el nombre del equipo. Parecía roto —y con razón: no era un error de
cálculo, era un error de cuento—. Ahora la respuesta trae las dos formas:

| Clave | Qué |
| --- | --- |
| `avisos` | La lista plana de siempre: un aviso por partido y patrón |
| `por_patron` | Agrupado: el patrón con su medición, y debajo sus partidos |

Dentro de cada grupo, los partidos van ordenados por **cuánto se separan del
mercado**, que es la única cifra que distingue a uno de otro. La interfaz y el
bot enseñan `por_patron`, con los que más se separan arriba.

## El mercado responde a la misma pregunta, o no se compara

«¿Evita la derrota?» no se compara con la probabilidad de que **gane**. Eso es lo
que hacía —enseñaba un 84 % de no perder al lado de un 49 % de ganar— y parecía
una ventaja enorme en todos los partidos del día cuando lo que había era una
resta entre dos cosas distintas.

Ahora cada patrón declara con qué número del mercado se compara:

| Patrón | Se compara con |
| --- | --- |
| El favorito no pierde, El rebote tras la derrota | `1 − P(gana el rival)` |
| El favorito claro gana, La reacción del favorito, El que gana todo | `P(gana)` |
| Goles, córners, tarjetas, marcan los dos | nada: el 1X2 no dice nada de eso |

Y cuando no hay equivalente, el aviso lo dice en vez de poner un número que no
viene al caso.

## Lo que no dice

- **No hay apuestas seguras.** El número más alto que sale de un historial de
  fútbol ronda el 85-90 %, y el mercado ya lo sabe: cuando la frecuencia y la
  cuota coinciden, no hay nada que ganar, solo algo que entender. Por eso cada
  aviso trae al lado lo que le da el mercado.
- **Se prueban doce patrones a la vez** sobre el mismo historial: alguno
  parecerá bueno por puro azar. Eso también está escrito en la respuesta, y la
  comprobación fuera de muestra es lo que pone a prueba a los que lo parecen.
- **La comprobación fuera de muestra no es una garantía**, es un filtro más:
  que algo se haya cumplido en el último tercio no obliga a que se cumpla
  mañana.
- **La muestra es tu memoria, no el fútbol.** Se mide sobre los partidos que tú
  has barrido, que son sobre todo de equipos que juegan hoy.
- Y cuanta más memoria, más fiable: con doscientos partidos no sale nada, y es
  correcto que no salga.

## Para la IA

La herramienta `casi_seguro` devuelve lo mismo, y su descripción le obliga al
modelo a leer la elevación antes de presentar nada como hallazgo.

---

[← Volver al índice](../README.md)
