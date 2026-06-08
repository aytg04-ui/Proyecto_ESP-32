# st7789x

from machine import Pin
import struct
import framebuf
import time

_SWRESET = b"\x01"
_SLPOUT  = b"\x11"
_NORON   = b"\x13"
_INVOFF  = b"\x20"
_INVON   = b"\x21"
_DISPOFF = b"\x28"
_DISPON  = b"\x29"
_CASET   = b"\x2a"
_RASET   = b"\x2b"
_RAMWR   = b"\x2c"
_MADCTL  = b"\x36"
_COLMOD  = b"\x3a"

def color565(r, g=0, b=0):
    if isinstance(r, (tuple, list)):
        r, g, b = r[:3]
    c = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
    return ((c & 0xFF) << 8) | (c >> 8)

BLACK   = color565(0,   0,   0)
WHITE   = color565(255, 255, 255)
RED     = color565(255, 0,   0)
GREEN   = color565(0,   255, 0)
BLUE    = color565(0,   0,   255)
CYAN    = color565(0,   255, 255)
MAGENTA = color565(255, 0,   255)
YELLOW  = color565(255, 255, 0)
ORANGE  = color565(255, 128, 0)

_ROTATIONS_240x320 = (
    (0x00, 240, 320, 0,  0),
    (0x60, 320, 240, 0,  0),
    (0xC0, 240, 320, 0,  0),
    (0xA0, 320, 240, 0,  0),
)
_ROTATIONS_240x240 = (
    (0x00, 240, 240,  0,  0),
    (0x60, 240, 240,  0,  0),
    (0xC0, 240, 240,  0, 80),
    (0xA0, 240, 240, 80,  0),
)
_ROTATIONS_135x240 = (
    (0x00, 135, 240, 52, 40),
    (0x60, 240, 135, 40, 53),
    (0xC0, 135, 240, 53, 40),
    (0xA0, 240, 135, 40, 52),
)
_ROTATIONS_128x128 = (
    (0x00, 128, 128, 2, 1),
    (0x60, 128, 128, 1, 2),
    (0xC0, 128, 128, 2, 1),
    (0xA0, 128, 128, 1, 2),
)

_SUPPORTED = {
    (240, 320): _ROTATIONS_240x320,
    (240, 240): _ROTATIONS_240x240,
    (135, 240): _ROTATIONS_135x240,
    (128, 128): _ROTATIONS_128x128,
}

_BUFFER_SIZE = 256


class Display:
    def __init__(self, spi, dc, cs=None, rst=None, bl=None,
                 width=135, height=240, rotation=0, invert=True):
        key = (width, height)
        if key not in _SUPPORTED:
            raise ValueError(
                f"Display {width}x{height} no soportado. "
                f"Opciones: {list(_SUPPORTED.keys())}"
            )
        self._rotations = _SUPPORTED[key]
        self.spi = spi
        self.dc  = dc
        self.cs  = cs
        self.rst = rst
        self.bl  = bl
        self._invert = invert
        self.physical_w = width
        self.physical_h = height

        self._init_display()
        self.rotation(rotation)

        self._buf = bytearray(self.width * self.height * 2)
        self.fb   = framebuf.FrameBuffer(self._buf, self.width, self.height, framebuf.RGB565)
        self.fb.fill(BLACK)

        self.fill(BLACK)
        if bl:
            bl.on()

    # ── SPI ──────────────────────────────────────────────────────────────────
    def _write(self, cmd=None, data=None):
        if self.cs:
            self.cs.off()
        if cmd is not None:
            self.dc.off()
            self.spi.write(cmd if isinstance(cmd, (bytes, bytearray)) else bytes([cmd]))
        if data is not None:
            self.dc.on()
            self.spi.write(data if isinstance(data, (bytes, bytearray)) else bytes([data]))
        if self.cs:
            self.cs.on()

    # ── Init ─────────────────────────────────────────────────────────────────
    def _init_display(self):
        if self.bl:
            self.bl.off()
        if self.rst:
            self.rst.off()
            time.sleep_ms(100)
            self.rst.on()
            time.sleep_ms(200)
        self._write(0x01); time.sleep_ms(150)
        self._write(0x11); time.sleep_ms(150)
        self._write(0x3A, b'\x55'); time.sleep_ms(10)
        self._write(0xB2, b'\x0C\x0C\x00\x33\x33')
        self._write(0xB7, b'\x35')
        self._write(0xBB, b'\x19')
        self._write(0xC0, b'\x2C')
        self._write(0xC2, b'\x01')
        self._write(0xC3, b'\x12')
        self._write(0xC4, b'\x20')
        self._write(0xC6, b'\x0F')
        self._write(0xD0, b'\xA4\xA1')
        self._write(0xE0, b'\xD0\x04\x0D\x11\x13\x2B\x3F\x54\x4C\x18\x0D\x0B\x1F\x23')
        self._write(0xE1, b'\xD0\x04\x0C\x11\x13\x2C\x3F\x44\x51\x2F\x1F\x1F\x20\x23')
        self._write(0x21 if self._invert else 0x20)
        self._write(0x29); time.sleep_ms(50)
        if self.bl:
            self.bl.on()

    # ── Rotación ─────────────────────────────────────────────────────────────
    def rotation(self, r):
        r = r % 4
        madctl, self.width, self.height, self.xstart, self.ystart = self._rotations[r]
        self._write(0x36, bytes([madctl]))
        if hasattr(self, '_buf'):
            self._buf = bytearray(self.width * self.height * 2)
            self.fb   = framebuf.FrameBuffer(self._buf, self.width, self.height, framebuf.RGB565)

    # ── Ventana de escritura ──────────────────────────────────────────────────
    def _set_window(self, x0, y0, x1, y1):
        xs = x0 + self.xstart
        xe = x1 + self.xstart
        ys = y0 + self.ystart
        ye = y1 + self.ystart
        self._write(_CASET, struct.pack(">HH", xs, xe))
        self._write(_RASET, struct.pack(">HH", ys, ye))
        self._write(_RAMWR)

    # ── show(): vuelca el framebuffer completo a la pantalla ─────────────────
    def show(self):
        self._set_window(0, 0, self.width - 1, self.height - 1)
        if self.cs:
            self.cs.off()
        self.dc.on()
        self.spi.write(self._buf)
        if self.cs:
            self.cs.on()

    # ── Dibujo directo ────────────────────────────────────────────────────────
    def pixel(self, x, y, color):
        if 0 <= x < self.width and 0 <= y < self.height:
            self._set_window(x, y, x, y)
            self._write(None, struct.pack(">H", color))

    def fill(self, color):
        self.fill_rect(0, 0, self.width, self.height, color)

    def clear(self, color=BLACK):
        self.fill(color)

    def fill_rect(self, x, y, w, h, color):
        if w <= 0 or h <= 0:
            return
        self._set_window(x, y, x + w - 1, y + h - 1)
        pixel = struct.pack(">H", color)
        chunk, rest = divmod(w * h, _BUFFER_SIZE)
        if chunk:
            data = pixel * _BUFFER_SIZE
            if self.cs: self.cs.off()
            self.dc.on()
            for _ in range(chunk):
                self.spi.write(data)
            if self.cs: self.cs.on()
        if rest:
            self._write(None, pixel * rest)

    def hline(self, x, y, length, color):
        self.fill_rect(x, y, length, 1, color)

    def vline(self, x, y, length, color):
        self.fill_rect(x, y, 1, length, color)

    def rect(self, x, y, w, h, color):
        self.hline(x,         y,         w, color)
        self.hline(x,         y + h - 1, w, color)
        self.vline(x,         y,         h, color)
        self.vline(x + w - 1, y,         h, color)

    def line(self, x0, y0, x1, y1, color):
        steep = abs(y1 - y0) > abs(x1 - x0)
        if steep:
            x0, y0 = y0, x0
            x1, y1 = y1, x1
        if x0 > x1:
            x0, x1 = x1, x0
            y0, y1 = y1, y0
        dx = x1 - x0
        dy = abs(y1 - y0)
        err = dx // 2
        ystep = 1 if y0 < y1 else -1
        while x0 <= x1:
            if steep: self.pixel(y0, x0, color)
            else:     self.pixel(x0, y0, color)
            err -= dy
            if err < 0:
                y0 += ystep
                err += dx
            x0 += 1

    def circle(self, cx, cy, r, color):
        x, y, err = r, 0, 1 - r
        while x >= y:
            for dx, dy in ((x,y),(-x,y),(x,-y),(-x,-y),(y,x),(-y,x),(y,-x),(-y,-x)):
                self.pixel(cx + dx, cy + dy, color)
            y += 1
            if err < 0: err += 2 * y + 1
            else:
                x -= 1
                err += 2 * (y - x) + 1

    def fill_circle(self, cx, cy, r, color):
        x, y, err = r, 0, 1 - r
        while x >= y:
            self.hline(cx - x, cy + y, 2 * x + 1, color)
            self.hline(cx - x, cy - y, 2 * x + 1, color)
            self.hline(cx - y, cy + x, 2 * y + 1, color)
            self.hline(cx - y, cy - x, 2 * y + 1, color)
            y += 1
            if err < 0: err += 2 * y + 1
            else:
                x -= 1
                err += 2 * (y - x) + 1

    def polygon(self, points, x_offset=0, y_offset=0, color=WHITE):
        if len(points) < 2:
            return
        pts = [(px + x_offset, py + y_offset) for px, py in points]
        for i in range(1, len(pts)):
            self.line(pts[i-1][0], pts[i-1][1], pts[i][0], pts[i][1], color)
        self.line(pts[-1][0], pts[-1][1], pts[0][0], pts[0][1], color)

    def blit_buffer(self, buf, x, y, w, h):
        self._set_window(x, y, x + w - 1, y + h - 1)
        self._write(None, buf)

    # ── Texto con fuente externa (bitmap) ─────────────────────────────────────
    def text(self, font, txt, x, y, fg=WHITE, bg=BLACK):
        """Texto con font externo — dibuja directo al hardware."""
        for ch in txt:
            code = ord(ch)
            if not (font.FIRST <= code < font.LAST):
                continue
            if x + font.WIDTH > self.width or y + font.HEIGHT > self.height:
                break
            idx = (code - font.FIRST) * font.WIDTH * ((font.HEIGHT + 7) // 8)
            buf = bytearray(font.WIDTH * font.HEIGHT * 2)
            bit = 0
            for row in range(font.HEIGHT):
                for col in range(font.WIDTH):
                    byte_idx = idx + (bit // 8)
                    bit_val  = (font.FONT[byte_idx] >> (7 - (bit % 8))) & 1
                    color    = fg if bit_val else bg
                    offset   = (row * font.WIDTH + col) * 2
                    buf[offset]     = (color >> 8) & 0xFF
                    buf[offset + 1] = color & 0xFF
                    bit += 1
            self.blit_buffer(buf, x, y, font.WIDTH, font.HEIGHT)
            x += font.WIDTH

    # ── text_big(): texto escalado en el framebuffer ──────────────────────────
    #
    #  Escala la fuente 8×8 integrada de MicroPython multiplicando cada píxel.
    #
    #  Parámetros:
    #    txt    — cadena de texto
    #    x, y   — posición inicial en el framebuffer
    #    color  — color del texto (color565)
    #    scale  — factor de escala entero (2 = 16×16, 3 = 24×24)
    #    bg     — color de fondo (por defecto BLACK)
    #    max_w  — ancho máximo permitido en píxeles (trunca si se sale)
    #
    #  Ejemplo de uso:
    #    display.text_big("HOLA",  5, 10, st7789.YELLOW, scale=2)   # 16px alto
    #    display.text_big("38.5C", 5, 40, st7789.RED,    scale=3)   # 24px alto
    #    display.text_big("OK",    5, 80, st7789.GREEN,  scale=2, max_w=60)
    # ─────────────────────────────────────────────────────────────────────────
    def text_big(self, txt, x, y, color, scale=2, bg=BLACK, max_w=None):
        CHAR_W = 8
        CHAR_H = 8
        if max_w is None:
            max_w = self.width - x

        tiny_buf = bytearray(CHAR_W * CHAR_H * 2)
        tiny_fb  = framebuf.FrameBuffer(tiny_buf, CHAR_W, CHAR_H, framebuf.RGB565)

        cur_x = x
        for ch in txt:
            if cur_x + CHAR_W * scale > x + max_w:
                break
            if cur_x + CHAR_W * scale > self.width:
                break

            tiny_fb.fill(bg)
            tiny_fb.text(ch, 0, 0, color)

            for row in range(CHAR_H):
                for col in range(CHAR_W):
                    idx = (row * CHAR_W + col) * 2
                    px  = (tiny_buf[idx] << 8) | tiny_buf[idx + 1]
                    for sy in range(scale):
                        dy = y + row * scale + sy
                        if dy >= self.height:
                            continue
                        for sx in range(scale):
                            dx = cur_x + col * scale + sx
                            if dx < self.width:
                                self.fb.pixel(dx, dy, px)

            cur_x += CHAR_W * scale

    # ── text_wrap(): texto 8×8 con word-wrap automático ───────────────────────
    #
    #  Parte el texto en líneas respetando el ancho máximo.
    #  Si una palabra no cabe en la línea actual, salta a la siguiente.
    #  Si una sola palabra es más larga que el ancho, la parte forzado.
    #
    #  Parámetros:
    #    txt    — cadena de texto (puede tener espacios)
    #    x, y   — posición inicial
    #    color  — color del texto
    #    max_w  — ancho máximo en píxeles (default: hasta el borde derecho)
    #    line_h — alto de línea en píxeles (default: 10 = 8px letra + 2px aire)
    #
    #  Retorna: la coordenada y donde terminó el texto (útil para continuar)
    #
    #  Ejemplo:
    #    y = display.text_wrap("Texto largo que se parte solo", 0, 0, st7789.WHITE)
    #    y = display.text_wrap("Más texto debajo", 0, y, st7789.YELLOW)
    #    display.show()
    # ─────────────────────────────────────────────────────────────────────────
    def text_wrap(self, txt, x, y, color, max_w=None, line_h=10):
        if max_w is None:
            max_w = self.width - x
        max_chars = max_w // 8

        palabras = txt.split(' ')
        linea = ''
        for palabra in palabras:
            prueba = linea + (' ' if linea else '') + palabra
            if len(prueba) <= max_chars:
                linea = prueba
            else:
                if linea:
                    self.fb.text(linea, x, y, color)
                    y += line_h
                # Palabra más larga que el ancho: partir forzado
                while len(palabra) > max_chars:
                    self.fb.text(palabra[:max_chars], x, y, color)
                    y += line_h
                    palabra = palabra[max_chars:]
                linea = palabra
        if linea:
            self.fb.text(linea, x, y, color)
            y += line_h
        return y

    # ── header(): encabezado izquierda/derecha en una sola llamada ────────────
    #
    #  Divide el ancho de la pantalla entre dos textos.
    #  El texto izquierdo ocupa 'split' píxeles; el derecho el resto.
    #
    #  Parámetros:
    #    izq        — texto izquierdo
    #    der        — texto derecho
    #    color_izq  — color del texto izquierdo
    #    color_der  — color del texto derecho (default WHITE)
    #    y          — fila vertical (default 0)
    #    split      — píxel donde empieza el texto derecho (default: mitad)
    #
    #  Ejemplo:
    #    display.header("Central B", "P35:sig P0:menu", st7789.YELLOW)
    #    display.header("Central B", "P35:sig P0:menu", st7789.YELLOW, split=80)
    # ─────────────────────────────────────────────────────────────────────────
    def header(self, izq, der, color_izq, color_der=WHITE, y=0, split=None):
        if split is None:
            split = self.width // 2
        max_izq = split // 8
        max_der = (self.width - split) // 8
        self.fb.text(izq[:max_izq], 0,     y, color_izq)
        self.fb.text(der[:max_der], split, y, color_der)

    # ── Utilidades ────────────────────────────────────────────────────────────
    def text_simple(self, txt, x, y, color, bg=BLACK, scale=1):
        self.fb.text(txt, x, y, color)

    def window(self, x0, y0, x1, y1):
        self._set_window(x0, y0, x1, y1)

    def invert(self, on=True):
        self._write(0x21 if on else 0x20)

    def sleep(self, on=True):
        self._write(0x10 if on else 0x11)
        time.sleep_ms(120)

    def backlight(self, on=True):
        if self.bl:
            self.bl.on() if on else self.bl.off()

    def clip_text(self, txt, max_chars):
        return txt[:max_chars]

    def text_clipped(self, txt, x, y, color, max_w=None):
        """Texto 8×8 en fb truncando si excede max_w píxeles."""
        if max_w is None:
            max_w = self.width - x
        max_chars = max_w // 8
        self.fb.text(txt[:max_chars], x, y, color)