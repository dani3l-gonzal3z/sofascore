"""El tope del barrido: tiene que contar todo lo que se pide, no una parte.

Un tope que ignora las peticiones más caras —descubrir competiciones y la
agenda liga por liga— deja al usuario gastando cuatro veces lo que pidió.
"""

from __future__ import annotations

from cancha import barrido
from cancha.almacen import Almacen


def test_el_tope_cuenta_todas_las_peticiones_no_solo_las_del_detalle(tmp_path, cliente,
                                                                    monkeypatch):
    gastadas_antes = []

    def asegurar_caro(c, a, g=None, avisar=None):
        # Descubrir competiciones cuesta, y ese coste también es del tope.
        for _ in range(4):
            c.stats.requests += 1
        gastadas_antes.append(c.stats.requests)
        return {"encontradas": 0, "buscadas": 4}

    monkeypatch.setattr(barrido, "asegurar", asegurar_caro)
    with Almacen(tmp_path / "t.db") as almacen:
        resumen = barrido.barrer(cliente, almacen, fecha="2024-10-26",
                                 grupos=["grandes"], maximo_peticiones=3)
    assert gastadas_antes, "asegurar no llegó a llamarse"
    # Lo que se informa es lo gastado de verdad, y ya pasa del tope por lo que
    # costó descubrir: así que el barrido no entra siquiera en los equipos.
    assert resumen["peticiones"] >= 4
    assert resumen["guardados"] == 0


def test_sin_tope_se_barre_entero(tmp_path, cliente):
    with Almacen(tmp_path / "t2.db") as almacen:
        resumen = barrido.barrer(cliente, almacen, fecha="2024-10-26", grupos=["grandes"])
    assert resumen["peticiones"] > 0


def test_el_tope_se_mira_entre_partidos_no_solo_entre_equipos(cliente, tmp_path):
    """Un equipo son seis partidos: mirarlo solo al empezar se pasa de largo."""
    import inspect

    fuente = inspect.getsource(barrido.rellenar_equipo)
    assert "puede_seguir" in fuente
    assert fuente.index("puede_seguir is not None") < fuente.index("guardar_partido(")
