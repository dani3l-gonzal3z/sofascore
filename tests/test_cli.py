"""Línea de comandos (con el cliente de mentira inyectado)."""

import json

import pytest
from conftest import EVENT_ID

from cancha import cli


@pytest.fixture
def cli_con_cliente(inyectar_cliente, cliente):
    inyectar_cliente(cliente)
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


def test_match_avisa_de_las_secciones_de_pago(inyectar_cliente, ajustes, capsys):
    from conftest import rutas_por_defecto

    from cancha.cache import MemoryCache
    from cancha.client import SofascoreClient
    from cancha.transport import FakeTransport

    rutas = rutas_por_defecto()
    rutas[f"/event/{EVENT_ID}/graph/win-probability"] = 403
    cliente = SofascoreClient(ajustes, transport=FakeTransport(rutas),
                              cache=MemoryCache(), sleep=lambda _s: None)
    inyectar_cliente(cliente)
    assert cli.main(["match", str(EVENT_ID), "--sections", "win_probability"]) == 0
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


def test_login_detecta_credenciales_rechazadas(inyectar_cliente, ajustes, capsys):
    from conftest import rutas_por_defecto

    from cancha.cache import MemoryCache
    from cancha.client import SofascoreClient
    from cancha.transport import FakeTransport

    rutas = rutas_por_defecto()
    rutas[f"/event/{EVENT_ID}/graph/win-probability"] = 401
    ajustes.plus_cookie = "sesion=caducada"
    cliente = SofascoreClient(ajustes, transport=FakeTransport(rutas),
                              cache=MemoryCache(), sleep=lambda _s: None)
    inyectar_cliente(cliente)
    assert cli.main(["login", str(EVENT_ID)]) == 1
    assert "ha rechazado" in capsys.readouterr().out


def test_login_sigue_probando_si_una_sonda_no_existe(inyectar_cliente, ajustes, capsys):
    """win_probability da 404 en muchos partidos: eso no dice nada de tu cuenta."""
    from conftest import rutas_por_defecto

    from cancha.cache import MemoryCache
    from cancha.client import SofascoreClient
    from cancha.transport import FakeTransport

    rutas = rutas_por_defecto()
    rutas[f"/event/{EVENT_ID}/graph/win-probability"] = 404      # no existe aquí
    rutas[f"/event/{EVENT_ID}/ai-insights/es"] = {"insights": ["algo"]}
    ajustes.plus_cookie = "sesion=mia"
    cliente = SofascoreClient(ajustes, transport=FakeTransport(rutas),
                              cache=MemoryCache(), sleep=lambda _s: None)
    inyectar_cliente(cliente)
    assert cli.main(["login", str(EVENT_ID)]) == 0
    salida = capsys.readouterr().out
    assert "funcionan" in salida
    assert "ai_insights" in salida


def test_login_lo_dice_cuando_ninguna_sonda_existe(inyectar_cliente, ajustes, capsys):
    from conftest import rutas_por_defecto

    from cancha.cache import MemoryCache
    from cancha.client import SofascoreClient
    from cancha.transport import FakeTransport

    rutas = rutas_por_defecto()
    rutas[f"/event/{EVENT_ID}/graph/win-probability"] = 404
    rutas[f"/event/{EVENT_ID}/ai-insights/es"] = 404
    ajustes.plus_cookie = "sesion=mia"
    cliente = SofascoreClient(ajustes, transport=FakeTransport(rutas),
                              cache=MemoryCache(), sleep=lambda _s: None)
    inyectar_cliente(cliente)
    assert cli.main(["login", str(EVENT_ID)]) == 0
    salida = capsys.readouterr().out
    assert "Sin conclusión" in salida
    assert "cancha live" in salida


def test_errores_salen_por_stderr(cli_con_cliente, capsys):
    assert cli.main(["match", "Equipo Que No Existe vs Otro Tampoco"]) == 2
    assert "error:" in capsys.readouterr().err


def test_cache_informa_del_estado(tmp_path, capsys):
    from cancha.cache import DiskCache

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
    """`python -m cancha` tiene que funcionar aunque el PATH no colabore."""
    import subprocess
    import sys
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[1]
    proceso = subprocess.run(
        [sys.executable, "-m", "cancha", "--version"],
        capture_output=True, text=True, cwd=raiz, timeout=60,
    )
    assert proceso.returncode == 0, proceso.stderr
    assert "cancha" in proceso.stdout


def test_doctor_dice_con_que_esta_pidiendo(cli_con_cliente, capsys):
    assert cli.main(["doctor"]) == 0
    salida = capsys.readouterr().out
    assert "Transportes disponibles" in salida
    assert "curl_cffi" in salida
    assert "En uso:" in salida


# ------------------------------------------------ listados: filtrar y agrupar

def _cliente_con_directos(eventos):
    from cancha.cache import MemoryCache
    from cancha.client import SofascoreClient
    from cancha.config import Settings
    from cancha.transport import FakeTransport

    return SofascoreClient(
        Settings(rate_limit=0),
        transport=FakeTransport({"/sport/football/events/live": {"events": eventos}}),
        cache=MemoryCache(), sleep=lambda _s: None,
    )


def _ev(id_, local, visitante, torneo, torneo_id=None):
    return {
        "id": id_, "startTimestamp": 1787000000,
        "tournament": {"name": torneo,
                       "uniqueTournament": {"id": torneo_id} if torneo_id else {},
                       "category": {"sport": {"slug": "football"}}},
        "status": {"code": 6, "type": "inprogress", "description": "1st half"},
        "homeTeam": {"id": 1, "name": local}, "awayTeam": {"id": 2, "name": visitante},
        "homeScore": {"current": 1}, "awayScore": {"current": 0},
    }


DIRECTOS = [
    _ev(1, "SSD Rovato", "AC Sant'Angelo", "Club Friendly Games"),
    _ev(3, "Real Madrid", "Getafe", "LaLiga", 8),
    _ev(4, "Girona", "Osasuna", "LaLiga", 8),
    _ev(6, "Arsenal", "Chelsea", "Premier League", 17),
]


def test_live_agrupa_por_competicion(inyectar_cliente, capsys):
    inyectar_cliente(_cliente_con_directos(DIRECTOS))
    assert cli.main(["live"]) == 0
    salida = capsys.readouterr().out
    assert "LaLiga" in salida and "Premier League" in salida
    # Los dos de LaLiga van seguidos, bajo su epígrafe.
    assert salida.index("Real Madrid") > salida.index("LaLiga")
    assert "4 partido(s) en 3 competición(es)" in salida


def test_live_filtra_por_liga_conocida(inyectar_cliente, capsys):
    inyectar_cliente(_cliente_con_directos(DIRECTOS))
    assert cli.main(["live", "--league", "laliga"]) == 0
    salida = capsys.readouterr().out
    assert "Real Madrid" in salida and "Girona" in salida
    assert "Arsenal" not in salida


def test_live_filtra_por_texto_libre(inyectar_cliente, capsys):
    inyectar_cliente(_cliente_con_directos(DIRECTOS))
    assert cli.main(["live", "--filter", "arsenal"]) == 0
    salida = capsys.readouterr().out
    assert "Arsenal" in salida and "Real Madrid" not in salida


def test_una_liga_desconocida_se_busca_como_texto(inyectar_cliente, capsys):
    inyectar_cliente(_cliente_con_directos(DIRECTOS))
    assert cli.main(["live", "--league", "Club Friendly"]) == 0
    assert "SSD Rovato" in capsys.readouterr().out


def test_el_limite_avisa_de_lo_que_se_deja_fuera(inyectar_cliente, capsys):
    inyectar_cliente(_cliente_con_directos(DIRECTOS))
    assert cli.main(["live", "--limit", "2"]) == 0
    salida = capsys.readouterr().out
    assert "se enseñan 2" in salida
    assert "--filter" in salida


def test_sin_resultados_dice_de_cuantos_venia(inyectar_cliente, capsys):
    """Distingue "el filtro no encaja" de "no hay nada en juego"."""
    inyectar_cliente(_cliente_con_directos(DIRECTOS))
    assert cli.main(["live", "--filter", "equipo que no juega"]) == 0
    assert "Ninguno de los 4 partidos encaja" in capsys.readouterr().out


def test_sin_nada_en_juego_lo_dice_de_otra_forma(inyectar_cliente, capsys):
    inyectar_cliente(_cliente_con_directos([]))
    assert cli.main(["live"]) == 0
    assert "No hay ningún partido ahora mismo" in capsys.readouterr().out


@pytest.mark.parametrize("comando", [
    ["team", "Real Madrid"], ["player", "Vinicius"], ["league", "laliga"],
    ["match", str(EVENT_ID)], ["live"], ["today", "--date", "2024-10-26"],
])
def test_debug_funciona_en_todos_los_comandos(cli_con_cliente, capsys, comando):
    """Estaba solo en `match`: los demás fallaban con 'unrecognized arguments'."""
    assert cli.main([*comando, "--debug"]) == 0
    salida = capsys.readouterr().out
    assert "Peticiones:" in salida
    assert "Transporte:" in salida
