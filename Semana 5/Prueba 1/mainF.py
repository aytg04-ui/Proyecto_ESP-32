# Nodo F — main.py
# Sensores: GY-906 (MLX90614), MPU-6050, DHT11, MQ-135

from machine import Pin, SPI, I2C, ADC, deepsleep, RTC
import network, espnow, ubinascii, time
import st7789, dht
from mpu6050 import MPU6050
from mlx90614 import MLX90614
from i2c_recovery import escanear_con_recuperacion

MAC_B = ubinascii.unhexlify('ac15186f760c'.replace(':', ''))

# --- Pantalla ---
spi = SPI(1, baudrate=20000000, polarity=0, phase=0,
          sck=Pin(18), mosi=Pin(19))
display = st7789.Display(spi, Pin(16, Pin.OUT), Pin(5,  Pin.OUT),
                              Pin(23, Pin.OUT), Pin(4,  Pin.OUT), rotation=1)

# --- RTC ---
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

# --- ESP-NOW ---
sta = network.WLAN(network.STA_IF)
sta.active(True)
e = espnow.ESPNow()
e.active(True)
e.add_peer(MAC_B)
time.sleep_ms(500)

# ===========================================
# MODO DORMIDO
# ===========================================
if modo_dormido == 1:
    display.fb_fill(st7789.BLACK)
    display.fb_text("Nodo F dormido", 5, 10, st7789.ORANGE)
    display.fb_text("Ciclo: " + str(ciclo), 5, 35, st7789.WHITE)
    display.fb_text("Esperando ACTIVAR", 5, 60, st7789.WHITE)
    display.show()

    activado = False
    inicio   = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), inicio) < 3000:
        sender, cmd = e.recv(100)
        if cmd == b'ACTIVAR':
            e.send(MAC_B, b'ACK:ACTIVAR')
            activado = True
            display.fb_fill(st7789.BLACK)
            display.fb_text("Activado!", 5, 80, st7789.GREEN)
            display.show()
            time.sleep(1)
            break
        elif cmd == b'SOLICITUD':
            e.send(MAC_B, b'DORMIDO')

    if not activado:
        rtc.memory((ciclo + 1).to_bytes(4, "big") + bytes([1]))
        deepsleep(30000)

# ===========================================
# MODO NORMAL — detectar sensores
# ===========================================

# --- I2C con recuperación automática ---
i2c, dispositivos_i2c = escanear_con_recuperacion(intentos=3, scl=22, sda=21)

if i2c is None:
    print("Bus I2C no disponible, saltando sensores I2C")
    tiene_mpu = False
    tiene_gy  = False
else:
    print("I2C encontrados:", [hex(d) for d in dispositivos_i2c])
    tiene_mpu = 0x68 in dispositivos_i2c
    tiene_gy  = 0x5A in dispositivos_i2c

# --- DHT11 ---
tiene_dht = False
temp_dht  = -1
hum_dht   = -1
try:
    sensor_dht = dht.DHT11(Pin(25))
    time.sleep(2)
    for _ in range(3):
        try:
            sensor_dht.measure()
            t = sensor_dht.temperature()
            h = sensor_dht.humidity()
            if 0 <= t <= 60 and 0 <= h <= 100:
                temp_dht  = t
                hum_dht   = h
                tiene_dht = True
                break
        except OSError:
            time.sleep(2)
except Exception as err:
    print("DHT11 no disponible:", err)

# --- MPU-6050 ---
ax, ay, az = 0.0, 0.0, 0.0
tiene_mpu_datos = False
if tiene_mpu:
    try:
        mpu   = MPU6050(i2c)
        time.sleep_ms(200)
        datos = mpu.get_values()
        ax    = datos["AcX"] / 16384.0
        ay    = datos["AcY"] / 16384.0
        az    = datos["AcZ"] / 16384.0
        tiene_mpu_datos = True
        print("MPU-6050 OK: X={:.2f} Y={:.2f} Z={:.2f}".format(ax, ay, az))
    except Exception as err:
        print("MPU-6050 error:", err)

# --- GY-906 (MLX90614) ---
temp_amb = -1.0
temp_obj = -1.0
tiene_gy_datos = False
if tiene_gy:
    try:
        sensor_gy  = MLX90614(i2c)
        temp_amb   = sensor_gy.read_ambient_temp()
        temp_obj   = sensor_gy.read_object_temp()
        tiene_gy_datos = True
        print("GY-906 OK: Amb={:.1f} Obj={:.1f}".format(temp_amb, temp_obj))
    except Exception as err:
        print("GY-906 error:", err)

# --- MQ-135 ---
UMBRAL_MINIMO_MQ = 400
UMBRAL_MAXIMO_MQ = 3800
UMBRAL_VARIANZA  = 300

valor_mq = -1
pct_mq   = -1.0
tiene_mq = False
try:
    adc = ADC(Pin(33))
    adc.atten(ADC.ATTN_11DB)
    adc.width(ADC.WIDTH_12BIT)
    lecturas = []
    for _ in range(5):
        lecturas.append(adc.read())
        time.sleep_ms(100)
    lectura_cruda = sum(lecturas) // len(lecturas)
    varianza      = max(lecturas) - min(lecturas)

    if lectura_cruda < UMBRAL_MINIMO_MQ:
        print("MQ-135: valor muy bajo ({}), probablemente desconectado".format(lectura_cruda))
    elif lectura_cruda > UMBRAL_MAXIMO_MQ:
        print("MQ-135: valor muy alto ({}), probablemente desconectado".format(lectura_cruda))
    elif varianza > UMBRAL_VARIANZA:
        print("MQ-135: inestable (varianza {}), probablemente desconectado".format(varianza))
    else:
        valor_mq = lectura_cruda
        pct_mq   = round(valor_mq / 4095 * 100, 1)
        tiene_mq = True
        print("MQ-135 OK: ADC={} varianza={}".format(valor_mq, varianza))
except Exception as err:
    print("MQ-135 no disponible:", err)

# ===========================================
# PANTALLA
# ===========================================
display.fb_fill(st7789.BLACK)
display.fb_text("Nodo F - Multi", 5, 2, st7789.ORANGE)
display.fb_text("Ciclo: " + str(ciclo), 5, 16, st7789.WHITE)

y = 34
if tiene_mpu_datos:
    mov = abs(az - 1.0) > 0.3 or abs(ax) > 0.3 or abs(ay) > 0.3
    display.fb_text("MPU X:{:.2f} Z:{:.2f}".format(ax, az), 5, y, st7789.YELLOW)
    y += 16
    display.fb_text("MOV!" if mov else "Reposo", 5, y,
                    st7789.RED if mov else st7789.GREEN)
    y += 16
else:
    display.fb_text("MPU: sin sensor", 5, y, st7789.RED)
    y += 16

if tiene_gy_datos:
    display.fb_text("GY:{:.1f}/{:.1f}C".format(temp_amb, temp_obj), 5, y, st7789.MAGENTA)
    y += 16
else:
    display.fb_text("GY: sin sensor", 5, y, st7789.RED)
    y += 16

if tiene_dht:
    display.fb_text("DHT {}C {}%".format(temp_dht, hum_dht), 5, y, st7789.GREEN)
    y += 16
else:
    display.fb_text("DHT: sin sensor", 5, y, st7789.RED)
    y += 16

if tiene_mq:
    if valor_mq < 1200:   cal = "Limpio"
    elif valor_mq < 2000: cal = "Regular"
    elif valor_mq < 2500: cal = "Malo"
    else:                 cal = "Peligroso"
    display.fb_text("MQ:{} {}".format(valor_mq, cal), 5, y, st7789.CYAN)
    y += 16
else:
    display.fb_text("MQ: sin sensor", 5, y, st7789.RED)
    y += 16

display.fb_text("Enviando...", 5, y + 4, st7789.WHITE)
display.show()
time.sleep(3)

# ===========================================
# ENVIAR
# ===========================================
msg = "F:{:.2f}:{:.2f}:{:.2f}:{:.1f}:{:.1f}:{}:{}:{}:{}".format(
    ax, ay, az,
    temp_amb, temp_obj,
    temp_dht, hum_dht,
    valor_mq, pct_mq
)
e.send(MAC_B, msg.encode())
print("Enviado:", msg)

display.fb_fill(st7789.BLACK)
display.fb_text("Nodo F - Multi", 5, 2, st7789.ORANGE)
display.fb_text("Ciclo: " + str(ciclo), 5, 16, st7789.WHITE)
display.fb_text("Durmiendo 5s...", 5, y + 4, st7789.RED)
display.show()
time.sleep(1)

# ===========================================
# ESCUCHAR COMANDOS
# ===========================================
inicio = time.ticks_ms()
while time.ticks_diff(time.ticks_ms(), inicio) < 3000:
    sender, cmd = e.recv(100)
    if cmd:
        print("Comando:", cmd)
        if cmd == b'SOLICITUD':
            e.send(MAC_B, msg.encode())
            e.send(MAC_B, b'ACK:SOLICITUD')
        elif cmd == b'DORMIR':
            e.send(MAC_B, b'ACK:DORMIR')
            display.fb_fill(st7789.BLACK)
            display.fb_text("Modo dormido", 5, 60, st7789.RED)
            display.show()
            rtc.memory((ciclo + 1).to_bytes(4, "big") + bytes([1]))
            deepsleep(30000)
        elif cmd == b'ACTIVAR':
            e.send(MAC_B, b'ACK:ACTIVAR')

rtc.memory((ciclo + 1).to_bytes(4, "big") + bytes([0]))
deepsleep(5000)