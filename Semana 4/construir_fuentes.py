# construir_fuentes.py — CORRER UNA VEZ EN PC (python3) en la carpeta
# donde estén comfortaa_16.py y comfortaa_24.py.
#
#   python3 construir_fuentes.py
#
# Genera 'fuentes.py' con dos clases (font_sm = 16px, font_md = 24px),
# recortado solo a los caracteres en KEEP → archivo ~50% más chico.
#
# Si algo no se ve bien en pantalla, agrega el caracter faltante a KEEP
# y vuelve a correr el script.

import comfortaa_16 as f16
import comfortaa_24 as f24

# Caracteres a conservar (todo lo demás se descarta del archivo final).
KEEP = (" !\"#$%&'()*+,-./0123456789:;<=>?@"
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`"
        "abcdefghijklmnopqrstuvwxyz{|}~"
        "¡°ÁÉÍÓÚÑáéíóúüñ")

def _bit(buf, i):
    return (buf[i >> 3] >> (7 - (i & 7))) & 1

def trim(f):
    keep   = [c for c in KEEP if c in f.MAP]   # mantiene orden de KEEP
    widths = bytearray()
    offs   = []          # offset en bits dentro del nuevo bitmap
    bits   = []          # lista temporal de 0/1
    for c in keep:
        idx = f.MAP.index(c)
        w   = f.WIDTHS[idx]
        widths.append(w)
        # offset de origen (OFFSET_WIDTH bytes, big-endian)
        o  = idx * f.OFFSET_WIDTH
        bo = f.OFFSETS[o]
        for k in range(1, f.OFFSET_WIDTH):
            bo = (bo << 8) + f.OFFSETS[o + k]
        offs.append(len(bits))
        for j in range(w * f.HEIGHT):
            bits.append(_bit(f.BITMAPS, bo + j))
    # empaquetar bits → bytes
    bm = bytearray((len(bits) + 7) // 8)
    for i, b in enumerate(bits):
        if b:
            bm[i >> 3] |= 1 << (7 - (i & 7))
    ow = 3   # OFFSET_WIDTH del nuevo archivo (3 bytes, siempre alcanza)
    ob = bytearray()
    for off in offs:
        ob += off.to_bytes(ow, "big")
    return "".join(keep), bytes(widths), bytes(ob), bytes(bm), ow

def bloque(nombre, f):
    mp, w, ofs, bm, ow = trim(f)
    return (
        "class {}:\n".format(nombre) +
        "    MAP = {!r}\n".format(mp) +
        "    BPP = 1\n" +
        "    HEIGHT = {}\n".format(f.HEIGHT) +
        "    MAX_WIDTH = {}\n".format(f.MAX_WIDTH) +
        "    OFFSET_WIDTH = {}\n".format(ow) +
        "    WIDTHS = {!r}\n".format(w) +
        "    OFFSETS = {!r}\n".format(ofs) +
        "    BITMAPS = {!r}\n".format(bm)
    )

out = ("# -*- coding: utf-8 -*-\n"
       "# fuentes.py — generado por construir_fuentes.py\n"
       "# font_sm = Comfortaa 16px,  font_md = Comfortaa 24px (recortadas)\n\n")
out += bloque("font_sm", f16) + "\n"
out += bloque("font_md", f24) + "\n"

with open("fuentes.py", "w", encoding="utf-8") as fp:
    fp.write(out)

print("fuentes.py generado.")
print("  font_sm chars:", len([c for c in KEEP if c in f16.MAP]))
print("  font_md chars:", len([c for c in KEEP if c in f24.MAP]))
print("  tamaño aprox:", len(out), "bytes")