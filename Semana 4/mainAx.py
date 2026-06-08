# ============================================================
#  PIF_NODE A — Nodo Mesh
#  Sensores: MPU-6050, GY-906, DHT11, MQ-135
#  Protocolo: WAVE/FB mesh ESP-NOW
# ============================================================

import gc
gc.collect()

from machine import Pin, SPI, I2C, ADC, RTC
import network, espnow, time, json, dht
import st7789
from mpu6050 import MPU6050
from mlx90614 import MLX90614
from i2c_recovery import escanear_con_recuperacion
from config import (BROADCAST_MAC, CANALES_SCAN, MAX_TTL, DEDUP_TTL_MS,
                    VENTANA_WAVE_MS, VENTANA_HIJOS_MS, CANAL_SCAN_MS,
                    CANAL_MISS_MAX, UMBRAL_MINIMO_MQ, UMBRAL_MAXIMO_MQ,
                    UMBRAL_VARIANZA)

# ───────────────────────────────────────────────
#  IDENTIDAD DEL NODO
# ───────────────────────────────────────────────
NODE_ID    = "NODO_A"
COLOR_NODO = st7789.CYAN

# ───────────────────────────────────────────────
#  HARDWARE — Pantalla ST7789
# ───────────────────────────────────────────────
spi = SPI(1, baudrate=20_000_000, polarity=0, phase=0,
          sck=Pin(18), mosi=Pin(19))
display = st7789.Display(spi,
                         Pin(16, Pin.OUT),
                         Pin(5,  Pin.OUT),
                         Pin(23, Pin.OUT),
                         Pin(4,  Pin.OUT),
                         rotation=1)

# ───────────────────────────────────────────────
#  ESTADO GLOBAL
# ───────────────────────────────────────────────
_canal_actual    = CANALES_SCAN[0]
_ultimo_padre    = "MASTER"
_ciclos_sin_wave = 0
_waves_vistas    = {}
_msg_counter     = 0
rtc = RTC()

# ───────────────────────────────────────────────
#  HELPERS
# ───────────────────────────────────────────────
def next_mid():
    global _msg_counter
    _msg_counter += 1
    return _msg_counter

def sincronizar_rtc(ts_str):
    if not ts_str:
        return
    try:
        fecha, hora = ts_str.split(" ")
        a, m, d    = [int(x) for x in fecha.split("-")]
        hh, mm, ss = [int(x) for x in hora.split(":")]
        rtc.datetime((a, m, d, 0, hh, mm, ss, 0))
    except:
        pass

def wave_ya_vista(mid):
    if mid is None:
        return False
    ahora = time.ticks_ms()
    a_borrar = [k for k, v in _waves_vistas.items()
                if time.ticks_diff(ahora, v) > DEDUP_TTL_MS]
    for k in a_borrar:
        del _waves_vistas[k]
    if mid in _waves_vistas:
        return True
    _waves_vistas[mid] = ahora
    return False

# ───────────────────────────────────────────────
#  PANTALLA
# ───────────────────────────────────────────────
def ui_simple(linea1, linea2="", col1=st7789.YELLOW, col2=st7789.WHITE):
    display.fb_fill(st7789.BLACK)
    display.fb_text(NODE_ID, 5, 2, COLOR_NODO)
    display.fb_text(linea1[:26], 5, 20, col1)
    if linea2:
        display.fb_text(linea2[:26], 5, 36, col2)
    display.show()

def ui_sensores(datos, status="", status_col=st7789.GREEN):
    display.fb_fill(st7789.BLACK)
    display.fb_text(NODE_ID, 5, 2, COLOR_NODO)
    if status:
        display.fb_text(status[:26], 5, 14, status_col)
    y = 30

    if datos.get("tiene_mpu"):
        ax, ay, az = datos["ax"], datos["ay"], datos["az"]
        mov = abs(az - 1.0) > 0.3 or abs(ax) > 0.3 or abs(ay) > 0.3
        display.fb_text("MPU X:{:.2f} Z:{:.2f}".format(ax, az), 5, y, st7789.YELLOW)
        y += 14
        display.fb_text("MOV!" if mov else "Reposo", 5, y,
                        st7789.RED if mov else st7789.GREEN)
        y += 14
    else:
        display.fb_text("MPU: sin sensor", 5, y, st7789.RED); y += 14

    if datos.get("tiene_gy"):
        display.fb_text("GY:{:.1f}/{:.1f}C".format(
            datos["temp_amb"], datos["temp_obj"]), 5, y, st7789.MAGENTA)
        y += 14
    else:
        display.fb_text("GY: sin sensor", 5, y, st7789.RED); y += 14

    if datos.get("tiene_dht"):
        display.fb_text("DHT {}C {}%".format(
            datos["temp_dht"], datos["hum_dht"]), 5, y, st7789.GREEN)
        y += 14
    else:
        display.fb_text("DHT: sin sensor", 5, y, st7789.RED); y += 14

    if datos.get("tiene_mq"):
        vmq = datos["valor_mq"]
        cal = "Limpio" if vmq < 1200 else "Regular" if vmq < 2000 else \
              "Malo"   if vmq < 2500 else "Peligroso"
        display.fb_text("MQ:{} {}".format(vmq, cal), 5, y, st7789.CYAN)
    else:
        display.fb_text("MQ: sin sensor", 5, y, st7789.RED)

    display.show()

# ───────────────────────────────────────────────
#  SENSORES
# ───────────────────────────────────────────────
def detectar_sensores():
    estado = {"i2c": None, "tiene_mpu": False, "tiene_gy": False,
              "tiene_dht": False, "tiene_mq": False}

    i2c, dispositivos = escanear_con_recuperacion(intentos=3, scl=22, sda=21)
    if i2c:
        print("I2C:", [hex(d) for d in dispositivos])
        estado["i2c"]      = i2c
        estado["tiene_mpu"] = 0x68 in dispositivos
        estado["tiene_gy"]  = 0x5A in dispositivos

    try:
        sensor_dht = dht.DHT11(Pin(25))
        time.sleep(2)
        for _ in range(3):
            try:
                sensor_dht.measure()
                t = sensor_dht.temperature()
                h = sensor_dht.humidity()
                if 0 <= t <= 60 and 0 <= h <= 100:
                    estado["tiene_dht"]  = True
                    estado["sensor_dht"] = sensor_dht
                    break
            except OSError:
                time.sleep(2)
    except Exception as e:
        print("DHT11:", e)

    try:
        adc = ADC(Pin(33))
        adc.atten(ADC.ATTN_11DB)
        adc.width(ADC.WIDTH_12BIT)
        lecturas = [adc.read() for _ in range(5)]
        time.sleep_ms(100)
        cruda    = sum(lecturas) // len(lecturas)
        varianza = max(lecturas) - min(lecturas)
        if UMBRAL_MINIMO_MQ <= cruda <= UMBRAL_MAXIMO_MQ and varianza <= UMBRAL_VARIANZA:
            estado["tiene_mq"] = True
            estado["adc_mq"]   = adc
    except Exception as e:
        print("MQ-135:", e)

    return estado

def leer_sensores(estado):
    datos   = dict(estado)
    payload = []

    datos["ax"] = datos["ay"] = datos["az"] = 0.0
    datos["tiene_mpu"] = False
    if estado.get("tiene_mpu") and estado.get("i2c"):
        try:
            mpu  = MPU6050(estado["i2c"])
            time.sleep_ms(200)
            vals = mpu.get_values()
            datos["ax"]        = vals["AcX"] / 16384.0
            datos["ay"]        = vals["AcY"] / 16384.0
            datos["az"]        = vals["AcZ"] / 16384.0
            datos["tiene_mpu"] = True
            payload += [{"t": "AccX", "v": round(datos["ax"], 3)},
                        {"t": "AccY", "v": round(datos["ay"], 3)},
                        {"t": "AccZ", "v": round(datos["az"], 3)}]
        except Exception as e:
            print("MPU-6050:", e)

    datos["temp_amb"] = datos["temp_obj"] = -1.0
    datos["tiene_gy"] = False
    if estado.get("tiene_gy") and estado.get("i2c"):
        try:
            gy = MLX90614(estado["i2c"])
            datos["temp_amb"] = gy.read_ambient_temp()
            datos["temp_obj"] = gy.read_object_temp()
            datos["tiene_gy"] = True
            payload += [{"t": "TempAmb", "v": round(datos["temp_amb"], 1)},
                        {"t": "TempObj", "v": round(datos["temp_obj"], 1)}]
        except Exception as e:
            print("GY-906:", e)

    datos["temp_dht"] = datos["hum_dht"] = -1
    datos["tiene_dht"] = False
    if estado.get("tiene_dht") and estado.get("sensor_dht"):
        for _ in range(3):
            try:
                estado["sensor_dht"].measure()
                t = estado["sensor_dht"].temperature()
                h = estado["sensor_dht"].humidity()
                if 0 <= t <= 60 and 0 <= h <= 100:
                    datos["temp_dht"]  = t
                    datos["hum_dht"]   = h
                    datos["tiene_dht"] = True
                    payload += [{"t": "Temp", "v": t}, {"t": "Hum", "v": h}]
                    break
            except OSError:
                time.sleep(1)

    datos["valor_mq"] = -1
    datos["tiene_mq"] = False
    if estado.get("tiene_mq") and estado.get("adc_mq"):
        try:
            lecturas = [estado["adc_mq"].read() for _ in range(5)]
            time.sleep_ms(100)
            cruda    = sum(lecturas) // len(lecturas)
            varianza = max(lecturas) - min(lecturas)
            if UMBRAL_MINIMO_MQ <= cruda <= UMBRAL_MAXIMO_MQ and varianza <= UMBRAL_VARIANZA:
                datos["valor_mq"]  = cruda
                datos["tiene_mq"]  = True
                payload.append({"t": "MQ135", "v": cruda})
        except Exception as e:
            print("MQ-135:", e)

    return datos, payload

# ───────────────────────────────────────────────
#  RADIO
# ───────────────────────────────────────────────
def init_espnow(canal):
    gc.collect()
    sta = network.WLAN(network.STA_IF)
    if not sta.active():
        sta.active(True)
    sta.config(channel=canal)
    time.sleep_ms(150)
    en = espnow.ESPNow()
    en.active(True)
    en.add_peer(BROADCAST_MAC)
    return en

def cerrar_espnow(en):
    try:    en.active(False)
    except: pass
    try:    del en
    except: pass
    gc.collect()

def escanear_canal():
    global _canal_actual
    print("[SCAN] Buscando canal del master...")
    ui_simple("Buscando master...", col1=st7789.YELLOW)
    for ch in CANALES_SCAN:
        sta = network.WLAN(network.STA_IF)
        sta.active(True)
        sta.config(channel=ch)
        time.sleep_ms(100)
        en = espnow.ESPNow()
        en.active(True)
        en.add_peer(BROADCAST_MAC)
        fin = time.ticks_add(time.ticks_ms(), CANAL_SCAN_MS)
        encontrado = False
        while time.ticks_diff(fin, time.ticks_ms()) > 0:
            try:
                host, msg = en.recv(50)
            except:
                continue
            if not msg:
                continue
            try:
                data = json.loads(msg.decode())
                if data.get("type") == "WAVE":
                    _canal_actual = data.get("ch", ch)
                    sincronizar_rtc(data.get("ts"))
                    encontrado = True
                    del data
                    break
                del data
            except:
                pass
        en.active(False)
        del en
        sta.active(False)
        gc.collect()
        if encontrado:
            print("[SCAN] Master en canal", _canal_actual)
            ui_simple("Canal: {}".format(_canal_actual), col1=st7789.GREEN)
            time.sleep_ms(500)
            return True
    print("[SCAN] No encontrado, usando ch:", _canal_actual)
    return False

# ───────────────────────────────────────────────
#  PROTOCOLO MESH
# ───────────────────────────────────────────────
def enviar_fb(en, payload, parent_id, mid_origen=None):
    pkt = {"type": "FB", "id": NODE_ID, "par": parent_id, "pl": payload}
    if mid_origen is not None:
        pkt["mid"] = mid_origen
    msg = json.dumps(pkt)
    if len(msg) > 248:
        pkt["pl"] = payload[:4]
        msg = json.dumps(pkt)
    try:
        ok = en.send(BROADCAST_MAC, msg)
        time.sleep_ms(80)
        print("[>>> FB TX] → {}  mid:{}  hw:{}".format(
            parent_id, mid_origen, "OK" if ok else "FALLO"))
        return ok
    except Exception as e:
        print("[FB ERR]", e)
        return False

def relay_fb_hijo(en, raw_str):
    try:
        data = json.loads(raw_str)
        via  = data.get("via", [])
        if NODE_ID in via:
            del data; return False
        via.append(NODE_ID)
        data["via"] = via
        relay = json.dumps(data)
        if len(relay) < 248:
            ok = en.send(BROADCAST_MAC, relay)
            time.sleep_ms(80)
            print("[RELAY FB] ← {}  hw:{}".format(
                data.get("id", "?"), "OK" if ok else "FALLO"))
        del data, relay
        return True
    except Exception as e:
        print("[RELAY ERR]", e)
        return False

def relay_wave(en, data, ttl_actual):
    if ttl_actual <= 1:
        return False
    nuevo = {"type": "WAVE", "cmd": data.get("cmd", "REQ:ALL"),
             "from": NODE_ID, "target": data.get("target", "ALL"),
             "ttl": ttl_actual - 1, "ch": _canal_actual}
    if "mid" in data: nuevo["mid"] = data["mid"]
    if "ts"  in data: nuevo["ts"]  = data["ts"]
    pkt = json.dumps(nuevo)
    try:
        ok1 = en.send(BROADCAST_MAC, pkt); time.sleep_ms(150)
        ok2 = en.send(BROADCAST_MAC, pkt); time.sleep_ms(80)
        print("[WAVE PROP] mid:{}  ttl:{}".format(data.get("mid"), ttl_actual - 1))
        return ok1 or ok2
    except Exception as e:
        print("[WAVE PROP ERR]", e)
        return False

# ───────────────────────────────────────────────
#  CICLO PRINCIPAL
# ───────────────────────────────────────────────
def ciclo(estado):
    global _canal_actual, _ultimo_padre, _ciclos_sin_wave

    gc.collect()
    ui_simple("Midiendo...", col1=st7789.YELLOW)
    datos, payload = leer_sensores(estado)
    ui_sensores(datos, "Escuchando mesh...", st7789.CYAN)

    en = init_espnow(_canal_actual)

    wave_data     = None
    fb_relay_auto = set()

    fin = time.ticks_add(time.ticks_ms(), VENTANA_WAVE_MS)
    while time.ticks_diff(fin, time.ticks_ms()) > 0:
        try:
            host, msg = en.recv(30)
        except:
            continue
        if not msg:
            continue
        try:
            txt  = msg.decode()
            data = json.loads(txt)
            tipo = data.get("type")

            if tipo == "WAVE":
                mid = data.get("mid")
                if not wave_ya_vista(mid):
                    wave_data = data
                    sincronizar_rtc(data.get("ts"))
                    ch_m = data.get("ch", _canal_actual)
                    if ch_m != _canal_actual:
                        _canal_actual = ch_m
                    del txt
                    break

            elif tipo == "FB":
                hijo_id  = data.get("id", "?")
                hijo_via = data.get("via", [])
                if hijo_id != NODE_ID and NODE_ID not in hijo_via:
                    clave = hijo_id + "|" + str(data.get("mid", ""))
                    if clave not in fb_relay_auto:
                        fb_relay_auto.add(clave)
                        relay_fb_hijo(en, txt)

            del data, txt
        except Exception as e:
            print("[RX ERR]", e)

    if wave_data is None:
        _ciclos_sin_wave += 1
        print("[NO WAVE] ciclos:", _ciclos_sin_wave)
        cerrar_espnow(en)
        if _ciclos_sin_wave >= CANAL_MISS_MAX:
            escanear_canal()
            _ciclos_sin_wave = 0
        ui_simple("Sin WAVE ({}x)".format(_ciclos_sin_wave),
                  "Esperando...", st7789.RED)
        return

    _ciclos_sin_wave = 0
    ttl    = wave_data.get("ttl", MAX_TTL)
    target = wave_data.get("target", "ALL")
    parent = wave_data.get("from", "MASTER")
    mid    = wave_data.get("mid")
    _ultimo_padre = parent

    print("[<<< WAVE RX] de:{}  target:{}  ttl:{}  mid:{}".format(
        parent, target, ttl, mid))

    if ttl > 1:
        relay_wave(en, wave_data, ttl)

    # Esperar FBs de hijos
    fb_ya_relayados = set()
    fin_hijos = time.ticks_add(time.ticks_ms(), VENTANA_HIJOS_MS)
    while time.ticks_diff(fin_hijos, time.ticks_ms()) > 0:
        try:
            host, msg = en.recv(20)
        except:
            continue
        if not msg:
            continue
        try:
            txt  = msg.decode()
            data = json.loads(txt)
            if data.get("type") == "FB":
                hijo_id  = data.get("id", "?")
                hijo_via = data.get("via", [])
                if hijo_id != NODE_ID and NODE_ID not in hijo_via:
                    clave = hijo_id + "|" + str(data.get("mid", ""))
                    if clave not in fb_ya_relayados:
                        fb_ya_relayados.add(clave)
                        relay_fb_hijo(en, txt)
            del data, txt
        except:
            pass

    # Responder con FB propio
    debe_responder = (target == "ALL" or target == NODE_ID)
    if debe_responder:
        enviar_fb(en, payload, parent, mid_origen=mid)
        ui_sensores(datos, "FB enviado OK", st7789.GREEN)
    else:
        ui_sensores(datos, "Relay:{}".format(target[:10]), st7789.YELLOW)

    cerrar_espnow(en)
    print("[RAM]", gc.mem_free(), "| ch:", _canal_actual)

# ───────────────────────────────────────────────
#  ARRANQUE
# ───────────────────────────────────────────────
print("=== {} arrancando ===".format(NODE_ID))

display.fb_fill(st7789.BLACK)
display.fb_text("PIF NODE", 5, 20, COLOR_NODO)
display.fb_text(NODE_ID,    5, 44, st7789.WHITE)
display.fb_text("Iniciando...", 5, 68, st7789.YELLOW)
display.show()
time.sleep(1)

ui_simple("Detectando sensores", col1=st7789.YELLOW)
estado_sensores = detectar_sensores()
gc.collect()

sta = network.WLAN(network.STA_IF)
sta.active(True)
escanear_canal()
sta.active(False)
gc.collect()

print("[OK] Entrando al loop.")

while True:
    try:
        ciclo(estado_sensores)
    except Exception as e:
        print("[ERROR]", e)
        display.fb_fill(st7789.BLACK)
        display.fb_text(NODE_ID, 5, 4, COLOR_NODO)
        display.fb_text("ERROR:", 5, 24, st7789.RED)
        display.fb_text(str(e)[:24], 5, 40, st7789.WHITE)
        display.fb_text("Reiniciando...", 5, 64, st7789.YELLOW)
        display.show()
        time.sleep(3)
        import machine
        machine.reset()

