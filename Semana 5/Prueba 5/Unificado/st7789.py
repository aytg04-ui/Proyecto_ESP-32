# st7789.py 

import struct
from time import sleep_ms

# ─────────────────────────────────────────
#  COLORES
# ─────────────────────────────────────────
def color565(r, g=0, b=0):
    if isinstance(r, (tuple, list)): r, g, b = r[:3]
    return (r & 0xF8) << 8 | (g & 0xFC) << 3 | b >> 3

BLACK   = const(0x0000)
WHITE   = const(0xFFFF)
RED     = const(0xF800)
GREEN   = const(0x07E0)
BLUE    = const(0x001F)
CYAN    = const(0x07FF)
MAGENTA = const(0xF81F)
YELLOW  = const(0xFFE0)
ORANGE  = color565(255, 128, 0)

# ─────────────────────────────────────────
#  ROTACIONES — solo 135x240
#  (madctl, width, height, xstart, ystart)
# ─────────────────────────────────────────
_ROT = (
    (0x00, 135, 240, 52, 40),
    (0x60, 240, 135, 40, 53),
    (0xC0, 135, 240, 53, 40),
    (0xA0, 240, 135, 40, 52),
)

# ─────────────────────────────────────────
#  COMANDOS ST7789
# ─────────────────────────────────────────
_CASET  = b"\x2a"
_RASET  = b"\x2b"
_RAMWR  = b"\x2c"
_MADCTL = b"\x36"
_INVON  = b"\x21"
_INVOFF = b"\x20"
_SLPIN  = b"\x10"
_SLPOUT = b"\x11"

_INIT = (
    (b"\x11", b"\x00", 120),
    (b"\x13", b"\x00", 0),
    (b"\xb6", b"\x0a\x82", 0),
    (b"\x3a", b"\x55", 10),
    (b"\xb2", b"\x0c\x0c\x00\x33\x33", 0),
    (b"\xb7", b"\x35", 0),
    (b"\xbb", b"\x28", 0),
    (b"\xc0", b"\x0c", 0),
    (b"\xc2", b"\x01\xff", 0),
    (b"\xc3", b"\x10", 0),
    (b"\xc4", b"\x20", 0),
    (b"\xc6", b"\x0f", 0),
    (b"\xd0", b"\xa4\xa1", 0),
    (b"\xe0", b"\xd0\x00\x02\x07\x0a\x28\x32\x44\x42\x06\x0e\x12\x14\x17", 0),
    (b"\xe1", b"\xd0\x00\x02\x07\x0a\x28\x31\x54\x47\x0e\x1c\x17\x1b\x1e", 0),
    (b"\x21", b"\x00", 0),
    (b"\x29", b"\x00", 120),
)

_BUFFER_SIZE = const(256)


class ST7789:
    def __init__(self, spi, width, height, dc, cs=None, reset=None,
                 backlight=None, rotation=0):
        self.spi = spi
        self.dc  = dc
        self.cs  = cs
        self.rst = reset
        self.bl  = backlight
        self._cx = 0    # cursor x
        self._cy = 0    # cursor y

        self._hard_reset()
        for cmd, data, delay in _INIT:
            self._write(cmd, data)
            if delay: sleep_ms(delay)

        self.rotation(rotation)
        self.fill(BLACK)
        if self.bl: self.bl.on()

    # ─── SPI ──────────────────────────────
    def _write(self, cmd=None, data=None):
        if self.cs: self.cs.off()
        if cmd is not None:
            self.dc.off()
            self.spi.write(cmd if isinstance(cmd, (bytes, bytearray)) else bytes([cmd]))
        if data is not None:
            self.dc.on()
            self.spi.write(data if isinstance(data, (bytes, bytearray)) else bytes([data]))
        if self.cs: self.cs.on()

    def _hard_reset(self):
        if self.cs: self.cs.on()
        if self.rst:
            self.rst.on();  sleep_ms(10)
            self.rst.off(); sleep_ms(10)
            self.rst.on();  sleep_ms(120)

    def _set_window(self, x0, y0, x1, y1):
        self._write(_CASET, struct.pack(">HH", x0 + self.xs, x1 + self.xs))
        self._write(_RASET, struct.pack(">HH", y0 + self.ys, y1 + self.ys))
        self._write(_RAMWR)

    # ─── ROTACIÓN ─────────────────────────
    def rotation(self, r):
        madctl, self.width, self.height, self.xs, self.ys = _ROT[r % 4]
        madctl |= 0x08          # ← BGR: el panel TTGO usa orden BGR (corrige rojo/azul)
        self._write(_MADCTL, bytes([madctl]))

    # ─── PRIMITIVAS ───────────────────────
    def fill(self, color):
        self.fill_rect(0, 0, self.width, self.height, color)

    def fill_rect(self, x, y, w, h, color):
        if w <= 0 or h <= 0: return
        self._set_window(x, y, x + w - 1, y + h - 1)
        pixel  = struct.pack(">H", color)
        chunks, rest = divmod(w * h, _BUFFER_SIZE)
        if self.cs: self.cs.off()        # ← CS BAJO durante TODO el volcado
        self.dc.on()
        if chunks:
            data = pixel * _BUFFER_SIZE
            for _ in range(chunks):
                self.spi.write(data)
        if rest:
            self.spi.write(pixel * rest)
        if self.cs: self.cs.on()         # ← CS ALTO al terminar

    def hline(self, x, y, l, c): self.fill_rect(x, y, l,  1, c)
    def vline(self, x, y, l, c): self.fill_rect(x, y, 1,  l, c)

    def rect(self, x, y, w, h, color):
        self.hline(x,     y,     w, color)
        self.hline(x,     y+h-1, w, color)
        self.vline(x,     y,     h, color)
        self.vline(x+w-1, y,     h, color)

    def pixel(self, x, y, color):
        self._set_window(x, y, x, y)
        self._write(None, struct.pack(">H", color))

    # ─── ANCHO DE TEXTO ───────────────────
    def text_width(self, font, text):
        """Ancho en píxeles del texto con esa fuente."""
        w = 0
        for ch in text:
            try: w += font.WIDTHS[font.MAP.index(ch)]
            except ValueError: pass
        return w

    # ─── WRITE UNIFICADO ──────────────────
    def write(self, font, text, color=WHITE, bg=BLACK,
              x=None, y=None, center=False, end="\n"):
        """
        Método único para escribir texto. Detecta el modo por los argumentos:

          Sin x,y   → usa cursor, lo avanza al terminar  (como print)
          Con x,y   → posición exacta, cursor no cambia  (como write viejo)
          center=True → calcula x para centrar horizontalmente

        Ejemplos:
            # Cursor automático (varias líneas seguidas)
            tft.cursor(4, 10)
            tft.write(font_sm, "Nodo A",    CYAN)
            tft.write(font_sm, "Conectado", VERDE)
            tft.write(font_md, "38.5C",     ROJO)

            # Posición exacta (sabes dónde va)
            tft.write(font_sm, "Nodo A", CYAN, x=4, y=2)
            tft.write(font_md, "38.5C",  ROJO, x=4, y=30)

            # Centrado automático
            tft.write(font_md, "ALERTA", ROJO, y=40, center=True)

            # Sin salto de línea (misma línea)
            tft.write(font_sm, "Amb: 24.1  ", BLANCO, end="")
            tft.write(font_sm, "Obj: 38.5",  ROJO)
        """
        use_cursor = (x is None and y is None)

        # Posición de dibujado
        px = self._cx if x is None else x
        py = self._cy if y is None else y

        buf = bytearray(font.HEIGHT * font.MAX_WIDTH * 2)
        fg_hi, fg_lo = color >> 8, color & 0xFF
        bg_hi, bg_lo = bg    >> 8, bg    & 0xFF

        def _line_x(line):
            return max(0, (self.width - self.text_width(font, line)) // 2) if center else px

        lines = text.split("\n")
        draw_x = _line_x(lines[0])
        line_i = 0

        for ch in text:
            # Salto de línea
            if ch == "\n":
                py    += font.HEIGHT + 2
                line_i += 1
                draw_x  = _line_x(lines[line_i]) if line_i < len(lines) else px
                continue

            try:
                idx    = font.MAP.index(ch)
                offset = idx * font.OFFSET_WIDTH
                bs_bit = font.OFFSETS[offset]
                if font.OFFSET_WIDTH > 1:
                    bs_bit = (bs_bit << 8) + font.OFFSETS[offset + 1]
                if font.OFFSET_WIDTH > 2:
                    bs_bit = (bs_bit << 8) + font.OFFSETS[offset + 2]

                ch_w   = font.WIDTHS[idx]
                needed = ch_w * font.HEIGHT * 2

                for i in range(0, needed, 2):
                    if font.BITMAPS[bs_bit // 8] & (1 << (7 - bs_bit % 8)):
                        buf[i], buf[i+1] = fg_hi, fg_lo
                    else:
                        buf[i], buf[i+1] = bg_hi, bg_lo
                    bs_bit += 1

                if draw_x + ch_w <= self.width and py + font.HEIGHT <= self.height:
                    self._set_window(draw_x, py, draw_x + ch_w - 1, py + font.HEIGHT - 1)
                    self._write(None, buf[:needed])
                draw_x += ch_w
            except ValueError:
                pass

        # Mover cursor solo si estábamos en modo cursor
        if use_cursor:
            if end == "\n":
                self._cy = py + font.HEIGHT + 2
            else:
                self._cx = draw_x   # misma línea

    # ─── CURSOR ───────────────────────────
    def cursor(self, x=0, y=0):
        """Posiciona el cursor. Uso: tft.cursor(4, 10)"""
        self._cx, self._cy = x, y

    # ─── HEADER ───────────────────────────
    def header(self, font, segments):
        """
        Barra superior dividida en zonas. Mueve el cursor debajo al terminar.
        segments: lista de (texto, color) o (texto, color, "right"/"center")

        Uso:
            tft.header(font_sm, [
                ("Central B",     YELLOW),
                ("P35:nav P0:ok", WHITE, "right"),
            ])
        """
        zone_w = self.width // len(segments)

        for i, seg in enumerate(segments):
            txt, color = seg[0], seg[1]
            align = seg[2] if len(seg) > 2 else "left"
            x_ini = i * zone_w

            if align == "right":
                x = x_ini + zone_w - self.text_width(font, txt)
            elif align == "center":
                x = x_ini + (zone_w - self.text_width(font, txt)) // 2
            else:
                x = x_ini

            self.write(font, txt, color, x=max(x_ini, x), y=0)

        self._cx = 0
        self._cy = font.HEIGHT + 2

    # ─── CONTROL DEL DISPLAY ──────────────
    def invert(self, on=True):
        self._write(_INVON if on else _INVOFF)

    def sleep(self, on=True):
        self._write(_SLPIN if on else _SLPOUT)
        sleep_ms(120)

    def backlight(self, on=True):
        if self.bl: self.bl.on() if on else self.bl.off()
