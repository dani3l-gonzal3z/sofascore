"""Caché en disco, limitador de peticiones y credenciales."""

import json
import time

from sofascore.auth import Credentials, _cookies_desde_fichero
from sofascore.cache import DiskCache, MemoryCache, NullCache, build_cache
from sofascore.config import Settings
from sofascore.ratelimit import RateLimiter


def test_cache_en_disco_guarda_y_recupera(tmp_path):
    cache = DiskCache(tmp_path)
    cache.set("clave", {"a": 1})
    assert cache.get("clave", ttl=60) == {"a": 1}
    assert cache.get("otra", ttl=60) is None


def test_cache_en_disco_respeta_el_ttl(tmp_path):
    cache = DiskCache(tmp_path)
    cache.set("clave", {"a": 1})
    time.sleep(0.01)
    assert cache.get("clave", ttl=0) is None
    assert cache.get("clave", ttl=-1) is None


def test_cache_en_disco_sobrevive_a_ficheros_corruptos(tmp_path):
    cache = DiskCache(tmp_path)
    cache.set("clave", {"a": 1})
    fichero = next(tmp_path.rglob("*.json"))
    fichero.write_text("esto no es json")
    assert cache.get("clave", ttl=60) is None


def test_vaciar_la_cache(tmp_path):
    cache = DiskCache(tmp_path)
    for i in range(3):
        cache.set(f"clave{i}", i)
    assert cache.clear() == 3
    assert cache.get("clave0", ttl=60) is None


def test_build_cache_elige_segun_ttl(tmp_path):
    assert isinstance(build_cache(tmp_path, 0), NullCache)
    assert isinstance(build_cache(tmp_path, 60), DiskCache)


def test_cache_nula_no_guarda():
    cache = NullCache()
    cache.set("a", 1)
    assert cache.get("a", 60) is None


def test_memoria_respeta_ttl():
    cache = MemoryCache()
    cache.set("a", 1)
    assert cache.get("a", 60) == 1
    assert cache.get("a", 0) is None


def test_el_limitador_espacia_las_peticiones():
    esperas, reloj = [], {"t": 0.0}

    def dormir(segundos):
        esperas.append(segundos)
        reloj["t"] += segundos

    limitador = RateLimiter(rate=2, sleep=dormir, clock=lambda: reloj["t"])
    limitador.wait()
    limitador.wait()
    assert esperas and abs(esperas[-1] - 0.5) < 1e-6


def test_el_limitador_desactivado_no_espera():
    limitador = RateLimiter(rate=0)
    assert limitador.wait() == 0.0


def test_credenciales_desde_cookie_y_token():
    credenciales = Credentials.from_settings(Settings(plus_cookie="a=1", plus_token="tok"))
    cabeceras = credenciales.headers()
    assert cabeceras["Cookie"] == "a=1"
    assert cabeceras["Authorization"] == "Bearer tok"
    assert credenciales.present


def test_token_que_ya_trae_bearer():
    assert Credentials(token="Bearer xyz").headers()["Authorization"] == "Bearer xyz"


def test_sin_credenciales_no_hay_cabeceras():
    credenciales = Credentials()
    assert credenciales.headers() == {}
    assert not credenciales.present
    assert "sin credenciales" in credenciales.describe()


def test_cookies_desde_fichero_lista(tmp_path):
    fichero = tmp_path / "cookies.json"
    fichero.write_text(json.dumps([{"name": "a", "value": "1"}, {"name": "b", "value": "2"}]))
    assert _cookies_desde_fichero(fichero) == "a=1; b=2"


def test_cookies_desde_fichero_diccionario(tmp_path):
    fichero = tmp_path / "cookies.json"
    fichero.write_text(json.dumps({"a": "1"}))
    credenciales = Credentials.from_settings(Settings(plus_cookie_file=str(fichero)))
    assert credenciales.cookie == "a=1"


def test_describe_no_filtra_la_cookie():
    credenciales = Credentials(cookie="sesion=supersecreta")
    assert "supersecreta" not in credenciales.describe()
