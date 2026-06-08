# st7789.py  

from machine import Pin
import struct
import framebuf  # Solo para text_simple() — texto 8x8 sin font module
import time

# ─── Constantes de comandos ST7789 ───────────────────────────────────────────
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

# ─── Colores básicos en RGB565 ───────────────────────────────────
def color565(r, g=0, b=0):

    if isinstance(r, (tuple, list)):
        r, g, b = r[:3]
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)

BLACK   = color565(0,   0,   0)
WHITE   = color565(255, 255, 255)
RED     = color565(255, 0,   0)
GREEN   = color565(0,   255, 0)
BLUE    = color565(0,   0,   255)
CYAN    = color565(0,   255, 255)
MAGENTA = color565(255, 0,   255)
YELLOW  = color565(255, 255, 0)
ORANGE  = color565(255, 128, 0)

# ─── Tablas de rotación por resolución ───────────────────────────────────────
# Cada tupla: (madctl, width, height, xstart, ystart)
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
_ROTATIONS_135x240 = (      # TTGO T-Display
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

_BUFFER_SIZE = 256  # píxeles por chunk en fill_rect

# ─── Clase principal ──────────────────────────────────────────────────────────
class Display:
    """
    Parámetros
    ----------
    spi      : objeto SPI configurado
    dc       : Pin de datos/comando  (obligatorio)
    cs       : Pin chip-select
    rst      : Pin de reset
    bl       : Pin de backlight (opcional; si se pasa, lo controla el driver)
    width    : ancho físico del panel  (default 135 para TTGO)
    height   : alto físico del panel   (default 240 para TTGO)
    rotation : 0=Portrait, 1=Landscape, 2=Portrait invertido, 3=Landscape invertido
    invert   : True para invertir colores (la mayoría de los ST7789 lo necesitan)
    """

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

        # Aplicar rotación inicial (también setea self.width, self.height, etc.)
        self._init_display()
        self.rotation(rotation)
        self.fill(BLACK)
        if bl:
            bl.on()

    # ── Comunicación SPI ─────────────────────────────────────────────────────
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

    # ── Inicialización ───────────────────────────────────────────────────────
    def _init_display(self):
        if self.bl:
            self.bl.off()

        # Reset hardware
        if self.rst:
            self.rst.off()
            time.sleep_ms(100)
            self.rst.on()
            time.sleep_ms(200)

        # Secuencia de inicio
        self._write(0x01)       # Software reset
        time.sleep_ms(150)
        self._write(0x11)       # Sleep out
        time.sleep_ms(150)
        self._write(0x3A, b'\x55')  # Pixel format: 16 bpp RGB565
        time.sleep_ms(10)
        self._write(0xB2, b'\x0C\x0C\x00\x33\x33')  # Porch control
        self._write(0xB7, b'\x35')   # Gate control
        self._write(0xBB, b'\x19')   # VCOMS
        self._write(0xC0, b'\x2C')   # LCM control
        self._write(0xC2, b'\x01')   # VDV/VRH enable
        self._write(0xC3, b'\x12')   # VRH set
        self._write(0xC4, b'\x20')   # VDV set
        self._write(0xC6, b'\x0F')   # FR control 2
        self._write(0xD0, b'\xA4\xA1')  # Power control 1
        # Curvas gamma positiva y negativa
        self._write(0xE0, b'\xD0\x04\x0D\x11\x13\x2B\x3F\x54\x4C\x18\x0D\x0B\x1F\x23')
        self._write(0xE1, b'\xD0\x04\x0C\x11\x13\x2C\x3F\x44\x51\x2F\x1F\x1F\x20\x23')

        if self._invert:
            self._write(0x21)   # Display inversion ON
        else:
            self._write(0x20)

        self._write(0x29)       # Display ON
        time.sleep_ms(50)

        if self.bl:
            self.bl.on()

    # ── Rotación ─────────────────────────────────────────────────────────────
    def rotation(self, r):
        """Cambia la rotación: 0=Portrait, 1=Landscape, 2=Portrait inv, 3=Landscape inv."""
        r = r % 4
        madctl, self.width, self.height, self.xstart, self.ystart = self._rotations[r]
        self._write(0x36, bytes([madctl]))

    # ── Ventana de escritura ──────────────────────────────────────────────────
    def _set_window(self, x0, y0, x1, y1):
        xs = x0 + self.xstart
        xe = x1 + self.xstart
        ys = y0 + self.ystart
        ye = y1 + self.ystart
        self._write(_CASET, struct.pack(">HH", xs, xe))
        self._write(_RASET, struct.pack(">HH", ys, ye))
        self._write(_RAMWR)

    # ── Primitivas de dibujo ─────────────────────────────────────────────────

    def pixel(self, x, y, color):
        """Dibuja un píxel."""
        if 0 <= x < self.width and 0 <= y < self.height:
            self._set_window(x, y, x, y)
            self._write(None, struct.pack(">H", color))

    def fill(self, color):
        """Rellena toda la pantalla con un color."""
        self.fill_rect(0, 0, self.width, self.height, color)

    def clear(self, color=BLACK):
        """Alias de fill(). Limpia la pantalla."""
        self.fill(color)

    def fill_rect(self, x, y, w, h, color):
        """Rectángulo relleno."""
        if w <= 0 or h <= 0:
            return
        self._set_window(x, y, x + w - 1, y + h - 1)
        pixel = struct.pack(">H", color)
        chunk, rest = divmod(w * h, _BUFFER_SIZE)
        if chunk:
            data = pixel * _BUFFER_SIZE
            if self.cs:
                self.cs.off()
            self.dc.on()
            for _ in range(chunk):
                self.spi.write(data)
            if self.cs:
                self.cs.on()
        if rest:
            self._write(None, pixel * rest)

    def hline(self, x, y, length, color):
        """Línea horizontal."""
        self.fill_rect(x, y, length, 1, color)

    def vline(self, x, y, length, color):
        """Línea vertical."""
        self.fill_rect(x, y, 1, length, color)

    def rect(self, x, y, w, h, color):
        """Rectángulo (solo borde)."""
        self.hline(x,         y,         w, color)
        self.hline(x,         y + h - 1, w, color)
        self.vline(x,         y,         h, color)
        self.vline(x + w - 1, y,         h, color)

    def line(self, x0, y0, x1, y1, color):
        """Línea entre dos puntos (Bresenham)."""
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
            if steep:
                self.pixel(y0, x0, color)
            else:
                self.pixel(x0, y0, color)
            err -= dy
            if err < 0:
                y0 += ystep
                err += dx
            x0 += 1

    def circle(self, cx, cy, r, color):
        """Círculo borde usando Midpoint circle."""
        x, y, err = r, 0, 1 - r
        while x >= y:
            for dx, dy in ((x,y),(-x,y),(x,-y),(-x,-y),(y,x),(-y,x),(y,-x),(-y,-x)):
                self.pixel(cx + dx, cy + dy, color)
            y += 1
            if err < 0:
                err += 2 * y + 1
            else:
                x -= 1
                err += 2 * (y - x) + 1

    def fill_circle(self, cx, cy, r, color):
        """Círculo relleno."""
        x, y, err = r, 0, 1 - r
        while x >= y:
            self.hline(cx - x, cy + y, 2 * x + 1, color)
            self.hline(cx - x, cy - y, 2 * x + 1, color)
            self.hline(cx - y, cy + x, 2 * y + 1, color)
            self.hline(cx - y, cy - x, 2 * y + 1, color)
            y += 1
            if err < 0:
                err += 2 * y + 1
            else:
                x -= 1
                err += 2 * (y - x) + 1

    def polygon(self, points, x_offset=0, y_offset=0, color=WHITE):
        """Polígono a partir de lista de puntos [(x0,y0),(x1,y1),...].
        Cierra automáticamente el último segmento al primero.
        """
        if len(points) < 2:
            return
        pts = [(px + x_offset, py + y_offset) for px, py in points]
        for i in range(1, len(pts)):
            self.line(pts[i-1][0], pts[i-1][1], pts[i][0], pts[i][1], color)
        self.line(pts[-1][0], pts[-1][1], pts[0][0], pts[0][1], color)

    def blit_buffer(self, buf, x, y, w, h):
        """Copia un buffer RGB565 (bytes/bytearray) a la pantalla."""
        self._set_window(x, y, x + w - 1, y + h - 1)
        self._write(None, buf)

    # ── Texto ─────────────────────────────────────────────────────────────────

    def text_simple(self, txt, x, y, color, bg=BLACK, scale=1):
        """Texto 8×8 sin módulo de fuente externo.
        Usa el font 8×8 integrado en MicroPython vía framebuf.
        Equivalente al antiguo display.text() / display.fb.text().

        Si scale > 1 amplía el texto (útil para fuentes más grandes).
        """
        char_w = 8 * scale
        char_h = 8 * scale
        buf = bytearray(8 * 8 * 2)
        fb  = framebuf.FrameBuffer(buf, 8, 8, framebuf.RGB565)
        for ch in txt:
            if x + char_w > self.width:
                break
            fb.fill(bg)
            fb.text(ch, 0, 0, color)
            if scale == 1:
                self.blit_buffer(buf, x, y, 8, 8)
            else:
                # Ampliar manualmente
                scaled = bytearray(char_w * char_h * 2)
                sfb = framebuf.FrameBuffer(scaled, char_w, char_h, framebuf.RGB565)
                for row in range(8):
                    for col in range(8):
                        # Leer color del píxel original
                        idx = (row * 8 + col) * 2
                        c16 = (buf[idx] << 8) | buf[idx + 1]
                        sfb.fill_rect(col * scale, row * scale, scale, scale, c16)
                self.blit_buffer(scaled, x, y, char_w, char_h)
            x += char_w

    def text(self, font, txt, x, y, fg=WHITE, bg=BLACK):
        """Texto con módulo de fuente externo (8-bit o 16-bit bitmap fonts).
        Uso: display.text(mi_font, "Hola", 10, 20, RED)

        Los font modules deben tener: FONT, FIRST, LAST, WIDTH, HEIGHT.
        """
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

    # ── Compatibilidad con versión anterior ───────────────────────────────────

    def show(self):
        pass

    def window(self, x0, y0, x1, y1):
        """Alias de _set_window() para compatibilidad."""
        self._set_window(x0, y0, x1, y1)

    # ── Utilidades ────────────────────────────────────────────────────────────

    def invert(self, on=True):
        """Activa/desactiva inversión de colores en hardware."""
        self._write(0x21 if on else 0x20)

    def sleep(self, on=True):
        """Manda la pantalla a sleep (True) o la despierta (False)."""
        self._write(0x10 if on else 0x11)
        time.sleep_ms(120)

    def backlight(self, on=True):
        """Controla el backlight si se configuró el pin bl."""
        if self.bl:
            self.bl.on() if on else self.bl.off()