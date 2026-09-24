# El backtest: el pasado, con lo que se sabía entonces

```bash
cancha historia --plan      # cuánto hay que traer
cancha historia             # traerlo (una vez; luego solo lo nuevo)
cancha backtest             # rehacer cada pronóstico y medirlo
cancha backtest --ultimo    # el último, sin rehacerlo
```

En la interfaz, **Seguro → Picks → El backtest**.

Sin esto, la única forma de saber si el modelo o la regla de picks valen algo
era esperar seis meses apuntando. Con la historia traída, la memoria ya tiene
miles de partidos jugados con sus cuotas. El backtest rehace el pronóstico de
cada uno **usando solo lo jugado antes de él** y contesta tres preguntas.

## Las tres preguntas

1. **¿El modelo sabe algo que el mercado no sabe?** No «¿acierta mucho?», que
   depende de qué partidos mires. La pregunta es: si a la probabilidad del
   mercado le mezclas un poco de la nuestra, ¿mejora? Se prueban pesos de 0 (el
   mercado solo) a 1 (nuestro modelo solo) y se mide con el log loss del 1X2.
2. **¿La regla de picks habría ganado?** Simulada partido a partido, a la cuota
   de cierre, con el peso elegido. Y al lado, lo que habría pasado eligiendo los
   picks con el modelo a secas.
3. **¿Quién acierta más en marcador exacto?** Cuando la fuente tenía ese
   mercado: la probabilidad que le dio cada uno al marcador que salió.

Además, suceso a suceso (más de 2,5, marcan los dos, córners, tarjetas), el
Brier nuestro contra el del mercado, y la **calibración** del 1X2: de las veces
que dijo 60 %, cuántas pasó.

## Lo que lo hace honesto

- **Sin mirar el futuro.** Las fuerzas de cada equipo y las medias de la liga se
  cortan en la fecha del partido. Hasta la 0.19 la media de la liga no se
  cortaba y el pronóstico «sabía» cómo había ido el resto de la temporada: un
  backtest así hace trampa sin que se note. Hay un test que lo comprueba
  metiendo cien partidos 7-6 después y viendo que el pronóstico no se mueve.
- **El peso se elige con la primera mitad y se mide en la segunda.** Elegirlo y
  medirlo sobre los mismos partidos garantiza que salga algo mejor que cero
  aunque el modelo no sirva para nada.
- **A la cuota de cierre**, la más difícil de batir: ya lleva dentro las
  alineaciones y el dinero.
- **Con menos de 300 partidos con cuotas lo dice**: lo que salga es un indicio,
  no un juicio. Con menos de 40 no concluye nada.

## Los veredictos

| Veredicto | Qué quiere decir | Qué pasa con los picks |
| --- | --- | --- |
| **aporta** | Con el peso elegido, la mezcla gana al mercado solo en la mitad que no vio, y el intervalo al 95 % de la mejora queda entero por encima de cero | Se usa ese peso |
| **no aporta** | El mejor peso, elegido con la primera mitad, era cero | Peso 0: **no hay picks** |
| **no se distingue** | Mejora, pero tan poco que cabe en el azar | Peso 0: **no hay picks** |
| **sin muestra** | Menos de 40 partidos con el 1X2 de los dos lados | Peso 0: **no hay picks** |

Lo que diga se guarda (`cancha backtest --no-guardar` para mirar sin cambiar
nada) y es lo que usan los picks desde la regla-2. Si el modelo no aporta, no
hay picks. Es incómodo, y es exactamente lo que hay que hacer: casi toda la
distancia entre un modelo y el mercado es **error del modelo**, y elegir picks
con el modelo a secas es elegir sus errores más grandes y apostar a ellos.

## Cómo se mezcla

En logit, no en probabilidad:

```
logit(p) = peso × logit(nuestra) + (1 − peso) × logit(mercado)
```

Mezclar en logit respeta los extremos: un 95 % y un 90 % no se promedian como un
55 % y un 50 %.

## Lo que se probó y cómo

Sobre una liga inventada en la que se sabe la verdad (`tests/liga_sintetica.py`):

- con un **mercado que sabe la verdad**, el modelo a secas elige muchos picks y
  pierde; la regla con el peso validado casi no da picks y el veredicto es «no se
  distingue»;
- con un **mercado que no sabe nada**, el peso elegido es alto, el veredicto es
  «aporta» y los picks ganan.

Un backtest que siempre sale bonito no vale para nada: lo que se prueba es que
cambie de veredicto cuando cambia la realidad. **No se ha corrido todavía sobre
datos reales**: eso es lo primero que hay que hacer con la historia traída.

## Lo que no dice

- Solo ve partidos **con cuotas guardadas**. Si solo hay cuotas de las ligas
  grandes, no dice nada de las pequeñas, que es donde un modelo suele tener más
  que aportar.
- En la vida real se apuesta antes del cierre, a una cuota que puede ser mejor o
  peor que la de aquí.
- Si alguien retoca la regla hasta que el backtest salga bonito, el backtest deja
  de valer. Por eso la regla lleva versión.

---

[← Volver al índice](../README.md)
