"""Las tablas de referencia: estados, estadísticas y ligas."""

from __future__ import annotations

from sofascore.catalog import (
    KNOWN_STAT_KEYS,
    LEAGUES,
    MATCH_STAT_KEYS,
    PLAYER_STAT_KEYS,
    STATUS_CODES,
    find_league,
    status_label,
    suggest_stat,
)


def test_estados_conocidos():
    assert status_label(100) == "Ended"
    assert status_label(0) == "Not started"
    assert status_label(None) == ""
    assert status_label(99999) == ""
    assert all(len(v) == 2 for v in STATUS_CODES.values())


def test_hay_estadisticas_de_sobra():
    assert len(PLAYER_STAT_KEYS) > 100
    assert "expectedGoals" in PLAYER_STAT_KEYS
    assert "ballPossession" in MATCH_STAT_KEYS
    assert set(MATCH_STAT_KEYS) <= set(KNOWN_STAT_KEYS)


def test_sugerencias_para_erratas():
    assert "expectedGoals" in suggest_stat("expectedGoal")
    assert suggest_stat("ballPosession")  # la típica con una ese
    assert suggest_stat("") == []


def test_sugerencia_exacta_se_devuelve_tal_cual():
    assert suggest_stat("expectedGoals") == ["expectedGoals"]


def test_ligas_por_nombre_alias_y_parecido():
    assert find_league("Spain La Liga") == LEAGUES["Spain La Liga"]
    assert find_league("laliga") == 8
    assert find_league("LaLiga") == 8
    assert find_league("champions") == 7
    assert find_league("premier league") == 17
    assert find_league("mundial") == 16
    # Un nombre aproximado también vale.
    assert find_league("bundesliga alemana") == 35


def test_liga_desconocida_devuelve_none():
    assert find_league("liga de mi barrio") is None
    assert find_league("") is None
