# Desarrollo

```bash
python -m pytest                  # 398 tests, sin red
ruff check .                      # el mismo estilo que exige el CI
python examples/demo_offline.py   # el informe completo con datos de ejemplo
python examples/entidades.py      # equipos, jugadores y ligas (necesita red)
```

### Grabar respuestas reales

Los tests de arriba usan respuestas escritas a mano: prueban que el código es
coherente **consigo mismo**, no que la API devuelva lo que aquí se supone. Esa
diferencia dejó pasar dos fallos serios (`/h2h/events` quería el `customId` y
no el id; los cambios de jugador no usan la clave `player`).

```bash
cancha grabar 12437616            # graba partido, equipo, jugador y liga
python -m pytest tests/test_contrato.py -v
```

`tests/test_contrato.py` comprueba lo único que los demás no pueden: que lo que
el código da por supuesto esté de verdad en la respuesta. Sin grabaciones se
salta entero, con el aviso de cómo conseguirlas.

Se guarda **solo la respuesta**, nunca la petición: tu cookie de Plus no acaba
en ningún fichero. Si subes las grabaciones al repositorio, el CI empieza a
comprobar el contrato en cada push.

Y cualquier comando puede servirse de ellas en vez de salir a internet:

```bash
cancha match 12437616 --all --replay tests/fixtures/reales
cancha grabaciones                # qué hay guardado
```

### Integración continua

Cada push y cada PR ejecutan los tests solos, en tres sistemas y cuatro
versiones de Python:

| Trabajo | Qué comprueba |
| --- | --- |
| `tests` | Python 3.10, 3.11, 3.12 y 3.13 en Linux; 3.12 en Windows y macOS |
| `sin-dependencias` | Que instalado **sin extras** todo sigue funcionando, y que no se ha colado ninguna dependencia por la puerta de atrás |
| `estilo` | `ruff` con la configuración de `pyproject.toml`, la misma que en tu máquina |

Los tests no tocan la red, así que el CI no depende de que Sofascore esté de
buenas ni se pone a hacerle peticiones.

Los tests usan `FakeTransport` y respuestas guardadas en `tests/fixtures/`:
nada sale a internet, así que corren igual de rápido con o sin conexión.

---

[← Volver al índice](../README.md)
