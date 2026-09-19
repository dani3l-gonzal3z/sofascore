# Respuestas reales

Esta carpeta está **vacía a propósito**. Aquí van las respuestas de verdad de
la API, y solo pueden ponerlas quien pueda llegar a ella.

## Por qué existe

Las respuestas de ejemplo de `tests/fixtures/` están escritas a mano. Sirven
para probar la lógica, pero no pueden decir si la API devuelve lo que el código
supone. Esa diferencia dejó pasar dos fallos serios:

- `/h2h/events` quiere el `customId` y no el id numérico — estuvo dos rondas
  roto en silencio, porque las respuestas de ejemplo no traían `customId`;
- los cambios de jugador no usan la clave `player`, así que salían sin nadie.

`tests/test_contrato.py` comprueba justo eso, y necesita esto para funcionar.
Sin grabaciones se salta entero, con un aviso.

## Cómo llenarla

```bash
cancha grabar 12437616
```

Graba un partido completo, un equipo, un jugador y una competición. Con
`--fuentes` añade Understat y ClubElo. Después:

```bash
python -m pytest tests/test_contrato.py -v
cancha grabaciones                 # qué hay guardado
```

## Qué se guarda, y qué no

**Solo la respuesta.** Nunca la petición, que es donde viaja tu cookie de
Sofascore Plus: no acaba en ningún fichero.

Aun así, míralo antes de subirlo: son datos de un servicio ajeno. Si los
subes al repositorio, el CI empieza a comprobar el contrato en cada push, que
es exactamente lo que interesa.

## Volver a usarlas sin red

Cualquier comando puede servirse de una grabación en vez de salir a internet:

```bash
cancha match 12437616 --all --replay tests/fixtures/reales
```

Útil para depurar un fallo sin gastar peticiones, y para reproducir tal cual lo
que pasó el día que se grabó.
