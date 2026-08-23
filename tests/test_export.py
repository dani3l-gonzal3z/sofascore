"""Exportación a JSON, Markdown y CSV."""

import csv
import json

from sofascore.export import to_csv_dir, to_json, to_markdown
from sofascore.match import build_report

from conftest import EVENT_ID


def _informe(cliente):
    return build_report(cliente, EVENT_ID)


def test_json_completo(cliente, tmp_path):
    destino = tmp_path / "salida" / "partido.json"
    texto = to_json(_informe(cliente), destino)
    datos = json.loads(texto)
    assert datos["partido"]["home"]["name"] == "Real Madrid"
    assert "statistics" in datos["secciones"]
    assert destino.is_file()
    assert json.loads(destino.read_text(encoding="utf-8"))["meta"]


def test_markdown_legible(cliente, tmp_path):
    destino = tmp_path / "partido.md"
    texto = to_markdown(_informe(cliente), destino)
    assert texto.startswith("# Real Madrid 0 - 4 Barcelona")
    assert "Posesión" in texto
    assert "Cronología" in texto
    assert "Alineaciones" in texto
    assert "4-3-3" in texto
    assert "Estadio Santiago Bernabéu" in texto
    assert destino.read_text(encoding="utf-8") == texto


def test_csv_por_tabla(cliente, tmp_path):
    creados = to_csv_dir(_informe(cliente), tmp_path)
    nombres = {ruta.name for ruta in creados}
    assert {"estadisticas.csv", "incidencias.csv", "alineaciones.csv"} <= nombres

    with (tmp_path / "estadisticas.csv").open(encoding="utf-8") as fichero:
        filas = list(csv.DictReader(fichero))
    assert any(f["clave"] == "expectedGoals" and f["visitante"] == "2.87" for f in filas)

    with (tmp_path / "alineaciones.csv").open(encoding="utf-8") as fichero:
        jugadores = list(csv.DictReader(fichero))
    assert any(j["jugador"] == "Robert Lewandowski" and j["valoracion"] == "8.8" for j in jugadores)


def test_csv_incluye_tiros_si_hay_plus(cliente, tmp_path):
    cliente.credentials.cookie = "sesion=mia"
    informe = build_report(cliente, EVENT_ID, sections=["shotmap"])
    creados = to_csv_dir(informe, tmp_path)
    assert (tmp_path / "tiros.csv") in creados
    with (tmp_path / "tiros.csv").open(encoding="utf-8") as fichero:
        tiros = list(csv.DictReader(fichero))
    assert tiros[0]["jugador"] == "Robert Lewandowski"
    assert tiros[0]["equipo"] == "visitante"


def test_las_secciones_bloqueadas_se_ven_en_el_markdown(cliente, tmp_path):
    from sofascore.cache import MemoryCache
    from sofascore.client import SofascoreClient
    from sofascore.config import Settings
    from sofascore.transport import FakeTransport
    from conftest import rutas_por_defecto

    rutas = rutas_por_defecto()
    rutas[f"/event/{EVENT_ID}/graph/win-probability"] = 403
    cli = SofascoreClient(
        Settings(rate_limit=0, cache_ttl=0), transport=FakeTransport(rutas),
        cache=MemoryCache(), sleep=lambda _s: None,
    )
    texto = to_markdown(build_report(cli, EVENT_ID, sections=["win_probability"]))
    assert "🔒 `win_probability`" in texto
    assert "Sofascore Plus" in texto
