# Los picks: una regla, el precio y un historial que no se toca

Esta es la parte que se puede vender, y conviene empezar por lo que **no** es:
**no es «la apuesta segura del día»**. No existe. Quien la vende o se equivoca o
miente, y el cliente lo descubre en dos semanas. Lo que sí aguanta es esto:

1. **Una regla escrita antes**, igual todos los días. No se elige a ojo ni se
   cambia según vaya el mes.
2. **El precio al que se dio**, apuntado antes del saque. Un acierto a 1,30 y
   uno a 2,40 no valen lo mismo, y un historial sin precios no se puede comprobar.
3. **Un historial que nadie puede reescribir**, medido al precio tomado, con su
   intervalo, y con el **CLV**: si la cuota se movió después hacia nuestro lado.

Y los días en que nada pasa la regla, **no hay pick**. Eso no es un fallo del
producto: es lo que lo hace creíble. Un servicio que da un pick todos los días
pase lo que pase está vendiendo volumen, no criterio.

```bash
cancha picks                  # los de hoy, apuntados o calculados ahora
cancha picks --apuntar        # apuntarlos con el precio de ahora (no se deshace)
cancha picks --resolver       # resolver los ya jugados
cancha picks --historial      # cómo van, en cada nivel
```

En la interfaz, **Seguro → Picks** y la portada de **Hoy**. En el bot, `/pick`,
`/picks` y `/historial`.

## La regla

| Condición | Por qué |
| --- | --- |
| Cuota entre 1,50 y 3,50 | Por debajo, el margen se come la ventaja posible; por encima, la varianza es tanta que cien picks no dicen nada |
| Valor de al menos un 5 % al precio que se da | `nuestra probabilidad × cuota − 1` |
| Al menos 4 puntos por encima del mercado | Valor sin separación suele ser un precio raro de una sola casa, no una opinión nuestra |
| 8 partidos guardados de cada equipo | Con menos, el pronóstico es una extrapolación |
| La casa cobra menos de un 8 % en ese mercado | Por encima no es un mercado, es un peaje |
| Uno por partido | Dos del mismo partido son la misma apuesta dos veces |

La cuota del pick es **la mejor que se puede apostar**. El precio medio de
Betfair sirve para saber qué cree el mercado, pero no se puede apostar a él.

La regla lleva versión (`regla-1`) y cada pick la apunta. Cambiar la regla es
cambiar de producto, y mezclar en un historial los picks de dos reglas es
mezclar dos productos.

## Los dos niveles

- **Gratis**: el mejor pick del día, si lo hay.
- **Premium**: todos los que pasan la regla, con su partido abierto al detalle
  —el pronóstico, las casas, el marcador exacto y la conversación con el
  modelo—.

Cada nivel lleva **su propio historial**. Son dos productos, y el premium no
puede presumir de lo que acertó el gratis ni al revés.

## Cómo se publican

La [guardia](dejarlo-funcionando.md) resuelve cada noche los de antes, elige los
del día siguiente con la regla, **los apunta con el precio de ese momento** y,
si hay canales puestos, el bot publica en cada uno su boletín:

_Ejemplo para ver la forma: **los números son inventados**, no es un resultado real._

```
El pick del 2026-09-26

⚽ Girona - Osasuna · 19:00 UTC
   Gana el local a 2.1 (bet365)
   Nosotros 55% · mercado 46% · valor +16%

Historial: 142 picks, 71 acertados, +9.40 unidades (+6.6%).
Con menos de 200 picks esto todavía no demuestra nada.

Una unidad por pick. Nada es seguro: esto es una probabilidad con su precio,
no una promesa. Juega con cabeza, y solo si eres mayor de edad.
```

Los canales van en **Ajustes → Telegram** (`canal_gratis`, `canal_premium`): el
id del canal (`-100…`) o su `@nombre`. El bot tiene que ser administrador de
cada canal. Quién entra en el premium lo decides tú al dar acceso al canal; aquí
no hay cobros.

## El historial

_Ejemplo para ver la forma: **los números son inventados**, no es un resultado real._

```
GRATIS
  142 picks (2026-03-02 → 2026-09-25) · 71 acertados (50%) · cuota media 2.14
  +9.40 unidades · rendimiento +6.6% [-9.8%, +23.0%] · peor racha -11.00
  gana al cierre en el 61% (138 con cierre) · CLV medio +2.3%
```

- **A una unidad por pick**, sin trucos de gestión de banca que maquillen nada.
- **El rendimiento con su intervalo al 95 %.** Cuarenta picks con un +15 % no son
  un +15 %: son algo entre un −20 % y un +50 %, y hay que decirlo así.
- **La peor racha**, que es lo que de verdad aguanta o no aguanta un cliente.
- **El CLV**: en cuántos picks la cuota cerró por debajo de la que se dio. Es lo
  que mejor predice si esto va a ganar a largo plazo, mucho antes que el acierto
  o el rendimiento, que con pocos picks son casi todo suerte.

## Antes de cobrar a nadie

Tres cosas, dichas claras:

1. **Todavía no sabemos si esto gana.** Nada de lo de arriba se ha medido con
   partidos de verdad. Hace falta un historial de **al menos 200 picks** —el
   propio boletín lo dice mientras no los haya— y, sobre todo, un CLV positivo
   sostenido. Si el mercado no se mueve hacia nosotros, un rendimiento bueno es
   suerte y se acabará.
2. **La regla es un punto de partida, no un descubrimiento.** Los umbrales son
   razonables, no están optimizados, y optimizarlos sobre el mismo historial
   con el que luego se presume sería hacerse trampas. Si se cambian, se cambia
   de versión y se empieza el historial de cero.
3. **Vender pronósticos deportivos tiene normas.** En España la publicidad del
   juego está regulada (Real Decreto 958/2020) y hay límites a cómo se puede
   anunciar algo así. Antes de cobrar, consúltalo con alguien que sepa.
