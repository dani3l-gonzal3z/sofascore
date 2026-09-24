"""El catálogo de competiciones, y cómo se corrige solo.

Hasta aquí las ligas eran una tabla de nombres a ids escrita a mano. Funciona
mientras no quieras añadir ninguna: los ids de Sofascore no se adivinan, y uno
mal puesto no falla —barre otra competición en silencio, que es peor—.

Así que aquí hay dos cosas:

1. **El catálogo**, por grupos y por género, con los ids que ya estaban
   contrastados contra la API de verdad (venían de ``ScraperFC``).
2. **El descubridor**: lo que no tiene id lo busca en la API, **comprueba que
   lo encontrado es lo que se pedía** —país, deporte y género— y lo guarda en
   la memoria. La siguiente vez ya está.

De modo que una competición nueva se añade escribiendo su nombre y qué buscar,
no un número sacado de ningún sitio. Y si Sofascore renumerara algo, se
redescubre con ``cancha ligas --descubrir --rehacer``.

    from cancha.ligas import COMPETICIONES, GRUPOS, resolver

    resolver(["grandes_f"], almacen)      # {id: nombre} de lo que ya se sabe
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .catalog import LEAGUES
from .errors import SofascoreError

#: Palabras que marcan una competición femenina en los idiomas que usa la API.
#: Sirven para no confundir la Liga F con LaLiga, que es justo el error que
#: cometería una búsqueda por nombre a secas.
MARCAS_FEMENINO = (
    "women", "woman", "femenin", "feminin", "femminil", "frauen", "damallsvenskan",
    "dames", "vrouwen", "kvinde", "kvinner", "naisten", "nwsl", " w ", "(w)", " wsl",
    "feminino", "femenil", "liga f",
)


@dataclass(frozen=True)
class Competicion:
    """Una competición del catálogo.

    ``id_conocido`` solo lo llevan las que ya venían contrastadas contra la API
    real. El resto se descubren: es la única forma honesta de añadir una liga
    sin poder comprobar su id.
    """

    nombre: str
    grupo: str
    #: ``masculino`` o ``femenino``.
    genero: str = "masculino"
    #: País o confederación, como lo escribe Sofascore en ``category.name``.
    pais: str = ""
    #: Qué escribir en el buscador de la API para encontrarla.
    busqueda: str = ""
    #: Id contrastado, si lo hay.
    id_conocido: int | None = None
    #: Otros nombres con los que llamarla.
    alias: tuple[str, ...] = field(default_factory=tuple)

    @property
    def femenina(self) -> bool:
        return self.genero == "femenino"

    def consulta(self) -> str:
        return self.busqueda or self.nombre


def _c(nombre: str, grupo: str, pais: str, busqueda: str = "", *,
       genero: str = "masculino", conocido: int | None = None,
       alias: tuple[str, ...] = ()) -> Competicion:
    return Competicion(nombre=nombre, grupo=grupo, genero=genero, pais=pais,
                       busqueda=busqueda, id_conocido=conocido, alias=alias)


#: El catálogo entero. Los ``conocido=`` son los ids que ya estaban
#: contrastados; los demás se descubren en la primera ejecución con red.
CATALOGO: tuple[Competicion, ...] = (
    # ---------------------------------------------------- Europa, masculino
    _c("Spain La Liga", "grandes", "Spain", "LaLiga", conocido=LEAGUES["Spain La Liga"],
       alias=("laliga", "primera division", "liga espanola")),
    _c("England Premier League", "grandes", "England", "Premier League",
       conocido=LEAGUES["England Premier League"], alias=("premier",)),
    _c("Italy Serie A", "grandes", "Italy", "Serie A", conocido=LEAGUES["Italy Serie A"],
       alias=("calcio",)),
    _c("Germany Bundesliga", "grandes", "Germany", "Bundesliga",
       conocido=LEAGUES["Germany Bundesliga"]),
    _c("France Ligue 1", "grandes", "France", "Ligue 1", conocido=LEAGUES["France Ligue 1"]),

    _c("UEFA Champions League", "uefa", "Europe", "Champions League",
       conocido=LEAGUES["UEFA Champions League"], alias=("champions",)),
    _c("UEFA Europa League", "uefa", "Europe", "Europa League",
       conocido=LEAGUES["UEFA Europa League"]),
    _c("UEFA Conference League", "uefa", "Europe", "Conference League",
       conocido=LEAGUES["UEFA Conference League"]),

    _c("Netherlands Eredivisie", "europeas", "Netherlands", "Eredivisie",
       conocido=LEAGUES["Netherlands Eredivisie"]),
    _c("Portugal Primeira Liga", "europeas", "Portugal", "Liga Portugal",
       conocido=LEAGUES["Portugal Primeira Liga"]),
    _c("Turkiye Super Lig", "europeas", "Türkiye", "Süper Lig",
       conocido=LEAGUES["Turkiye Super Lig"]),
    _c("England EFL Championship", "europeas", "England", "Championship",
       conocido=LEAGUES["England EFL Championship"]),
    _c("Spain La Liga 2", "europeas", "Spain", "LaLiga 2", conocido=LEAGUES["Spain La Liga 2"]),
    _c("Italy Serie B", "europeas", "Italy", "Serie B", conocido=LEAGUES["Italy Serie B"]),
    _c("Germany 2.Bundesliga", "europeas", "Germany", "2. Bundesliga",
       conocido=LEAGUES["Germany 2.Bundesliga"]),
    _c("France Ligue 2", "europeas", "France", "Ligue 2", conocido=LEAGUES["France Ligue 2"]),
    _c("Belgium Pro League", "europeas", "Belgium", "Jupiler Pro League"),
    _c("Scotland Premiership", "europeas", "Scotland", "Premiership"),
    _c("Austria Bundesliga", "europeas", "Austria", "Bundesliga"),
    _c("Switzerland Super League", "europeas", "Switzerland", "Super League"),
    _c("Denmark Superliga", "europeas", "Denmark", "Superliga"),
    _c("Norway Eliteserien", "europeas", "Norway", "Eliteserien"),
    _c("Sweden Allsvenskan", "europeas", "Sweden", "Allsvenskan"),
    _c("Greece Super League", "europeas", "Greece", "Super League"),
    _c("Czechia First League", "europeas", "Czech Republic", "Chance Liga"),
    _c("Poland Ekstraklasa", "europeas", "Poland", "Ekstraklasa"),
    _c("Croatia HNL", "europeas", "Croatia", "HNL"),
    _c("Serbia Super Liga", "europeas", "Serbia", "Super liga"),
    _c("Romania Superliga", "europeas", "Romania", "Superliga"),
    _c("Ukraine Premier League", "europeas", "Ukraine", "Premier League",
       conocido=LEAGUES["Ukraine Premier League"]),

    # ----------------------------------------------------- Europa, femenino
    _c("Spain Liga F", "grandes_f", "Spain", "Liga F", genero="femenino",
       alias=("liga f", "primera femenina")),
    _c("England WSL", "grandes_f", "England", "Women's Super League", genero="femenino",
       conocido=LEAGUES["England WSL"], alias=("wsl",)),
    _c("Germany Frauen-Bundesliga", "grandes_f", "Germany", "Frauen Bundesliga",
       genero="femenino"),
    _c("France Premiere Ligue", "grandes_f", "France", "Première Ligue Féminine",
       genero="femenino", alias=("d1 arkema",)),
    _c("Italy Serie A Femminile", "grandes_f", "Italy", "Serie A Femminile",
       genero="femenino"),
    _c("UEFA Women's Champions League", "uefa_f", "Europe", "Women's Champions League",
       genero="femenino", alias=("champions femenina",)),
    _c("England WSL 2", "europeas_f", "England", "Women's Championship", genero="femenino",
       conocido=LEAGUES["England WSL 2"]),
    _c("Netherlands Eredivisie Vrouwen", "europeas_f", "Netherlands", "Eredivisie Vrouwen",
       genero="femenino"),
    _c("Portugal Campeonato Feminino", "europeas_f", "Portugal",
       "Campeonato Nacional Feminino", genero="femenino"),
    _c("Sweden Damallsvenskan", "europeas_f", "Sweden", "Damallsvenskan", genero="femenino"),
    _c("Norway Toppserien", "europeas_f", "Norway", "Toppserien", genero="femenino"),
    _c("Switzerland Women's Super League", "europeas_f", "Switzerland",
       "Women's Super League", genero="femenino"),

    # ------------------------------------------------------ América del Norte
    _c("USA MLS", "usa", "USA", "MLS", conocido=LEAGUES["USA MLS"], alias=("mls",)),
    _c("USA USL championship", "usa", "USA", "USL Championship",
       conocido=LEAGUES["USA USL championship"]),
    _c("USA USL League 1", "usa", "USA", "USL League One",
       conocido=LEAGUES["USA USL League 1"]),
    _c("USA MLS Next Pro", "usa", "USA", "MLS Next Pro"),
    _c("Canada Premier League", "usa", "Canada", "Canadian Premier League"),
    _c("Mexico Liga MX Apertura", "usa", "Mexico", "Liga MX Apertura",
       conocido=LEAGUES["Mexico Liga MX Apertura"], alias=("liga mx",)),
    _c("Mexico Liga MX Clausura", "usa", "Mexico", "Liga MX Clausura",
       conocido=LEAGUES["Mexico Liga MX Clausura"]),
    _c("CONCACAF Champions Cup", "usa", "North & Central America",
       "CONCACAF Champions Cup"),
    _c("Leagues Cup", "usa", "North & Central America", "Leagues Cup"),
    _c("USA NWSL", "usa_f", "USA", "NWSL", genero="femenino", alias=("nwsl",)),
    _c("Mexico Liga MX Femenil", "usa_f", "Mexico", "Liga MX Femenil", genero="femenino"),

    # ------------------------------------------------------------ Sudamérica
    _c("Brazil Serie A", "sudamerica", "Brazil", "Brasileirão Série A",
       alias=("brasileirao",)),
    _c("Brazil Serie B", "sudamerica", "Brazil", "Brasileirão Série B"),
    _c("Argentina Liga Profesional", "sudamerica", "Argentina", "Liga Profesional",
       conocido=LEAGUES["Argentina Liga Profesional"]),
    _c("Argentina Copa de la Liga Profesional", "sudamerica", "Argentina",
       "Copa de la Liga Profesional", conocido=LEAGUES["Argentina Copa de la Liga Profesional"]),
    _c("Colombia Primera A", "sudamerica", "Colombia", "Primera A"),
    _c("Chile Primera Division", "sudamerica", "Chile", "Primera División"),
    _c("Uruguay Primera Division", "sudamerica", "Uruguay", "Primera División"),
    _c("Ecuador Liga Pro", "sudamerica", "Ecuador", "Liga Pro"),
    _c("Paraguay Division Profesional", "sudamerica", "Paraguay", "División Profesional"),
    _c("Bolivia Division Profesional", "sudamerica", "Bolivia", "División Profesional"),
    _c("Venezuela Liga FUTVE", "sudamerica", "Venezuela", "Liga FUTVE"),
    _c("Peru Liga 1", "sudamerica", "Peru", "Liga 1", conocido=LEAGUES["Peru Liga 1"]),
    _c("CONMEBOL Copa Libertadores", "sudamerica", "South America", "Copa Libertadores",
       conocido=LEAGUES["CONMEBOL Copa Libertadores"], alias=("libertadores",)),
    _c("CONMEBOL Copa Sudamericana", "sudamerica", "South America", "Copa Sudamericana"),
    _c("Brazil Serie A1 Feminino", "sudamerica_f", "Brazil", "Brasileirão Feminino",
       genero="femenino"),
    _c("Colombia Liga Femenina", "sudamerica_f", "Colombia", "Liga Femenina",
       genero="femenino"),
    _c("Argentina Campeonato Femenino", "sudamerica_f", "Argentina",
       "Campeonato Femenino", genero="femenino"),

    # ----------------------------------------------------------------- resto
    _c("Saudi Arabia Pro League", "arabia", "Saudi Arabia", "Saudi Pro League",
       conocido=LEAGUES["Saudi Arabia Pro League"], alias=("saudi",)),
)

#: Por nombre, para buscarlas rápido.
COMPETICIONES: dict[str, Competicion] = {c.nombre: c for c in CATALOGO}

#: Qué competiciones lleva cada grupo.
GRUPOS: dict[str, tuple[str, ...]] = {}
for _c_ in CATALOGO:
    GRUPOS.setdefault(_c_.grupo, ())
    GRUPOS[_c_.grupo] += (_c_.nombre,)

#: Grupos que se barren si no dices otra cosa: todo el catálogo. El femenino
#: entra por defecto —es la mitad del fútbol y la API lo sirve igual— y
#: América también. Son muchas competiciones y el primer barrido es largo:
#: para probar, `--grupos grandes` o `--max`.
POR_DEFECTO: tuple[str, ...] = tuple(GRUPOS)

#: Atajos para escribir menos.
ALIAS_GRUPO: dict[str, tuple[str, ...]] = {
    "todo": tuple(GRUPOS),
    "femenino": tuple(g for g in GRUPOS if g.endswith("_f")),
    "masculino": tuple(g for g in GRUPOS if not g.endswith("_f")),
    "europa": ("grandes", "grandes_f", "uefa", "uefa_f", "europeas", "europeas_f"),
    "america": ("usa", "usa_f", "sudamerica", "sudamerica_f"),
    "americas": ("usa", "usa_f", "sudamerica", "sudamerica_f"),
}


def competiciones_de(grupos: tuple[str, ...] | list[str] | None = None) -> list[Competicion]:
    """Las competiciones de unos grupos, sin repetir y en orden de catálogo.

    Acepta grupos (``grandes``), atajos (``femenino``, ``europa``), nombres de
    competición sueltos y alias (``laliga``).
    """
    elegidos = tuple(grupos) if grupos else POR_DEFECTO
    nombres: list[str] = []
    for bruto in elegidos:
        clave = " ".join(str(bruto).strip().lower().split())
        if clave in ALIAS_GRUPO:
            for grupo in ALIAS_GRUPO[clave]:
                nombres += list(GRUPOS.get(grupo, ()))
            continue
        if clave in GRUPOS:
            nombres += list(GRUPOS[clave])
            continue
        encontrada = por_nombre(str(bruto))
        if encontrada:
            nombres.append(encontrada.nombre)
    vistos: dict[str, None] = {}
    for nombre in nombres:
        vistos.setdefault(nombre, None)
    return [COMPETICIONES[n] for n in vistos if n in COMPETICIONES]


#: En qué orden se enseñan las competiciones cuando no hay más criterio: las
#: cinco grandes primero, y lo demás detrás. Sin esto, «qué se juega hoy»
#: ordenado por número de partidos abría con diez de la MLS a las dos y media de
#: la mañana y dejaba el Atlético - Real Madrid en tercer lugar.
ORDEN_DE_GRUPOS = ("grandes", "uefa", "europeas", "grandes_f", "uefa_f",
                   "europeas_f", "sudamerica", "usa", "arabia", "sudamerica_f",
                   "usa_f")


def relevancia(nombre: str) -> int:
    """Lo importante que es una competición, para ordenar una lista.

    Cuanto más bajo, más arriba. Lo que no está en el catálogo va al final, que
    es donde tiene que ir: son las categorías menores y los juveniles.
    """
    competicion = por_nombre(nombre)
    if competicion is None:
        return len(ORDEN_DE_GRUPOS) + 1
    try:
        return ORDEN_DE_GRUPOS.index(competicion.grupo)
    except ValueError:
        return len(ORDEN_DE_GRUPOS)


def por_nombre(texto: str) -> Competicion | None:
    """Encuentra una competición por su nombre, un alias o algo parecido."""
    if not texto:
        return None
    from difflib import get_close_matches

    clave = " ".join(str(texto).strip().lower().split())
    for competicion in CATALOGO:
        if clave == competicion.nombre.lower() or clave in competicion.alias:
            return competicion
    parciales = [c for c in CATALOGO if clave in c.nombre.lower()]
    if len(parciales) == 1:
        return parciales[0]
    aproximados = get_close_matches(clave, [c.nombre.lower() for c in CATALOGO], n=1, cutoff=0.75)
    if aproximados:
        return next(c for c in CATALOGO if c.nombre.lower() == aproximados[0])
    return None


# ------------------------------------------------------------------ resolver

def resolver(grupos: tuple[str, ...] | list[str] | None = None,
             almacen=None) -> dict[int, str]:
    """``{id: nombre}`` de las competiciones que ya se sabe cuáles son.

    Primero el id contrastado del catálogo; si no lo hay, el que se descubrió y
    quedó guardado en la memoria. Las que sigan sin id no salen: para eso está
    :func:`descubrir`, que es lo que las trae.
    """
    aprendidas = _aprendidas(almacen)
    salida: dict[int, str] = {}
    for competicion in competiciones_de(grupos):
        identificador = competicion.id_conocido or aprendidas.get(competicion.nombre)
        if identificador:
            salida[int(identificador)] = competicion.nombre
    return salida


def sin_resolver(grupos: tuple[str, ...] | list[str] | None = None,
                 almacen=None) -> list[Competicion]:
    """Las competiciones de esos grupos a las que todavía les falta el id."""
    aprendidas = _aprendidas(almacen)
    return [c for c in competiciones_de(grupos)
            if not (c.id_conocido or aprendidas.get(c.nombre))]


def _aprendidas(almacen) -> dict[str, int]:
    if almacen is None:
        return {}
    try:
        filas = almacen.consulta("SELECT nombre, id FROM ligas WHERE id IS NOT NULL")
    except Exception:  # noqa: BLE001 - una base vieja aún no tiene la tabla
        return {}
    return {f["nombre"]: f["id"] for f in filas}


# --------------------------------------------------------------- descubridor

def _parece_femenina(texto: str) -> bool:
    minuscula = f" {str(texto or '').lower()} "
    return any(marca in minuscula for marca in MARCAS_FEMENINO)


def puntuar(entidad: dict, competicion: Competicion) -> tuple[float, str]:
    """Cuánto se parece un resultado de búsqueda a la competición buscada.

    Lo importante no es el parecido del nombre —«Liga F» y «LaLiga» se parecen
    demasiado— sino **el país y el género**. Un candidato del país equivocado o
    del género equivocado se descarta aunque el nombre sea idéntico.
    """
    from .resolve import parecido

    nombre = entidad.get("name") or ""
    categoria = (entidad.get("category") or {})
    pais = categoria.get("name") or ""
    deporte = ((categoria.get("sport") or {}).get("slug")
               or (categoria.get("sport") or {}).get("name") or "").lower()

    if deporte and "football" not in deporte and "soccer" not in deporte:
        return 0.0, f"no es fútbol ({deporte})"
    if _parece_femenina(nombre) != competicion.femenina:
        cual = "femenina" if competicion.femenina else "masculina"
        return 0.0, f"se buscaba {cual} y '{nombre}' no lo es"
    if competicion.pais:
        encaje_pais = parecido(pais, competicion.pais)
        if encaje_pais < 0.55:
            return 0.0, f"país distinto ('{pais}' en vez de '{competicion.pais}')"
    else:
        encaje_pais = 0.5

    encaje_nombre = max(parecido(nombre, competicion.consulta()),
                        parecido(nombre, competicion.nombre))
    puntos = 0.65 * encaje_nombre + 0.35 * encaje_pais
    return puntos, f"'{nombre}' ({pais})"


def descubrir(cliente, almacen, grupos: tuple[str, ...] | list[str] | None = None,
              rehacer: bool = False, avisar=None, maximo: int = 0) -> dict:
    """Busca en la API las competiciones sin id, las comprueba y las guarda.

    Devuelve un resumen con lo encontrado y lo que no. Nada que no supere el
    listón de :func:`puntuar` se guarda: antes que un id equivocado —que
    barrería otra competición sin decir nada— es mejor no tener ninguno.
    """
    decir = avisar or (lambda _t: None)
    pendientes = (competiciones_de(grupos) if rehacer else sin_resolver(grupos, almacen))
    pendientes = [c for c in pendientes if not (c.id_conocido and not rehacer)]
    if maximo:
        pendientes = pendientes[:maximo]

    resumen: dict[str, Any] = {"buscadas": len(pendientes), "encontradas": 0,
                               "dudosas": [], "fallos": [], "nuevas": {}}
    for competicion in pendientes:
        try:
            resultados = cliente.search(competicion.consulta())
        except SofascoreError as exc:
            resumen["fallos"].append(f"{competicion.nombre}: {exc}")
            decir(f"  ✗ {competicion.nombre}: {exc}")
            continue

        candidatos = []
        for resultado in resultados:
            if resultado.get("type") != "uniqueTournament":
                continue
            entidad = resultado.get("entity") or {}
            if not entidad.get("id"):
                continue
            puntos, motivo = puntuar(entidad, competicion)
            if puntos > 0:
                candidatos.append((puntos, entidad, motivo))
        candidatos.sort(key=lambda t: -t[0])

        if not candidatos or candidatos[0][0] < 0.62:
            cerca = candidatos[0][2] if candidatos else "ningún candidato del país y género"
            resumen["dudosas"].append({"competicion": competicion.nombre, "mejor": cerca})
            decir(f"  ? {competicion.nombre}: no me fío ({cerca})")
            continue

        puntos, entidad, motivo = candidatos[0]
        almacen.guardar_liga(competicion, int(entidad["id"]), entidad)
        resumen["encontradas"] += 1
        resumen["nuevas"][competicion.nombre] = int(entidad["id"])
        decir(f"  ✓ {competicion.nombre} → {entidad['id']}  {motivo}")
    return resumen


def asegurar(cliente, almacen, grupos=None, avisar=None) -> dict:
    """Descubre lo que falte, solo si falta. Es lo que llama el barrido."""
    faltan = sin_resolver(grupos, almacen)
    if not faltan:
        return {"buscadas": 0, "encontradas": 0, "dudosas": [], "fallos": [], "nuevas": {}}
    decir = avisar or (lambda _t: None)
    decir(f"Faltan {len(faltan)} competiciones por identificar; las busco una vez:")
    return descubrir(cliente, almacen, grupos, avisar=avisar)


def resumen_catalogo(almacen=None) -> dict:
    """Qué hay en el catálogo y cuánto de él está ya identificado."""
    aprendidas = _aprendidas(almacen)
    por_grupo: dict[str, dict] = {}
    for competicion in CATALOGO:
        bloque = por_grupo.setdefault(competicion.grupo, {"total": 0, "con_id": 0,
                                                          "genero": competicion.genero,
                                                          "faltan": []})
        bloque["total"] += 1
        if competicion.id_conocido or aprendidas.get(competicion.nombre):
            bloque["con_id"] += 1
        else:
            bloque["faltan"].append(competicion.nombre)
    return {
        "competiciones": len(CATALOGO),
        "identificadas": sum(b["con_id"] for b in por_grupo.values()),
        "masculinas": sum(1 for c in CATALOGO if not c.femenina),
        "femeninas": sum(1 for c in CATALOGO if c.femenina),
        "por_grupo": por_grupo,
        "grupos": sorted(GRUPOS),
        "atajos": sorted(ALIAS_GRUPO),
    }


__all__ = [
    "ORDEN_DE_GRUPOS", "relevancia",
    "Competicion", "CATALOGO", "COMPETICIONES", "GRUPOS", "POR_DEFECTO", "ALIAS_GRUPO",
    "competiciones_de", "por_nombre", "resolver", "sin_resolver", "descubrir",
    "asegurar", "puntuar", "resumen_catalogo", "MARCAS_FEMENINO",
]
