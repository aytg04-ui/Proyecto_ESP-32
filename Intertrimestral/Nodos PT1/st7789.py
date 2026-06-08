# st7789.py ST7789
from machine import Pin
import time
import framebuf

# --------------------------------
# Conversión RGB → RGB565
# --------------------------------
def color565(r, g, b):
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)

# Colores básicos
BLACK   = color565(0,0,0)
WHITE   = color565(255,255,255)
RED     = color565(255,0,0)
GREEN   = color565(0,255,0)
BLUE    = color565(0,0,255)
YELLOW  = color565(255,255,0)
CYAN    = color565(0,255,255)
MAGENTA = color565(255,0,255)

class Display:

    def __init__(self, spi, dc, cs, rst, bl):

        self.spi = spi
        self.dc = dc
        self.cs = cs
        self.rst = rst
        self.bl  = bl  

        bl.on()

        self.width = 135
        self.height = 240

        self.xoff = 52
        self.yoff = 40

        # Buffer gráfico
        self.buffer = bytearray(self.width * self.height * 2)
        self.fb = framebuf.FrameBuffer(
            self.buffer,
            self.width,
            self.height,
            framebuf.RGB565
        )

    # ----------------------------
    # Enviar comandos
    # ----------------------------

    def cmd(self,c):
        self.cs.off()
        self.dc.off()
        self.spi.write(bytearray([c]))
        self.cs.on()

    def data(self,d):
        self.cs.off()
        self.dc.on()
        self.spi.write(d)
        self.cs.on()

    # ----------------------------
    # Inicializar pantalla
    # ----------------------------

    def init(self):
        # Apagar backlight durante reset
        self.bl.off()
        
        self.rst.off()
        time.sleep_ms(200)
        self.rst.on()
        time.sleep_ms(200)
        
        # Encender backlight
        self.bl.on()
        time.sleep_ms(50)
        
        self.cmd(0x01)        # Software reset
        time.sleep_ms(150)
        self.cmd(0x11)        # Sleep out
        time.sleep_ms(150)
        self.cmd(0x3A)
        self.data(bytearray([0x55]))
        time.sleep_ms(10)
        self.cmd(0x36)
        self.data(bytearray([0x00]))
        time.sleep_ms(10)
        self.cmd(0x21)
        self.cmd(0x29)
        time.sleep_ms(50)

    # ----------------------------
    # Área visible
    # ----------------------------

    def window(self, x0, y0, x1, y1):
        # Columnas
        self.cmd(0x2A)
        self.data(bytearray([
            (x0 + self.xoff) >> 8,
            (x0 + self.xoff) & 0xFF,
            (x1 + self.xoff) >> 8,
            (x1 + self.xoff) & 0xFF
        ]))
        # Filas
        self.cmd(0x2B)
        self.data(bytearray([
            (y0 + self.yoff) >> 8,
            (y0 + self.yoff) & 0xFF,
            (y1 + self.yoff) >> 8,
            (y1 + self.yoff) & 0xFF
        ]))
        self.cmd(0x2C)

    # ----------------------------
    # Mostrar buffer
    # ----------------------------

    def show(self):
        self.window(0, 0, self.width - 1, self.height - 1)
        self.cs.off()
        self.dc.on()
        self.spi.write(self.buffer)
        self.cs.on()

    # ----------------------------
    # Escribir texto
    # ----------------------------

    def text(self, txt, x, y, color):
        self.fb.text(txt, x, y, color)

    # ----------------------------
    # Limpiar pantalla
    # ----------------------------

    def clear(self, color=BLACK):
        self.fb.fill(color)

    def fill_color_raw(self, color):
        self.window(0, 0, self.width - 1, self.height - 1)  # ← 4 argumentos
        self.cs.off()
        self.dc.on()
        chunk = bytearray([color >> 8, color & 0xFF] * 100)
        for _ in range(self.width * self.height // 100):
            self.spi.write(chunk)
        self.cs.on()

