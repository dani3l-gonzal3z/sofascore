"""El briefing: el documento de la mañana."""

from __future__ import annotations

import json

import pytest
from conftest import EVENT_ID

from cancha.almacen import Almacen
from cancha.briefing import a_markdown, briefing, cargar, guardados, guardar
from cancha.match import build_report


@pytest.fixture
def almacen():
    with Almacen(":memory:") as base:
        yield base


def test_el_briefing_recorre_la_agenda_del_dia(almacen, cliente):
    datos = briefing(almacen, cliente, fecha="2024-10-26", grupos=["grandes"])
    assert datos["fecha"] == "2024-10-26"
    assert datos["total"] == 1
    partido = datos["partidos"][0]["partido"]
    assert partido["local"] == "Real Madrid" and partido["hora_utc"] == "20:00"
    assert "duelos" in datos["partidos"][0] and "evolucion" in datos["partidos"][0]


def test_sin_memoria_cada_partido_dice_que_barras(almacen, cliente):
    datos = briefing(almacen, cliente, fecha="2024-10-26", grupos=["grandes"])
    equipos = datos["partidos"][0]["equipos"]
    assert not equipos["local"]["disponible"] and "barrido" in equipos["local"]["nota"]
    texto = a_markdown(datos)
    assert "# Briefing del 2024-10-26" in texto
    assert "Real Madrid - Barcelona" in texto
    assert "barrido" in texto


def test_con_memoria_el_briefing_lleva_estilo_mercado_y_arbitro(almacen, cliente):
    almacen.guardar_informe(build_report(cliente, EVENT_ID, sections=["all"]))
    datos = briefing(almacen, cliente, fecha="2024-10-26", grupos=["grandes"])
    partido = datos["partidos"][0]
    assert partido["equipos"]["local"]["disponible"]
    assert partido["mercado"]["disponible"]
    assert partido["arbitro"]["disponible"]
    texto = a_markdown(datos)
    assert "**Mercado:**" in texto and "**Árbitro:** César Soto Grado" in texto
    assert "**Real Madrid**" in texto


def test_un_dia_sin_partidos_lo_dice(almacen, cliente):
    datos = briefing(almacen, cliente, fecha="2024-10-26", grupos=["americas"])
    assert datos["total"] == 0
    assert "No hay partidos" in a_markdown(datos)


def test_se_guarda_uno_por_dia_y_se_vuelve_a_leer(almacen, cliente, tmp_path):
    datos = briefing(almacen, cliente, fecha="2024-10-26", grupos=["grandes"])
    rutas = guardar(datos, tmp_path)
    assert rutas["markdown"].name == "2024-10-26.md" and rutas["json"].exists()
    assert guardados(tmp_path) == ["2024-10-26"]
    assert cargar("2024-10-26", tmp_path)["total"] == 1
    assert cargar("1999-01-01", tmp_path) is None
    assert guardados(tmp_path / "no-existe") == []


def test_los_duelos_del_briefing_solo_traen_lo_relevante(tmp_path):
    """Con la liga inventada de los sistemas: El Nueve contra Muro CD."""
    from test_sistemas import _poblar

    from cancha.cache import MemoryCache
    from cancha.client import SofascoreClient
    from cancha.config import Settings
    from cancha.transport import FakeTransport

    hoy = {"id": 900, "startTimestamp": 1780000000 + 40 * 86400,
           "tournament": {"name": "LaLiga", "uniqueTournament": {"id": 8}},
           "homeTeam": {"id": 100, "name": "Nuestro CF"},
           "awayTeam": {"id": 301, "name": "Muro CD"},
           "status": {"type": "notstarted"}}
    cliente = SofascoreClient(
        Settings(rate_limit=0, retries=0, cache_ttl=0, fallback_base_urls=()),
        transport=FakeTransport({
            "/unique-tournament/8/seasons": {"seasons": [{"id": 61643}]},
            "/unique-tournament/8/season/61643/events/next/0": {"events": [hoy]},
        }),
        cache=MemoryCache(), sleep=lambda _s: None)
    from cancha.models import Event

    fecha = Event.from_api(hoy).date
    with Almacen(":memory:") as base:
        _poblar(base)
        datos = briefing(base, cliente, fecha=fecha, grupos=["laliga"], jugadores=2)
    duelos = datos["partidos"][0]["duelos"]
    assert duelos, "El Nueve desaparece contra el bloque bajo: tenía que salir"
    assert all(d["veredicto"] in ("señal", "indicio") for d in duelos)
    assert duelos[0]["jugador"] == "El Nueve" and duelos[0]["rival"] == "Muro CD"
    assert "**Jugador contra sistema**" in a_markdown(datos)


def test_la_consola_escribe_el_briefing(inyectar_cliente, cliente, tmp_path, capsys):
    from cancha import cli

    inyectar_cliente(cliente)
    assert cli.main(["briefing", "--date", "2024-10-26", "--grupos", "grandes",
                     "--db", str(tmp_path / "b.db"), "--carpeta", str(tmp_path / "br"),
                     "--quiet"]) == 0
    salida = capsys.readouterr().out
    assert "Escrito en" in salida
    assert (tmp_path / "br" / "2024-10-26.md").exists()

    assert cli.main(["briefing", "--date", "2024-10-26", "--grupos", "grandes",
                     "--db", str(tmp_path / "b.db"), "--no-guardar", "--stdout-json"]) == 0
    assert json.loads(capsys.readouterr().out)["total"] == 1


def test_la_consola_puede_barrer_antes(inyectar_cliente, cliente, tmp_path, capsys):
    from cancha import cli

    inyectar_cliente(cliente)
    assert cli.main(["briefing", "--date", "2024-10-26", "--grupos", "grandes", "--barrer",
                     "--db", str(tmp_path / "b.db"), "--carpeta", str(tmp_path / "br"),
                     "--quiet"]) == 0
    assert "Barriendo" in capsys.readouterr().out
    with Almacen(tmp_path / "b.db") as base:
        assert base.resumen()["partidos"] >= 1


def test_la_herramienta_devuelve_el_guardado_si_existe(tmp_path, monkeypatch, cliente):
    from cancha import briefing as modulo
    from cancha.herramientas import ejecutar
    from cancha.sesion import Sesion

    monkeypatch.setattr(modulo, "CARPETA_POR_DEFECTO", str(tmp_path))
    # La herramienta usa los valores por defecto de cargar/guardar, que se
    # evalúan al definir la función: se parchea la carpeta en esos defaults.
    monkeypatch.setattr(modulo.cargar, "__defaults__", (str(tmp_path),))
    monkeypatch.setattr(modulo.guardar, "__defaults__", (str(tmp_path),))
    sesion = Sesion(cliente=cliente, ruta_almacen=str(tmp_path / "h.db"))
    try:
        primero = ejecutar("briefing_del_dia", {"fecha": "2024-10-26"}, sesion=sesion)
        assert primero["total"] >= 0 and (tmp_path / "2024-10-26.json").exists()
        peticiones = cliente.stats.requests
        segundo = ejecutar("briefing_del_dia", {"fecha": "2024-10-26"}, sesion=sesion)
        assert segundo["generado"] == primero["generado"]
        assert cliente.stats.requests == peticiones
    finally:
        sesion.close()
