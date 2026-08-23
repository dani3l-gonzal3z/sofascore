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
