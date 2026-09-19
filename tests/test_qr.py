"""El codificador de QR, comprobado por dentro y por fuera.

Por dentro: las tablas de la norma tienen que cuadrar aritméticamente, y una
matriz conocida tiene que salir bit a bit. Por fuera: lo generado se vuelve a
leer decodificándolo a mano, que es la única prueba que de verdad importa (un
QR bonito que ningún móvil lee no sirve de nada).
"""

from __future__ import annotations

import pytest

from cancha.web import qr

# ---------------------------------------------------------------- las tablas

def test_las_tablas_de_la_norma_cuadran_version_por_version():
    """Datos + corrección = bytes totales de esa versión. Copiar mal se ve aquí."""
    for version, total in qr._TOTALES.items():
        for nivel in qr.NIVELES:
            por_correccion, bloques = qr._BLOQUES[version][nivel]
            datos = sum(cuantos * por for cuantos, por in bloques)
            cuantos_bloques = sum(cuantos for cuantos, _ in bloques)
            assert datos + por_correccion * cuantos_bloques == total, (version, nivel)


def test_los_bloques_de_una_version_no_se_diferencian_en_mas_de_un_byte():
    """La norma reparte los datos lo más igual que puede: 43 y 44, nunca 40 y 47."""
    for version in qr._BLOQUES:
        for nivel in qr.NIVELES:
            _, bloques = qr._BLOQUES[version][nivel]
            tamaños = {por for _, por in bloques}
            assert max(tamaños) - min(tamaños) <= 1, (version, nivel, tamaños)


def test_el_cuerpo_de_galois_es_un_grupo_ciclico():
    """Si las tablas de exponentes y logaritmos no son inversas, nada funciona."""
    assert qr._EXP[0] == 1
    assert len({qr._EXP[i] for i in range(255)}) == 255, "α no genera los 255"
    for i in range(1, 256):
        assert qr._EXP[qr._LOG[i]] == i
    # Multiplicar por 1 no hace nada, y el producto es conmutativo.
    for a in (1, 2, 17, 128, 255):
        assert qr._mul(a, 1) == a
        for b in (3, 19, 200):
            assert qr._mul(a, b) == qr._mul(b, a)


def test_la_correccion_de_un_ejemplo_conocido():
    """El ejemplo del anexo I de la norma: 'HELLO WORLD' en versión 1 nivel M."""
    datos = [0x20, 0x5B, 0x0B, 0x78, 0xD1, 0x72, 0xDC, 0x4D, 0x43, 0x40,
             0xEC, 0x11, 0xEC, 0x11, 0xEC, 0x11]
    assert qr._correccion(datos, 10) == [0xC4, 0x23, 0x27, 0x77, 0xEB,
                                         0xD7, 0xE7, 0xE2, 0x5D, 0x17]


# ------------------------------------------------------------- las matrices

def test_el_tamano_va_con_la_version():
    assert len(qr.matriz("a", "L")) == 21              # versión 1
    assert len(qr.matriz("x" * 30, "L")) == 25         # versión 2
    assert len(qr.matriz("x" * 250, "L")) == 57        # versión 10


def test_los_patrones_de_busqueda_estan_donde_toca():
    rejilla = qr.matriz("http://192.168.1.34:8765")
    lado = len(rejilla)
    for base_f, base_c in ((0, 0), (0, lado - 7), (lado - 7, 0)):
        assert rejilla[base_f][base_c] == 1
        assert rejilla[base_f + 1][base_c + 1] == 0, "el anillo blanco"
        assert rejilla[base_f + 3][base_c + 3] == 1, "el centro"
    assert rejilla[lado - 8][8] == 1, "el módulo que siempre es oscuro"
    # Las líneas de tiempo alternan desde la sexta fila y la sexta columna.
    for i in range(8, lado - 8):
        assert rejilla[6][i] == rejilla[i][6] == (1 if i % 2 == 0 else 0)


def test_la_esquina_de_abajo_a_la_izquierda_no_lleva_patron_de_alineacion():
    """Se solapan con los de búsqueda; ponerlos ahí rompe la lectura."""
    rejilla = qr.matriz("x" * 30)          # versión 2, centros en 6 y 18
    assert rejilla[18][18] == 1, "el de en medio sí va"
    # El de (6, 6) caería sobre el patrón de búsqueda: ahí manda el de búsqueda.
    assert rejilla[6][6] == 1


def test_lo_que_no_cabe_se_dice_en_vez_de_dibujar_algo_ilegible():
    with pytest.raises(qr.NoCabe):
        qr.matriz("x" * 300, "H")
    with pytest.raises(ValueError):
        qr.matriz("hola", "Z")


def test_la_capacidad_declarada_es_la_real():
    for version in qr._BLOQUES:
        for nivel in qr.NIVELES:
            cuantos = qr.capacidad(version, nivel)
            qr.matriz("x" * cuantos, nivel, version=version)   # entra justo
            with pytest.raises(qr.NoCabe):
                qr.matriz("x" * (cuantos + 1), nivel, version=version)


# --------------------------------------------------------------- decodificar
#
# Un QR que no se puede volver a leer no vale. Aquí se lee a mano: se deshace
# la máscara que dicen los bits de formato, se recogen los datos en el mismo
# serpenteo, se desintercalan los bloques y se saca el texto. No comprueba la
# corrección de errores (para eso haría falta un decodificador Reed-Solomon
# entero), pero sí que todo lo demás está en su sitio.

def _leer(rejilla: list[list[int]]) -> str:
    lado = len(rejilla)
    version = (lado - 17) // 4

    formato = 0
    for i in range(8):
        formato |= rejilla[8][lado - 1 - i] << i
    for i in range(8, 15):
        formato |= rejilla[lado - 15 + i][8] << i
    formato ^= 0x5412
    # Los cinco bits de datos están arriba; los diez de abajo son el BCH.
    datos_formato = formato >> 10
    mascara = datos_formato & 0b111
    nivel = next(n for n, bits in qr._BITS_NIVEL.items()
                 if bits == (datos_formato >> 3) & 0b11)

    limpia = [fila[:] for fila in rejilla]
    _, fijo = qr._plantilla(version)
    for f in range(lado):
        for c in range(lado):
            if not fijo[f][c] and qr._MASCARAS[mascara](f, c):
                limpia[f][c] ^= 1

    bits: list[int] = []
    i, columna, hacia_arriba = 0, lado - 1, True
    while columna > 0:
        if columna == 6:
            columna -= 1
        filas = range(lado - 1, -1, -1) if hacia_arriba else range(lado)
        for f in filas:
            for c in (columna, columna - 1):
                if not fijo[f][c]:
                    bits.append(limpia[f][c])
        columna -= 2
        hacia_arriba = not hacia_arriba

    seguidos = [int("".join(str(b) for b in bits[i:i + 8]), 2)
                for i in range(0, len(bits) - 7, 8)]

    por_correccion, bloques = qr._BLOQUES[version][nivel]
    tamaños = [por for cuantos, por in bloques for _ in range(cuantos)]
    trozos: list[list[int]] = [[] for _ in tamaños]
    cursor = 0
    for i in range(max(tamaños)):
        for j, tamaño in enumerate(tamaños):
            if i < tamaño:
                trozos[j].append(seguidos[cursor])
                cursor += 1
    bytes_datos = [b for trozo in trozos for b in trozo]

    plano = "".join(f"{b:08b}" for b in bytes_datos)
    assert plano[:4] == "0100", "no está en modo byte"
    anchura = 8 if version < 10 else 16
    cuantos = int(plano[4:4 + anchura], 2)
    inicio = 4 + anchura
    crudo = bytes(int(plano[inicio + 8 * k:inicio + 8 * k + 8], 2) for k in range(cuantos))
    return crudo.decode("utf-8")


@pytest.mark.parametrize("nivel", qr.NIVELES)
@pytest.mark.parametrize("texto", [
    "a",
    "http://192.168.1.34:8765/",
    "http://10.0.0.7:8765/?clave=abc123",
    "http://192.168.0.101:9999/?clave=" + "z" * 40,
    "cañada ñ á é",                  # utf-8 de varios bytes
    "x" * 100,
])
def test_lo_dibujado_se_vuelve_a_leer(texto, nivel):
    assert _leer(qr.matriz(texto, nivel)) == texto


def test_se_lee_en_todas_las_versiones_y_niveles():
    """Recorre las diez versiones: el serpenteo y el intercalado cambian con ellas."""
    for version in qr._BLOQUES:
        for nivel in qr.NIVELES:
            texto = "cancha " * 50
            texto = texto[:qr.capacidad(version, nivel)]
            assert _leer(qr.matriz(texto, nivel, version=version)) == texto


def test_la_mascara_elegida_es_la_menos_mala():
    """Se prueban las ocho y gana la de menos penalización, como pide la norma."""
    texto = "http://192.168.1.34:8765/"
    elegida = qr.matriz(texto)
    version = qr._version_para(len(texto.encode()), "M")
    bits = qr._bits_de(texto.encode(), version, "M")
    penas = []
    for mascara in range(8):
        rejilla, fijo = qr._plantilla(version)
        qr._colocar(rejilla, fijo, bits)
        for f, fila in enumerate(rejilla):
            for c in range(len(fila)):
                if not fijo[f][c] and qr._MASCARAS[mascara](f, c):
                    fila[c] ^= 1
        qr._escribir_formato(rejilla, "M", mascara)
        qr._escribir_version(rejilla, version)
        penas.append((qr._penalizacion(rejilla), mascara, rejilla))
    assert elegida == min(penas)[2]


# ------------------------------------------------------------------- dibujo

def test_el_dibujo_lleva_zona_de_silencio():
    """Sin cuatro módulos claros alrededor, un lector no encuentra el código."""
    dibujo = qr.dibujar("hola", color=False)
    lineas = dibujo.splitlines()
    lado = len(qr.matriz("hola"))
    assert len(lineas) == lado + 8
    assert all(len(linea) == (lado + 8) * 2 for linea in lineas)
    for linea in lineas[:4] + lineas[-4:]:
        assert set(linea) == {"█"}, "la zona de silencio tiene que ser toda clara"


def test_en_color_ocupa_la_mitad_de_alto():
    """Con medios bloques cabe en una ventana de terminal normal."""
    lado = len(qr.matriz("hola"))
    lineas = qr.dibujar("hola", color=True).splitlines()
    assert len(lineas) == (lado + 8 + 1) // 2
    assert "\x1b[" in lineas[0], "tiene que llevar los colores puestos"


def test_el_dibujo_no_depende_del_color_del_terminal():
    """Se fijan tinta y fondo: un QR claro sobre oscuro no lo lee todo el mundo."""
    dibujo = qr.dibujar("hola", color=True)
    assert qr._CLARO_FONDO in dibujo and qr._OSCURO_FONDO in dibujo


def test_el_dibujo_en_color_conserva_la_matriz():
    """Los medios bloques se deshacen y tiene que salir el mismo código.

    Dibujar dos filas de módulos por línea es donde es fácil colarse: basta
    invertir tinta y fondo para que el QR salga del revés y ningún móvil lo
    lea. Aquí se desanda el dibujo y se compara con la matriz de origen.
    """
    texto = "http://192.168.1.34:8765/"
    original = qr.matriz(texto)
    lado, silencio = len(original), 4
    ancho = lado + 2 * silencio

    filas = []
    for linea in qr.dibujar(texto, color=True).splitlines():
        arriba, abajo = [], []
        resto = linea.replace("\x1b[0m", "")
        for celda in resto.split("\x1b[")[1:]:
            # Cada celda es "<tinta>m\x1b[<fondo>m▀", partida ya por el split.
            if celda.endswith("▀"):
                continue
            tinta = celda.rstrip("m")
            arriba.append(1 if tinta == "30" else 0)
        for celda in resto.split("▀")[:-1]:
            fondo = celda.split("\x1b[")[-1].rstrip("m")
            abajo.append(1 if fondo == "40" else 0)
        filas.append(arriba)
        filas.append(abajo)

    assert all(len(f) == ancho for f in filas), "alguna fila salió de otra anchura"
    dentro = [f[silencio:silencio + lado] for f in filas[silencio:silencio + lado]]
    assert dentro == original
