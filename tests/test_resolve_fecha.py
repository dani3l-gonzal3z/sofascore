"""La fecha es una condición, no una sugerencia.

Reproduce el caso real que apareció al ejecutarlo por primera vez contra la
API: se pidió "Real Madrid vs Barcelona" con `--date 2024-10-26` y devolvió un
Barcelona-Real Madrid de la Liga F de **2026**. El nombre encajaba perfecto
(1.0), la penalización por fecha errónea (-0.35) lo dejaba en 0.65 —por encima
del umbral— y eso hacía que ni se llegara a consultar la lista de partidos del
día pedido, que era donde estaba el bueno.
"""

from __future__ import annotations

import pytest

from sofascore.cache import MemoryCache
from sofascore.client import SofascoreClient
from sofascore.config import Settings
from sofascore.errors import MatchNotFound
from sofascore.resolve import resolve_event
from sofascore.transport import FakeTransport

FECHA = "2024-10-26"
#: 26/10/2024 12:00 UTC y 04/10/2026 12:00 UTC.
CUANDO_BUENO = 1729944000
CUANDO_MALO = 1791460800


def _evento(id_, local, visitante, torneo, cuando, marcador=(0, 4)):
    return {
        "id": id_,
        "slug": f"{local.lower().replace(' ', '-')}-{visitante.lower().replace(' ', '-')}",
        "startTimestamp": cuando,
        "tournament": {"name": torneo, "uniqueTournament": {"id": 8},
                       "category": {"sport": {"slug": "football"}}},
        "season": {"id": 52376},
        "status": {"code": 100, "type": "finished", "description": "Finalizado"},
        "homeTeam": {"id": 1, "name": local},
        "awayTeam": {"id": 2, "name": visitante},
        "homeScore": {"current": marcador[0]},
        "awayScore": {"current": marcador[1]},
    }


#: El clásico de verdad, el que se pidió.
BUENO = _evento(11352550, "Real Madrid", "Barcelona", "LaLiga", CUANDO_BUENO)
#: El que devolvía el buscador: mismos nombres, otra competición, otro año.
MALO = _evento(16425733, "Fútbol Club Barcelona", "Real Madrid",
               "Liga F Moeve", CUANDO_MALO, marcador=(None, None))


def _cliente(rutas):
    return SofascoreClient(
        Settings(rate_limit=0, retries=0, fallback_base_urls=()),
        transport=FakeTransport(rutas),
        cache=MemoryCache(),
        sleep=lambda _s: None,
    )


def _rutas(busqueda, del_dia):
    return {
        "/search/all": {"results": [{"type": "event", "entity": e} for e in busqueda]},
        f"/sport/football/scheduled-events/{FECHA}": {"events": del_dia},
        "/team/1/events/last/0": {"events": []},
        "/team/1/events/next/0": {"events": []},
    }


def test_no_elige_otra_fecha_teniendo_una_de_la_pedida():
    """El caso exacto que falló: el buscador solo trae el malo."""
    cliente = _cliente(_rutas(busqueda=[MALO], del_dia=[BUENO]))
    resolucion = resolve_event(cliente, "Real Madrid vs Barcelona", date=FECHA)
    assert resolucion.event.id == 11352550
    assert resolucion.event.date == FECHA
    assert not resolucion.warning


def test_los_partidos_del_dia_se_consultan_siempre():
    """Antes solo se miraban si nada llegaba al umbral. Por eso falló."""
    cliente = _cliente(_rutas(busqueda=[MALO], del_dia=[BUENO]))
    resolve_event(cliente, "Real Madrid vs Barcelona", date=FECHA)
    assert any(f"scheduled-events/{FECHA}" in url for url in cliente.transport.calls)


def test_los_candidatos_de_otra_fecha_ni_aparecen():
    cliente = _cliente(_rutas(busqueda=[MALO], del_dia=[BUENO]))
    resolucion = resolve_event(cliente, "Real Madrid vs Barcelona", date=FECHA)
    assert all(c.event.date == FECHA for c in resolucion.candidates)


def test_si_no_hay_nada_ese_dia_lo_dice_en_vez_de_callarse():
    cliente = _cliente(_rutas(busqueda=[MALO], del_dia=[]))
    resolucion = resolve_event(cliente, "Real Madrid vs Barcelona", date=FECHA)
    assert resolucion.event.id == 16425733
    assert FECHA in resolucion.warning
    assert "otra fecha" in resolucion.warning


def test_sin_fecha_no_se_filtra_nada():
    cliente = _cliente(_rutas(busqueda=[MALO, BUENO], del_dia=[]))
    resolucion = resolve_event(cliente, "Real Madrid vs Barcelona")
    assert len(resolucion.candidates) == 2
    assert not resolucion.warning


def test_dos_partidos_el_mismo_dia_se_ofrecen_los_dos():
    """Liga F y LaLiga el mismo día: se elige uno, pero se enseña el otro."""
    femenino = _evento(999, "Barcelona", "Real Madrid", "Liga F Moeve", CUANDO_BUENO)
    cliente = _cliente(_rutas(busqueda=[], del_dia=[BUENO, femenino]))
    resolucion = resolve_event(cliente, "Real Madrid vs Barcelona", date=FECHA)
    assert len(resolucion.candidates) == 2
    assert {c.event.id for c in resolucion.candidates} == {11352550, 999}


def test_ningun_partido_ese_dia_ni_parecido():
    cliente = _cliente(_rutas(busqueda=[], del_dia=[]))
    with pytest.raises(MatchNotFound):
        resolve_event(cliente, "Equipo Inventado vs Otro", date=FECHA)


def test_un_partido_sin_jugar_no_marca_guiones():
    from sofascore.models import Event

    assert Event.from_api(MALO).scoreline == "vs"
    assert Event.from_api(BUENO).scoreline == "0 - 4"
    assert "vs" in Event.from_api(MALO).label
