"""Adaptadores a ScraperFC y soccerdata: sus fuentes, con nuestra interfaz.

Hay datos que este framework no va a scrapear por su cuenta: **FBref** exige
un navegador de verdad desde que endureció su anti-bot (ScraperFC 4 abre
Chrome para leerlo), **Transfermarkt** y **Capology** son HTML que cambia. Las
dos librerías de referencia llevan años manteniendo esos lectores, y
reescribirlos aquí sería copiar su trabajo y heredar su fragilidad sin su
mantenimiento.

Así que se usan. Si están instaladas:

    pip install ScraperFC        # FBref (con navegador), Transfermarkt, Capology
    pip install soccerdata       # FBref, WhoScored, SoFIFA, MatchHistory

el framework las detecta y las expone con la misma forma que el resto: listas
de diccionarios, errores tipados, nombres de liga los nuestros. Si no están,
lo dice y explica qué instalar, en vez de fallar con un ImportError.

Lo que devuelven son *DataFrames* de pandas; aquí se convierten a registros
para que una IA los lea y para que la interfaz los pinte sin depender de
pandas. Y lo que no cambia: **todo esto se ejecuta en tu máquina**, tarda
(FBref obliga a esperar varios segundos por página) y necesita red.
"""

from __future__ import annotations

import importlib
import importlib.util
from typing import Any

from ..catalog import LEAGUES, find_league
from ..errors import SofascoreError


class AdaptadorNoDisponible(SofascoreError):
    """La librería externa no está instalada."""


#: Nombre de liga que entiende soccerdata, por competición de Sofascore.
#: Solo las que soccerdata trae de serie; el resto no tiene equivalente.
SOCCERDATA: dict[int, str] = {
    8: "ESP-La Liga", 17: "ENG-Premier League", 23: "ITA-Serie A",
    35: "GER-Bundesliga", 34: "FRA-Ligue 1",
}


def disponibles() -> dict[str, dict]:
    """Qué librerías externas hay instaladas, con su versión."""
    salida = {}
    for modulo, paquete in (("ScraperFC", "ScraperFC"), ("soccerdata", "soccerdata")):
        instalado = importlib.util.find_spec(modulo) is not None
        version = None
        if instalado:
            try:
                from importlib.metadata import version as _version

                version = _version(paquete)
            except Exception:  # noqa: BLE001 - la versión es cosmética
                version = "?"
        salida[modulo.lower()] = {
            "instalado": instalado,
            "version": version,
            "instalar": f"pip install {paquete}",
            "aporta": {
                "scraperfc": "FBref (abre un navegador), Transfermarkt (valores de mercado), "
                             "Capology (salarios), Understat, Sofascore, ClubElo.",
                "soccerdata": "FBref, ESPN, ClubElo, MatchHistory (football-data.co.uk), "
                              "SoFIFA, Understat, WhoScored (necesita navegador).",
            }[modulo.lower()],
        }
    return salida


def _registros(tabla: Any, maximo: int = 0) -> list[dict]:
    """Un DataFrame a lista de diccionarios sin depender de pandas aquí.

    Las columnas multinivel de FBref (``("Performance", "Gls")``) se aplanan
    con un espacio, y el índice se vuelca a columnas para no perder el equipo
    o el jugador.
    """
    if tabla is None:
        return []
    if isinstance(tabla, list):
        return [r if isinstance(r, dict) else {"valor": r} for r in tabla]
    if isinstance(tabla, dict) and "columns" not in dir(tabla):
        return [{"clave": k, **(v if isinstance(v, dict) else {"valor": v})}
                for k, v in tabla.items()]
    try:
        plana = tabla.reset_index() if hasattr(tabla, "reset_index") else tabla
        if hasattr(plana.columns, "nlevels") and plana.columns.nlevels > 1:
            plana.columns = [" ".join(str(p) for p in col if str(p) and "Unnamed" not in str(p))
                             .strip() for col in plana.columns]
        if maximo:
            plana = plana.head(maximo)
        filas = plana.to_dict(orient="records")
    except Exception as exc:  # noqa: BLE001 - lo que no se pueda aplanar se describe
        return [{"error": f"No se pudo convertir la tabla: {exc}", "tipo": type(tabla).__name__}]
    limpias = []
    for fila in filas:
        limpias.append({str(k): (None if _es_nan(v) else v) for k, v in fila.items()})
    return limpias


def _es_nan(valor: Any) -> bool:
    return isinstance(valor, float) and valor != valor


def nombre_de_liga(liga: int | str) -> str:
    """El nombre que usa ScraperFC, que es el mismo de nuestro catálogo."""
    if isinstance(liga, int) or str(liga).isdigit():
        for nombre, identificador in LEAGUES.items():
            if identificador == int(liga):
                return nombre
        raise ValueError(f"No conozco la competición {liga}.")
    if liga in LEAGUES:
        return liga
    identificador = find_league(str(liga))
    if identificador:
        return nombre_de_liga(identificador)
    raise ValueError(f"No sé qué liga es '{liga}'.")


def _importar(modulo: str):
    try:
        return importlib.import_module(modulo)
    except ImportError as exc:
        raise AdaptadorNoDisponible(
            f"{modulo} no está instalado. Instálalo con `pip install {modulo}` "
            f"(en tu máquina: abre navegadores y tarda)."
        ) from exc


# ----------------------------------------------------------------- ScraperFC

class ScraperFCAdaptador:
    """FBref, Transfermarkt y Capology a través de ScraperFC.

    Los años se pasan tal como los quiere cada módulo de ScraperFC (FBref:
    ``"2024-2025"``; Transfermarkt: ``"24/25"``). Si dudas, pregunta con
    :meth:`temporadas` y usa una de las que devuelva.
    """

    nombre = "scraperfc"

    def __init__(self) -> None:
        self.sfc = _importar("ScraperFC")

    def temporadas(self, modulo: str, liga: int | str) -> list[str]:
        """Las temporadas válidas de un módulo (``fbref``, ``transfermarkt``,
        ``capology``) para una liga, en el formato exacto que pide."""
        clase = {"fbref": "FBref", "transfermarkt": "Transfermarkt",
                 "capology": "Capology"}.get(modulo.lower())
        if not clase:
            raise ValueError("modulo debe ser fbref, transfermarkt o capology")
        instancia = getattr(self.sfc, clase)()
        validas = instancia.get_valid_seasons(nombre_de_liga(liga))
        return list(validas.keys()) if isinstance(validas, dict) else list(validas)

    def fbref_estadisticas(self, liga: int | str, año: str, categoria: str = "standard",
                           maximo: int = 0) -> dict:
        """Las tablas de una categoría de FBref: equipos, rivales y jugadores.

        ``categoria``: standard, shooting, passing, defensive, possession, misc,
        goalkeeping, playing time, goal and shot creation, pass types.
        Abre un navegador: tarda.
        """
        fbref = self.sfc.FBref()
        tablas = fbref.scrape_stats(str(año), nombre_de_liga(liga), categoria)
        if isinstance(tablas, dict):
            return {clave: _registros(tabla, maximo) for clave, tabla in tablas.items()}
        claves = ("equipos", "rivales", "jugadores")
        return {clave: _registros(tabla, maximo)
                for clave, tabla in zip(claves, tablas, strict=False)}

    def fbref_partidos(self, liga: int | str, año: str, maximo: int = 0) -> list[dict]:
        """Los partidos de una temporada en FBref, con sus tiros y jugadores."""
        fbref = self.sfc.FBref()
        partidos = fbref.scrape_matches(str(año), nombre_de_liga(liga))
        salida = []
        for partido in partidos[:maximo] if maximo else partidos:
            salida.append({k: (v if not hasattr(v, "to_dict") else _registros(v))
                           for k, v in vars(partido).items()})
        return salida

    def transfermarkt_valores(self, liga: int | str, año: str, maximo: int = 0) -> list[dict]:
        """Valores de mercado, edades, contratos: todos los jugadores de una liga."""
        tm = self.sfc.Transfermarkt()
        return _registros(tm.scrape_players(str(año), nombre_de_liga(liga)), maximo)

    def capology_salarios(self, liga: int | str, año: str, moneda: str = "eur",
                          maximo: int = 0) -> list[dict]:
        """Salarios por jugador según Capology."""
        capology = self.sfc.Capology()
        return _registros(capology.scrape_salaries(str(año), nombre_de_liga(liga), moneda),
                          maximo)


# ----------------------------------------------------------------- soccerdata

class SoccerdataAdaptador:
    """FBref (sin navegador), SoFIFA y WhoScored a través de soccerdata.

    Las temporadas van como las entiende soccerdata: ``2024`` o ``"24-25"``.
    Solo cubre de serie las cinco grandes ligas.
    """

    nombre = "soccerdata"

    def __init__(self) -> None:
        self.sd = _importar("soccerdata")

    @staticmethod
    def liga(liga: int | str) -> str:
        if isinstance(liga, int) or str(liga).isdigit():
            nombre = SOCCERDATA.get(int(liga))
        elif str(liga) in SOCCERDATA.values():
            nombre = str(liga)
        else:
            identificador = find_league(str(liga))
            nombre = SOCCERDATA.get(identificador or 0)
        if not nombre:
            raise ValueError(f"soccerdata no trae de serie la competición '{liga}'. "
                             f"Cubre: {', '.join(SOCCERDATA.values())}.")
        return nombre

    def fbref_equipos(self, liga: int | str, temporada: int | str, tipo: str = "standard",
                      rivales: bool = False, maximo: int = 0) -> list[dict]:
        """Estadísticas de temporada por equipo (``standard``, ``shooting``,
        ``keeper``, ``playing_time``, ``misc``)."""
        lector = self.sd.FBref(leagues=self.liga(liga), seasons=temporada)
        return _registros(lector.read_team_season_stats(stat_type=tipo, opponent_stats=rivales),
                          maximo)

    def fbref_jugadores(self, liga: int | str, temporada: int | str, tipo: str = "standard",
                        maximo: int = 0) -> list[dict]:
        """Estadísticas de temporada por jugador."""
        lector = self.sd.FBref(leagues=self.liga(liga), seasons=temporada)
        return _registros(lector.read_player_season_stats(stat_type=tipo), maximo)

    def fbref_calendario(self, liga: int | str, temporada: int | str,
                         maximo: int = 0) -> list[dict]:
        """El calendario con resultados y xG de FBref."""
        lector = self.sd.FBref(leagues=self.liga(liga), seasons=temporada)
        return _registros(lector.read_schedule(), maximo)

    def sofifa_valoraciones(self, liga: int | str, temporada: int | str,
                            maximo: int = 0) -> list[dict]:
        """Las valoraciones de SoFIFA (el videojuego) por jugador."""
        lector = self.sd.SoFIFA(leagues=self.liga(liga), versions="latest")
        del temporada  # SoFIFA va por versión del juego, no por temporada
        return _registros(lector.read_players(), maximo)


def adaptador(nombre: str):
    """Construye un adaptador por nombre, o dice qué instalar."""
    if nombre.lower() == "scraperfc":
        return ScraperFCAdaptador()
    if nombre.lower() == "soccerdata":
        return SoccerdataAdaptador()
    raise ValueError("adaptadores: scraperfc, soccerdata")


__all__ = ["disponibles", "adaptador", "ScraperFCAdaptador", "SoccerdataAdaptador",
           "AdaptadorNoDisponible", "nombre_de_liga", "SOCCERDATA"]
