"""Traerse años de partidos de golpe, y poder cortar y seguir.

La memoria se llenaba partido a partido, y así no se junta muestra: para que un
perfil de equipo signifique algo hacen falta un par de temporadas, y a seis
partidos por visita eso son meses.

Lo que se prueba aquí es lo que hace que esto sea usable y no un botón que se
cuelga: que se sepa lo que va a costar **antes**, que corte por fecha en cuanto
se pasa, que respete el tope y que repetirlo no vuelva a pedir lo mismo.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from cancha.almacen import Almacen
from cancha.historia import plan, temporadas_de, traer


def _dia(hace_dias: int) -> int:
    return int((datetime.now(timezone.utc) - timedelta(days=hace_dias)).timestamp())


class ClienteFalso:
    """Se hace pasar por Sofascore: dos temporadas y unos partidos por página."""

    def __init__(self, temporadas=None, paginas=None):
        self.temporadas = temporadas if temporadas is not None else [
            {"id": 100, "year": "25/26"}, {"id": 99, "year": "24/25"},
            {"id": 50, "year": "05/06"},          # fuera de la ventana
        ]
        self.paginas = paginas if paginas is not None else {}
        self.pedidos: list[tuple] = []

        class Contadores:
            requests = 0
        self.stats = Contadores()

    def seasons(self, liga_id):
        self.pedidos.append(("seasons", liga_id))
        self.stats.requests += 1
        return self.temporadas

    def season_events(self, liga_id, temporada_id, pagina=0, when="last"):
        self.pedidos.append(("eventos", liga_id, temporada_id, pagina))
        self.stats.requests += 1
        return self.paginas.get((temporada_id, pagina), [])


def _evento(identificador: int, hace_dias: int) -> dict:
    return {
        "id": identificador,
        "startTimestamp": _dia(hace_dias),
        "status": {"type": "finished", "description": "Ended"},
        "tournament": {"name": "LaLiga", "uniqueTournament": {"id": 8}},
        "homeTeam": {"id": 100, "name": "Local FC"},
        "awayTeam": {"id": 200, "name": "Visitante CF"},
        "homeScore": {"current": 1}, "awayScore": {"current": 0},
    }


@pytest.fixture
def base():
    with Almacen(":memory:") as almacen:
        yield almacen


@pytest.fixture
def ligas(monkeypatch):
    """Una sola liga, para que las pruebas no dependan del catálogo entero."""
    import cancha.historia as modulo

    monkeypatch.setattr(modulo, "ligas_de", lambda *a, **k: {8: "LaLiga"})


@pytest.fixture(autouse=True)
def sin_informes(monkeypatch):
    """Guardar un partido con su detalle ya está probado en el barrido.

    Aquí lo que se prueba es el **recorrido** —dónde corta, cuándo para, qué se
    salta—, así que se sustituye la parte que habla con la fuente por una que
    apunta la cabecera y ya. Si no, cada prueba tendría que fingir media API.
    """
    import cancha.historia as modulo

    def guardar(cliente, almacen, evento, progreso, forzar=False, secciones=None):
        if almacen.dado_por_hecho(evento.id):
            progreso.ya_estaban += 1
            return False
        almacen.guardar_evento(evento)
        # Marcarlo como hecho es lo que hace que la segunda vuelta lo salte, que
        # es justo lo que se quiere probar.
        almacen.marcar_sin_estadisticas(evento.id)
        progreso.partidos_guardados += 1
        return True

    monkeypatch.setattr(modulo, "guardar_partido", guardar)


# --------------------------------------------------------------- las temporadas

def test_solo_entran_las_temporadas_de_la_ventana():
    """Traerse 2005 cuando pides tres años es gastar peticiones para nada."""
    cliente = ClienteFalso()
    dentro = temporadas_de(cliente, 8, anos=3)
    assert [t["year"] for t in dentro] == ["25/26", "24/25"]


def test_una_temporada_sin_año_legible_entra_por_si_acaso():
    """Más vale mirar una de más —sus partidos se descartan por fecha— que
    dejarse media temporada fuera por no saber leer su nombre."""
    cliente = ClienteFalso(temporadas=[{"id": 1, "year": "Apertura"}])
    assert len(temporadas_de(cliente, 8, anos=3)) == 1


# ---------------------------------------------------------------------- el plan

def test_el_plan_dice_lo_que_va_a_costar_sin_pedir_los_partidos(base, ligas):
    """Descubrir a mitad que son veinte mil peticiones es descubrirlo tarde."""
    cliente = ClienteFalso()
    datos = plan(cliente, base, ["laliga"], anos=3,
                 secciones=["statistics", "lineups"])

    assert datos["temporadas"] == 2
    assert datos["peticiones_estimadas"] > 0
    assert "estimación" in datos["aviso"]
    # Solo la lista de temporadas: ni un partido pedido.
    assert [p[0] for p in cliente.pedidos] == ["seasons"]


def test_el_plan_cuenta_las_secciones_elegidas(base, ligas):
    """Cada sección es una petición más por partido: es lo que multiplica."""
    cliente = ClienteFalso()
    pocas = plan(cliente, base, ["laliga"], anos=3, secciones=["statistics"])
    muchas = plan(ClienteFalso(), base, ["laliga"], anos=3,
                  secciones=["statistics", "lineups", "shotmap", "incidents"])
    assert muchas["peticiones_estimadas"] > pocas["peticiones_estimadas"]


# -------------------------------------------------------------------- traerlos

def test_se_para_en_cuanto_un_partido_se_pasa_del_corte(base, ligas):
    """Vienen del más nuevo al más viejo: pasado el corte, lo que queda también."""
    cliente = ClienteFalso(paginas={
        (100, 0): [_evento(1, 10), _evento(2, 20), _evento(3, 5000)],
    }, temporadas=[{"id": 100, "year": "25/26"}])
    salida = traer(cliente, base, ["laliga"], anos=3, secciones=["statistics"])

    assert salida["partidos_vistos"] == 2, "el tercero es de hace catorce años"
    # Y no pide la página siguiente de esa temporada.
    assert ("eventos", 8, 100, 1) not in cliente.pedidos


def test_el_tope_de_peticiones_corta_y_lo_dice(base, ligas):
    """Tres años de cinco ligas son horas: hay que poder dejarlo a ratos."""
    cliente = ClienteFalso(paginas={
        (100, p): [_evento(100 * p + n, 10) for n in range(30)] for p in range(5)
    }, temporadas=[{"id": 100, "year": "25/26"}])
    salida = traer(cliente, base, ["laliga"], anos=3, secciones=["statistics"],
                   maximo=3)

    assert salida["completo"] is False
    assert cliente.stats.requests <= 6, "para poco después del tope, no al final"


def test_lo_que_ya_esta_guardado_no_se_vuelve_a_pedir(base, ligas):
    """Es lo que hace que esto se pueda repetir sin volver a pagarlo entero."""
    paginas = {(100, 0): [_evento(1, 10), _evento(2, 12)]}
    temporadas = [{"id": 100, "year": "25/26"}]

    primera = traer(ClienteFalso(paginas=paginas, temporadas=temporadas), base,
                    ["laliga"], anos=3, secciones=["statistics"])
    assert primera["partidos_vistos"] == 2

    segunda = traer(ClienteFalso(paginas=paginas, temporadas=temporadas), base,
                    ["laliga"], anos=3, secciones=["statistics"])
    assert segunda["ya_estaban"] == 2, "la segunda vez no cuesta nada"
    assert segunda["guardados"] == 0


def test_una_liga_que_falla_no_para_las_demas(base, monkeypatch):
    """Un id malo en el catálogo no puede tumbar una tanda de cuatro horas."""
    import cancha.historia as modulo
    from cancha.errors import SofascoreError

    monkeypatch.setattr(modulo, "ligas_de",
                        lambda *a, **k: {8: "LaLiga", 9: "La Rota"})

    class Roto(ClienteFalso):
        def seasons(self, liga_id):
            if liga_id == 9:
                raise SofascoreError("esa competición no existe")
            return super().seasons(liga_id)

    salida = traer(Roto(paginas={}), base, None, anos=3, secciones=["statistics"])
    assert salida["ligas"] == 2
    assert salida["fallos"] == 1
    assert any("La Rota" in d for d in salida["detalle"])


def test_se_puede_parar_desde_fuera(base, ligas):
    """Para el botón de la interfaz: pararlo tiene que ser inmediato."""
    cliente = ClienteFalso(paginas={
        (100, 0): [_evento(n, 10) for n in range(30)],
    }, temporadas=[{"id": 100, "year": "25/26"}])
    salida = traer(cliente, base, ["laliga"], anos=3, secciones=["statistics"],
                   puede_seguir=lambda: False)
    assert salida["partidos_vistos"] == 0
    assert salida["completo"] is False
