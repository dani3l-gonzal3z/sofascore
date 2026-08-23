"""Línea de comandos (con el cliente de mentira inyectado)."""

import json

import pytest

from sofascore import cli

from conftest import EVENT_ID


@pytest.fixture
def cli_con_cliente(monkeypatch, cliente):
    monkeypatch.setattr(cli, "_construir_cliente", lambda args: cliente)
    return cliente


def test_sections_lista_el_catalogo(capsys):
    assert cli.main(["sections"]) == 0
    salida = capsys.readouterr().out
    assert "statistics" in salida and "shotmap" in salida
    assert "plus" in salida


def test_match_imprime_el_resumen(cli_con_cliente, capsys):
    assert cli.main(["match", str(EVENT_ID)]) == 0
    salida = capsys.readouterr().out
    assert "Real Madrid 0 - 4 Barcelona" in salida
    assert "statistics" in salida


def test_match_por_nombres(cli_con_cliente, capsys):
    assert cli.main(["match", "Real Madrid vs Barcelona", "--date", "2024-10-26"]) == 0
    assert f"id={EVENT_ID}" in capsys.readouterr().out


def test_match_escribe_los_ficheros(cli_con_cliente, tmp_path, capsys):
    destino_json = tmp_path / "p.json"
    destino_md = tmp_path / "p.md"
    codigo = cli.main([
        "match", str(EVENT_ID),
        "--json", str(destino_json),
        "--markdown", str(destino_md),
        "--csv", str(tmp_path / "csv"),
    ])
    assert codigo == 0
    assert json.loads(destino_json.read_text(encoding="utf-8"))["partido"]["id"] == EVENT_ID
    assert destino_md.read_text(encoding="utf-8").startswith("# Real Madrid")
    assert (tmp_path / "csv" / "estadisticas.csv").is_file()
    assert "CSV escritos" in capsys.readouterr().out


def test_match_print_de_una_seccion(cli_con_cliente, capsys):
    assert cli.main(["match", str(EVENT_ID), "--print", "statistics", "--quiet"]) == 0
    datos = json.loads(capsys.readouterr().out)
    assert datos[0]["period"] == "ALL"


def test_match_stdout_json(cli_con_cliente, capsys):
    assert cli.main(["match", str(EVENT_ID), "--stdout-json", "--quiet"]) == 0
    datos = json.loads(capsys.readouterr().out)
    assert datos["partido"]["id"] == EVENT_ID


def test_match_avisa_de_las_secciones_de_pago(monkeypatch, ajustes, capsys):
    from sofascore.cache import MemoryCache
    from sofascore.client import SofascoreClient
    from sofascore.transport import FakeTransport
    from conftest import rutas_por_defecto

    rutas = rutas_por_defecto()
    rutas[f"/event/{EVENT_ID}/shotmap"] = 403
    cliente = SofascoreClient(ajustes, transport=FakeTransport(rutas),
                              cache=MemoryCache(), sleep=lambda _s: None)
    monkeypatch.setattr(cli, "_construir_cliente", lambda args: cliente)
    assert cli.main(["match", str(EVENT_ID)]) == 0
    salida = capsys.readouterr().out
    assert "Requieren Sofascore Plus" in salida
    assert "SOFA_PLUS_COOKIE" in salida


def test_search_lista_candidatos(cli_con_cliente, capsys):
    assert cli.main(["search", "Real Madrid vs Barcelona"]) == 0
    salida = capsys.readouterr().out
    assert "candidato" in salida
    assert f"id={EVENT_ID}" in salida


def test_raw_vuelca_el_json(cli_con_cliente, capsys):
    assert cli.main(["raw", f"/event/{EVENT_ID}/statistics"]) == 0
    datos = json.loads(capsys.readouterr().out)
    assert datos["statistics"][0]["period"] == "ALL"


def test_login_sin_credenciales(cli_con_cliente, capsys):
    assert cli.main(["login"]) == 0
    assert "sin credenciales" in capsys.readouterr().out


def test_login_comprueba_contra_un_partido(cli_con_cliente, capsys):
    cli_con_cliente.credentials.cookie = "sesion=mia"
    assert cli.main(["login", str(EVENT_ID)]) == 0
    assert "funcionan" in capsys.readouterr().out


def test_login_detecta_credenciales_rechazadas(monkeypatch, ajustes, capsys):
    from sofascore.cache import MemoryCache
    from sofascore.client import SofascoreClient
    from sofascore.transport import FakeTransport
    from conftest import rutas_por_defecto

    rutas = rutas_por_defecto()
    rutas[f"/event/{EVENT_ID}/shotmap"] = 401
    ajustes.plus_cookie = "sesion=caducada"
    cliente = SofascoreClient(ajustes, transport=FakeTransport(rutas),
                              cache=MemoryCache(), sleep=lambda _s: None)
    monkeypatch.setattr(cli, "_construir_cliente", lambda args: cliente)
    assert cli.main(["login", str(EVENT_ID)]) == 1
    assert "no ha aceptado" in capsys.readouterr().out


def test_errores_salen_por_stderr(cli_con_cliente, capsys):
    assert cli.main(["match", "Equipo Que No Existe vs Otro Tampoco"]) == 2
    assert "error:" in capsys.readouterr().err


def test_cache_informa_del_estado(tmp_path, capsys):
    from sofascore.cache import DiskCache

    DiskCache(tmp_path).set("clave", {"a": 1})
    assert cli.main(["cache", "--cache-dir", str(tmp_path)]) == 0
    assert "1 respuestas en caché" in capsys.readouterr().out
    assert cli.main(["cache", "--clear", "--cache-dir", str(tmp_path)]) == 0
    assert "Borrados 1" in capsys.readouterr().out


# --------------------------------------------- comandos de equipo, jugador y liga

def test_team_imprime_el_informe(cli_con_cliente, capsys):
    assert cli.main(["team", "Real Madrid"]) == 0
    salida = capsys.readouterr().out
    assert "equipo: Real Madrid" in salida
    assert "players" in salida


def test_player_imprime_el_informe(cli_con_cliente, capsys):
    assert cli.main(["player", "Vinicius"]) == 0
    assert "attributes" in capsys.readouterr().out


def test_league_usa_la_temporada_en_curso(cli_con_cliente, capsys):
    assert cli.main(["league", "laliga"]) == 0
    assert "standings" in capsys.readouterr().out


def test_league_imprime_una_seccion_suelta(cli_con_cliente, capsys):
    assert cli.main(["league", "laliga", "--print", "standings"]) == 0
    assert "Barcelona" in capsys.readouterr().out


def test_team_escribe_json(cli_con_cliente, tmp_path, capsys):
    destino = tmp_path / "equipo.json"
    assert cli.main(["team", "2829", "--json", str(destino)]) == 0
    datos = json.loads(destino.read_text(encoding="utf-8"))
    assert datos["tipo"] == "team"
    assert datos["id"] == 2829


def test_live_lista_los_partidos_en_juego(cli_con_cliente, capsys):
    assert cli.main(["live"]) == 0
    assert "partido(s)" in capsys.readouterr().out


def test_today_admite_fecha(cli_con_cliente, capsys):
    assert cli.main(["today", "--date", "2024-10-26"]) == 0
    assert "Partidos del 2024-10-26" in capsys.readouterr().out


def test_leagues_lista_el_catalogo(capsys):
    assert cli.main(["leagues"]) == 0
    salida = capsys.readouterr().out
    assert "Spain La Liga" in salida and "UEFA Champions League" in salida


def test_leagues_filtra(capsys):
    assert cli.main(["leagues", "england"]) == 0
    salida = capsys.readouterr().out
    assert "England Premier League" in salida
    assert "Spain La Liga" not in salida


def test_sections_por_catalogo(capsys):
    assert cli.main(["sections", "--kind", "tournament"]) == 0
    salida = capsys.readouterr().out
    assert "standings" in salida and "top_players" in salida
    assert "shotmap" not in salida


def test_match_acepta_parallel(cli_con_cliente, capsys):
    assert cli.main(["match", str(EVENT_ID), "--parallel", "1"]) == 0
    assert "Real Madrid" in capsys.readouterr().out


def test_se_puede_ejecutar_como_modulo():
    """`python -m sofascore` tiene que funcionar aunque el PATH no colabore."""
    import subprocess
    import sys
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[1]
    proceso = subprocess.run(
        [sys.executable, "-m", "sofascore", "--version"],
        capture_output=True, text=True, cwd=raiz, timeout=60,
    )
    assert proceso.returncode == 0, proceso.stderr
    assert "sofascore-framework" in proceso.stdout


def test_doctor_dice_con_que_esta_pidiendo(cli_con_cliente, capsys):
    assert cli.main(["doctor"]) == 0
    salida = capsys.readouterr().out
    assert "Transportes disponibles" in salida
    assert "curl_cffi" in salida
    assert "En uso:" in salida
