# GY-906
from machine import Pin, SPI, I2C, deepsleep
import time
import st7789
import mlx90614

# -------------------------
# I2C Sensor MLX90614
# -------------------------
i2c = I2C(0, scl=Pin(22), sda=Pin(21), freq=100000)
print("I2C devices:", i2c.scan())
sensor = mlx90614.MLX90614(i2c)

# -------------------------
# SPI Pantalla ST7789
# -------------------------
spi = SPI(
    1,
    baudrate=20000000,
    polarity=0,
    phase=0,
    sck=Pin(18),
    mosi=Pin(19)
)

display = st7789.Display(
    spi,
    Pin(16, Pin.OUT),  # DC
    Pin(5, Pin.OUT),   # CS
    Pin(23, Pin.OUT),  # RST
    Pin(4, Pin.OUT)    # BL
)

display.init()

# -------------------------
# Termómetro con degradado
# -------------------------
def dibujar_termometro(display, temp, min_temp=33, max_temp=42):

    x = 10
    y = 170
    ancho = 120
    alto = 18

    # Marco
    display.fb.rect(x, y, ancho, alto, st7789.WHITE)

    # limitar rango
    if temp < min_temp:
        temp = min_temp
    if temp > max_temp:
        temp = max_temp

    rango = max_temp - min_temp
    proporcion = (temp - min_temp) / rango
    ancho_relleno = int(proporcion * (ancho - 4))

    # cubrir parte no activa
    display.fb.fill_rect(
        x + 2,
        y + 2,
        ancho_relleno,
        alto - 4,
        st7789.RED
    )

    # marcador temperatura
    pos = int((temp - min_temp) / rango * (ancho - 4))

    display.fb.vline(
        x + 2 + pos,
        y - 4,
        alto + 8,
        st7789.WHITE
    )

    # escala
    display.text("33C", x, y + 25, st7789.CYAN)
    display.text("42C", x + 90, y + 25, st7789.RED)


# -------------------------
# Loop principal
# -------------------------
while True:

    try:

        temp_obj = sensor.read_object_temp()
        temp_amb = sensor.read_ambient_temp()

        if temp_obj >= 38:
            estado = "FIEBRE"
            color_estado = st7789.RED
        else:
            estado = "NORMAL"
            color_estado = st7789.GREEN

        display.clear(st7789.BLACK)

        # Título
        display.text("GY906 SENSOR", 10, 10, st7789.CYAN)

        # Temperatura ambiente
        display.text("Amb:", 10, 50, st7789.WHITE)
        display.text("{:.2f}".format(temp_amb), 70, 50, st7789.WHITE)

        # Temperatura objeto
        display.text("Obj:", 10, 80, st7789.WHITE)
        display.text("{:.2f}".format(temp_obj), 70, 80, st7789.YELLOW)

        # Estado
        display.text("Estado:", 10, 120, st7789.WHITE)
        display.text(estado, 80, 120, color_estado)

        # Termómetro
        dibujar_termometro(display, temp_obj)

        display.show()

    except Exception as e:

        print("ERROR:", e)

        display.clear(st7789.BLACK)
        display.text("ERROR SENSOR", 20, 100, st7789.RED)
        display.show()

    time.sleep(0.5)


