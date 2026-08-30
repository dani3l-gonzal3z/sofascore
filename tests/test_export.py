"""Exportación a JSON, Markdown y CSV."""

import csv
import json

from conftest import EVENT_ID

from cancha.export import to_csv_dir, to_json, to_markdown
from cancha.match import build_report


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
    from conftest import rutas_por_defecto

    from cancha.cache import MemoryCache
    from cancha.client import SofascoreClient
    from cancha.config import Settings
    from cancha.transport import FakeTransport

    rutas = rutas_por_defecto()
    rutas[f"/event/{EVENT_ID}/graph/win-probability"] = 403
    cli = SofascoreClient(
        Settings(rate_limit=0, cache_ttl=0), transport=FakeTransport(rutas),
        cache=MemoryCache(), sleep=lambda _s: None,
    )
    texto = to_markdown(build_report(cli, EVENT_ID, sections=["win_probability"]))
    assert "🔒 `win_probability`" in texto
    assert "Sofascore Plus" in texto


def test_la_cronologia_del_csv_va_hacia_delante(cliente):
    """La API las devuelve del final al principio; el CSV no puede salir así."""
    from cancha.export import _filas_incidencias

    minutos = [f["minuto"] for f in _filas_incidencias(_informe(cliente))]
    assert minutos == sorted(minutos)
    assert len(minutos) > 1


def test_un_cambio_no_pierde_a_los_jugadores(cliente):
    """En un cambio la API no usa 'player': el CSV salía sin nadie."""
    from cancha.export import _filas_incidencias

    cambios = [f for f in _filas_incidencias(_informe(cliente))
               if f["tipo"] == "substitution"]
    assert cambios
    assert cambios[0]["jugador"] == "Frenkie de Jong"
    assert cambios[0]["jugador_sale"] == "Marc Casadó"


def test_el_gol_guarda_quien_asistio(cliente):
    from cancha.export import _filas_incidencias

    goles = [f for f in _filas_incidencias(_informe(cliente)) if f["tipo"] == "goal"]
    assert any(f["asistencia"] for f in goles)


def test_el_markdown_ensena_el_cambio_entero(cliente):
    texto = to_markdown(_informe(cliente))
    assert "Frenkie de Jong ← Marc Casadó" in texto
    assert "asist. Raphinha" in texto
