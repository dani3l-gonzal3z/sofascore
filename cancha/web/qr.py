"""Un código QR dibujado en el terminal, sin instalar nada.

Para abrir la interfaz en el móvil hay que teclear una IP, un puerto y a veces
una clave, sin equivocarse, con el móvil en la mano. Un QR se come ese paso
entero. Y no hace falta una librería: el formato está publicado (ISO/IEC
18004) y es aritmética en GF(256) y unas tablas.

Se implementan las versiones 1 a 10 en modo byte, que llegan a 271 bytes en
nivel L: de sobra para ``http://192.168.1.34:8765/?clave=...``. Por encima de
eso se avisa en vez de dibujar algo que el móvil no va a leer.
"""

from __future__ import annotations

# ------------------------------------------------------- aritmética GF(256)
#
# El cuerpo de 256 elementos con el polinomio 0x11D, que es el que fija la
# norma. Con las tablas de exponentes y logaritmos, multiplicar es sumar
# índices, y eso es todo lo que necesita Reed-Solomon.

_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _mul(a: int, b: int) -> int:
    return 0 if (a == 0 or b == 0) else _EXP[_LOG[a] + _LOG[b]]


def _generador(grado: int) -> list[int]:
    """El polinomio generador de grado n: producto de (x - α^i)."""
    poly = [1]
    for i in range(grado):
        nuevo = [0] * (len(poly) + 1)
        for j, coeficiente in enumerate(poly):
            nuevo[j] ^= coeficiente
            nuevo[j + 1] ^= _mul(coeficiente, _EXP[i])
        poly = nuevo
    return poly


def _correccion(datos: list[int], cuantos: int) -> list[int]:
    """Los bytes de corrección: el resto de dividir los datos por el generador."""
    generador = _generador(cuantos)
    resto = [0] * cuantos
    for byte in datos:
        factor = byte ^ resto[0]
        resto = resto[1:] + [0]
        for i, coeficiente in enumerate(generador[1:]):
            resto[i] ^= _mul(coeficiente, factor)
    return resto


# -------------------------------------------------------------------- tablas
#
# Por versión y nivel de corrección: cuántos bytes de corrección lleva cada
# bloque, y cómo se reparten los datos en bloques. Sale de las tablas 13 a 22
# de la norma. La comprobación de que están bien copiadas es aritmética: los
# datos más la corrección tienen que dar el total de bytes de esa versión, y
# hay un test que lo verifica versión por versión.

NIVELES = ("L", "M", "Q", "H")

_BLOQUES: dict[int, dict[str, tuple[int, tuple[tuple[int, int], ...]]]] = {
    1: {"L": (7, ((1, 19),)), "M": (10, ((1, 16),)),
        "Q": (13, ((1, 13),)), "H": (17, ((1, 9),))},
    2: {"L": (10, ((1, 34),)), "M": (16, ((1, 28),)),
        "Q": (22, ((1, 22),)), "H": (28, ((1, 16),))},
    3: {"L": (15, ((1, 55),)), "M": (26, ((1, 44),)),
        "Q": (18, ((2, 17),)), "H": (22, ((2, 13),))},
    4: {"L": (20, ((1, 80),)), "M": (18, ((2, 32),)),
        "Q": (26, ((2, 24),)), "H": (16, ((4, 9),))},
    5: {"L": (26, ((1, 108),)), "M": (24, ((2, 43),)),
        "Q": (18, ((2, 15), (2, 16))), "H": (22, ((2, 11), (2, 12)))},
    6: {"L": (18, ((2, 68),)), "M": (16, ((4, 27),)),
        "Q": (24, ((4, 19),)), "H": (28, ((4, 15),))},
    7: {"L": (20, ((2, 78),)), "M": (18, ((4, 31),)),
        "Q": (18, ((2, 14), (4, 15))), "H": (26, ((4, 13), (1, 14)))},
    8: {"L": (24, ((2, 97),)), "M": (22, ((2, 38), (2, 39))),
        "Q": (22, ((4, 18), (2, 19))), "H": (26, ((4, 14), (2, 15)))},
    9: {"L": (30, ((2, 116),)), "M": (22, ((3, 36), (2, 37))),
        "Q": (20, ((4, 16), (4, 17))), "H": (24, ((4, 12), (4, 13)))},
    10: {"L": (18, ((2, 68), (2, 69))), "M": (26, ((4, 43), (1, 44))),
         "Q": (24, ((6, 19), (2, 20))), "H": (28, ((6, 15), (2, 16)))},
}

#: Bytes totales de cada versión, para comprobar las tablas de arriba.
_TOTALES = {1: 26, 2: 44, 3: 70, 4: 100, 5: 134,
            6: 172, 7: 196, 8: 242, 9: 292, 10: 346}

#: Dónde van los centros de los patrones de alineación de cada versión.
_ALINEACION: dict[int, tuple[int, ...]] = {
    1: (), 2: (6, 18), 3: (6, 22), 4: (6, 26), 5: (6, 30),
    6: (6, 34), 7: (6, 22, 38), 8: (6, 24, 42), 9: (6, 26, 46), 10: (6, 28, 50),
}

#: Los dos bits con los que se anuncia el nivel de corrección en el formato.
_BITS_NIVEL = {"L": 0b01, "M": 0b00, "Q": 0b11, "H": 0b10}

#: Las ocho máscaras de la norma, como condición sobre (fila, columna).
_MASCARAS = (
    lambda f, c: (f + c) % 2 == 0,
    lambda f, c: f % 2 == 0,
    lambda f, c: c % 3 == 0,
    lambda f, c: (f + c) % 3 == 0,
    lambda f, c: (f // 2 + c // 3) % 2 == 0,
    lambda f, c: (f * c) % 2 + (f * c) % 3 == 0,
    lambda f, c: ((f * c) % 2 + (f * c) % 3) % 2 == 0,
    lambda f, c: ((f + c) % 2 + (f * c) % 3) % 2 == 0,
)


class NoCabe(ValueError):
    """Lo que se quiere codificar no entra en una versión 1-10."""


def capacidad(version: int, nivel: str = "M") -> int:
    """Cuántos bytes de datos caben, descontando la cabecera del modo byte."""
    _, bloques = _BLOQUES[version][nivel]
    datos = sum(cuantos * por_bloque for cuantos, por_bloque in bloques)
    cabecera = 4 + (8 if version < 10 else 16)  # modo + cuenta de caracteres
    return datos - (cabecera + 7) // 8


def _version_para(cuantos: int, nivel: str) -> int:
    for version in sorted(_BLOQUES):
        if capacidad(version, nivel) >= cuantos:
            return version
    raise NoCabe(f"{cuantos} bytes no entran en un QR de versión 10 nivel {nivel}.")


# -------------------------------------------------------------------- datos

def _bits_de(datos: bytes, version: int, nivel: str) -> list[int]:
    """Los bits ya troceados, con corrección e intercalados como pide la norma."""
    bits: list[int] = [0, 1, 0, 0]  # modo byte
    anchura = 8 if version < 10 else 16
    for desplazamiento in range(anchura - 1, -1, -1):
        bits.append((len(datos) >> desplazamiento) & 1)
    for byte in datos:
        for desplazamiento in range(7, -1, -1):
            bits.append((byte >> desplazamiento) & 1)

    por_correccion, bloques = _BLOQUES[version][nivel]
    total_datos = sum(cuantos * por_bloque for cuantos, por_bloque in bloques)
    # Terminador, relleno hasta el byte y luego los dos bytes de relleno de la
    # norma alternándose. Nada de esto es decorativo: el lector espera
    # exactamente este relleno.
    bits += [0] * min(4, total_datos * 8 - len(bits))
    bits += [0] * (-len(bits) % 8)
    for i in range((total_datos * 8 - len(bits)) // 8):
        relleno = 0xEC if i % 2 == 0 else 0x11
        bits += [(relleno >> d) & 1 for d in range(7, -1, -1)]

    bytes_datos = [int("".join(str(b) for b in bits[i:i + 8]), 2)
                   for i in range(0, len(bits), 8)]

    trozos, correcciones, cursor = [], [], 0
    for cuantos, por_bloque in bloques:
        for _ in range(cuantos):
            trozo = bytes_datos[cursor:cursor + por_bloque]
            cursor += por_bloque
            trozos.append(trozo)
            correcciones.append(_correccion(trozo, por_correccion))

    # Intercalado: primero el byte 0 de cada bloque, luego el 1... y después
    # lo mismo con la corrección. Los bloques largos aportan su último byte
    # cuando a los cortos ya no les queda.
    salida: list[int] = []
    for i in range(max(len(t) for t in trozos)):
        salida += [t[i] for t in trozos if i < len(t)]
    for i in range(por_correccion):
        salida += [c[i] for c in correcciones]

    return [(byte >> d) & 1 for byte in salida for d in range(7, -1, -1)]


# ------------------------------------------------------------------ plantilla

def _plantilla(version: int) -> tuple[list[list[int]], list[list[bool]]]:
    """La rejilla con todo lo que no son datos, y qué casillas son esas."""
    lado = 17 + 4 * version
    rejilla = [[0] * lado for _ in range(lado)]
    fijo = [[False] * lado for _ in range(lado)]

    def poner(fila: int, columna: int, valor: int) -> None:
        rejilla[fila][columna] = valor
        fijo[fila][columna] = True

    for base_f, base_c in ((0, 0), (0, lado - 7), (lado - 7, 0)):
        for df in range(-1, 8):
            for dc in range(-1, 8):
                fila, columna = base_f + df, base_c + dc
                if not (0 <= fila < lado and 0 <= columna < lado):
                    continue
                dentro = 0 <= df < 7 and 0 <= dc < 7
                anillo = dentro and (df in (0, 6) or dc in (0, 6))
                centro = 2 <= df <= 4 and 2 <= dc <= 4
                poner(fila, columna, 1 if (anillo or centro) else 0)

    centros = _ALINEACION[version]
    esquinas = {(centros[0], centros[0]), (centros[0], centros[-1]),
                (centros[-1], centros[0])} if centros else set()
    for fila in centros:
        for columna in centros:
            if (fila, columna) in esquinas:
                continue
            for df in range(-2, 3):
                for dc in range(-2, 3):
                    poner(fila + df, columna + dc,
                          0 if max(abs(df), abs(dc)) == 1 else 1)

    for i in range(8, lado - 8):
        valor = 1 if i % 2 == 0 else 0
        poner(6, i, valor)
        poner(i, 6, valor)

    for i in range(9):  # sitio del formato, que se rellena al final
        if not fijo[8][i]:
            poner(8, i, 0)
        if not fijo[i][8]:
            poner(i, 8, 0)
    for i in range(8):
        poner(8, lado - 1 - i, 0)
        poner(lado - 1 - i, 8, 0)
    poner(lado - 8, 8, 1)  # el módulo que siempre es oscuro

    if version >= 7:  # sitio de la versión
        for i in range(18):
            poner(i // 3, lado - 11 + i % 3, 0)
            poner(lado - 11 + i % 3, i // 3, 0)

    return rejilla, fijo


def _colocar(rejilla: list[list[int]], fijo: list[list[bool]], bits: list[int]) -> None:
    """Los datos, en columnas de dos que serpentean desde la esquina de abajo."""
    lado = len(rejilla)
    i, columna, hacia_arriba = 0, lado - 1, True
    while columna > 0:
        if columna == 6:  # la columna de tiempo no cuenta
            columna -= 1
        filas = range(lado - 1, -1, -1) if hacia_arriba else range(lado)
        for fila in filas:
            for c in (columna, columna - 1):
                if fijo[fila][c]:
                    continue
                rejilla[fila][c] = bits[i] if i < len(bits) else 0
                i += 1
        columna -= 2
        hacia_arriba = not hacia_arriba


def _formato(nivel: str, mascara: int) -> int:
    datos = (_BITS_NIVEL[nivel] << 3) | mascara
    resto = datos
    for _ in range(10):
        resto = (resto << 1) ^ ((resto >> 9) * 0x537)
    return ((datos << 10) | resto) ^ 0x5412


def _bits_version(version: int) -> int:
    resto = version
    for _ in range(12):
        resto = (resto << 1) ^ ((resto >> 11) * 0x1F25)
    return (version << 12) | resto


def _escribir_formato(rejilla: list[list[int]], nivel: str, mascara: int) -> None:
    lado = len(rejilla)
    bits = _formato(nivel, mascara)

    def bit(i: int) -> int:
        return (bits >> i) & 1

    for i in range(6):
        rejilla[i][8] = bit(i)
    rejilla[7][8] = bit(6)
    rejilla[8][8] = bit(7)
    rejilla[8][7] = bit(8)
    for i in range(9, 15):
        rejilla[8][14 - i] = bit(i)
    for i in range(8):
        rejilla[8][lado - 1 - i] = bit(i)
    for i in range(8, 15):
        rejilla[lado - 15 + i][8] = bit(i)
    rejilla[lado - 8][8] = 1


def _escribir_version(rejilla: list[list[int]], version: int) -> None:
    if version < 7:
        return
    lado, bits = len(rejilla), _bits_version(version)
    for i in range(18):
        valor = (bits >> i) & 1
        rejilla[i // 3][lado - 11 + i % 3] = valor
        rejilla[lado - 11 + i % 3][i // 3] = valor


# ------------------------------------------------------------------- máscaras

def _penalizacion(rejilla: list[list[int]]) -> int:
    """Lo mala que es una máscara, con las cuatro reglas de la norma.

    Existe porque un QR con grandes manchas iguales, o con algo que se parece
    a un patrón de búsqueda, se lee mal. Se prueban las ocho y se queda la
    menos mala.
    """
    lado = len(rejilla)
    total = 0
    #: 1011101 con cuatro claros delante o detrás: lo que un lector puede
    #: confundir con un patrón de búsqueda. Son las dos ventanas de once.
    trampas = ((1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0),
               (0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1))

    lineas = [list(f) for f in rejilla] + [list(c) for c in zip(*rejilla, strict=True)]
    for linea in lineas:
        seguidos, anterior = 1, linea[0]
        for valor in linea[1:]:
            if valor == anterior:
                seguidos += 1
            else:
                if seguidos >= 5:
                    total += 3 + (seguidos - 5)
                seguidos, anterior = 1, valor
        if seguidos >= 5:
            total += 3 + (seguidos - 5)
        for i in range(lado - 10):
            if tuple(linea[i:i + 11]) in trampas:
                total += 40

    for f in range(lado - 1):
        for c in range(lado - 1):
            cuadro = (rejilla[f][c], rejilla[f][c + 1],
                      rejilla[f + 1][c], rejilla[f + 1][c + 1])
            if len(set(cuadro)) == 1:
                total += 3

    # Regla 4: cada 5% de desvío sobre el 50% de módulos oscuros, diez puntos.
    oscuros = sum(sum(f) for f in rejilla)
    casillas = lado * lado
    total += (abs(oscuros * 20 - casillas * 10) // casillas) * 10
    return total


# --------------------------------------------------------------------- público

def matriz(texto: str, nivel: str = "M", version: int | None = None) -> list[list[int]]:
    """La rejilla del QR: 1 es módulo oscuro, 0 claro. Sin zona de silencio."""
    if nivel not in _BITS_NIVEL:
        raise ValueError(f"Nivel {nivel!r}: solo {', '.join(NIVELES)}.")
    datos = texto.encode("utf-8")
    version = version or _version_para(len(datos), nivel)
    if len(datos) > capacidad(version, nivel):
        raise NoCabe(f"{len(datos)} bytes no entran en la versión {version} nivel {nivel}.")

    bits = _bits_de(datos, version, nivel)
    mejor, mejor_pena = None, None
    for mascara in range(8):
        rejilla, fijo = _plantilla(version)
        _colocar(rejilla, fijo, bits)
        for f, fila in enumerate(rejilla):
            for c in range(len(fila)):
                if not fijo[f][c] and _MASCARAS[mascara](f, c):
                    fila[c] ^= 1
        _escribir_formato(rejilla, nivel, mascara)
        _escribir_version(rejilla, version)
        pena = _penalizacion(rejilla)
        if mejor_pena is None or pena < mejor_pena:
            mejor, mejor_pena = rejilla, pena
    assert mejor is not None
    return mejor


#: Blanco y negro de verdad, no «el color del terminal»: un QR claro sobre
#: oscuro no lo leen todos los móviles, y el fondo del terminal no se sabe.
_CLARO_FONDO, _OSCURO_FONDO = "\x1b[107m", "\x1b[40m"
_CLARO_TINTA, _OSCURO_TINTA = "\x1b[97m", "\x1b[30m"


def dibujar(texto: str, nivel: str = "M", color: bool = True, silencio: int = 4) -> str:
    """El QR como texto, listo para un ``print``.

    Con ``color`` se usan medios bloques y colores fijos: dos filas de módulos
    por línea, así que cabe en una ventana normal. Sin color se dibuja con dos
    caracteres por módulo, que es el doble de alto pero funciona en cualquier
    sitio (y es lo que miran los tests).
    """
    rejilla = matriz(texto, nivel)
    lado = len(rejilla)
    ancho = lado + 2 * silencio
    filas = ([[0] * ancho] * silencio
             + [[0] * silencio + fila + [0] * silencio for fila in rejilla]
             + [[0] * ancho] * silencio)

    if not color:
        return "\n".join("".join("  " if v else "██" for v in fila) for fila in filas)

    if len(filas) % 2:
        filas.append([0] * ancho)
    lineas = []
    for i in range(0, len(filas), 2):
        arriba, abajo = filas[i], filas[i + 1]
        trozo = []
        for a, b in zip(arriba, abajo, strict=True):
            tinta = _OSCURO_TINTA if a else _CLARO_TINTA
            fondo = _OSCURO_FONDO if b else _CLARO_FONDO
            trozo.append(f"{tinta}{fondo}▀")
        lineas.append("".join(trozo) + "\x1b[0m")
    return "\n".join(lineas)


__all__ = ["NoCabe", "NIVELES", "capacidad", "dibujar", "matriz"]
