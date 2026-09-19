"""El catálogo de competiciones y el descubridor que lo completa.

Lo que hay que comprobar aquí no es que la tabla tenga muchas filas, sino lo
contrario: que **no se guarda un id que no se ha podido confirmar**. Un id
equivocado no da error, barre otra competición en silencio, y eso es peor que
no tener ninguno.
"""

from __future__ import annotations

import pytest

from cancha.almacen import Almacen
from cancha.cache import MemoryCache
from cancha.client import SofascoreClient
from cancha.config import Settings
from cancha.ligas import (
    CATALOGO,
    COMPETICIONES,
    GRUPOS,
    Competicion,
    asegurar,
    competiciones_de,
    descubrir,
    por_nombre,
    puntuar,
    resolver,
    resumen_catalogo,
    sin_resolver,
)
from cancha.transport import FakeTransport


@pytest.fixture
def base():
    with Almacen(":memory:") as almacen:
        yield almacen


def _entidad(identificador, nombre, pais, deporte="football"):
    return {"type": "uniqueTournament",
            "entity": {"id": identificador, "name": nombre,
                       "category": {"name": pais, "sport": {"slug": deporte}}}}


def _cliente(resultados_por_consulta):
    """Un cliente cuyo buscador devuelve lo que se le diga por consulta."""
    class Buscador(SofascoreClient):
        def search(self, query, page=0):
            return resultados_por_consulta.get(query, [])

    return Buscador(Settings(rate_limit=0, retries=0, fallback_base_urls=()),
                    transport=FakeTransport({}), cache=MemoryCache(), sleep=lambda _s: None)


# --------------------------------------------------------------- el catálogo

def test_el_catalogo_cubre_lo_que_se_pidio():
    resumen = resumen_catalogo()
    assert resumen["competiciones"] >= 60
    assert resumen["femeninas"] >= 15, "el femenino no es un añadido, es la mitad"
    for grupo in ("grandes", "grandes_f", "uefa", "uefa_f", "europeas", "europeas_f",
                  "usa", "usa_f", "sudamerica", "sudamerica_f"):
        assert grupo in GRUPOS, grupo


def test_las_cinco_grandes_estan_en_los_dos_generos():
    masculinas = {c.pais for c in competiciones_de(["grandes"])}
    femeninas = {c.pais for c in competiciones_de(["grandes_f"])}
    assert masculinas == {"Spain", "England", "Italy", "Germany", "France"}
    assert masculinas == femeninas


def test_sudamerica_y_estados_unidos_estan_de_verdad():
    paises = {c.pais for c in competiciones_de(["sudamerica"])}
    assert {"Brazil", "Argentina", "Colombia", "Chile", "Uruguay"} <= paises
    usa = {c.nombre for c in competiciones_de(["usa", "usa_f"])}
    assert "USA MLS" in usa and "USA NWSL" in usa


def test_los_atajos_agrupan_como_se_espera():
    assert len(competiciones_de(["femenino"])) == sum(1 for c in CATALOGO if c.femenina)
    assert len(competiciones_de(["todo"])) == len(CATALOGO)
    americanas = competiciones_de(["america"])
    assert all(c.grupo.startswith(("usa", "sudamerica")) for c in americanas)


def test_una_competicion_suelta_o_un_alias_tambien_vale():
    assert [c.nombre for c in competiciones_de(["laliga"])] == ["Spain La Liga"]
    assert [c.nombre for c in competiciones_de(["nwsl"])] == ["USA NWSL"]
    assert [c.nombre for c in competiciones_de(["Spain Liga F"])] == ["Spain Liga F"]


def test_no_se_repite_una_competicion_pedida_dos_veces():
    dos_veces = competiciones_de(["grandes", "laliga", "grandes"])
    assert len(dos_veces) == len({c.nombre for c in dos_veces})


def test_por_nombre_encuentra_y_se_rinde_cuando_toca():
    assert por_nombre("premier").nombre == "England Premier League"
    assert por_nombre("brasileirao").nombre == "Brazil Serie A"
    assert por_nombre("") is None
    assert por_nombre("la liga de mi pueblo") is None


def test_los_ids_que_ya_estaban_contrastados_siguen_ahi():
    """Venían de ScraperFC, que sí los había ejercitado contra la API."""
    assert COMPETICIONES["Spain La Liga"].id_conocido == 8
    assert COMPETICIONES["England Premier League"].id_conocido == 17
    assert COMPETICIONES["USA MLS"].id_conocido == 242
    assert COMPETICIONES["England WSL"].id_conocido == 1044


def test_lo_que_no_esta_contrastado_no_finge_estarlo():
    """La Liga F no lleva id inventado: sale como pendiente hasta descubrirla."""
    assert COMPETICIONES["Spain Liga F"].id_conocido is None
    pendientes = {c.nombre for c in sin_resolver(["grandes_f"])}
    assert "Spain Liga F" in pendientes and "England WSL" not in pendientes


# ------------------------------------------------------------------ resolver

def test_resolver_solo_devuelve_lo_que_se_sabe(base):
    ids = resolver(["grandes"], base)
    assert ids == {8: "Spain La Liga", 17: "England Premier League",
                   23: "Italy Serie A", 35: "Germany Bundesliga", 34: "France Ligue 1"}


def test_lo_descubierto_se_recuerda(base):
    liga_f = COMPETICIONES["Spain Liga F"]
    base.guardar_liga(liga_f, 1234, {"name": "Liga F", "category": {"name": "Spain"}})
    assert resolver(["grandes_f"], base)[1234] == "Spain Liga F"
    assert not [c for c in sin_resolver(["grandes_f"], base) if c.nombre == "Spain Liga F"]
    guardada = base.ligas_aprendidas()[0]
    assert guardada["nombre_api"] == "Liga F" and guardada["genero"] == "femenino"


def test_se_puede_olvidar_lo_aprendido_para_rehacerlo(base):
    base.guardar_liga(COMPETICIONES["Spain Liga F"], 1234)
    assert base.olvidar_ligas() == 1
    assert base.ligas_aprendidas() == []


def test_una_base_vieja_sin_la_tabla_no_rompe_el_resolver(tmp_path):
    import sqlite3

    ruta = tmp_path / "v3.db"
    viejo = sqlite3.connect(str(ruta))
    # El esquema de la versión 3: todo menos la tabla de ligas.
    viejo.execute("CREATE TABLE partidos (id INTEGER PRIMARY KEY, custom_id TEXT, fecha TEXT, "
                  "momento INTEGER, deporte TEXT, liga_id INTEGER, liga TEXT, temporada_id "
                  "INTEGER, jornada INTEGER, local_id INTEGER, local TEXT, visitante_id INTEGER, "
                  "visitante TEXT, goles_local INTEGER, goles_visitante INTEGER, estado TEXT, "
                  "arbitro TEXT, sede TEXT, formacion_local TEXT, formacion_visitante TEXT, "
                  "visto_en TEXT)")
    viejo.commit()
    viejo.close()
    with Almacen(ruta) as almacen:
        assert almacen.nota("version_esquema") == "4"
        assert resolver(["grandes"], almacen)[8] == "Spain La Liga"


# --------------------------------------------------------------- el puntuador

def test_el_pais_manda_sobre_el_nombre():
    """«Bundesliga» existe en Alemania y en Austria: el país desempata."""
    alemana = COMPETICIONES["Germany Bundesliga"]
    puntos, motivo = puntuar({"name": "Bundesliga",
                              "category": {"name": "Austria", "sport": {"slug": "football"}}},
                             alemana)
    assert puntos == 0.0 and "país distinto" in motivo


def test_una_competicion_femenina_no_se_confunde_con_la_masculina():
    """El error que costaría caro: Liga F resuelta a LaLiga."""
    liga_f = COMPETICIONES["Spain Liga F"]
    puntos, motivo = puntuar({"name": "LaLiga",
                              "category": {"name": "Spain", "sport": {"slug": "football"}}},
                             liga_f)
    assert puntos == 0.0 and "femenina" in motivo

    buenos, _ = puntuar({"name": "Liga F",
                         "category": {"name": "Spain", "sport": {"slug": "football"}}}, liga_f)
    assert buenos > 0.62


def test_y_al_reves_una_masculina_no_se_resuelve_a_la_femenina():
    puntos, motivo = puntuar({"name": "Liga F Femenina",
                              "category": {"name": "Spain", "sport": {"slug": "football"}}},
                             COMPETICIONES["Spain La Liga"])
    assert puntos == 0.0 and "masculina" in motivo


def test_otro_deporte_se_descarta():
    puntos, motivo = puntuar({"name": "MLS",
                              "category": {"name": "USA", "sport": {"slug": "basketball"}}},
                             COMPETICIONES["USA MLS"])
    assert puntos == 0.0 and "no es fútbol" in motivo


@pytest.mark.parametrize("nombre,femenina", [
    ("Liga F", True), ("Women's Super League", True), ("Frauen-Bundesliga", True),
    ("NWSL", True), ("Serie A Femminile", True), ("Brasileirão Feminino", True),
    ("LaLiga", False), ("Premier League", False), ("Serie A", False),
])
def test_se_reconoce_el_genero_por_el_nombre(nombre, femenina):
    from cancha.ligas import _parece_femenina

    assert _parece_femenina(nombre) is femenina


# ------------------------------------------------------------- el descubridor

def test_descubrir_encuentra_comprueba_y_guarda(base):
    cliente = _cliente({
        "Liga F": [_entidad(1, "LaLiga", "Spain"),          # el señuelo
                   _entidad(2, "Liga F", "Spain")],          # la buena
        "Frauen Bundesliga": [_entidad(3, "Frauen-Bundesliga", "Germany")],
    })
    resumen = descubrir(cliente, base, ["grandes_f"])
    assert resumen["nuevas"]["Spain Liga F"] == 2, "eligió LaLiga en vez de Liga F"
    assert resumen["nuevas"]["Germany Frauen-Bundesliga"] == 3
    assert resolver(["grandes_f"], base)[2] == "Spain Liga F"


def test_lo_que_no_convence_no_se_guarda(base):
    cliente = _cliente({"Liga F": [_entidad(1, "LaLiga", "Spain")]})
    resumen = descubrir(cliente, base, ["Spain Liga F"])
    assert resumen["encontradas"] == 0
    assert resumen["dudosas"][0]["competicion"] == "Spain Liga F"
    assert not base.ligas_aprendidas()


def test_sin_ningun_candidato_lo_dice_sin_romperse(base):
    resumen = descubrir(_cliente({}), base, ["Spain Liga F"])
    assert resumen["encontradas"] == 0 and resumen["dudosas"]


def test_un_fallo_de_red_en_una_no_para_las_demas(base):
    from cancha.errors import HTTPError

    class Roto(SofascoreClient):
        def search(self, query, page=0):
            if "Liga F" in query:
                raise HTTPError(500, "x", "boom")
            return [_entidad(3, "Frauen-Bundesliga", "Germany")]

    cliente = Roto(Settings(rate_limit=0, retries=0, fallback_base_urls=()),
                   transport=FakeTransport({}), cache=MemoryCache(), sleep=lambda _s: None)
    resumen = descubrir(cliente, base, ["grandes_f"])
    assert resumen["fallos"] and resumen["encontradas"] >= 1


def test_descubrir_no_vuelve_a_buscar_lo_que_ya_sabe(base):
    llamadas = []

    class Contador(SofascoreClient):
        def search(self, query, page=0):
            llamadas.append(query)
            return [_entidad(2, "Liga F", "Spain")]

    cliente = Contador(Settings(rate_limit=0, retries=0, fallback_base_urls=()),
                       transport=FakeTransport({}), cache=MemoryCache(), sleep=lambda _s: None)
    descubrir(cliente, base, ["Spain Liga F"])
    primeras = len(llamadas)
    asegurar(cliente, base, ["Spain Liga F"])
    assert len(llamadas) == primeras, "ha vuelto a buscar algo que ya tenía"


def test_rehacer_vuelve_a_buscarlo_todo(base):
    cliente = _cliente({"Liga F": [_entidad(99, "Liga F", "Spain")]})
    base.guardar_liga(COMPETICIONES["Spain Liga F"], 2)
    descubrir(cliente, base, ["Spain Liga F"], rehacer=True)
    assert resolver(["Spain Liga F"], base) == {99: "Spain Liga F"}


def test_asegurar_no_hace_nada_si_no_falta_nada(base):
    resumen = asegurar(_cliente({}), base, ["grandes"])
    assert resumen["buscadas"] == 0


def test_la_consola_lista_el_catalogo_y_lo_que_falta(tmp_path, capsys):
    from cancha import cli

    ruta = str(tmp_path / "c.db")
    assert cli.main(["ligas", "--db", ruta]) == 0
    salida = capsys.readouterr().out
    assert "competiciones" in salida and "grandes_f" in salida and "Spain Liga F" in salida

    assert cli.main(["ligas", "--faltan", "--db", ruta]) == 0
    assert "Spain Liga F" in capsys.readouterr().out


def test_la_consola_descubre(tmp_path, capsys, inyectar_cliente):
    from cancha import cli

    inyectar_cliente(_cliente({"Liga F": [_entidad(2, "Liga F", "Spain")]}))
    ruta = str(tmp_path / "d.db")
    assert cli.main(["ligas", "--descubrir", "--grupos", "Spain Liga F", "--db", ruta]) == 0
    assert "Spain Liga F → 2" in capsys.readouterr().out
    with Almacen(ruta) as almacen:
        assert resolver(["Spain Liga F"], almacen) == {2: "Spain Liga F"}


def test_el_barrido_descubre_lo_que_falte_antes_de_empezar(tmp_path, cliente, monkeypatch):
    """Sin esto, pedir un grupo nuevo barrería cero partidos sin explicar por qué."""
    from cancha import barrido

    vistos = []
    monkeypatch.setattr(barrido, "asegurar",
                        lambda c, a, g=None, avisar=None: (vistos.append(g) or
                                                           {"encontradas": 0, "buscadas": 0}))
    with Almacen(tmp_path / "b.db") as almacen:
        resumen = barrido.barrer(cliente, almacen, fecha="2024-10-26", grupos=["grandes"])
    assert vistos == [["grandes"]]
    assert resumen["competiciones"] == 5
    assert "competiciones_sin_identificar" in resumen


def test_una_competicion_del_catalogo_esta_bien_formada():
    for competicion in CATALOGO:
        assert isinstance(competicion, Competicion)
        assert competicion.nombre and competicion.grupo and competicion.pais
        assert competicion.genero in ("masculino", "femenino")
        assert competicion.consulta()
        assert competicion.femenina == competicion.grupo.endswith("_f"), competicion.nombre
