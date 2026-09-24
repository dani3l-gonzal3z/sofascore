# El registro: qué predijo y cómo acabó

Un pronóstico que nadie apunta no se puede juzgar. Y uno que se puede reescribir
después de ver el resultado no vale absolutamente nada.

Así que cada predicción se escribe **antes** del partido —con su fecha, su
probabilidad, la del mercado en ese momento y la versión del cálculo que la
hizo— y no se vuelve a tocar. Lo único que se rellena luego es el resultado.

```bash
cancha resultados                  # qué tal acierta
cancha resultados --mercado 1x2    # solo un mercado
cancha resultados --resolver       # puntuar las que ya se han jugado
```

En la interfaz es **Seguro → Cómo acierto**, y en el bot `/resultados`.

Cada predicción lleva además **quién la hizo**. `calculo` es el Poisson de
siempre, `mercado` son las cuotas apuntadas como un concursante más —gratis, y es
el listón—, y un [agente](agentes.md) es cualquier analista que le hayas escrito.
Varios pueden opinar del mismo suceso del mismo partido, y eso es lo que hace
posible la [clasificación](agentes.md#la-clasificación-y-por-qué-no-ordena-por-lo-que-parece).

```bash
cancha resultados --autor calculo    # el balance de uno solo
cancha clasificacion                 # todos, ordenados por la ventaja sobre el mercado
```

## Se apunta solo

La guardia nocturna, cuando prepara el día siguiente, apunta el pronóstico de
cada partido de la agenda y resuelve los de días anteriores que ya se hayan
jugado. No hay que acordarse de nada: si dejas el ordenador encendido, el
registro se llena solo.

De cada partido se apuntan seis cosas, y cada una es un **sí o no** con su
probabilidad —que es lo que se puede calibrar—:

| Mercado | Qué se apunta |
| --- | --- |
| `1x2` | Las tres: local, empate y visitante, por separado |
| `mas_2_5` | Si pasan de 2,5 goles |
| `ambos_marcan` | Si marcan los dos |
| `corners` | Si pasan de 9,5 córners |
| `tarjetas` | Si pasan de 3,5 amarillas |
| `marcador` | El marcador exacto más probable |

Una predicción no se puede escribir dos veces: la primera es la que cuenta. Si
vuelves a pedir el pronóstico de ese partido —y va a salir distinto, porque
mientras tanto has barrido más— lo que queda registrado sigue siendo lo que se
dijo entonces.

## Cómo se mide, y por qué en ese orden

**1. Calibración.** De las veces que dijiste 70 %, ¿pasó el 70 %? Esta es *la*
medida, y viene de la meteorología, no de las apuestas: un hombre del tiempo que
dice «70 % de lluvia» y acierta el 70 % es bueno aunque falle tres de cada diez.
Uno que dice 70 % y llueve el 95 % de las veces no es mejor: está mal escrito.

```
Calibración (de las veces que dijo X, pasó Y):
     0%-20%  dijo 15%  ↓  pasó  9%   (22 casos)
    20%-40%  dijo 28%  ↑  pasó 34%  (102 casos)
    40%-60%  dijo 48%  ↓  pasó 36%   (47 casos)
    60%-80%  dijo 65%  →  pasó 67%    (9 casos)
```

**2. Brier**, el error cuadrático medio de la probabilidad: `(p − resultado)²`.
Menos es mejor, y **siempre va al lado del 0,25** que saca quien dice 50 % a
todo. Un Brier suelto no significa nada.

**3. Contra el mercado.** El mismo Brier, calculado sobre las probabilidades que
implicaban las cuotas. Es la única comparación que importa: el mercado es el
rival, y lo normal —lo esperable— es perder contra él.

**4. CLV** (*closing line value*): si dijiste 45 % y el mercado acabó en 52 %, el
mercado se movió hacia ti. Es el único indicio de ventaja que **no depende de
haber acertado**, y por eso es el que miran los que se juegan dinero de verdad.
Aquí sale de restar la probabilidad del mercado cuando se predijo y la última
vista, así que es una aproximación: para el cierre exacto haría falta guardar el
historial entero de cuotas.

**5. El acierto**, el último y con su intervalo de Wilson. «Acerté 7 de 10» no
dice nada: si las diez eran favoritos claros, acertar 7 es malo.

Con menos de **50 casos resueltos** todo esto se publica como indicio, no como
juicio, y lo dice.

## Lo que no hay, a propósito

Ni unidades, ni bankroll, ni ROI, ni consejos. Esto mide si el cálculo describe
bien el fútbol. Lo que alguien haga con eso es cosa suya, y el programa no opina.

## De dónde sale la idea

Vale la pena decir en qué se parece y en qué no a las herramientas de pago del
sector —Opta y StatsBomb por el lado de los datos, Smartodds y las casas por el
lado del modelo, y los servicios de pronósticos por suscripción—.

**Lo que hacen bien, y está copiado aquí:**

- **Calibración antes que acierto.** Cualquier sitio serio mide así. Los que
  venden pronósticos, no.
- **El CLV como juez.** Es lo que usan las casas para decidir a quién limitan:
  si le ganas al cierre, sabes algo; si no, has tenido suerte.
- **Comparar siempre contra el mercado**, que es el listón real.
- **Fuera de muestra.** Medir con datos que no participaron en elegir el patrón,
  que es lo que hace [Casi seguro](seguro.md).
- **Registro inmutable y fechado.** Nadie que se lo tome en serio permite editar
  una predicción pasada.

**Lo que hacen mal, y aquí se evita:**

- **Publicar algo todos los días.** Un servicio de suscripción *tiene* que sacar
  pronósticos aunque no haya nada que decir, porque cobra por eso. Aquí, cuando
  no hay muestra, lo que sale es «no hay muestra».
- **El acierto como titular.** Es la cifra que mejor se vende y la que menos
  informa.
- **Sin número de casos ni intervalos.** Un 78 % sin decir sobre cuántos es
  publicidad.
- **La caja negra.** Aquí cada número trae de dónde sale y con qué muestra, y el
  método está escrito en el propio documento.
- **El ROI de un plan de apuestas elegido a posteriori.** Con el criterio de
  reparto adecuado, cualquier historial parece rentable.
- **Historiales que se limpian.** Los perdedores desaparecen. Por eso la tabla no
  se puede reescribir.

## Lo que todavía no sabe medir

- **El cierre exacto.** Se guarda una cuota por partido, no su historial, así que
  el CLV usa la última vista. Se dice a cuántas horas del saque fue.
- **Alineaciones y bajas**, que es justo donde el mercado saca su ventaja.
- **Y la muestra es tu memoria, no el fútbol**: lo que barres son sobre todo
  equipos que juegan pronto.

---

[← Volver al índice](../README.md)
