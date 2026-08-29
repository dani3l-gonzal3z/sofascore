# Análisis: las cuentas ya hechas

Un modelo sumando treinta valores de xG te da un número redondo, con aplomo y
equivocado. Estas métricas se calculan en Python y llegan **correctas**:

```bash
cancha analisis 12437616
```
```
Real Madrid 0 - 4 Barcelona  (LaLiga, 2024-10-26)

¿Ganó el que mereció?
  gana Real Madrid               9.6%
  empate                        24.0%
  gana Barcelona                66.4%
  puntos esperados: Real Madrid 0.53 · Barcelona 2.23
  Barcelona sacó algo más de lo que merecía por ocasiones.

Calidad de las ocasiones
  Barcelona
    5 tiros · xG 1.52 (0.304 por tiro) · 3 claras · 1 lejanos
    Muy por encima de lo esperable: acierto excepcional o portero rival flojo.

Manda en xG: Barcelona, desde el minuto 56
```

| Métrica | Qué contesta |
| --- | --- |
| **Puntos esperados** | ¿Ganó el que mereció? Probabilidad de victoria, empate y derrota |
| **Calidad de tiro** | ¿Tres ocasiones claras o quince chutes de lejos? |
| **Carrera de xG** | ¿*Cuándo* se generó el peligro, no solo cuánto? |
| **Por situación** | Jugada abierta, córner, falta, penalti |
| **Aportación** | Quién generó el peligro, ordenado por xG (no por nota) |
| **Por periodos** | Qué cambió del descanso a la vuelta |

Los puntos esperados no son una estimación a ojo: cada disparo es una moneda
trucada con probabilidad su xG, y la distribución de goles sale de
**convolucionarlas una a una** —exacta, no una aproximación de Poisson—. De ahí
la probabilidad de cada resultado. El único supuesto es que los disparos son
independientes entre sí, y queda dicho en la propia respuesta.

Todo son funciones puras sobre un informe ya traído (`sofascore/analisis.py`):
no tocan la red, así que son rápidas y deterministas.

```python
from cancha import get_match
from cancha.analisis import analisis_completo, puntos_esperados

partido = get_match(12437616, sections=["all"])
puntos_esperados(partido)["probabilidades"]
analisis_completo(partido)
```

---

[← Volver al índice](../README.md)
