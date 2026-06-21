# Nodo A — main.py
# Sensores: GY-906 (MLX90614), MPU-6050, DHT11, MQ-135
# Compatible con MASTER_TTGO v18.7 (broadcast, JSON, NET_ID)
# Modo: deepsleep entre ciclos (batería)

import gc
from machine import Pin, SPI, I2C, ADC, deepsleep, RTC
import network, espnow, time, json
import st7789
from fuentes import font_sm, font_md
from sensores import leer_todo

gc.collect()

# ───────────────────────────────────────────────
#  IDENTIDAD
# ───────────────────────────────────────────────
NODE_ID   = "A"
NET_ID    = "PIFNET"
MASTER_ID = "MASTER_TTGO_GATEWAY"

# ───────────────────────────────────────────────
#  TIEMPOS
# ───────────────────────────────────────────────
SLEEP_MS        = 30_000   # 5 min entre ciclos
VENTANA_WAVE_MS = 8_000     # espera WAVE del master
SCAN_MS         = 1_200     # tiempo por canal buscando master
CANALES_SCAN    = [1, 6, 11, 4, 8, 2, 3, 5, 7, 9, 10]
BROADCAST_MAC   = b'\xff\xff\xff\xff\xff\xff'

# ───────────────────────────────────────────────
#  UMBRALES MQ-135
# ───────────────────────────────────────────────
MQ_MIN      = 400
MQ_MAX      = 3800
MQ_VARIANZA = 300

# ───────────────────────────────────────────────
#  PANTALLA
# ───────────────────────────────────────────────

spi     = SPI(1, baudrate=20000000, polarity=0, phase=0,
              sck=Pin(18), mosi=Pin(19))
tft     = st7789.ST7789(spi, 135, 240,
              dc=Pin(16, Pin.OUT), cs=Pin(5,  Pin.OUT),
              reset=Pin(23, Pin.OUT), backlight=Pin(4, Pin.OUT),
              rotation=1)

# ───────────────────────────────────────────────
#  RTC — ciclo y modo dormido
# ───────────────────────────────────────────────
rtc = RTC()
mem = rtc.memory()
if len(mem) >= 5:
    ciclo        = int.from_bytes(mem[:4], "big")
    modo_dormido = mem[4]
elif len(mem) >= 4:
    ciclo        = int.from_bytes(mem, "big")
    modo_dormido = 0
else:
    ciclo        = 0
    modo_dormido = 0

# ───────────────────────────────────────────────
#  HELPERS DE PANTALLA
# ───────────────────────────────────────────────
def ui_estado(linea1, linea2="", color1=st7789.WHITE, color2=st7789.WHITE):
    """Pantalla simple de dos líneas para estados transitorios."""
    tft.fill(st7789.BLACK)
    tft.write(font_sm, NODE_ID + " — Nodo A", st7789.CYAN, x=4, y=2)
    tft.write(font_sm, "Ciclo: " + str(ciclo), st7789.WHITE, x=4, y=18)
    tft.write(font_md, linea1, color1, x=4, y=40)
    if linea2:
        tft.write(font_sm, linea2, color2, x=4, y=76)

def ui_sensores(ax, ay, az, temp_amb, temp_obj, temp_dht, hum_dht, valor_mq, estado):
    """Pantalla completa con todos los sensores."""
    tft.fill(st7789.BLACK)
    tft.write(font_sm, "Nodo A", st7789.CYAN, x=4, y=2)
    tft.write(font_sm, "Ciclo: " + str(ciclo), st7789.WHITE, x=130, y=2)

    tft.cursor(4, 20)

    if ax is not None:
        mov = abs(az - 1.0) > 0.3 or abs(ax) > 0.3 or abs(ay) > 0.3
        tft.write(font_sm, "MPU X:{:.2f} Z:{:.2f}".format(ax, az), st7789.YELLOW)
        tft.write(font_sm, "MOV!" if mov else "Reposo",
                  st7789.RED if mov else st7789.GREEN)
    else:
        tft.write(font_sm, "MPU: sin sensor", st7789.RED)

    if temp_amb is not None:
        fiebre = isinstance(temp_obj, float) and temp_obj >= 38
        tft.write(font_sm, "GY:{:.1f}/{:.1f}C".format(temp_amb, temp_obj),
                  st7789.RED if fiebre else st7789.MAGENTA)
    else:
        tft.write(font_sm, "GY: sin sensor", st7789.RED)

    if temp_dht != -1:
        tft.write(font_sm, "DHT {}C {}%".format(temp_dht, hum_dht), st7789.GREEN)
    else:
        tft.write(font_sm, "DHT: sin sensor", st7789.RED)

    if valor_mq != -1:
        cal = ("Limpio"   if valor_mq < 1200 else
               "Regular"  if valor_mq < 2000 else
               "Malo"     if valor_mq < 2500 else "Peligroso")
        tft.write(font_sm, "MQ:{} {}".format(valor_mq, cal), st7789.CYAN)
    else:
        tft.write(font_sm, "MQ: sin sensor", st7789.RED)

    tft.write(font_sm, estado, st7789.WHITE)

# ───────────────────────────────────────────────
#  MODO DORMIDO — espera ACTIVAR del master
# ───────────────────────────────────────────────
if modo_dormido == 1:
    ui_estado("Dormido", "Esperando ACTIVAR...", st7789.RED, st7789.WHITE)

    sta = network.WLAN(network.STA_IF)
    sta.active(True)
    en = espnow.ESPNow()
    en.active(True)
    en.add_peer(BROADCAST_MAC)

    activado  = False
    inicio    = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), inicio) < 35_000:
        try:
            _, msg = en.recv(200)
        except:
            continue
        if not msg: continue
        try:
            data = json.loads(msg.decode())
            if (data.get("net") == NET_ID and
                    data.get("type") == "WAVE" and
                    data.get("cmd")  == "ACTIVAR"):
                # Responder ACK
                ack = json.dumps({"type":"FB","net":NET_ID,
                                  "id":NODE_ID,"par":MASTER_ID,
                                  "pl":[{"t":"ACK","v":"ACTIVAR"}]})
                en.send(BROADCAST_MAC, ack.encode())
                activado = True
                ui_estado("Activado!", "", st7789.GREEN)
                time.sleep(1)
                break
        except:
            pass

    en.active(False)
    sta.active(False)

    if not activado:
        rtc.memory((ciclo + 1).to_bytes(4, "big") + bytes([1]))
        deepsleep(SLEEP_MS)
    # Si activado, cae al ciclo normal abajo

ui_estado("Leyendo...", "sensores", st7789.YELLOW)
s = leer_todo()
ax, ay, az         = s["ax"], s["ay"], s["az"]
temp_amb, temp_obj = s["amb"], s["obj"]
temp_dht, hum_dht  = s["tdht"], s["hdht"]
valor_mq           = s["mq"]
pl                 = s["pl"]

# ───────────────────────────────────────────────
#  PANTALLA CON DATOS
# ───────────────────────────────────────────────
ui_sensores(ax, ay, az, temp_amb, temp_obj, temp_dht, hum_dht, valor_mq,
            "Buscando master...")

# ───────────────────────────────────────────────
#  ESP-NOW — escanear canal y esperar WAVE
# ───────────────────────────────────────────────
sta = network.WLAN(network.STA_IF)
sta.active(True)
en  = espnow.ESPNow()
en.active(True)
en.add_peer(BROADCAST_MAC)

# Leer canal guardado en RTC (byte 5 en adelante)
mem = rtc.memory()
canal = mem[5] if len(mem) > 5 else 1

def escanear_canal():
    """Busca la WAVE del master para encontrar su canal."""
    global canal
    for ch in CANALES_SCAN:
        sta.config(channel=ch)
        time.sleep_ms(100)
        fin = time.ticks_add(time.ticks_ms(), SCAN_MS)
        while time.ticks_diff(fin, time.ticks_ms()) > 0:
            try: _, msg = en.recv(50)
            except: continue
            if not msg: continue
            try:
                data = json.loads(msg.decode())
                if (data.get("net")  == NET_ID and
                        data.get("type") == "WAVE" and
                        data.get("from") == MASTER_ID):
                    canal = data.get("ch", ch)
                    print("[SCAN] master en canal", canal)
                    return data   # devuelve la WAVE encontrada
            except: pass
    return None

# Intentar en el canal guardado primero
sta.config(channel=canal)
time.sleep_ms(100)

wave_data = None
fin = time.ticks_add(time.ticks_ms(), VENTANA_WAVE_MS)
while time.ticks_diff(fin, time.ticks_ms()) > 0:
    try: _, msg = en.recv(100)
    except: continue
    if not msg: continue
    try:
        data = json.loads(msg.decode())
        if (data.get("net")  == NET_ID and
                data.get("type") == "WAVE" and
                data.get("from") == MASTER_ID):
            wave_data = data
            break
    except: pass

# Si no encontró, escanear otros canales
if wave_data is None:
    ui_sensores(ax, ay, az, temp_amb, temp_obj, temp_dht, hum_dht, valor_mq,
                "Escaneando canales...")
    wave_data = escanear_canal()

# ───────────────────────────────────────────────
#  RESPONDER AL MASTER
# ───────────────────────────────────────────────
mid     = wave_data.get("mid", 0) if wave_data else 0
target  = wave_data.get("target", "ALL") if wave_data else "ALL"
cmd = wave_data.get("cmd", "") if wave_data else ""
if wave_data and cmd == "DORMIR" and target in ("ALL", NODE_ID):
    ack = json.dumps({"type":"FB","net":NET_ID,"id":NODE_ID,"par":MASTER_ID,
                      "pl":[{"t":"ACK","v":"DORMIR"}]})
    try: en.send(BROADCAST_MAC, ack.encode())
    except: pass
    ui_estado("Durmiendo...", "", st7789.RED)
    time.sleep(1)
    en.active(False); sta.active(False)
    rtc.memory((ciclo+1).to_bytes(4,"big") + bytes([1]) + bytes([canal]))
    deepsleep(SLEEP_MS)
debe_responder = (target == "ALL" or target == NODE_ID)

if wave_data and debe_responder:
    pkt = json.dumps({
        "type": "FB",
        "net" : NET_ID,
        "id"  : NODE_ID,
        "par" : MASTER_ID,
        "mid" : mid,
        "pl"  : pl
    })
    # Enviar 2 veces para fiabilidad
    for _ in range(2):
        try:
            en.send(BROADCAST_MAC, pkt.encode())
            time.sleep_ms(150)
        except Exception as e:
            print("TX err:", e)
    print("[FB TX]", pkt[:80])
    ui_sensores(ax, ay, az, temp_amb, temp_obj, temp_dht, hum_dht, valor_mq,
                "Enviado OK")
else:
    # Sin master — mandar igual en broadcast por si alguien escucha
    if pl:
        pkt = json.dumps({
            "type": "FB",
            "net" : NET_ID,
            "id"  : NODE_ID,
            "par" : MASTER_ID,
            "pl"  : pl
        })
        try: en.send(BROADCAST_MAC, pkt.encode())
        except: pass
    ui_sensores(ax, ay, az, temp_amb, temp_obj, temp_dht, hum_dht, valor_mq,
                "Sin master")

# ───────────────────────────────────────────────
#  ESCUCHAR COMANDOS (ventana corta post-envío)
# ───────────────────────────────────────────────
time.sleep_ms(100)                 # antes 500
inicio = time.ticks_ms()
while time.ticks_diff(time.ticks_ms(), inicio) < 4000:   # antes 3000
    try: _, msg = en.recv(100)
    except: continue
    if not msg: continue
    try:
        data = json.loads(msg.decode())
        if data.get("net") != NET_ID: continue
        tipo = data.get("type")
        cmd  = data.get("cmd", "")

        if tipo == "WAVE":
            if cmd == "DORMIR":
                ack = json.dumps({"type":"FB","net":NET_ID,
                                  "id":NODE_ID,"par":MASTER_ID,
                                  "pl":[{"t":"ACK","v":"DORMIR"}]})
                en.send(BROADCAST_MAC, ack.encode())
                ui_estado("Durmiendo...", "", st7789.RED)
                time.sleep(1)
                en.active(False)
                sta.active(False)
                rtc.memory((ciclo + 1).to_bytes(4, "big") +
                            bytes([1]) + bytes([canal]))
                deepsleep(SLEEP_MS)

            elif cmd == "SOLICITUD" or data.get("target") in ("ALL", NODE_ID):
                # Re-enviar datos si nos los piden de nuevo
                try: en.send(BROADCAST_MAC, pkt.encode())
                except: pass
    except: pass

# ───────────────────────────────────────────────
#  GUARDAR CANAL Y DORMIR
# ───────────────────────────────────────────────
en.active(False)
sta.active(False)

ui_sensores(ax, ay, az, temp_amb, temp_obj, temp_dht, hum_dht, valor_mq,
            "Durmiendo {}min...".format(SLEEP_MS // 60000))
time.sleep(1)

rtc.memory((ciclo + 1).to_bytes(4, "big") + bytes([0]) + bytes([canal]))
deepsleep(SLEEP_MS)