"""Datos de referencia: códigos de estado, claves de estadísticas y ligas.

Nada de esto se inventa aquí. Son tablas que se han contrastado con las
librerías públicas que ya hablan con Sofascore (``ScraperFC``, ``soccerdata``,
``sofascore-wrapper``, ``sofascrape``, ``pysofascore``), que llevan años
funcionando contra la API real. Sirven para dos cosas:

* traducir lo que devuelve la API a algo legible (``status_label``);
* avisarte cuando pides una estadística que no existe, con una sugerencia de la
  que probablemente querías (``suggest_stat``).

Son *pistas*, no dogma: la API manda. Si pides una clave que no está en estas
listas, el framework la pide igual.
"""

from __future__ import annotations

from difflib import get_close_matches

#: Códigos de ``event["status"]["code"]`` con su descripción y tipo.
#: Contrastado con la tabla que documenta ScraperFC.
STATUS_CODES: dict[int, tuple[str, str]] = {
    0: ("Not started", "notstarted"),
    6: ("1st half", "inprogress"),
    7: ("2nd half", "inprogress"),
    31: ("Halftime", "inprogress"),
    60: ("Postponed", "postponed"),
    70: ("Canceled", "canceled"),
    90: ("Abandoned", "canceled"),
    93: ("Removed", "finished"),
    100: ("Ended", "finished"),
    110: ("AET", "finished"),
    120: ("AP", "finished"),
}


def status_label(code: int | None) -> str:
    """Descripción legible de un código de estado (``100`` -> ``"Ended"``)."""
    if code is None:
        return ""
    return STATUS_CODES.get(int(code), ("", ""))[0]


#: Claves de estadística de un jugador en una temporada.
#: Salen de muestrear jugadores de campo y porteros en
#: ``/player/{id}/unique-tournament/{t}/season/{s}/statistics/overall``.
PLAYER_STAT_KEYS: tuple[str, ...] = (
    'accurateChippedPasses',
    'accurateCrosses',
    'accurateCrossesPercentage',
    'accurateFinalThirdPasses',
    'accurateLongBalls',
    'accurateLongBallsPercentage',
    'accurateOppositionHalfPasses',
    'accurateOwnHalfPasses',
    'accuratePasses',
    'accuratePassesPercentage',
    'aerialDuelsWon',
    'aerialDuelsWonPercentage',
    'aerialLost',
    'appearances',
    'assists',
    'attemptPenaltyMiss',
    'attemptPenaltyPost',
    'attemptPenaltyTarget',
    'ballRecovery',
    'bigChancesCreated',
    'bigChancesMissed',
    'blockedShots',
    'cleanSheet',
    'clearances',
    'countRating',
    'crossesNotClaimed',
    'directRedCards',
    'dispossessed',
    'dribbledPast',
    'duelLost',
    'errorLeadToGoal',
    'errorLeadToShot',
    'expectedAssists',
    'expectedGoals',
    'fouls',
    'freeKickGoal',
    'goalConversionPercentage',
    'goalKicks',
    'goals',
    'goalsAssistsSum',
    'goalsConceded',
    'goalsConcededInsideTheBox',
    'goalsConcededOutsideTheBox',
    'goalsFromInsideTheBox',
    'goalsFromOutsideTheBox',
    'goalsPrevented',
    'groundDuelsWon',
    'groundDuelsWonPercentage',
    'headedGoals',
    'highClaims',
    'hitWoodwork',
    'inaccuratePasses',
    'interceptions',
    'keyPasses',
    'leftFootGoals',
    'matchesStarted',
    'minutesPlayed',
    'offsides',
    'outfielderBlocks',
    'ownGoals',
    'passToAssist',
    'penaltiesTaken',
    'penaltyConceded',
    'penaltyConversion',
    'penaltyFaced',
    'penaltyGoals',
    'penaltySave',
    'penaltyWon',
    'possessionLost',
    'possessionWonAttThird',
    'punches',
    'rating',
    'redCards',
    'rightFootGoals',
    'runsOut',
    'savedShotsFromInsideTheBox',
    'savedShotsFromOutsideTheBox',
    'saves',
    'savesCaught',
    'savesParried',
    'scoringFrequency',
    'setPieceConversion',
    'shotFromSetPiece',
    'shotsFromInsideTheBox',
    'shotsFromOutsideTheBox',
    'shotsOffTarget',
    'shotsOnTarget',
    'successfulDribbles',
    'successfulDribblesPercentage',
    'successfulRunsOut',
    'tackles',
    'tacklesWon',
    'tacklesWonPercentage',
    'totalAttemptAssist',
    'totalChippedPasses',
    'totalContest',
    'totalCross',
    'totalDuelsWon',
    'totalDuelsWonPercentage',
    'totalLongBalls',
    'totalOppositionHalfPasses',
    'totalOwnHalfPasses',
    'totalPasses',
    'totalRating',
    'totalShots',
    'totwAppearances',
    'touches',
    'wasFouled',
    'yellowCards',
    'yellowRedCards',
)

#: Claves habituales de las estadísticas de equipo de un partido
#: (``/event/{id}/statistics``). La API agrupa por periodo y por bloque; estas
#: son las que aparecen en casi todos los partidos de fútbol.
MATCH_STAT_KEYS: tuple[str, ...] = (
    "ballPossession",
    "expectedGoals",
    "bigChanceCreated",
    "bigChanceMissed",
    "totalShotsOnGoal",
    "shotsOnGoal",
    "shotsOffGoal",
    "blockedScoringAttempt",
    "hitWoodwork",
    "totalShotsInsideBox",
    "totalShotsOutsideBox",
    "goalkeeperSaves",
    "cornerKicks",
    "offsides",
    "fouls",
    "yellowCards",
    "redCards",
    "passes",
    "accuratePasses",
    "totalLongBalls",
    "accurateLongBalls",
    "totalCross",
    "accurateCross",
    "duelWonPercent",
    "dispossessed",
    "groundDuelsPercentage",
    "aerialDuelsPercentage",
    "totalClearance",
    "interceptionWon",
    "totalTackle",
    "touchesInOppBox",
    "fouledFinalThird",
    "throwIns",
    "goalKicks",
    "totalSaves",
)

#: Todas las claves conocidas, para sugerir cuando te equivocas al escribir.
KNOWN_STAT_KEYS: tuple[str, ...] = tuple(sorted(set(PLAYER_STAT_KEYS) | set(MATCH_STAT_KEYS)))


def suggest_stat(clave: str, n: int = 3) -> list[str]:
    """Claves parecidas a ``clave``, para el típico ``expectedGoal`` sin la ese."""
    if not clave:
        return []
    exactas = [k for k in KNOWN_STAT_KEYS if k.lower() == clave.lower()]
    if exactas:
        return exactas
    return get_close_matches(clave, KNOWN_STAT_KEYS, n=n, cutoff=0.6)


#: Ligas conocidas: nombre -> id de ``unique-tournament``.
#: Los ids vienen del catálogo que mantiene ScraperFC (``comps.yaml``), que sí
#: se ha ejercitado contra la API real.
LEAGUES: dict[str, int] = {
    'Argentina Copa de la Liga Profesional': 13475,
    'Argentina Liga Profesional': 155,
    'Bulgaria Parva Liga': 247,
    'CONCACAF Gold Cup': 140,
    'CONMEBOL Copa Libertadores': 384,
    'England EFL Championship': 18,
    'England Premier League': 17,
    'England WSL': 1044,
    'England WSL 2': 10553,
    'FIFA Womens World Cup': 290,
    'FIFA World Cup': 16,
    'France Ligue 1': 34,
    'France Ligue 2': 182,
    'France National 1': 183,
    'Germany 2.Bundesliga': 44,
    'Germany Bundesliga': 35,
    'Italy Serie A': 23,
    'Italy Serie B': 53,
    'Mexico Liga MX Apertura': 11621,
    'Mexico Liga MX Clausura': 11620,
    'Netherlands Eredivisie': 37,
    'Peru Liga 1': 406,
    'Portugal Liga Portugal 2': 239,
    'Portugal Primeira Liga': 238,
    'Saudi Arabia Pro League': 955,
    'Spain La Liga': 8,
    'Spain La Liga 2': 54,
    'Turkiye Super Lig': 52,
    'UEFA Champions League': 7,
    'UEFA Conference League': 17015,
    'UEFA Europa League': 679,
    'UEFA European Championship': 1,
    'USA MLS': 242,
    'USA USL League 1': 13362,
    'USA USL Leauge 2': 13546,
    'USA USL championship': 13363,
    'Ukraine Premier League': 218,
}

#: Alias cómodos en castellano y en jerga habitual.
LEAGUE_ALIASES: dict[str, str] = {
    "laliga": "Spain La Liga",
    "la liga": "Spain La Liga",
    "primera division": "Spain La Liga",
    "liga espanola": "Spain La Liga",
    "segunda": "Spain La Liga 2",
    "premier": "England Premier League",
    "premier league": "England Premier League",
    "championship": "England EFL Championship",
    "serie a": "Italy Serie A",
    "calcio": "Italy Serie A",
    "bundesliga": "Germany Bundesliga",
    "ligue 1": "France Ligue 1",
    "eredivisie": "Netherlands Eredivisie",
    "champions": "UEFA Champions League",
    "champions league": "UEFA Champions League",
    "europa league": "UEFA Europa League",
    "conference league": "UEFA Conference League",
    "eurocopa": "UEFA European Championship",
    "mundial": "FIFA World Cup",
    "world cup": "FIFA World Cup",
    "libertadores": "CONMEBOL Copa Libertadores",
    "mls": "USA MLS",
    "liga mx": "Mexico Liga MX Apertura",
    "saudi": "Saudi Arabia Pro League",
    "primeira liga": "Portugal Primeira Liga",
}


def find_league(nombre: str) -> int | None:
    """Id de ``unique-tournament`` a partir de un nombre libre de liga.

    Acepta el nombre del catálogo (``"Spain La Liga"``), un alias
    (``"laliga"``, ``"champions"``) o algo parecido: ``"bundesliga alemana"``
    también encuentra la Bundesliga.
    """
    if not nombre:
        return None
    texto = " ".join(nombre.lower().split())
    if texto in LEAGUE_ALIASES:
        return LEAGUES.get(LEAGUE_ALIASES[texto])
    for clave, valor in LEAGUES.items():
        if clave.lower() == texto:
            return valor
    parciales = [v for k, v in LEAGUES.items() if texto in k.lower()]
    if len(parciales) == 1:
        return parciales[0]
    for alias, canonico in LEAGUE_ALIASES.items():
        if alias in texto:
            return LEAGUES.get(canonico)
    aproximados = get_close_matches(texto, [k.lower() for k in LEAGUES], n=1, cutoff=0.6)
    if aproximados:
        for clave, valor in LEAGUES.items():
            if clave.lower() == aproximados[0]:
                return valor
    return None


__all__ = [
    "STATUS_CODES",
    "status_label",
    "PLAYER_STAT_KEYS",
    "MATCH_STAT_KEYS",
    "KNOWN_STAT_KEYS",
    "suggest_stat",
    "LEAGUES",
    "LEAGUE_ALIASES",
    "find_league",
]
