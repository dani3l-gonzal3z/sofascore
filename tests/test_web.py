"""La interfaz: el servidor, su API y lo que sirve.

Se levanta el servidor de verdad en un puerto libre, con el cliente de mentira
y una memoria en un fichero temporal, y se le habla por HTTP con
``http.client`` (no con ``urllib``, que el guardián de red de los tests corta).
"""

from __future__ import annotations

import json
import pathlib
import threading
from http.client import HTTPConnection

import pytest
from conftest import EVENT_ID

from cancha.match import build_report
from cancha.sesion import Sesion
from cancha.web.servidor import Servidor, construir, icono_png, ip_local


@pytest.fixture
def servidor(cliente, tmp_path):
    """El servidor en marcha, con un partido guardado en la memoria."""
    sesion = Sesion(cliente=cliente, ruta_almacen=str(tmp_path / "web.db"))
    sesion.almacen.guardar_informe(build_report(cliente, EVENT_ID, sections=["all"]))
    app = Servidor(sesion=sesion, carpeta_briefings=str(tmp_path / "briefings"))
    http = construir(app, "127.0.0.1", 0)
    hilo = threading.Thread(target=lambda: http.serve_forever(poll_interval=0.02), daemon=True)
    hilo.start()
    app.puerto = http.server_address[1]
    try:
        yield app
    finally:
        http.shutdown()
        http.server_close()
        app.close()


def _pedir(app, metodo, ruta, cuerpo=None, cabeceras=None):
    conexion = HTTPConnection("127.0.0.1", app.puerto, timeout=10)
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    cabeceras = {"Content-Type": "application/json", **(cabeceras or {})}
    conexion.request(metodo, ruta, body=datos, headers=cabeceras)
    respuesta = conexion.getresponse()
    crudo = respuesta.read()
    conexion.close()
    tipo = respuesta.getheader("Content-Type") or ""
    return respuesta.status, tipo, (json.loads(crudo) if "json" in tipo else crudo)


# ------------------------------------------------------------------ estáticos

def test_la_pagina_se_sirve_y_es_una_pwa(servidor):
    estado, tipo, cuerpo = _pedir(servidor, "GET", "/")
    assert estado == 200 and tipo.startswith("text/html")
    html = cuerpo.decode("utf-8")
    assert "<title>cancha</title>" in html
    assert 'rel="manifest"' in html and "apple-touch-icon" in html
    assert "serviceWorker" in html


def test_el_manifiesto_y_el_service_worker(servidor):
    estado, tipo, cuerpo = _pedir(servidor, "GET", "/manifest.webmanifest")
    assert estado == 200 and "manifest" in tipo
    manifiesto = cuerpo if isinstance(cuerpo, dict) else json.loads(cuerpo)
    assert manifiesto["display"] == "standalone" and manifiesto["start_url"] == "/"
    estado, tipo, _ = _pedir(servidor, "GET", "/sw.js")
    assert estado == 200 and "javascript" in tipo


@pytest.mark.parametrize("ruta", ["/icono-180.png", "/icono-192.png", "/icono-512.png"])
def test_los_iconos_son_png_de_verdad(servidor, ruta):
    estado, tipo, cuerpo = _pedir(servidor, "GET", ruta)
    assert estado == 200 and tipo == "image/png"
    assert cuerpo[:8] == b"\x89PNG\r\n\x1a\n"


def test_el_icono_se_dibuja_con_el_lado_pedido():
    png = icono_png(32)
    # Ancho y alto en la cabecera IHDR, big-endian.
    assert int.from_bytes(png[16:20], "big") == 32 and int.from_bytes(png[20:24], "big") == 32


def test_no_se_sale_de_la_carpeta_de_estaticos(servidor):
    estado, _, _ = _pedir(servidor, "GET", "/../servidor.py")
    assert estado == 404
    estado, _, _ = _pedir(servidor, "GET", "/no-existe.css")
    assert estado == 404


# ------------------------------------------------------------------------ API

def test_el_estado_dice_que_hay_en_la_memoria(servidor):
    estado, _, datos = _pedir(servidor, "GET", "/api/estado")
    assert estado == 200
    assert datos["memoria"]["partidos"] == 1
    assert "futboldata" in datos["fuentes"] and "scraperfc" in datos["librerias"]
    assert datos["version"] and datos["barrido"]["en_marcha"] is False


def test_las_herramientas_se_listan(servidor):
    estado, _, datos = _pedir(servidor, "GET", "/api/herramientas")
    assert estado == 200
    nombres = {t["name"] for t in datos}
    assert {"resumen_partido", "duelo_jugador_rival", "briefing_del_dia"} <= nombres


def test_una_herramienta_se_ejecuta_por_http(servidor):
    estado, _, datos = _pedir(servidor, "POST", "/api/herramienta/resumen_partido",
                              {"partido": str(EVENT_ID)})
    assert estado == 200
    assert datos["partido"]["home"]["name"] == "Real Madrid"
    estado, _, datos = _pedir(servidor, "POST", "/api/herramienta/estilo_de_equipo",
                              {"equipo": "Real Madrid"})
    assert estado == 200 and datos["disponible"]


def test_una_herramienta_que_no_existe_da_404(servidor):
    estado, _, datos = _pedir(servidor, "POST", "/api/herramienta/inventada", {})
    assert estado == 404 and "disponibles" in datos


def test_un_cuerpo_que_no_es_json_no_tumba_nada(servidor):
    conexion = HTTPConnection("127.0.0.1", servidor.puerto, timeout=10)
    conexion.request("POST", "/api/herramienta/estado_de_la_memoria", body=b"esto no es json",
                     headers={"Content-Type": "application/json"})
    respuesta = conexion.getresponse()
    assert respuesta.status == 200
    assert json.loads(respuesta.read())["partidos"] == 1


def test_una_ruta_desconocida_de_la_api_da_404(servidor):
    assert _pedir(servidor, "GET", "/api/nada")[0] == 404
    assert _pedir(servidor, "POST", "/api/nada", {})[0] == 404


def test_la_sesion_se_comparte_entre_peticiones(servidor):
    peticiones = servidor.sesion.cliente.stats.requests
    _pedir(servidor, "POST", "/api/herramienta/resumen_partido", {"partido": str(EVENT_ID)})
    tras_una = servidor.sesion.cliente.stats.requests
    _pedir(servidor, "POST", "/api/herramienta/resumen_partido", {"partido": str(EVENT_ID)})
    assert servidor.sesion.cliente.stats.requests == tras_una
    assert tras_una >= peticiones


def test_el_briefing_guardado_se_sirve_y_el_que_no_existe_lo_dice(servidor):
    assert _pedir(servidor, "GET", "/api/briefing/2024-10-26")[0] == 404
    estado, _, datos = _pedir(servidor, "POST", "/api/herramienta/briefing_del_dia",
                              {"fecha": "2024-10-26", "grupos": "grandes"})
    assert estado == 200 and datos["total"] == 1


def test_el_barrido_corre_en_segundo_plano(servidor):
    estado, _, datos = _pedir(servidor, "POST", "/api/barrido",
                              {"fecha": "2024-10-26", "grupos": "grandes", "max": 50})
    assert estado == 200 and "error" not in datos
    servidor.esperar_barrido()
    estado, _, datos = _pedir(servidor, "GET", "/api/barrido")
    assert datos["en_marcha"] is False
    assert datos["resumen"]["partidos_del_dia"] == 1
    assert any("partidos el 2024-10-26" in linea for linea in datos["lineas"])


def test_no_se_lanzan_dos_barridos_a_la_vez(servidor):
    servidor.barrido["en_marcha"] = True
    try:
        _, _, datos = _pedir(servidor, "POST", "/api/barrido", {})
        assert "error" in datos
    finally:
        servidor.barrido["en_marcha"] = False


def test_con_clave_la_api_la_exige_y_la_pagina_no(servidor):
    servidor.clave = "secreto"
    try:
        assert _pedir(servidor, "GET", "/api/estado")[0] == 401
        assert _pedir(servidor, "POST", "/api/herramienta/estado_de_la_memoria", {})[0] == 401
        assert _pedir(servidor, "GET", "/api/estado", cabeceras={"X-Clave": "secreto"})[0] == 200
        assert _pedir(servidor, "GET", "/api/estado?clave=secreto")[0] == 200
        assert _pedir(servidor, "GET", "/")[0] == 200
    finally:
        servidor.clave = ""


def test_la_ip_local_es_una_ip():
    partes = ip_local().split(".")
    assert len(partes) == 4 and all(p.isdigit() for p in partes)


def test_el_comando_web_existe_y_tiene_sus_opciones():
    from cancha.cli import build_parser

    args = build_parser().parse_args(["web", "--lan", "--port", "9000", "--clave", "x"])
    assert args.lan and args.port == 9000 and args.clave == "x"


# ------------------------------------------------------- casi seguro y analista

def test_el_estado_lleva_el_catalogo_y_el_modelo(servidor):
    _, _, datos = _pedir(servidor, "GET", "/api/estado")
    catalogo = datos["catalogo"]
    assert catalogo["competiciones"] >= 60 and catalogo["femeninas"] >= 15
    assert "grandes_f" in catalogo["por_grupo"]
    assert datos["modelo"]


def test_casi_seguro_por_http(servidor):
    estado, _, datos = _pedir(servidor, "POST", "/api/seguro", {"calibrar": True})
    assert estado == 200
    assert len(datos["patrones"]) >= 10
    assert "Wilson" in datos["como_leerlo"]

    estado, _, datos = _pedir(servidor, "POST", "/api/seguro", {"fecha": "2024-10-26"})
    assert estado == 200 and "avisos" in datos
    assert "apuesta segura" in datos["lo_que_no_dice"]


def test_el_estado_del_analista_dice_que_falta_ollama(servidor):
    """Sin Ollama detrás, la página tiene que poder explicarlo en vez de colgarse."""
    estado, _, datos = _pedir(servidor, "GET", "/api/analista")
    assert estado == 200
    assert datos["disponible"] is False
    assert "Ollama" in datos["nota"] or "ollama" in datos["nota"]
    assert "langchain" in datos


def test_el_analista_contesta_en_ndjson_paso_a_paso(servidor):
    """El formato que lee la interfaz: una línea por paso, según van pasando."""
    from cancha.analista import Analista

    guion = [
        {"message": {"role": "assistant", "content": "",
                     "tool_calls": [{"function": {"name": "estado_de_la_memoria",
                                                  "arguments": {}}}]}},
        {"message": {"role": "assistant", "content": "Hay un partido guardado."}},
    ]
    servidor._analistas[servidor.modelo] = Analista(
        sesion=servidor.sesion, pedir=lambda ruta, cuerpo=None: guion.pop(0))

    conexion = HTTPConnection("127.0.0.1", servidor.puerto, timeout=15)
    conexion.request("POST", "/api/analista", body=json.dumps({"pregunta": "¿qué hay?"}).encode(),
                     headers={"Content-Type": "application/json"})
    respuesta = conexion.getresponse()
    assert respuesta.status == 200
    assert "ndjson" in (respuesta.getheader("Content-Type") or "")
    lineas = [json.loads(x) for x in respuesta.read().decode().splitlines() if x.strip()]
    conexion.close()

    tipos = [x["paso"]["tipo"] for x in lineas if "paso" in x]
    assert tipos == ["herramienta", "resultado", "respuesta"]
    fin = next(x["fin"] for x in lineas if "fin" in x)
    assert fin["respuesta"] == "Hay un partido guardado."
    assert fin["historial"][0]["role"] == "system"


def test_una_pregunta_vacia_se_rechaza(servidor):
    estado, _, datos = _pedir(servidor, "POST", "/api/analista", {"pregunta": "  "})
    assert estado == 400 and "Falta la pregunta" in datos["error"]


def test_si_ollama_falla_el_error_viaja_por_la_misma_linea(servidor):
    from cancha.analista import Analista, OllamaNoDisponible

    def roto(ruta, cuerpo=None):
        raise OllamaNoDisponible("No hay nadie escuchando.")

    servidor._analistas[servidor.modelo] = Analista(sesion=servidor.sesion, pedir=roto)
    conexion = HTTPConnection("127.0.0.1", servidor.puerto, timeout=15)
    conexion.request("POST", "/api/analista", body=json.dumps({"pregunta": "hola"}).encode(),
                     headers={"Content-Type": "application/json"})
    respuesta = conexion.getresponse()
    lineas = [json.loads(x) for x in respuesta.read().decode().splitlines() if x.strip()]
    conexion.close()
    assert lineas and "escuchando" in lineas[-1]["error"]


def test_la_pagina_trae_las_seis_pestanas_y_el_tema(servidor):
    _, _, cuerpo = _pedir(servidor, "GET", "/")
    html = cuerpo.decode("utf-8")
    for pestana in ("Hoy", "Seguro", "Analista", "Buscar", "Agentes", "Memoria"):
        assert f'"{pestana}"' in html, pestana
    # Los tres estados del tema: claro, oscuro por sistema y oscuro elegido.
    assert "prefers-color-scheme: dark" in html
    assert ':root:not([data-theme="light"])' in html
    assert ':root[data-theme="dark"]' in html
    assert "prefers-reduced-motion" in html


# ------------------------------------------------------- llegar desde el móvil

def test_se_enseñan_todas_las_ip_y_la_primera_es_privada():
    """Con VPN o Docker hay varias IP; enseñar solo una y fallar es lo peor."""
    from cancha.web.servidor import ips_locales

    ips = ips_locales()
    assert ip_local() in ips or ip_local().startswith("127.")
    assert not any(ip.startswith("127.") for ip in ips), "el bucle local no sirve"
    privadas = [i for i, ip in enumerate(ips)
                if ip.startswith(("192.168.", "10.", "172."))]
    if privadas and len(privadas) < len(ips):
        assert max(privadas) < min(set(range(len(ips))) - set(privadas))


def test_al_abrir_a_la_red_se_dibuja_el_qr_con_la_clave_dentro(cliente, tmp_path):
    """Escanear y entrar, sin teclear la clave en el móvil."""
    from cancha.web.qr import matriz
    from cancha.web.servidor import arrancar

    sesion = Sesion(cliente=cliente, ruta_almacen=str(tmp_path / "qr.db"))
    app = Servidor(sesion=sesion, clave="s3creta")
    lineas: list[str] = []

    class Falso:
        server_address = ("0.0.0.0", 8765)

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            pass

    import cancha.web.servidor as servidor_modulo

    antes = servidor_modulo.construir
    servidor_modulo.construir = lambda *a, **k: Falso()
    try:
        arrancar(app, host="0.0.0.0", puerto=8765, avisar=lineas.append)
    finally:
        servidor_modulo.construir = antes

    texto = "\n".join(lineas)
    assert "clave=s3creta" in texto, "la clave tiene que ir en la dirección del QR"
    assert "\x1b[" in texto, "el QR se dibuja con colores fijos"
    assert "pantalla de inicio" in texto
    # Y lo dibujado es un QR de verdad del tamaño que toca para esa dirección.
    url = next(x.strip() for x in lineas
               if x.strip().startswith("http://") and "clave=" in x)
    assert len(matriz(url)) >= 25


def test_sin_qr_se_siguen_dando_las_direcciones(cliente, tmp_path):
    from cancha.web.servidor import arrancar

    sesion = Sesion(cliente=cliente, ruta_almacen=str(tmp_path / "qr2.db"))
    app = Servidor(sesion=sesion)
    lineas: list[str] = []

    class Falso:
        server_address = ("0.0.0.0", 8765)

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            pass

    import cancha.web.servidor as servidor_modulo

    antes = servidor_modulo.construir
    servidor_modulo.construir = lambda *a, **k: Falso()
    try:
        arrancar(app, host="0.0.0.0", puerto=8765, avisar=lineas.append, qr=False)
    finally:
        servidor_modulo.construir = antes

    texto = "\n".join(lineas)
    assert "\x1b[" not in texto
    assert ":8765/" in texto


def test_la_pagina_coge_la_clave_de_la_direccion_y_la_borra(servidor):
    """Es lo que hace que escanear el QR sea un solo gesto."""
    _, _, cuerpo = _pedir(servidor, "GET", "/")
    html = cuerpo.decode("utf-8")
    assert "claveDeLaUrl" in html
    assert 'URLSearchParams(location.search).get("clave")' in html
    assert "history.replaceState" in html, "la clave no se queda en la barra"


# --------------------------------------------- todo, también desde el móvil

#: Las cuatro herramientas que la página no llama por su nombre, y por qué. Si
#: una más se cuela aquí sin razón escrita, el test de abajo lo dice.
POR_OTRO_CAMINO = {
    "puntos_esperados": "viene dentro de analisis_partido, que la vista del partido ya pinta",
    "carrera_xg": "viene dentro de analisis_partido",
    "estado_de_la_memoria": "la página usa /api/estado, que es lo mismo con el barrido dentro",
    "casi_seguro": "la página usa /api/seguro, que además permite calibrar",
    "expediente_partido": "la página usa /api/dictamen, que lo monta y además se "
                          "lo manda al modelo; el documento se enseña entero dentro",
    "briefing_del_dia": "la página usa /api/briefing, que lo lanza en segundo plano "
                        "y deja ver por dónde va: por la herramienta se quedaba "
                        "colgado varios minutos y el navegador se rendía antes",
}


def _pagina() -> str:
    from cancha.web.servidor import ESTATICO

    return (ESTATICO / "index.html").read_text(encoding="utf-8")


def test_todas_las_herramientas_se_pueden_usar_desde_la_pagina():
    """El móvil tiene que llegar a todo, no a la mitad.

    Cada herramienta o tiene su sitio en una vista, o está en la lista de las
    que llegan por otro camino —y esa lista lleva escrito el camino—.
    """
    from cancha.herramientas import esquemas

    html = _pagina()
    sin_sitio = [e["name"] for e in esquemas()
                 if f'"{e["name"]}"' not in html and e["name"] not in POR_OTRO_CAMINO]
    assert not sin_sitio, f"sin manera de usarlas desde la página: {sin_sitio}"
    # Y la lista de excepciones no se queda con nombres que ya no existen.
    nombres = {e["name"] for e in esquemas()}
    assert set(POR_OTRO_CAMINO) <= nombres


def test_la_consola_alcanza_cualquier_herramienta_futura():
    """Las vistas cubren lo de cada día; la consola cubre el resto, y lo que venga."""
    html = _pagina()
    assert "tarjetaConsola" in html
    assert '/api/herramientas' in html, "la lista se pide al servidor, no está escrita a mano"
    assert "input_schema" in html, "los campos se montan desde el esquema de cada herramienta"


def test_la_pagina_llega_a_lo_que_antes_solo_estaba_en_el_terminal(servidor):
    """doctor, cache, el directo, la clasificación y descubrir ligas."""
    html = _pagina()
    for pieza in ("/api/diagnostico", "/api/cache", "/api/ligas", "/api/red",
                  "pintarDirecto", "pintarLiga", "ficha_equipo", "ficha_jugador"):
        assert pieza in html, pieza


def test_el_diagnostico_se_sirve_sin_tocar_la_red(servidor):
    estado, _, cuerpo = _pedir(servidor, "GET", "/api/diagnostico")
    assert estado == 200
    assert [t["nombre"] for t in cuerpo["transportes"]] == ["curl", "httpx", "urllib"]
    assert "credenciales" in cuerpo and "cache" in cuerpo
    assert "api" not in cuerpo, "sin ?red=1 no se pide nada a nadie"


def test_el_qr_de_la_red_sale_del_servidor(servidor):
    servidor.abierto = True
    estado, _, cuerpo = _pedir(servidor, "GET", "/api/red")
    assert estado == 200
    assert cuerpo["abierto_a_la_red"] is True
    if cuerpo["urls"]:
        assert len(cuerpo["qr"]) >= 21
        assert set(cuerpo["qr"][0]) <= {0, 1}


def test_cerrado_a_la_red_el_qr_lo_dice_en_vez_de_enganar(servidor):
    estado, _, cuerpo = _pedir(servidor, "GET", "/api/red")
    assert estado == 200 and cuerpo["abierto_a_la_red"] is False


def test_vaciar_la_cache_desde_la_pagina(servidor):
    estado, _, cuerpo = _pedir(servidor, "POST", "/api/cache", {})
    assert estado == 200 and "borrados" in cuerpo


def test_el_directo_no_se_queda_pidiendo_cuando_te_vas_de_la_vista():
    """Un temporizador que sobrevive a la vista se come la batería del móvil."""
    html = _pagina()
    desde = html.index("async function pintarDirecto")
    hasta = html.index("async function generarBriefing")
    trozo = html[desde:hasta]
    assert trozo.count("location.hash !== mio") >= 1
    assert trozo.count("location.hash === mio") >= 2


# ------------------------------------------------------------------ ajustes

def test_los_ajustes_se_leen_con_el_catalogo_de_ligas(servidor, tmp_path):
    servidor.ruta_ajustes = str(tmp_path / "aj.json")
    estado, _, cuerpo = _pedir(servidor, "GET", "/api/ajustes")
    assert estado == 200
    assert cuerpo["ajustes"]["guardia"]["hora"] == "03:00"
    assert len(cuerpo["competiciones"]) == 71, "para poder elegirlas de una lista"
    assert {"grupo", "competiciones"} <= set(cuerpo["grupos"][0])
    assert cuerpo["problemas"] == []


def test_los_ajustes_se_guardan_desde_la_pagina(servidor, tmp_path):
    ruta = tmp_path / "aj2.json"
    servidor.ruta_ajustes = str(ruta)
    estado, _, cuerpo = _pedir(servidor, "POST", "/api/ajustes", {
        "guardia": {"hora": "02:15", "partidos": 4},
        "ligas": ["grandes", "uefa"], "modelo": "qwen2.5:7b"})
    assert estado == 200 and cuerpo["guardado"] is True
    assert ruta.is_file()

    from cancha.ajustes import cargar

    guardados = cargar(ruta)
    assert guardados["guardia"]["hora"] == "02:15"
    assert guardados["ligas"] == ["grandes", "uefa"]
    assert guardados["modelo"] == "qwen2.5:7b"


def test_unos_ajustes_imposibles_no_se_guardan_y_se_explican(servidor, tmp_path):
    ruta = tmp_path / "aj3.json"
    servidor.ruta_ajustes = str(ruta)
    _, _, cuerpo = _pedir(servidor, "POST", "/api/ajustes",
                          {"guardia": {"hora": "a las tres"}})
    assert cuerpo["guardado"] is False
    assert any("03:00" in p for p in cuerpo["problemas"])
    assert not ruta.is_file(), "no puede quedarse escrito algo que no vale"


def test_se_dice_qué_cambios_necesitan_reiniciar(servidor, tmp_path):
    """La hora se coge al vuelo; el puerto no. Callárselo es el «no me funciona»."""
    servidor.ruta_ajustes = str(tmp_path / "aj4.json")
    _, _, cuerpo = _pedir(servidor, "POST", "/api/ajustes",
                          {"web": {"puerto": 9100}, "guardia": {"hora": "01:00"}})
    assert cuerpo["guardado"] is True
    assert "el puerto" in cuerpo["hace_falta_reiniciar"]
    assert not any("hora" in x for x in cuerpo["hace_falta_reiniciar"])


def test_el_token_del_bot_no_sale_por_la_api(servidor, tmp_path):
    ruta = tmp_path / "aj5.json"
    servidor.ruta_ajustes = str(ruta)
    _pedir(servidor, "POST", "/api/ajustes", {"telegram": {"token": "123:SECRETISIMO"}})
    _, _, cuerpo = _pedir(servidor, "GET", "/api/ajustes")
    assert "SECRETISIMO" not in json.dumps(cuerpo)
    assert cuerpo["ajustes"]["telegram"]["token_puesto"] is True


def test_la_pagina_tiene_el_panel_de_ajustes(servidor):
    html = _pagina()
    assert "tarjetaAjustes" in html
    assert "/api/ajustes" in html
    for pieza in ("a qué hora", "Ligas que sigues", "modelo de ollama",
                  "token del bot de telegram"):
        assert pieza in html, pieza


# ------------------------------------- que un fallo no tumbe la petición

def test_una_herramienta_que_revienta_devuelve_un_error_y_no_una_traza(servidor,
                                                                       monkeypatch):
    """Antes se llevaba por delante el hilo: traza en la consola y el navegador
    esperando a una conexión muerta, sin saber qué había pasado."""
    def revienta(*_a, **_k):
        raise OSError(22, "Invalid argument")

    monkeypatch.setattr(type(servidor), "ejecutar", revienta)
    estado, tipo, cuerpo = _pedir(servidor, "POST", "/api/herramienta/resumen_partido",
                                  {"partido": "1"})
    assert estado == 500
    assert "json" in tipo
    assert "OSError" in cuerpo["error"]
    assert "Invalid argument" in cuerpo["error"]
    assert "resumen_partido" in cuerpo["donde"]


def test_y_el_servidor_sigue_vivo_despues(servidor, monkeypatch):
    """Lo importante no es el mensaje: es que la siguiente petición funcione."""
    def revienta(*_a, **_k):
        raise RuntimeError("se rompió")

    monkeypatch.setattr(type(servidor), "ejecutar", revienta)
    _pedir(servidor, "POST", "/api/herramienta/resumen_partido", {"partido": "1"})
    estado, _, cuerpo = _pedir(servidor, "GET", "/api/estado")
    assert estado == 200 and "memoria" in cuerpo


def test_un_fallo_al_leer_tambien_se_contesta(servidor, monkeypatch):
    def revienta(_self):
        raise ValueError("algo raro")

    monkeypatch.setattr(type(servidor), "estado", revienta)
    estado, _, cuerpo = _pedir(servidor, "GET", "/api/estado")
    assert estado == 500 and "ValueError" in cuerpo["error"]


def test_buscar_los_ids_que_faltan_funciona(servidor):
    """El botón «Buscar los ids que faltan» llamaba a asegurar con el cliente y
    la memoria cambiados de orden, y salía un AttributeError a media página."""
    # Con «grandes» no falta ningún id y no se llega a buscar nada: hace falta
    # un grupo con competiciones sin identificar para recorrer el camino entero.
    estado, _, cuerpo = _pedir(servidor, "POST", "/api/ligas", {"grupos": "europeas"})
    assert estado == 200, cuerpo
    assert "encontradas" in cuerpo
    assert "catalogo" in cuerpo and "competiciones" in cuerpo["catalogo"]


def test_los_ajustes_ofrecen_quien_ha_escrito_al_bot(servidor, tmp_path):
    """Para no tener que copiar el número a mano de Telegram a la interfaz."""
    from cancha.telegrama import NOTA_VISTOS

    servidor.ruta_ajustes = str(tmp_path / "aj_tg.json")
    servidor.sesion.almacen.anotar(
        NOTA_VISTOS, json.dumps([{"chat": 4242, "quien": "Dani G"}]))
    _, _, cuerpo = _pedir(servidor, "GET", "/api/ajustes")
    assert cuerpo["telegram_vistos"] == [{"chat": 4242, "quien": "Dani G"}]


def test_la_pagina_explica_como_conseguir_el_id_de_chat(servidor):
    html = _pagina()
    assert "telegram_vistos" in html
    assert "¿Me ha escrito ya?" in html, "hay que poder mirarlo sin recargar"
    assert "identificador de chat" in html


def test_la_pagina_no_manda_reiniciar_para_el_bot(servidor):
    """Decía «guarda el token y reinicia cancha», y ya no hace falta.

    Aquello mandaba a reiniciar el programa para algo que ahora se coge al
    vuelo, y peor: si no reiniciabas, escribirle al bot no hacía nada.
    """
    html = _pagina()
    assert "guarda el token aquí, reinicia cancha" not in html
    assert "el bot se cogen al arrancar" not in html
    assert "el bot mira los ajustes" in html
    assert "no hace falta reiniciar" in html


def test_la_pagina_dice_si_el_bot_esta_escuchando(servidor):
    html = _pagina()
    assert "telegram_estado" in html
    assert "El bot está escuchando" in html
    assert "esperando un token" in html


def test_el_estado_del_bot_sale_en_los_ajustes(servidor, tmp_path):
    """Sin bot es None, y con bot es lo que diga él: se mira desde el móvil."""
    servidor.ruta_ajustes = str(tmp_path / "aj_estado.json")
    _, _, cuerpo = _pedir(servidor, "GET", "/api/ajustes")
    assert cuerpo["telegram_estado"] is None

    class BotDeMentira:
        def estado(self):
            return {"token_puesto": True, "escuchando": True,
                    "permitidos": [42], "ultimo_error": ""}

    servidor.bot = BotDeMentira()
    _, _, cuerpo = _pedir(servidor, "GET", "/api/ajustes")
    assert cuerpo["telegram_estado"]["escuchando"] is True


def test_el_token_del_bot_ya_no_pide_reiniciar(servidor, tmp_path):
    """Lo coge el bot solo, y decir lo contrario hacía reiniciar sin motivo."""
    servidor.ruta_ajustes = str(tmp_path / "aj_frio.json")
    _, _, cuerpo = _pedir(servidor, "POST", "/api/ajustes",
                          {"telegram": {"token": "123:ABC", "chats": [42]}})
    assert cuerpo["guardado"] is True
    assert cuerpo["hace_falta_reiniciar"] == []
    _, _, cuerpo = _pedir(servidor, "POST", "/api/ajustes", {"web": {"puerto": 9191}})
    assert cuerpo["hace_falta_reiniciar"] == ["el puerto"], "el puerto sí"


def test_la_clave_de_la_nube_no_sale_por_la_api(servidor, tmp_path):
    """Como el token del bot: se escribe, pero no se devuelve."""
    ruta = tmp_path / "aj_nube.json"
    servidor.ruta_ajustes = str(ruta)
    _pedir(servidor, "POST", "/api/ajustes", {"ollama_api_key": "s3cr3ta-de-verdad"})
    _, _, cuerpo = _pedir(servidor, "GET", "/api/ajustes")
    assert "s3cr3ta-de-verdad" not in json.dumps(cuerpo)
    assert cuerpo["ajustes"]["ollama_api_key_puesto"] is True

    from cancha.ajustes import cargar

    assert cargar(ruta)["ollama_api_key"] == "s3cr3ta-de-verdad", "sí se guarda"


def test_guardar_los_ajustes_no_borra_la_clave_de_la_nube(servidor, tmp_path):
    ruta = tmp_path / "aj_nube2.json"
    servidor.ruta_ajustes = str(ruta)
    _pedir(servidor, "POST", "/api/ajustes", {"ollama_api_key": "la-buena"})
    # El campo se enseña vacío aunque haya una guardada: vacío = no la toques.
    _pedir(servidor, "POST", "/api/ajustes",
           {"ollama_api_key": "", "guardia": {"hora": "04:00"}})

    from cancha.ajustes import cargar

    assert cargar(ruta)["ollama_api_key"] == "la-buena"


def test_una_clave_pegada_encima_de_la_mascara_se_dice_en_la_pantalla(servidor, tmp_path):
    """Y no se traga en silencio, que es lo que hacía."""
    ruta = tmp_path / "aj_nube3.json"
    servidor.ruta_ajustes = str(ruta)
    _pedir(servidor, "POST", "/api/ajustes", {"ollama_api_key": "la-buena"})
    _, _, cuerpo = _pedir(servidor, "POST", "/api/ajustes",
                          {"ollama_api_key": "••••••••ueneask-nueva"})
    assert cuerpo["guardado"] is False
    assert any("puntos" in x for x in cuerpo["problemas"])

    from cancha.ajustes import cargar

    assert cargar(ruta)["ollama_api_key"] == "la-buena", "no se ha tocado"


def test_la_pagina_no_devuelve_la_clave_ni_tapada_en_el_campo(servidor):
    """Rellenar el campo con la máscara era la causa del fallo."""
    html = _pagina()
    assert 'value: a.ollama_api_key' not in html
    assert "escribe otra para cambiarla" in html
    assert "Probar la clave" in html


def test_se_puede_probar_la_clave_sin_abrir_un_partido(servidor, tmp_path):
    """El 401 se descubría en mitad de un dictamen, y ahí no se sabe qué falla."""
    servidor.ruta_ajustes = str(tmp_path / "aj_probar.json")
    _, _, cuerpo = _pedir(servidor, "POST", "/api/nube", {})
    assert cuerpo["vale"] is False
    assert "ninguna clave" in cuerpo["nota"]


def test_el_dictamen_monta_el_expediente_y_lo_manda(servidor, monkeypatch):
    from cancha.analista import Analista

    monkeypatch.setattr(Analista, "dictaminar",
                        lambda self, doc, preg="": {"respuesta": "Lo veo claro.",
                                                    "modelo": self.modelo,
                                                    "en_la_nube": False,
                                                    "recibido": len(doc)})
    estado, _, cuerpo = _pedir(servidor, "POST", "/api/dictamen",
                               {"partido": str(EVENT_ID)})
    assert estado == 200, cuerpo
    assert cuerpo["respuesta"] == "Lo veo claro."
    assert cuerpo["expediente"]["texto"].startswith("EXPEDIENTE DE PARTIDO")
    assert cuerpo["expediente"]["tokens_aprox"] > 0
    assert cuerpo["recibido"] == len(cuerpo["expediente"]["texto"])


def test_el_dictamen_sin_partido_lo_dice(servidor):
    _, _, cuerpo = _pedir(servidor, "POST", "/api/dictamen", {})
    assert "Falta el partido" in cuerpo["error"]


def test_la_pagina_avisa_de_que_la_nube_saca_los_datos_de_tu_ordenador(servidor):
    html = _pagina()
    assert "clave de la nube de ollama" in html
    assert "SALE de tu ordenador" in html
    assert "tarjetaDictamen" in html


# ------------------------------------------------------------- certificados

def test_la_ruta_de_tls_dice_si_alguien_abre_el_https(servidor):
    """Para poder mirarlo desde el móvil, que es donde se mira cuando falla."""
    _, _, cuerpo = _pedir(servidor, "GET", "/api/tls?host=localhost")
    assert "lectura" in cuerpo, "con qué certificados se habla"
    assert "interceptado" in cuerpo


def test_el_diagnostico_lleva_el_estado_de_los_certificados(servidor):
    _, _, cuerpo = _pedir(servidor, "GET", "/api/diagnostico")
    assert cuerpo["tls"]["lectura"]
    assert "sin_verificar" in cuerpo["tls"]


def test_la_pagina_deja_mirar_quien_abre_el_https(servidor):
    html = _pagina()
    assert "/api/tls" in html
    assert "¿Alguien abre mi HTTPS?" in html
    assert "fichero de certificados" in html, "y se puede arreglar desde ahí"


def test_los_certificados_se_guardan_desde_la_pagina(servidor, tmp_path):
    ruta = tmp_path / "aj_tls.json"
    servidor.ruta_ajustes = str(ruta)
    pem = tmp_path / "bueno.pem"
    pem.write_text("-----BEGIN CERTIFICATE-----\n")
    _, _, cuerpo = _pedir(servidor, "POST", "/api/ajustes",
                          {"red": {"ca_bundle": str(pem), "sin_verificar": False}})
    assert cuerpo["guardado"] is True, cuerpo
    assert cuerpo["hace_falta_reiniciar"] == [], "el cliente los coge al construirse"
    _, _, cuerpo = _pedir(servidor, "GET", "/api/ajustes")
    assert cuerpo["ajustes"]["red"]["ca_bundle"] == str(pem)


def test_un_fichero_de_certificados_que_no_esta_no_se_guarda(servidor, tmp_path):
    servidor.ruta_ajustes = str(tmp_path / "aj_tls2.json")
    _, _, cuerpo = _pedir(servidor, "POST", "/api/ajustes",
                          {"red": {"ca_bundle": "/no/existe.pem"}})
    assert cuerpo["guardado"] is False
    assert any("no está" in x for x in cuerpo["problemas"])


# ----------------------------------------------- el dictamen no se pierde

def test_el_dictamen_se_guarda_y_se_puede_volver_a_leer(servidor, monkeypatch):
    """Cuesta dinero y tiempo: mañana tiene que seguir ahí."""
    from cancha.analista import Analista

    monkeypatch.setattr(Analista, "dictaminar",
                        lambda self, doc, pregunta="", instrucciones=None: {
                            "respuesta": "Lo veo claro.", "modelo": "grande",
                            "en_la_nube": True, "tokens": {"prompt_eval_count": 900,
                                                           "eval_count": 80}})
    estado, _, cuerpo = _pedir(servidor, "POST", "/api/dictamen",
                               {"partido": str(EVENT_ID)})
    assert estado == 200, cuerpo
    assert cuerpo["guardado"] is True
    assert cuerpo["partido_id"] == EVENT_ID

    # Y al volver, sin pedirle nada a ningún modelo.
    _, _, guardados = _pedir(servidor, "POST", "/api/dictamenes",
                             {"partido": str(EVENT_ID)})
    assert guardados["cuantos"] == 1
    primero = guardados["dictamenes"][0]
    assert primero["respuesta"] == "Lo veo claro."
    assert primero["modelo"] == "grande"
    assert primero["hecho_el"]
    assert "expediente" not in primero, "no se arrastra el documento entero sin pedirlo"

    _, _, con_todo = _pedir(servidor, "POST", "/api/dictamenes",
                            {"partido": str(EVENT_ID), "con_expediente": True})
    assert "EXPEDIENTE DE PARTIDO" in con_todo["dictamenes"][0]["expediente"]


def test_pedir_otro_dictamen_no_borra_el_anterior(servidor, monkeypatch):
    from cancha.analista import Analista

    respuestas = iter(["Primero", "Segundo"])
    monkeypatch.setattr(Analista, "dictaminar",
                        lambda self, doc, pregunta="", instrucciones=None: {
                            "respuesta": next(respuestas), "modelo": "grande"})
    _pedir(servidor, "POST", "/api/dictamen", {"partido": str(EVENT_ID)})
    _pedir(servidor, "POST", "/api/dictamen", {"partido": str(EVENT_ID)})
    _, _, guardados = _pedir(servidor, "POST", "/api/dictamenes",
                             {"partido": str(EVENT_ID)})
    assert [d["respuesta"] for d in guardados["dictamenes"]] == ["Segundo", "Primero"]


def test_la_pagina_lee_los_dictamenes_guardados(servidor):
    html = _pagina()
    assert "/api/dictamenes" in html
    assert "mañana seguirá aquí" in html
    assert "con todas las estadísticas" in html, "y se puede elegir cuánto crudo"


# ------------------------------------------------------------------ agentes

def test_los_agentes_se_listan_con_las_herramientas_que_puede_elegir(servidor):
    _, _, cuerpo = _pedir(servidor, "POST", "/api/agentes", {})
    datos = cuerpo
    assert datos["agentes"], "la primera vez salen los de ejemplo"
    assert all("huella" in a and "problemas" in a for a in datos["agentes"])
    assert len(datos["herramientas"]) > 20, "hay que poder elegir a qué llega"


def test_una_definicion_mala_no_se_escribe_y_se_dice_por_que(servidor, tmp_path,
                                                             monkeypatch):
    monkeypatch.setenv("CANCHA_AGENTES", str(tmp_path / "ag.json"))
    _, _, cuerpo = _pedir(servidor, "POST", "/api/agente",
                          {"clave": "El Mío", "agente": {"instrucciones": "x"}})
    datos = cuerpo
    assert datos["guardado"] is False
    assert any("nombre corto" in p for p in datos["problemas"])
    assert not (tmp_path / "ag.json").exists(), "no se escribe nada"


def test_un_agente_se_guarda_y_se_vuelve_a_leer(servidor, tmp_path, monkeypatch):
    monkeypatch.setenv("CANCHA_AGENTES", str(tmp_path / "ag.json"))
    _, _, cuerpo = _pedir(servidor, "POST", "/api/agente", {
        "clave": "el-mio", "agente": {"nombre": "El mío", "crudo": "todo",
                                      "instrucciones": "Mira las faltas primero.",
                                      "herramientas": ["casi_seguro"]}})
    assert cuerpo["guardado"] is True
    _, _, cuerpo = _pedir(servidor, "POST", "/api/agentes", {})
    mio = [a for a in cuerpo["agentes"] if a["clave"] == "el-mio"][0]
    assert mio["crudo"] == "todo"
    assert mio["herramientas"] == ["casi_seguro"]
    assert mio["problemas"] == []


def test_borrar_un_agente_que_no_existe_se_dice(servidor):
    _, _, cuerpo = _pedir(servidor, "POST", "/api/agente/borrar", {"clave": "el-nadie"})
    assert "No tengo" in cuerpo["error"]


def test_correr_un_agente_que_no_existe_no_gasta_nada(servidor):
    _, _, cuerpo = _pedir(servidor, "POST", "/api/agente/correr",
                          {"clave": "el-nadie", "partido": "Girona vs Osasuna"})
    assert "No tengo" in cuerpo["error"]


def test_la_clasificacion_contesta_aunque_no_haya_nadie(servidor):
    _, _, cuerpo = _pedir(servidor, "POST", "/api/clasificacion", {})
    datos = cuerpo
    assert datos["clasificacion"] == []
    assert datos["minimo"] > 0
    assert any("CLASIFICACIÓN" in linea for linea in datos["lineas"])


# ------------------------------------------------------- la palabra «null»

def test_nadie_mete_hijos_en_el_dom_sin_filtrar_los_nulos():
    """`replaceChildren` convierte un null en la palabra «null» en la pantalla.

    Salió así: en la tarjeta «memoria de este partido» aparecía un `null` suelto
    entre las cifras y la nota, porque un `x ? algo : null` y un `nota("")` —que
    devuelve null cuando no hay nada que decir— llegaban tal cual. `el()` y
    `poner()` los filtran; llamar a `replaceChildren` a pelo, no.

    Esta prueba es un cepo: mientras todo pase por `poner`, no puede volver.
    """
    import re

    pagina = (pathlib.Path("cancha/web/estatico/index.html")
              .read_text(encoding="utf-8"))
    sueltas = [linea.strip() for linea in pagina.splitlines()
               if ".replaceChildren(" in linea
               # El de dentro del propio `poner`, que es quien filtra.
               and "nodo.replaceChildren(...hijos" not in linea
               # Vaciar un nodo no pasa hijos, así que no hay null que colar.
               and not re.search(r"\.replaceChildren\(\s*\)", linea)
               # Y los comentarios, que hablan de esto precisamente.
               and not linea.strip().startswith(("/*", "*", "//"))]
    assert sueltas == [], (
        "Estas llamadas meten hijos en el DOM sin filtrar los nulos; usa "
        "`poner(nodo, ...)`:\n  " + "\n  ".join(sueltas))


def test_poner_es_el_unico_que_toca_replacechildren_con_hijos():
    """Y que `poner` siga filtrando, que es lo único que sostiene lo de arriba."""
    pagina = (pathlib.Path("cancha/web/estatico/index.html")
              .read_text(encoding="utf-8"))
    cuerpo = pagina[pagina.index("function poner("):]
    cuerpo = cuerpo[:cuerpo.index("\n}")]
    assert "filter" in cuerpo and "null" in cuerpo and "undefined" in cuerpo


# ------------------------------------------------------- trabajos largos

def test_el_briefing_se_lanza_y_contesta_al_momento(servidor, monkeypatch):
    """Antes iba dentro de la petición y por eso «no funcionaba muy bien».

    Un día normal son doscientos y pico partidos, y de cada uno se monta la
    previa entera, la evolución de los dos equipos y los duelos de sus jugadores.
    Son miles de peticiones: el navegador se rendía mucho antes de que acabara.
    """
    import cancha.briefing as modulo

    # Se sujeta el briefing a mitad: si la petición esperase a que acabe, esto
    # se quedaría colgado, que es exactamente el fallo que se está arreglando.
    suelta = threading.Event()

    def lento(*a, **k):
        suelta.wait(5)
        return {"fecha": "2026-09-21", "total": 3, "partidos": [], "completo": True}

    monkeypatch.setattr(modulo, "briefing", lento)
    monkeypatch.setattr(modulo, "guardar", lambda *a, **k: {})
    try:
        estado, _, cuerpo = _pedir(servidor, "POST", "/api/briefing",
                                   {"fecha": "2026-09-21"})
        assert estado == 200
        assert cuerpo["en_marcha"] is True, "contesta ya, no cuando acabe"
    finally:
        suelta.set()
    servidor.esperar_tarea("briefing", 10)

    _, _, cuerpo = _pedir(servidor, "GET", "/api/tarea/briefing")
    assert cuerpo["en_marcha"] is False
    assert cuerpo["resumen"]["partidos"] == 3


def test_dos_briefings_a_la_vez_no(servidor, monkeypatch):
    """Lanzarlo dos veces duplicaría las peticiones sin traer nada nuevo."""
    import cancha.briefing as modulo

    suelta = threading.Event()
    monkeypatch.setattr(modulo, "briefing",
                        lambda *a, **k: (suelta.wait(5), {"fecha": "x", "total": 0,
                                                          "partidos": []})[1])
    monkeypatch.setattr(modulo, "guardar", lambda *a, **k: {})
    try:
        _pedir(servidor, "POST", "/api/briefing", {"fecha": "2026-09-21"})
        _, _, segundo = _pedir(servidor, "POST", "/api/briefing",
                               {"fecha": "2026-09-21"})
        assert "Ya hay" in segundo["error"]
    finally:
        suelta.set()
        servidor.esperar_tarea("briefing", 10)


def test_un_trabajo_se_puede_parar(servidor, monkeypatch):
    """Parar no mata el hilo: levanta una bandera que el trabajo mira.

    Matarlo a mitad dejaría la memoria escrita a medias.
    """
    import cancha.briefing as modulo

    visto = {}

    def lento(*a, **k):
        visto["podia_seguir"] = k["puede_seguir"]()
        return {"fecha": "x", "total": 0, "partidos": [], "completo": False}

    monkeypatch.setattr(modulo, "briefing", lento)
    monkeypatch.setattr(modulo, "guardar", lambda *a, **k: {})
    _pedir(servidor, "POST", "/api/briefing", {"fecha": "2026-09-21"})
    servidor.esperar_tarea("briefing", 10)
    assert visto["podia_seguir"] is True, "mientras nadie lo pare, puede seguir"

    _, _, cuerpo = _pedir(servidor, "POST", "/api/tarea/parar",
                          {"nombre": "briefing"})
    assert "No hay" in cuerpo["error"], "y parar lo que ya acabó se dice"


def test_el_plan_de_la_historia_no_trae_nada(servidor, monkeypatch):
    """Descubrir a mitad que son veinte mil peticiones es descubrirlo tarde."""
    import cancha.historia as modulo

    monkeypatch.setattr(modulo, "plan", lambda *a, **k: {
        "ligas": 2, "temporadas": 6, "partidos_estimados": 1800,
        "peticiones_estimadas": 9000, "por_liga": [], "aviso": "es una estimación"})
    _, _, cuerpo = _pedir(servidor, "POST", "/api/historia/plan",
                          {"anos": 3, "secciones": ["statistics"]})
    assert cuerpo["peticiones_estimadas"] == 9000


def test_el_estado_dice_que_secciones_se_pueden_pedir(servidor):
    """Elegir qué datos traer sin saber qué hace cada uno es elegir a ciegas."""
    _, _, cuerpo = _pedir(servidor, "GET", "/api/estado")
    nombres = {s["nombre"] for s in cuerpo["secciones"]}
    assert {"statistics", "lineups", "shotmap", "incidents"} <= nombres
    assert all(s["que"] for s in cuerpo["secciones"]), "cada una dice qué trae"
    # Y las que necesitan un jugador o un equipo no salen: no se piden por partido.
    assert "player_statistics" not in nombres
    assert cuerpo["ajustes"]["historia"]["anos"] >= 1


def test_preguntar_por_un_trabajo_que_nunca_ha_corrido_no_revienta(servidor):
    _, _, cuerpo = _pedir(servidor, "GET", "/api/tarea/loquesea")
    assert cuerpo["nunca"] is True
    assert cuerpo["en_marcha"] is False
