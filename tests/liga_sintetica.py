"""Una liga inventada en la que se sabe la verdad, para probar el backtest.

Cada equipo tiene un ataque y una defensa fijos; los goles salen de una Poisson
con esas fuerzas. El «mercado» puede saber la verdad o no saber nada, a voluntad:
así se comprueba que el backtest dice «aporta» cuando el modelo sabe algo que el
mercado no, y «no aporta» cuando no, en vez de decir siempre lo mismo.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

from cancha.mercados import con_probabilidades

EQUIPOS = {  # id: (ataque, defensa) — defensa > 1 es que concede más
    1: (1.6, 0.7), 2: (1.4, 0.8), 3: (1.1, 1.0),
    4: (0.9, 1.1), 5: (0.8, 1.3), 6: (0.6, 1.4),
}
BASE, CASA = 1.25, 1.15


def _poisson(rng: random.Random, lam: float) -> int:
    limite, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limite:
            return k
        k += 1


def _prob_1x2(lam_l: float, lam_v: float) -> dict[str, float]:
    pl = [math.exp(-lam_l) * lam_l ** g / math.factorial(g) for g in range(11)]
    pv = [math.exp(-lam_v) * lam_v ** g / math.factorial(g) for g in range(11)]
    local = sum(pl[a] * pv[b] for a in range(11) for b in range(11) if a > b)
    empate = sum(pl[a] * pv[a] for a in range(11))
    return {"local": local, "empate": empate, "visitante": 1 - local - empate}


def sembrar(almacen, vueltas: int = 8, mercado: str = "sabe", semilla: int = 7) -> int:
    """Llena la memoria con `vueltas` ligas enteras de ida y vuelta.

    `mercado` es «sabe» (cuotas sacadas de las fuerzas de verdad, con un 5 % de
    margen), «no_sabe» (un 1X2 plano, igual para todos) o «nada» (sin cuotas).
    Devuelve cuántos partidos ha metido.
    """
    rng = random.Random(semilla)
    dia = datetime(2023, 8, 1, 18, tzinfo=timezone.utc)
    pid = 1
    for _ in range(vueltas):
        for local in EQUIPOS:
            for visitante in EQUIPOS:
                if local == visitante:
                    continue
                al, dl = EQUIPOS[local]
                av, dv = EQUIPOS[visitante]
                lam_l, lam_v = BASE * al * dv * CASA, BASE * av * dl / CASA
                gl, gv = _poisson(rng, lam_l), _poisson(rng, lam_v)
                almacen._conexion.execute(
                    """INSERT INTO partidos (id, fecha, momento, liga_id, liga, local_id,
                       local, visitante_id, visitante, goles_local, goles_visitante,
                       estado) VALUES (?,?,?,?,?,?,?,?,?,?,?, 'finished')""",
                    (pid, dia.strftime("%Y-%m-%d"), dia.timestamp(), 99, "Liga Inventada",
                     local, f"Equipo {local}", visitante, f"Equipo {visitante}", gl, gv))
                if mercado != "nada":
                    verdad = (_prob_1x2(lam_l, lam_v) if mercado == "sabe"
                              else {"local": 1 / 3, "empate": 1 / 3, "visitante": 1 / 3})
                    filas = [{"casa": "casa", "mercado": "1x2", "linea": "", "seleccion": s,
                              "cuota": round(1 / (p * 1.05), 3)} for s, p in verdad.items()]
                    almacen.guardar_mercados(pid, con_probabilidades(filas), "prueba")
                pid += 1
                dia += timedelta(days=1)
    almacen._conexion.commit()
    return pid - 1
