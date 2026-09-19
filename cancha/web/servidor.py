"""El servidor de la interfaz: una API JSON sobre las herramientas, y estáticos.

Todo cuelga de :mod:`cancha.herramientas`: ``POST /api/herramienta/<nombre>``
ejecuta una con los argumentos del cuerpo, con la misma sesión para toda la
vida del servidor (lo ya traído no se vuelve a pedir). Encima hay cuatro
rutas de conveniencia —estado, briefings, el barrido en segundo plano— y los
ficheros de la página.

Es un servidor para **una persona en su red**: un hilo por petición, las
herramientas en serie (la memoria es SQLite y no le gustan los hilos) y una
clave opcional para cuando se abre a la wifi.
"""

from __future__ import annotations

import json
import socket
import struct
import threading
import zlib
from contextlib import suppress
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from .. import __version__
from ..sesion import Sesion
from .qr import dibujar as dibujar_qr

ESTATICO = Path(__file__).parent / "estatico"
TIPOS = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".webmanifest": "application/manifest+json",
         ".svg": "image/svg+xml", ".png": "image/png", ".json": "application/json"}
#: La página puede con mucho más que el contexto de un modelo.
MAX_CHARS_WEB = 2_000_000


class Servidor:
    """Lo que comparten las peticiones: la sesión, el barrido y la clave."""

    def __init__(self, sesion: Sesion | None = None, ruta_almacen: str = "datos/cancha.db",
                 clave: str = "", carpeta_briefings: str = "datos/briefings",
                 modelo: str = "", ollama: str = "") -> None:
        from ..analista import MODELO_POR_DEFECTO, URL_OLLAMA

        self.sesion = sesion or Sesion(ruta_almacen=ruta_almacen)
        self.clave = clave
        self.carpeta_briefings = carpeta_briefings
        self.modelo = modelo or MODELO_POR_DEFECTO
        self.ollama = ollama or URL_OLLAMA
        self._analistas: dict[str, Any] = {}
        #: Los rellena ``arrancar``; la página los usa para el QR de la wifi.
        self.puerto = 8765
        self.abierto = False
        self.cerrojo = threading.Lock()
        self.barrido = {"en_marcha": False, "lineas": [], "resumen": None,
                        "empezado": None, "terminado": None}
        self._hilo_barrido: threading.Thread | None = None

    # --- herramientas ---

    def ejecutar(self, nombre: str, argumentos: dict) -> Any:
        from ..herramientas import ejecutar

        with self.cerrojo:
            return ejecutar(nombre, argumentos, sesion=self.sesion, max_chars=MAX_CHARS_WEB)

    def esquemas(self) -> list[dict]:
        from ..herramientas import esquemas

        return esquemas()

    def estado(self) -> dict:
        from ..briefing import guardados
        from ..ligas import resumen_catalogo
        from ..sources import FUENTES, disponibles

        with self.cerrojo:
            memoria = self.sesion.almacen.resumen()
        return {
            "version": __version__,
            "memoria": memoria,
            "briefings": guardados(self.carpeta_briefings)[:30],
            "fuentes": sorted(FUENTES),
            "librerias": disponibles(),
            "barrido": self.estado_barrido(),
            "catalogo": resumen_catalogo(self.sesion.almacen),
            "modelo": self.modelo,
            "hora": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    # --- analista ---

    def analista(self, modelo: str | None = None):
        """El analista, uno por modelo, reaprovechando la sesión del servidor."""
        from ..analista import Analista

        clave = modelo or self.modelo
        if clave not in self._analistas:
            self._analistas[clave] = Analista(sesion=self.sesion, modelo=clave,
                                              url=self.ollama)
        return self._analistas[clave]

    def estado_analista(self, modelo: str | None = None) -> dict:
        """Si Ollama está y con qué modelos, sin que su ausencia tumbe la página.

        Se atrapa cualquier fallo y no solo el tipado: aquí se está preguntando
        por algo que puede no existir, y la página tiene que poder explicarlo.
        """
        from ..agentes.langchain import disponible as langchain_disponible

        try:
            estado = self.analista(modelo).comprobar()
        except Exception as exc:  # noqa: BLE001 - se enseña, no se esconde
            estado = {"disponible": False, "nota": f"Ollama no contesta: {exc}",
                      "como": "Instala Ollama (ollama.com), arráncalo y trae un modelo:\n"
                              "    ollama pull hermes3"}
        estado["langchain"] = langchain_disponible()
        estado.setdefault("modelo", modelo or self.modelo)
        return estado

    def preguntar(self, pregunta: str, historial=None, modelo=None, al_paso=None) -> dict:
        with self.cerrojo:
            return self.analista(modelo).preguntar(pregunta, historial=historial,
                                                   al_paso=al_paso)

    # --- casi seguro ---

    def seguro(self, fecha: str | None = None, grupos=None, calibrar: bool = False,
               umbral: float = 0.65) -> dict:
        from ..seguro import avisos
        from ..seguro import calibrar as calibrar_patrones

        with self.cerrojo:
            if calibrar:
                return calibrar_patrones(self.sesion.almacen)
            return avisos(self.sesion.almacen, self.sesion.cliente, fecha=fecha,
                          grupos=grupos, umbral=umbral)

    # --- diagnóstico y mantenimiento ---

    def diagnostico(self, con_red: bool = False) -> dict:
        """Lo que dice ``cancha doctor``, para poder verlo desde el móvil."""
        from ..diagnostico import diagnostico

        with self.cerrojo:
            return diagnostico(self.sesion.cliente, con_red=con_red)

    def limpiar_cache(self) -> dict:
        from ..diagnostico import limpiar_cache

        with self.cerrojo:
            return limpiar_cache()

    def descubrir_ligas(self, grupos=None) -> dict:
        """Busca los ids que faltan del catálogo. Necesita red y tarda."""
        from ..ligas import asegurar, resumen_catalogo

        with self.cerrojo:
            encontradas = asegurar(self.sesion.almacen, self.sesion.cliente, grupos=grupos)
            return {"encontradas": encontradas, "catalogo": resumen_catalogo(self.sesion.almacen)}

    def red(self, puerto: int | None = None) -> dict:
        """Por dónde se llega a este servidor, con el QR ya dibujado.

        Sirve para lo de siempre: estás en el ordenador y quieres abrirlo en el
        móvil. En vez de dictarte una IP, se pinta el mismo QR que el terminal.
        """
        from .qr import NoCabe, matriz

        puerto = puerto or self.puerto
        sufijo = f"/?clave={quote(self.clave)}" if self.clave else "/"
        urls = [f"http://{ip}:{puerto}{sufijo}" for ip in ips_locales()]
        salida: dict[str, Any] = {"urls": urls, "con_clave": bool(self.clave),
                                  "abierto_a_la_red": self.abierto}
        if urls:
            with suppress(NoCabe):
                salida["qr"] = matriz(urls[0])
        return salida

    # --- briefings ---

    def briefing(self, fecha: str) -> dict | None:
        from ..briefing import cargar

        return cargar(fecha, self.carpeta_briefings)

    # --- barrido en segundo plano ---

    def estado_barrido(self) -> dict:
        return {k: (v[-40:] if k == "lineas" else v) for k, v in self.barrido.items()}

    def lanzar_barrido(self, fecha: str | None, grupos: list[str] | None, maximo: int,
                       ultimos: int = 6) -> dict:
        if self.barrido["en_marcha"]:
            return {"error": "Ya hay un barrido en marcha.", **self.estado_barrido()}
        self.barrido.update({"en_marcha": True, "lineas": [], "resumen": None,
                             "empezado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                             "terminado": None})

        def correr() -> None:
            from ..barrido import barrer

            try:
                with self.cerrojo:
                    resumen = barrer(self.sesion.cliente, self.sesion.almacen, fecha=fecha,
                                     grupos=grupos, ultimos=ultimos, maximo_peticiones=maximo,
                                     avisar=self.barrido["lineas"].append)
                self.barrido["resumen"] = resumen
            except Exception as exc:  # noqa: BLE001 - se enseña, no se esconde
                self.barrido["lineas"].append(f"error: {exc}")
                self.barrido["resumen"] = {"error": str(exc)}
            finally:
                self.barrido["en_marcha"] = False
                self.barrido["terminado"] = datetime.now(timezone.utc).isoformat(
                    timespec="seconds")

        self._hilo_barrido = threading.Thread(target=correr, daemon=True)
        self._hilo_barrido.start()
        return self.estado_barrido()

    def esperar_barrido(self, segundos: float = 30) -> None:
        """Para los tests: espera a que el barrido acabe."""
        if self._hilo_barrido:
            self._hilo_barrido.join(segundos)

    def close(self) -> None:
        self.sesion.close()


# ---------------------------------------------------------------------- icono

def icono_png(lado: int = 192) -> bytes:
    """Un icono dibujado a mano: campo verde, círculo central y línea de medio.

    iOS exige un PNG para la pantalla de inicio y aquí no hay librerías de
    imagen: se escribe el PNG con ``zlib`` y ``struct``, que siempre están.
    """
    fondo, linea = (26, 94, 62), (240, 244, 240)
    centro, radio = lado / 2, lado * 0.22
    filas = []
    for y in range(lado):
        fila = bytearray([0])
        for x in range(lado):
            dx, dy = x - centro + 0.5, y - centro + 0.5
            distancia = (dx * dx + dy * dy) ** 0.5
            en_circulo = abs(distancia - radio) < lado * 0.028
            en_linea = abs(dx) < lado * 0.016 and lado * 0.12 < y < lado * 0.88
            punto = distancia < lado * 0.035
            fila += bytes(linea if (en_circulo or en_linea or punto) else fondo)
        filas.append(bytes(fila))

    def trozo(tipo: bytes, datos: bytes) -> bytes:
        return (struct.pack(">I", len(datos)) + tipo + datos
                + struct.pack(">I", zlib.crc32(tipo + datos) & 0xFFFFFFFF))

    cabecera = struct.pack(">IIBBBBB", lado, lado, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + trozo(b"IHDR", cabecera)
            + trozo(b"IDAT", zlib.compress(b"".join(filas), 9)) + trozo(b"IEND", b""))


# ---------------------------------------------------------------- peticiones

class Manejador(BaseHTTPRequestHandler):
    """Una petición. El estado vive en ``self.server.app``."""

    server_version = f"cancha/{__version__}"

    @property
    def app(self) -> Servidor:
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, formato: str, *args: Any) -> None:
        if getattr(self.server, "callado", True):
            return
        super().log_message(formato, *args)

    # --- respuestas ---

    def _json(self, datos: Any, estado: int = 200) -> None:
        cuerpo = json.dumps(datos, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(estado)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _fichero(self, nombre: str) -> None:
        ruta = (ESTATICO / nombre).resolve()
        if not str(ruta).startswith(str(ESTATICO.resolve())) or not ruta.is_file():
            self._json({"error": f"No existe {nombre}."}, 404)
            return
        cuerpo = ruta.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", TIPOS.get(ruta.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _png(self, lado: int) -> None:
        cuerpo = icono_png(lado)
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _autorizado(self, consulta: dict) -> bool:
        if not self.app.clave:
            return True
        dada = self.headers.get("X-Clave") or (consulta.get("clave") or [""])[0]
        return dada == self.app.clave

    def _cuerpo(self) -> dict:
        largo = int(self.headers.get("Content-Length") or 0)
        if not largo:
            return {}
        try:
            datos = json.loads(self.rfile.read(largo).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}
        return datos if isinstance(datos, dict) else {}

    def _analista(self, cuerpo: dict) -> None:
        """Contesta en NDJSON, un paso por línea, según van pasando.

        Sin ``Content-Length``: el cuerpo lo cierra la conexión. Así el
        navegador ve «estoy pidiendo los tiros» mientras ocurre, en vez de un
        minuto de reloj girando y luego un párrafo.
        """
        from ..analista import OllamaNoDisponible

        pregunta = str(cuerpo.get("pregunta") or "").strip()
        if not pregunta:
            return self._json({"error": "Falta la pregunta."}, 400)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        def escribir(objeto: dict) -> None:
            try:
                self.wfile.write(
                    (json.dumps(objeto, ensure_ascii=False, default=str) + "\n").encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                raise

        try:
            salida = self.app.preguntar(
                pregunta, historial=cuerpo.get("historial"),
                modelo=cuerpo.get("modelo"),
                al_paso=lambda paso: escribir({"paso": paso.as_dict()}))
            escribir({"fin": {k: v for k, v in salida.items() if k != "pasos"}})
        except OllamaNoDisponible as exc:
            with suppress(OSError):
                escribir({"error": str(exc)})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:  # noqa: BLE001 - el servidor no se cae por una pregunta
            with suppress(OSError):
                escribir({"error": f"{type(exc).__name__}: {exc}"})

    # --- rutas ---

    def do_GET(self) -> None:  # noqa: N802 - nombre que exige http.server
        url = urlparse(self.path)
        ruta, consulta = unquote(url.path), parse_qs(url.query)

        if ruta in ("/", "/index.html"):
            return self._fichero("index.html")
        if ruta == "/icono-180.png":
            return self._png(180)
        if ruta == "/icono-192.png":
            return self._png(192)
        if ruta == "/icono-512.png":
            return self._png(512)
        if not ruta.startswith("/api/"):
            return self._fichero(ruta.lstrip("/"))

        if not self._autorizado(consulta):
            return self._json({"error": "Hace falta la clave (cabecera X-Clave)."}, 401)
        if ruta == "/api/estado":
            return self._json(self.app.estado())
        if ruta == "/api/herramientas":
            return self._json(self.app.esquemas())
        if ruta == "/api/barrido":
            return self._json(self.app.estado_barrido())
        if ruta == "/api/analista":
            return self._json(self.app.estado_analista(
                (consulta.get("modelo") or [None])[0]))
        if ruta == "/api/diagnostico":
            con_red = (consulta.get("red") or ["0"])[0] not in ("0", "", "no")
            return self._json(self.app.diagnostico(con_red=con_red))
        if ruta == "/api/red":
            return self._json(self.app.red())
        if ruta.startswith("/api/briefing/"):
            fecha = ruta.rsplit("/", 1)[-1]
            datos = self.app.briefing(fecha)
            if datos is None:
                return self._json({"error": f"No hay briefing guardado del {fecha}."}, 404)
            return self._json(datos)
        return self._json({"error": f"No existe {ruta}."}, 404)

    def do_POST(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        ruta, consulta = unquote(url.path), parse_qs(url.query)
        if not self._autorizado(consulta):
            return self._json({"error": "Hace falta la clave (cabecera X-Clave)."}, 401)
        cuerpo = self._cuerpo()

        if ruta.startswith("/api/herramienta/"):
            nombre = ruta.rsplit("/", 1)[-1]
            resultado = self.app.ejecutar(nombre, cuerpo)
            estado = 404 if (isinstance(resultado, dict) and "disponibles" in resultado
                             and "error" in resultado) else 200
            return self._json(resultado, estado)
        if ruta == "/api/seguro":
            grupos = cuerpo.get("grupos")
            if isinstance(grupos, str):
                grupos = [g for g in grupos.split(",") if g]
            return self._json(self.app.seguro(
                cuerpo.get("fecha") or None, grupos or None,
                calibrar=bool(cuerpo.get("calibrar")),
                umbral=float(cuerpo.get("umbral") or 0.65)))
        if ruta == "/api/analista":
            return self._analista(cuerpo)
        if ruta == "/api/cache":
            return self._json(self.app.limpiar_cache())
        if ruta == "/api/ligas":
            grupos = cuerpo.get("grupos")
            if isinstance(grupos, str):
                grupos = [g for g in grupos.split(",") if g]
            return self._json(self.app.descubrir_ligas(grupos or None))
        if ruta == "/api/barrido":
            grupos = cuerpo.get("grupos")
            if isinstance(grupos, str):
                grupos = [g for g in grupos.split(",") if g]
            return self._json(self.app.lanzar_barrido(
                cuerpo.get("fecha") or None, grupos or None,
                int(cuerpo.get("max") or 0), int(cuerpo.get("ultimos") or 6)))
        return self._json({"error": f"No existe {ruta}."}, 404)


# ---------------------------------------------------------------- arrancar

def ip_local() -> str:
    """La IP de este ordenador en su red, para teclearla en el móvil."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # no envía nada: solo elige interfaz
            return s.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"


#: Los rangos que una wifi de casa usa de verdad. Una máquina con Docker, una
#: VPN o WSL tiene varias IP y solo una sirve, así que se ordenan en vez de
#: adivinar una y dejar al otro probando.
_PRIVADAS = ("192.168.", "10.", "172.16.", "172.17.", "172.18.", "172.19.",
             "172.20.", "172.21.", "172.22.", "172.23.", "172.24.", "172.25.",
             "172.26.", "172.27.", "172.28.", "172.29.", "172.30.", "172.31.")


def ips_locales() -> list[str]:
    """Todas las IP por las que se puede llegar a este ordenador, la mejor primero.

    ``ip_local`` devuelve la de la ruta por defecto, que es la buena casi
    siempre. Casi: con una VPN levantada o Docker instalado hay varias, y si se
    enseña solo una y resulta ser la que no es, el móvil no entra y nadie sabe
    por qué. Se enseñan todas.
    """
    candidatas: list[str] = []

    def añadir(ip: str) -> None:
        if ip and ip not in candidatas and not ip.startswith("127."):
            candidatas.append(ip)

    añadir(ip_local())
    with suppress(OSError):
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            añadir(info[4][0])
    # Las privadas primero, manteniendo el orden dentro de cada grupo: la de la
    # ruta por defecto sigue siendo la primera de las suyas.
    return sorted(candidatas, key=lambda ip: 0 if ip.startswith(_PRIVADAS) else 1)


def construir(app: Servidor, host: str = "127.0.0.1", puerto: int = 8765,
              callado: bool = True) -> ThreadingHTTPServer:
    servidor = ThreadingHTTPServer((host, puerto), Manejador)
    servidor.app = app  # type: ignore[attr-defined]
    servidor.callado = callado  # type: ignore[attr-defined]
    servidor.daemon_threads = True
    return servidor


def arrancar(app: Servidor, host: str = "127.0.0.1", puerto: int = 8765,
             abrir: bool = False, avisar=print, qr: bool = True,
             color: bool = True) -> int:
    """Sirve hasta Ctrl+C."""
    servidor = construir(app, host, puerto)
    puerto_real = servidor.server_address[1]
    # La página también enseña el QR, así que necesita saber esto.
    app.puerto = puerto_real
    app.abierto = host not in ("127.0.0.1", "localhost")
    avisar(f"cancha {__version__} · interfaz en http://127.0.0.1:{puerto_real}")
    if host not in ("127.0.0.1", "localhost"):
        sufijo = f"/?clave={quote(app.clave)}" if app.clave else "/"
        urls = [f"http://{ip}:{puerto_real}{sufijo}" for ip in ips_locales()]
        if urls:
            avisar("")
            avisar("  Desde el móvil, en la misma wifi. Apunta la cámara:")
            if qr:
                avisar("")
                for linea in dibujar_qr(urls[0], color=color).splitlines():
                    avisar("  " + linea)
                avisar("")
            for url in urls:
                avisar(f"    {url}")
            if len(urls) > 1:
                avisar("    (varias IP: el QR lleva a la primera; si no entra, prueba las otras)")
            avisar("  En iOS: Safari → Compartir → «Añadir a pantalla de inicio»")
        if not app.clave:
            avisar("  (sin clave: cualquiera en tu red puede usarla; pon --clave si te importa)")
    avisar("Ctrl+C para parar.")
    if abrir:
        import webbrowser

        webbrowser.open(f"http://127.0.0.1:{puerto_real}")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()
        app.close()
    return 0


__all__ = ["Servidor", "Manejador", "construir", "arrancar", "icono_png",
           "ip_local", "ips_locales"]
