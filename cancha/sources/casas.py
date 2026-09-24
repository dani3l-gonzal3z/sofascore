"""Cuotas de fuera de Sofascore: Betfair y The Odds API.

Sofascore enseña los mercados de **una** casa. Para saber qué cree el mercado de
verdad hace falta mirar más de una, y para el marcador exacto hace falta una en
concreto: **Betfair Exchange**. Es una bolsa, no una casa —los precios los ponen
apostantes contra apostantes y Betfair solo cobra comisión—, así que su margen
es casi nulo y su marcador exacto es lo más parecido a la distribución «real» que
hay en público. Tiene API oficial con una clave gratuita (con unos segundos de
retraso, que para esto sobran).

The Odds API junta varias casas por región con una sola clave. Tiene capa
gratuita con un tope de peticiones al mes, y cada mercado y cada región cuentan.

Lo que **no** hay aquí, a propósito: rascar la web de bet365. Va contra sus
condiciones, los programas que lo hacen se rompen cada vez que cambian la página,
y para algo que se quiera vender no vale.

Las dos fuentes escriben en el mismo sitio y en el mismo formato que Sofascore
(`cuotas_mercado`), así que el resto del programa no sabe de dónde vino cada
cuota: el registro coge la casa que menos cobra, y el marcador exacto, la que más
resultados lista.
"""

from __future__ import annotations

import difflib
import json
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from typing import Any

from ..errors import SofascoreError
from ..mercados import con_probabilidades, seleccion


class CasaNoDisponible(SofascoreError):
    """No se ha podido hablar con una fuente de cuotas, y se dice por qué."""


# ------------------------------------------------------------ emparejar

#: Lo que sobra en el nombre de un equipo para compararlo con otro: siglas de
#: sociedad y artículos. **No** «real», «atlético» o «sporting», que distinguen
#: equipos: quitándolos, el Real Madrid y el Atlético se quedaban los dos en
#: «madrid».
_RUIDO = {"fc", "cf", "sc", "ac", "afc", "cd", "ud", "sd", "rcd", "ca", "club",
          "de", "del", "la", "the", "calcio"}


def _limpio(nombre: str) -> str:
    plano = unicodedata.normalize("NFKD", str(nombre or "")).encode("ascii", "ignore")
    palabras = re.sub(r"[^a-z0-9 ]+", " ", plano.decode().lower()).split()
    utiles = [p for p in palabras if p not in _RUIDO]
    return " ".join(utiles or palabras)


def parecido(uno: str, otro: str) -> float:
    """De 0 a 1, cuánto se parecen dos nombres de equipo.

    Cada fuente escribe los equipos a su manera —«Girona FC», «Girona»,
    «Athletic Club», «Ath Bilbao»—, así que se comparan limpios de sufijos y
    mirando tanto las letras como las palabras en común.
    """
    a, b = _limpio(uno), _limpio(otro)
    if not a or not b:
        return 0.0
    if a == b or a in b or b in a:
        return 1.0
    letras = difflib.SequenceMatcher(None, a, b).ratio()
    pa, pb = set(a.split()), set(b.split())
    palabras = len(pa & pb) / max(len(pa | pb), 1)
    return max(letras, palabras)


#: Por debajo de esto no se da un partido por el mismo. Se prefiere perder unas
#: cuotas a pegarle las de otro partido a uno: eso envenenaría el registro.
PARECIDO_MINIMO = 0.72


def emparejar(almacen, local: str, visitante: str, momento: float,
              ventana_horas: float = 3.0) -> int | None:
    """El id nuestro de un partido que otra fuente llama a su manera.

    Se buscan los partidos que empiezan a la misma hora (con margen, porque no
    todas las fuentes ponen la misma) y se queda el que más se parece **en los
    dos equipos**. Si ninguno pasa el listón, ninguno: mejor sin cuotas que con
    las de otro partido.
    """
    desde, hasta = momento - ventana_horas * 3600, momento + ventana_horas * 3600
    candidatos = almacen.consulta(
        "SELECT id, local, visitante FROM partidos WHERE momento BETWEEN ? AND ?",
        (desde, hasta))
    mejor, nota = None, 0.0
    for fila in candidatos:
        suyo = min(parecido(local, fila["local"] or ""),
                   parecido(visitante, fila["visitante"] or ""))
        if suyo > nota:
            mejor, nota = fila["id"], suyo
    return mejor if nota >= PARECIDO_MINIMO else None


def _pedir(url: str, cuerpo: Any = None, cabeceras: dict | None = None,
           formulario: bool = False, contexto: Any = None,
           timeout: float = 30.0) -> Any:
    """Una petición HTTP con JSON o formulario. Sin dependencias."""
    datos = None
    if cuerpo is not None:
        datos = (urllib.parse.urlencode(cuerpo) if formulario
                 else json.dumps(cuerpo)).encode("utf-8")
    peticion = urllib.request.Request(
        url, data=datos, method="POST" if datos is not None else "GET",
        headers={"Accept": "application/json",
                 "Content-Type": ("application/x-www-form-urlencoded" if formulario
                                  else "application/json"),
                 **(cabeceras or {})})
    try:
        with urllib.request.urlopen(peticion, timeout=timeout,  # noqa: S310
                                    context=contexto) as respuesta:
            return json.loads(respuesta.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detalle = ""
        with suppress(Exception):
            detalle = exc.read().decode("utf-8", "replace")[:300]
        raise CasaNoDisponible(f"{urllib.parse.urlparse(url).netloc} contesta "
                               f"{exc.code}: {detalle}") from exc
    except OSError as exc:
        from ..tls import es_de_certificado, explicar

        host = urllib.parse.urlparse(url).netloc
        if es_de_certificado(exc):
            raise CasaNoDisponible(f"No llego a {host}. {explicar(host)}") from exc
        raise CasaNoDisponible(f"No llego a {host}: {exc}") from exc


# ------------------------------------------------------------------ Betfair

#: Los mercados de fútbol de Betfair que se piden, y cómo se llaman aquí.
BETFAIR_MERCADOS = {
    "MATCH_ODDS": ("1x2", ""),
    "CORRECT_SCORE": ("marcador", ""),
    "OVER_UNDER_25": ("goles", "2.5"),
    "OVER_UNDER_15": ("goles", "1.5"),
    "OVER_UNDER_35": ("goles", "3.5"),
    "BOTH_TEAMS_TO_SCORE": ("ambos_marcan", ""),
}

#: Dónde vive Betfair según el país de la cuenta. Una cuenta española no entra
#: por el .com: usa su propio dominio, y con el otro el acceso falla sin más.
BETFAIR_HOSTS = {
    "com": ("https://identitysso.betfair.com", "https://api.betfair.com"),
    "es": ("https://identitysso.betfair.es", "https://api.betfair.es"),
    "it": ("https://identitysso.betfair.it", "https://api.betfair.it"),
}

#: Cuántos mercados caben en una petición de precios. Betfair pone un peso a
#: cada cosa que se pide y un tope de 200 por llamada; los mejores precios pesan
#: 5 por mercado.
POR_TANDA = 40


def _runner_betfair(mercado: str, nombre: str, local: str, visitante: str) -> str:
    """El nombre de una selección de Betfair, en el nuestro."""
    crudo = str(nombre or "").strip()
    if mercado == "1x2":
        if crudo.lower() == "the draw":
            return "empate"
        return "local" if parecido(crudo, local) >= parecido(crudo, visitante) \
            else "visitante"
    if mercado == "marcador":
        bajo = crudo.lower()
        if bajo.startswith("any other"):
            # «Any Other Home Win / Away Win / Draw»: tres cajones de «otro».
            return ("otro_local" if "home" in bajo else
                    "otro_visitante" if "away" in bajo else "otro_empate")
        return seleccion(crudo)
    if mercado == "goles":
        return "mas" if crudo.lower().startswith("over") else "menos"
    return seleccion(crudo)


def precio_justo(runner: dict) -> float | None:
    """El precio de una selección en la bolsa: el punto medio entre comprar y vender.

    En una bolsa hay dos precios: al que alguien te deja apostar a favor (back) y
    al que te deja apostar en contra (lay). La verdad está en medio. Si falta uno
    de los dos, o están tan separados que el medio no significa nada, se usa el
    último precio al que se cruzó dinero.
    """
    ex = runner.get("ex") or {}
    back = ((ex.get("availableToBack") or [{}])[0]).get("price")
    lay = ((ex.get("availableToLay") or [{}])[0]).get("price")
    if back and lay and lay / back < 1.25:
        return round((back + lay) / 2, 3)
    return runner.get("lastPriceTraded") or back or None


class Betfair:
    """Betfair Exchange, por su API oficial. Hace falta una clave de aplicación.

    La clave gratuita (con retraso) se pide en developer.betfair.com y sale en
    minutos. Con ella y tu usuario se entra; no hacen falta certificados para
    esto.
    """

    fuente = "betfair"

    def __init__(self, clave_app: str, usuario: str, contrasena: str,
                 jurisdiccion: str = "com", pedir: Callable | None = None,
                 contexto: Any = None) -> None:
        if not (clave_app and usuario and contrasena):
            raise CasaNoDisponible(
                "Para Betfair hacen falta tres cosas: la clave de aplicación (se "
                "pide gratis en developer.betfair.com), tu usuario y tu contraseña. "
                "Van en Ajustes → Cuotas.")
        self.clave_app, self.usuario, self.contrasena = clave_app, usuario, contrasena
        self.sso, self.api = BETFAIR_HOSTS.get(jurisdiccion, BETFAIR_HOSTS["com"])
        self._pedir = pedir or (lambda *a, **k: _pedir(*a, contexto=contexto, **k))
        self._sesion = ""

    def entrar(self) -> None:
        datos = self._pedir(f"{self.sso}/api/login",
                            {"username": self.usuario, "password": self.contrasena},
                            {"X-Application": self.clave_app}, formulario=True)
        if (datos or {}).get("status") != "SUCCESS":
            raise CasaNoDisponible(
                f"Betfair no deja entrar: {(datos or {}).get('error') or datos}. "
                "Si tu cuenta es española, pon la jurisdicción en «es».")
        self._sesion = datos["token"]

    def _rpc(self, metodo: str, parametros: dict) -> Any:
        if not self._sesion:
            self.entrar()
        datos = self._pedir(
            f"{self.api}/exchange/betting/json-rpc/v1",
            {"jsonrpc": "2.0", "method": f"SportsAPING/v1.0/{metodo}",
             "params": parametros, "id": 1},
            {"X-Application": self.clave_app, "X-Authentication": self._sesion})
        if isinstance(datos, dict) and datos.get("error"):
            raise CasaNoDisponible(f"Betfair: {datos['error']}")
        return (datos or {}).get("result") or []

    def partidos(self, desde: datetime, hasta: datetime) -> list[dict]:
        """Los mercados de fútbol que empiezan entre dos momentos, con sus precios.

        Devuelve un partido por evento de Betfair, con sus equipos, su hora y sus
        filas en el formato largo de siempre.
        """
        catalogo = self._rpc("listMarketCatalogue", {
            "filter": {"eventTypeIds": ["1"],
                       "marketTypeCodes": list(BETFAIR_MERCADOS),
                       "marketStartTime": {
                           "from": desde.strftime("%Y-%m-%dT%H:%M:%SZ"),
                           "to": hasta.strftime("%Y-%m-%dT%H:%M:%SZ")}},
            "marketProjection": ["EVENT", "RUNNER_DESCRIPTION", "MARKET_START_TIME",
                                 "MARKET_DESCRIPTION"],
            "maxResults": "1000"})
        por_mercado = {m["marketId"]: m for m in catalogo if m.get("marketId")}
        libros: list[dict] = []
        ids = list(por_mercado)
        for n in range(0, len(ids), POR_TANDA):
            libros += self._rpc("listMarketBook", {
                "marketIds": ids[n:n + POR_TANDA],
                "priceProjection": {"priceData": ["EX_BEST_OFFERS"]}})

        eventos: dict[str, dict] = {}
        for libro in libros:
            mercado = por_mercado.get(libro.get("marketId")) or {}
            tipo = (mercado.get("description") or {}).get("marketType")
            if tipo not in BETFAIR_MERCADOS or libro.get("status") != "OPEN":
                continue
            evento = mercado.get("event") or {}
            local, _, visitante = str(evento.get("name") or "").partition(" v ")
            if not visitante:
                continue
            suyo = eventos.setdefault(evento.get("id"), {
                "local": local.strip(), "visitante": visitante.strip(),
                "momento": _marca_de_tiempo(mercado.get("marketStartTime")),
                "filas": []})
            nombres = {r["selectionId"]: r.get("runnerName")
                       for r in mercado.get("runners") or []}
            nuestro, linea = BETFAIR_MERCADOS[tipo]
            for runner in libro.get("runners") or []:
                if runner.get("status") != "ACTIVE":
                    continue
                precio = precio_justo(runner)
                if not precio or precio <= 1:
                    continue
                suyo["filas"].append({
                    "casa": "betfair-exchange", "mercado": nuestro, "linea": linea,
                    "seleccion": _runner_betfair(nuestro, nombres.get(runner.get(
                        "selectionId")), suyo["local"], suyo["visitante"]),
                    "cuota": precio, "cuota_inicial": None})
        for suyo in eventos.values():
            suyo["filas"] = con_probabilidades(suyo["filas"])
        return list(eventos.values())


# ------------------------------------------------------------- The Odds API

#: Nuestras competiciones → la clave de The Odds API. Las de fuera de esta
#: lista no se piden: cada una cuesta peticiones del cupo mensual.
ODDS_API_LIGAS = {
    "laliga": "soccer_spain_la_liga",
    "laliga2": "soccer_spain_segunda_division",
    "premier": "soccer_epl",
    "championship": "soccer_efl_champ",
    "serie-a": "soccer_italy_serie_a",
    "bundesliga": "soccer_germany_bundesliga",
    "ligue-1": "soccer_france_ligue_one",
    "eredivisie": "soccer_netherlands_eredivisie",
    "primeira": "soccer_portugal_primeira_liga",
    "champions": "soccer_uefa_champs_league",
    "europa-league": "soccer_uefa_europa_league",
    "mls": "soccer_usa_mls",
    "liga-mx": "soccer_mexico_ligamx",
    "brasileirao": "soccer_brazil_campeonato",
    "argentina": "soccer_argentina_primera_division",
}


class TheOddsApi:
    """Varias casas por región, con una sola clave (the-odds-api.com)."""

    fuente = "the-odds-api"
    raiz = "https://api.the-odds-api.com/v4"

    def __init__(self, clave: str, regiones: str = "eu,uk", casas: str = "",
                 pedir: Callable | None = None, contexto: Any = None) -> None:
        if not clave:
            raise CasaNoDisponible(
                "Para The Odds API hace falta una clave (the-odds-api.com, tiene "
                "capa gratuita). Va en Ajustes → Cuotas.")
        self.clave, self.regiones, self.casas = clave, regiones, casas
        self._pedir = pedir or (lambda *a, **k: _pedir(*a, contexto=contexto, **k))

    def partidos(self, ligas: list[str], mercados: str = "h2h,totals") -> list[dict]:
        salida = []
        for liga in ligas:
            clave_liga = ODDS_API_LIGAS.get(liga)
            if not clave_liga:
                continue
            parametros = {"apiKey": self.clave, "regions": self.regiones,
                          "markets": mercados, "oddsFormat": "decimal",
                          "dateFormat": "unix"}
            if self.casas:
                parametros["bookmakers"] = self.casas
                parametros.pop("regions")
            eventos = self._pedir(f"{self.raiz}/sports/{clave_liga}/odds/?"
                                  + urllib.parse.urlencode(parametros))
            for evento in eventos or []:
                salida.append(self._uno(evento))
        return salida

    @staticmethod
    def _uno(evento: dict) -> dict:
        local, visitante = evento.get("home_team") or "", evento.get("away_team") or ""
        filas = []
        for casa in evento.get("bookmakers") or []:
            for mercado in casa.get("markets") or []:
                for salida in mercado.get("outcomes") or []:
                    nombre, precio = salida.get("name"), salida.get("price")
                    if not precio or precio <= 1:
                        continue
                    if mercado.get("key") == "h2h":
                        suyo, linea = "1x2", ""
                        cual = ("empate" if str(nombre).lower() == "draw" else
                                "local" if nombre == local else "visitante")
                    elif mercado.get("key") == "totals":
                        suyo, linea = "goles", f"{salida.get('point')}"
                        cual = "mas" if str(nombre).lower() == "over" else "menos"
                    elif mercado.get("key") == "btts":
                        suyo, linea, cual = "ambos_marcan", "", seleccion(nombre)
                    else:
                        continue
                    filas.append({"casa": casa.get("key") or "?", "mercado": suyo,
                                  "linea": linea, "seleccion": cual,
                                  "cuota": float(precio), "cuota_inicial": None})
        return {"local": local, "visitante": visitante,
                "momento": float(evento.get("commence_time") or 0),
                "filas": con_probabilidades(filas)}


# ------------------------------------------------------------------ juntarlo

def _marca_de_tiempo(texto: Any) -> float:
    with suppress(ValueError, TypeError):
        return datetime.fromisoformat(str(texto).replace("Z", "+00:00")).timestamp()
    return 0.0


def guardar_partidos(almacen, fuente: str, partidos: list[dict]) -> dict:
    """Empareja cada partido de fuera con uno nuestro y guarda sus cuotas.

    Lo que no se empareja se cuenta y se enseña: un partido que no aparece suele
    ser una liga que no sigues, pero si son muchos es que algún nombre de equipo
    se escribe muy distinto, y eso conviene verlo.
    """
    guardados, sin_pareja, filas = 0, [], 0
    for partido in partidos:
        suyo = emparejar(almacen, partido["local"], partido["visitante"],
                         partido["momento"])
        if suyo is None:
            sin_pareja.append(f"{partido['local']} - {partido['visitante']}")
            continue
        escritas = almacen.guardar_mercados(suyo, partido["filas"], fuente=fuente)
        guardados += 1
        filas += escritas
    return {"fuente": fuente, "partidos": len(partidos), "emparejados": guardados,
            "filas": filas, "sin_pareja": sin_pareja[:30],
            "cuantos_sin_pareja": len(sin_pareja)}


def traer(almacen, ajustes: dict, fuente: str, dias: int = 2,
          ligas: list[str] | None = None, contexto: Any = None) -> dict:
    """Trae las cuotas de una fuente para lo que se juega en los próximos días."""
    cuotas = (ajustes.get("cuotas") or {})
    ahora = datetime.now(timezone.utc)
    if fuente == "betfair":
        suyo = cuotas.get("betfair") or {}
        casa = Betfair(suyo.get("clave_app", ""), suyo.get("usuario", ""),
                       suyo.get("contrasena", ""), suyo.get("jurisdiccion", "com"),
                       contexto=contexto)
        partidos = casa.partidos(ahora - timedelta(hours=1), ahora + timedelta(days=dias))
    elif fuente == "the-odds-api":
        suyo = cuotas.get("the_odds_api") or {}
        casa = TheOddsApi(suyo.get("clave", ""), suyo.get("regiones", "eu,uk"),
                          suyo.get("casas", ""), contexto=contexto)
        partidos = casa.partidos(list(ligas or ODDS_API_LIGAS))
    else:
        raise CasaNoDisponible(f"No conozco la fuente de cuotas «{fuente}». Las que "
                               "hay: betfair, the-odds-api.")
    return guardar_partidos(almacen, fuente, partidos)


__all__ = ["BETFAIR_MERCADOS", "ODDS_API_LIGAS", "PARECIDO_MINIMO", "Betfair",
           "CasaNoDisponible", "TheOddsApi", "emparejar", "guardar_partidos",
           "parecido", "precio_justo", "traer"]
