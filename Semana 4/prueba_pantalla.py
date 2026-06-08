# prueba_pantalla.py — Diagnóstico de la TTGO T-Display
# Sube esto como un archivo aparte y córrelo en Thonny (no como main.py).
# Avanza entre pruebas con el botón P35. Lee la consola para saber qué
# DEBERÍA verse en cada paso.
#
# Necesita: st7789.py y fuentes.py en el dispositivo.
#
# Si tras aplicar el fix de fill_rect sigue habiendo puntitos:
#   - Cambia SPI_BUS a 2 (la TTGO suele usar el bus 2 / VSPI).
#   - Baja BAUD a 10_000_000 (ruido por velocidad).
# Repite y compara.

import st7789
from fuentes import font_sm, font_md
from machine import Pin, SPI
import time

# ─── AJUSTA AQUÍ Y VUELVE A CORRER ───
SPI_BUS = 1            # prueba 1 (tu Nodo A) y luego 2
BAUD    = 20_000_000   # si hay ruido: 10_000_000  /  o sube a 27_000_000
ROT     = 1

C = st7789

spi = SPI(SPI_BUS, baudrate=BAUD, polarity=0, phase=0,
          sck=Pin(18), mosi=Pin(19))
tft = st7789.ST7789(spi, 135, 240,
                    dc=Pin(16, Pin.OUT), cs=Pin(5, Pin.OUT),
                    reset=Pin(23, Pin.OUT), backlight=Pin(4, Pin.OUT),
                    rotation=ROT)

btn = Pin(35, Pin.IN, Pin.PULL_UP)

def siguiente(msg):
    print(msg, " -> P35 para continuar")
    while btn.value() == 1: time.sleep_ms(20)   # espera press
    while btn.value() == 0: time.sleep_ms(20)   # espera release
    time.sleep_ms(150)

print("\n=== PRUEBA PANTALLA  bus:{}  baud:{} ===".format(SPI_BUS, BAUD))

while True:
    # 1) FILLS SÓLIDOS — prueba SPI + fill_rect + color
    for nombre, col in (("ROJO", C.RED), ("VERDE", C.GREEN), ("AZUL", C.BLUE),
                        ("BLANCO", C.WHITE), ("NEGRO", C.BLACK)):
        tft.fill(col)
        siguiente("1) Fill " + nombre + ": pantalla COMPLETA y uniforme del color")

    # 2) BARRAS — prueba fill_rect en zonas
    tft.fill(C.BLACK)
    cols = (C.RED, C.GREEN, C.BLUE, C.YELLOW, C.CYAN, C.MAGENTA)
    x = 0
    for i in range(12):
        tft.fill_rect(x, 0, 18, 135, cols[i % len(cols)])
        x += 20
    siguiente("2) Barras verticales nítidas, sin puntitos entre ellas")

    # 3) TEXTO sobre negro — prueba write() y las fuentes
    tft.fill(C.BLACK)
    tft.write(font_md, "AaBb 38.5", C.WHITE,  x=2, y=6)
    tft.write(font_md, "1234 OK",   C.CYAN,   x=2, y=42)
    tft.write(font_sm, "abcdef ghijk", C.YELLOW, x=2, y=84)
    tft.write(font_sm, "acentos: a e i o u n", C.GREEN, x=2, y=108)
    tft.write(font_md, "áéíóú ñÑ", st7789.WHITE, x=120, y=40)
    tft.write(font_sm, "38.5°C ¡OK!", st7789.CYAN, x=120, y=90)
    siguiente("3) Texto limpio, SIN puntitos de color alrededor")

    # 4) ACENTOS Y SÍMBOLOS — confirma que el recorte de fuentes los incluye
    tft.fill(C.BLACK)
    tft.write(font_md, "38.5\u00b0C",  C.WHITE, x=2, y=10)   # °
    tft.write(font_md, "\u00a1ALERTA!", C.RED,   x=2, y=50)  # ¡
    tft.write(font_sm, "anio nino sec", C.CYAN,  x=2, y=95)
    siguiente("4) Se ven el grado y el signo de exclamacion inicial")

    # 5) TEXTO sobre fondo de color — prueba el bg de write()
    tft.fill(C.BLUE)
    tft.write(font_md, "Fondo azul", C.WHITE, bg=C.BLUE, x=4, y=40)
    siguiente("5) El fondo de las letras coincide con el azul (sin recuadro)")

    print("--- Vuelta completa, repite ---\n")