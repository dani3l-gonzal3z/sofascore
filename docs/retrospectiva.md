# Un partido ya jugado: lo que dijimos, frente a lo que pasó

```bash
cancha retrospectiva "Betis vs Sevilla"
cancha retrospectiva 12345678 --json
```

En la interfaz, al abrir un partido ya jugado sale arriba **Lo que dijimos antes,
y lo que pasó**. En la conversación del partido, el modelo lo tiene en la ficha y
como herramienta (`retrospectiva_partido`), y las preguntas sugeridas cambian:
«¿qué dijimos antes y en qué nos equivocamos?», «¿quién estuvo más cerca?».

## De dónde sale

Todo lo que se dice de un partido antes de jugarse queda escrito en sitios que
no se tocan después:

- **el briefing de su día** (un fichero por día en `datos/briefings`): nuestro
  1X2, los marcadores más probables, lo que decía el mercado, dónde
  discrepábamos y el pick. Se busca también el día de antes y el de después,
  porque un partido a medianoche cae en uno o en otro según el huso;
- **el registro**: la primera predicción apuntada de cada autor —el cálculo, el
  mercado, cada agente— es la que cuenta;
- **los picks**, con la cuota a la que se dieron;
- **el primer dictamen del analista**, solo si se hizo **antes del saque**. Uno
  hecho después ya sabía el resultado, y ponerlo al lado del marcador como si
  fuera una predicción sería hacerse trampas.

## Cómo se mide quién estuvo más cerca

No con «¿acertó?». En un 1X2, un 45 % al que ganó es mejor pronóstico que un
30 %, aunque ninguno de los dos «acertase» nada. Así que de cada suceso se mira
**cuánta probabilidad le dio cada uno a lo que pasó**:

_Ejemplo para ver la forma: **los números son inventados**._

```
A LO QUE PASÓ, CUÁNTO LE DIO CADA UNO
  1X2                  pasó: empate                 el cálculo 30% · el mercado 27%  → nosotros
  Más de 2,5 goles     pasó: no (2 goles)           el cálculo 40% · el mercado 48%  → el mercado
  Marcador exacto      pasó: 1-1                    el cálculo 11%  → sin mercado
```

Diferencias de menos de dos puntos salen como «igual». Y del marcador exacto se
dice en qué puesto de nuestra lista estaba el que salió: un 1-1 que era nuestro
segundo más probable no es lo mismo que uno que era el vigésimo.

## Lo que no dice

Un partido suelto no dice si el modelo es bueno. Eso lo dice el
[backtest](backtest.md) con cientos, y la lectura lo recuerda cada vez. Esto
sirve para otra cosa: ver en qué se equivocó y si lo que se veía venir tenía
sentido.

Si un partido no pasó por el briefing ni por la guardia de su día, no se apuntó
nada antes, y lo dice en vez de compararlo con un pronóstico calculado después,
que ya tendría el resultado dentro.

---

[← Volver al índice](../README.md)
