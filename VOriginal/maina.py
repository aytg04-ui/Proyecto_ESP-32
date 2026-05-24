# maina.py
from machine import Pin, SPI, I2C, deepsleep, RTC
import network, espnow, ubinascii, time
import st7789
from mpu6050 import MPU6050

# --- MACs ---
MAC_B = ubinascii.unhexlify('ac15186f760c'.replace(':', ''))

# --- Pantalla ---
spi = SPI(1, baudrate=20000000, polarity=0, phase=0,
          sck=Pin(18), mosi=Pin(19))
display = st7789.Display(spi, Pin(16,Pin.OUT), Pin(5,Pin.OUT),
                         Pin(23,Pin.OUT), Pin(4,Pin.OUT))
display.init()

# --- RTC: recuperar ciclo y modo ---
rtc = RTC()
if len(rtc.memory()) == 0:
    ciclo        = 0
    modo_dormido = 0
elif len(rtc.memory()) >= 5:
    ciclo        = int.from_bytes(rtc.memory()[:4], "big")
    modo_dormido = rtc.memory()[4]
else:
    ciclo        = int.from_bytes(rtc.memory(), "big")
    modo_dormido = 0

# --- ESP-NOW (se necesita en ambos modos) ---
sta = network.WLAN(network.STA_IF)
sta.active(True)
e = espnow.ESPNow()
e.active(True)
e.add_peer(MAC_B)

# ===========================================
# MODO DORMIDO — no lee sensor, solo escucha
# ===========================================
if modo_dormido == 1:
    display.fb.fill(st7789.BLACK)
    display.fb.text("TTGO A - Dormido", 5, 10, st7789.RED)
    display.fb.text("Ciclo: " + str(ciclo), 5, 40, st7789.WHITE)
    display.fb.text("Esperando ACTIVAR", 5, 70, st7789.WHITE)
    display.fb.text("Revisando cada 30s", 5, 100, st7789.WHITE)
    display.show()

    # Escuchar ACTIVAR por 2 segundos
    activado = False
    inicio = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), inicio) < 2000:
        sender, cmd = e.recv(100)
        if cmd == b'ACTIVAR':
            activado = True
            display.fb.fill(st7789.BLACK)
            display.fb.text("Activado por B!", 5, 80, st7789.GREEN)
            display.show()
            time.sleep(1)
            break

    if not activado:
        # Volver a dormir 30s en modo dormido
        rtc.memory((ciclo + 1).to_bytes(4, "big") + bytes([1]))
        deepsleep(30000)
    # Si llegó ACTIVAR, el código continúa abajo al modo normal

# ===========================================
# MODO NORMAL — leer sensor y enviar datos
# ===========================================
i2c = I2C(0, scl=Pin(22), sda=Pin(21), freq=100000)
mpu = MPU6050(i2c)
time.sleep_ms(200)
datos = mpu.get_values()

ax = datos["AcX"] / 16384.0
ay = datos["AcY"] / 16384.0
az = datos["AcZ"] / 16384.0

# Pantalla con datos
display.fb.fill(st7789.BLACK)
display.fb.text("TTGO A - Nodo", 5, 10, st7789.CYAN)
display.fb.text("Ciclo: " + str(ciclo), 5, 35, st7789.WHITE)
display.fb.text("X:{:.2f}g".format(ax), 5, 65, st7789.YELLOW)
display.fb.text("Y:{:.2f}g".format(ay), 5, 85, st7789.YELLOW)
display.fb.text("Z:{:.2f}g".format(az), 5, 105, st7789.YELLOW)
display.fb.text("Enviando...", 5, 135, st7789.GREEN)
display.show()
time.sleep(1)

# Enviar datos
msg = "A:{:.2f}:{:.2f}:{:.2f}".format(ax, ay, az)
e.send(MAC_B, msg.encode())
print("Enviado:", msg)

# Pantalla antes de dormir
display.fb.fill(st7789.BLACK)
display.fb.text("TTGO A - Nodo", 5, 10, st7789.CYAN)
display.fb.text("Ciclo: " + str(ciclo), 5, 35, st7789.WHITE)
display.fb.text("X:{:.2f}g".format(ax), 5, 65, st7789.YELLOW)
display.fb.text("Y:{:.2f}g".format(ay), 5, 85, st7789.YELLOW)
display.fb.text("Z:{:.2f}g".format(az), 5, 105, st7789.YELLOW)
display.fb.text("Durmiendo 5s...", 5, 135, st7789.RED)
display.show()
time.sleep(1)

# Escuchar comandos antes de dormir
inicio = time.ticks_ms()
while time.ticks_diff(time.ticks_ms(), inicio) < 2000:
    sender, cmd = e.recv(100)
    if cmd:
        print("Comando:", cmd)
        if cmd == b'SOLICITUD':
            e.send(MAC_B, msg.encode())
            print("Solicitud atendida")
        elif cmd == b'DORMIR':
            modo_dormido = 1
            display.fb.fill(st7789.BLACK)
            display.fb.text("Modo dormido", 5, 60, st7789.RED)
            display.fb.text("Ciclo: " + str(ciclo), 5, 90, st7789.WHITE)
            display.show()
            break
        elif cmd == b'ACTIVAR':
            # Ya estaba activo, ignorar
            pass

# Guardar estado y dormir
if modo_dormido == 1:
    rtc.memory((ciclo + 1).to_bytes(4, "big") + bytes([1]))
    deepsleep(30000)
else:
    rtc.memory((ciclo + 1).to_bytes(4, "big") + bytes([0]))
    deepsleep(5000)
