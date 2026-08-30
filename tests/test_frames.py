"""Las tablas del informe y los ayudantes del propio informe."""

from __future__ import annotations

import pytest
from conftest import EVENT_ID, rutas_por_defecto

from cancha.cache import MemoryCache
from cancha.client import SofascoreClient
from cancha.config import Settings
from cancha.frames import flatten, to_tables
from cancha.match import build_report
from cancha.transport import FakeTransport


@pytest.fixture
def informe(tmp_path):
    cliente = SofascoreClient(
        Settings(cache_dir=tmp_path / "c", rate_limit=0, retries=0),
        transport=FakeTransport(rutas_por_defecto()),
        cache=MemoryCache(),
        sleep=lambda _s: None,
    )
    return build_report(cliente, EVENT_ID, sections=["all"], include_plus=False)


def test_tablas_del_partido(informe):
    tablas = to_tables(informe)
    assert "partido" in tablas
    assert len(tablas["partido"]) == 1
    assert tablas["partido"][0]["local_name"] == "Real Madrid"
    assert tablas["estadisticas"]
    assert tablas["incidencias"]
    assert tablas["alineaciones"]


def test_las_tablas_vacias_no_aparecen(informe):
    tablas = to_tables(informe)
    assert all(filas for filas in tablas.values())
    # Sin posiciones medias en las respuestas de ejemplo, esa tabla no sale.
    assert "posiciones_medias" not in tablas


def test_incluir_vacias_las_devuelve_igual(informe):
    tablas = to_tables(informe, incluir_vacias=True)
    assert "posiciones_medias" in tablas and tablas["posiciones_medias"] == []


def test_metodo_tables_del_informe(informe):
    assert informe.tables()["estadisticas"] == to_tables(informe)["estadisticas"]


def test_aplanar_json_anidado():
    plano = flatten({"player": {"name": "Vini", "stats": {"goals": 2}}, "tags": ["a", "b"]})
    assert plano == {
        "player.name": "Vini",
        "player.stats.goals": 2,
        "tags.0": "a",
        "tags.1": "b",
    }


def test_aplanar_un_valor_suelto():
    assert flatten(7, "rating") == {"rating": 7}
    assert flatten(7) == {}


def test_frames_devuelve_dataframes(informe):
    pd = pytest.importorskip("pandas")
    frames = informe.frames()
    assert isinstance(frames["estadisticas"], pd.DataFrame)
    assert len(frames["estadisticas"]) == len(to_tables(informe)["estadisticas"])
    assert list(frames["partido"].index) == [0]


def test_frames_avisa_bien_si_no_hay_pandas(informe, monkeypatch):
    import builtins

    importar = builtins.__import__

    def sin_pandas(nombre, *args, **kwargs):
        if nombre == "pandas":
            raise ImportError("no está")
        return importar(nombre, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", sin_pandas)
    with pytest.raises(ImportError, match="pandas"):
        informe.frames()


# ------------------------------------------------- ayudantes del propio informe

def test_incidencias_por_tipo(informe):
    assert informe.goals()
    assert all(i["incidentType"] == "goal" for i in informe.goals())
    assert informe.incidents("card") == informe.cards()


def test_las_incidencias_salen_en_orden(informe):
    minutos = [i.get("time", 0) for i in informe.incidents()]
    assert minutos == sorted(minutos)


def test_valoraciones_de_mayor_a_menor(informe):
    notas = [f["rating"] for f in informe.ratings()]
    assert notas == sorted(notas, reverse=True)


def test_claves_de_estadistica_disponibles(informe):
    claves = informe.statistic_keys()
    assert "ballPossession" in claves
    assert claves == sorted(set(claves))


def test_sugerencia_cuando_te_equivocas_al_escribir(informe):
    assert informe.statistic("ballPosession") is None
    assert "ballPossession" in informe.suggest("ballPosession")


def test_sugerencia_cae_al_catalogo_general(informe):
    # 'expectedGoals' no está en este partido, pero sí en el catálogo.
    assert "expectedGoals" in informe.suggest("expectedGoal")


def test_tabla_plana_de_estadisticas(informe):
    filas = informe.statistics_table()
    assert filas and {"periodo", "grupo", "clave", "local", "visitante"} <= set(filas[0])
