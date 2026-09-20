# El pronóstico

```bash
cancha pronostico "Girona vs Osasuna"
cancha pronostico "Girona vs Osasuna" --abastecer   # y trae antes lo que falte
```

En Telegram, `/pronostico Girona vs Osasuna`. En la interfaz, dentro del
partido.

Marcador exacto con su probabilidad, 1X2, más/menos goles, marcan los dos,
córners y tarjetas. Y una cosa que conviene decir antes que ninguna otra:

> **Estos números los calcula esta aritmética, no un modelo de lenguaje.**

Si le das treinta y ocho partidos a un modelo de 8B y le pides el marcador
exacto, te lo da. Con seguridad, con detalle y sin ninguna base: se lo inventa,
y suena perfecto. Por eso el pronóstico se calcula aquí y el modelo solo lo lee
en voz alta. Sus instrucciones le prohíben dar una cifra que no le hayan dado.

## Cómo se calculan los goles

El modelo clásico de fuerzas multiplicativas, que es lo que hay detrás de casi
todo lo que se publica:

```
λ_local   = media_liga × ataque(local) × defensa(visitante) × ventaja
λ_visita  = media_liga × ataque(visitante) × defensa(local) ÷ ventaja
```

`ataque(e)` es lo que marca ese equipo dividido por lo que marca un equipo medio
de su liga; `defensa(e)`, lo mismo con lo que encaja. La `ventaja` de jugar en
casa sale de comparar lo que se marca de local y de visitante **en esa
competición**, no de un número de manual.

Con las dos lambdas, la matriz de marcadores es el producto de dos Poisson, y de
ahí salen el 1X2, los marcadores exactos, los más/menos y el «marcan los dos».

### Se prefiere el xG a los goles

Marcar dos con 0,4 de xG es suerte, y la suerte no se repite. Cuando hay
muestra suficiente las fuerzas se miden en xG; si no, en goles. La respuesta
dice siempre cuál se ha usado (`medido_en`).

### Las fuerzas van encogidas

Esta es la parte que más importa y la que más se salta la gente. Sin ella, un
equipo que en diez partidos ha marcado el doble de la media, contra otro que ha
encajado el doble, da **lambdas de cinco goles**. Y no es un fallo de la
fórmula: es que con diez partidos **no se sabe** que un equipo sea el doble de
bueno; lo parece.

Así que la fuerza medida se tira hacia la media de su liga según la muestra:

| Partidos | Ataque medido 2,0 | Ataque medido 0,5 |
| --- | --- | --- |
| 5 | 1,38 | 0,81 |
| 10 | 1,56 | 0,72 |
| 20 | 1,71 | 0,64 |
| 100 | 1,93 | 0,54 |

Con mucha muestra apenas la toca. Con poca, la deja cerca de 1, que es decir
«de este equipo todavía no sé nada especial». La respuesta trae los dos números,
`ataque` y `ataque_sin_encoger`, para que se vea lo que se ha movido.

## Córners y tarjetas

Por la media entre lo que hace uno y lo que concede el otro: si el Girona saca
seis córners y al Osasuna le sacan ocho, lo razonable es esperar siete, no seis
ni ocho. Con esa media y una Poisson salen las líneas.

Las tarjetas además llevan **el árbitro**, si está designado y tiene al menos
ocho partidos guardados: se compara su ritmo con el de su liga y se ajusta. Con
menos partidos no se ajusta nada y se dice.

## Contra el mercado

Cada pronóstico se compara con la cuota cuando la hay, porque es la única
pregunta honesta:

> **El mercado es un modelo, y es bueno.** Sabe de alineaciones, de bajas y de
> dinero. Donde coincide con este cálculo no hay nada que ganar, solo algo que
> entender. Donde no coincide, lo más probable sigue siendo que se equivoque
> este.

Eso sale escrito en la respuesta, no en una nota al pie.

## Lo que no dice

- **No sabe de lesiones, rotaciones ni de si el partido se juega a nada.**
- **No corrige la correlación entre los dos marcadores** (Dixon-Coles), así que
  el 0-0 y el 1-1 salen algo por debajo de lo real. Se dice en vez de
  disimularlo: corregirlo bien exige ajustar un parámetro con datos, y
  inventarse el parámetro sería peor que no tenerlo.
- **El marcador más probable de un partido de fútbol ronda el 10-12 %.** Que uno
  encabece la lista no significa que vaya a pasar: significa que es el menos raro
  de muchos. Cualquier cosa que presente un marcador exacto sin esa cifra al
  lado te está vendiendo algo.
- Y si falta muestra, lo dice y te manda a `--abastecer` en vez de pronosticar
  sobre tres partidos.

## El agente

El analista local (`cancha analista`, el chat de la interfaz y el texto libre de
Telegram) tiene esta herramienta y la orden de usarla:

> Los pronósticos salen de `pronostico_partido`, no de tu cabeza. No sumes
> medias, no redondees, no inventes una probabilidad que «suena bien». Y al dar
> un marcador di su probabilidad.

Sobre qué modelo poner, ver [El analista local](analista.md).

---

[← Volver al índice](../README.md)
