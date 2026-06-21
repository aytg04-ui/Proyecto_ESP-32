# master_prueba.py

import gc, network, espnow, time, json
from machine import Pin, SPI
import st7789
from fuentes import font_sm, font_md
try:
    import urequests
except:
    urequests = None

gc.collect()

# ════════════════════════════════════════════════
#  CONFIGURACION  <- edita esto
# ════════════════════════════════════════════════
NET_ID    = "PIFNET"
MASTER_ID = "MASTER_TTGO_GATEWAY"

# Redes conocidas (casa, uni, etc.). Se conecta a la PRIMERA disponible.
REDES = [
    ("Xiaomi_667C",    ""),
    ("Totalplay-C5AC", ""),
    ("Arte_Tenda2.4",  ""),
    # ("RedUni",       "claveuni"),
]
CANAL_FALLBACK = 1

# Telegram (toggle en vivo con boton P0)
TELEGRAM = True
TG_TOKEN = "PON_AQUI_TU_TOKEN"
TG_CHAT  = "PON_AQUI_TU_CHAT_ID"

# Tiempos
T_WAVE_MS   = 15_000     # WAVE REQ:ALL (pide mediciones)
T_BEACON_MS = 2_000      # BEACON (solo sincroniza canal, no pide datos)
T_TG_MS     = 30_000     # vaciar cola a Telegram
BROADCAST_MAC = b'\xff\xff\xff\xff\xff\xff'

# ════════════════════════════════════════════════
#  PANTALLA
# ════════════════════════════════════════════════
spi = SPI(1, baudrate=20000000, polarity=0, phase=0, sck=Pin(18), mosi=Pin(19))
tft = st7789.ST7789(spi, 135, 240,
                    dc=Pin(16, Pin.OUT), cs=Pin(5, Pin.OUT),
                    reset=Pin(23, Pin.OUT), backlight=Pin(4, Pin.OUT),
                    rotation=1)
C = st7789

def ui(estado, color=C.WHITE, extra=""):
    tft.fill(C.BLACK)
    tft.write(font_sm, "MASTER prueba", C.GREEN, x=4, y=2)
    tft.write(font_sm, "ch:{} wifi:{} TG:{}".format(
        _canal, "OK" if _wifi_ok else "--", "ON" if TELEGRAM else "OFF"),
        C.CYAN, x=4, y=20)
    tft.write(font_md, estado, color, x=4, y=42)
    if extra:
        tft.write(font_sm, extra[:30], C.WHITE, x=4, y=80)
    tft.write(font_sm, "nodos:{}".format(len(_nodos)), C.YELLOW, x=4, y=110)

# ════════════════════════════════════════════════
#  BOTONES
# ════════════════════════════════════════════════
btn_tg  = Pin(0, Pin.IN, Pin.PULL_UP)    # P0: alternar Telegram
btn_req = Pin(35, Pin.IN, Pin.PULL_UP)   # P35: forzar REQ:ALL ya
_ult_btn = 0
T_OFFLINE_MS = 90_000                    # nodo sin reportar este tiempo -> se quita del conteo

# ════════════════════════════════════════════════
#  WIFI — elige sola entre las redes conocidas
# ════════════════════════════════════════════════
_sta     = network.WLAN(network.STA_IF)
_wifi_ok = False
_canal   = CANAL_FALLBACK

def conectar_wifi():
    global _wifi_ok, _canal
    _sta.active(True)
    try:
        _sta.config(pm=0xa11140)           # power-save off (coexistir con ESP-NOW)
    except: pass
    try:
        vistas = [s[0].decode() for s in _sta.scan()]
    except:
        vistas = []
    print("[WIFI] a la vista:", vistas)
    for ssid, pwd in REDES:
        if ssid in vistas:
            print("[WIFI] conectando a", ssid)
            _sta.connect(ssid, pwd)
            t = time.ticks_ms()
            while not _sta.isconnected() and time.ticks_diff(time.ticks_ms(), t) < 9000:
                time.sleep_ms(200)
            if _sta.isconnected():
                _wifi_ok = True
                try:    _canal = _sta.config('channel')
                except: _canal = CANAL_FALLBACK
                print("[WIFI] OK", ssid, "ip:", _sta.ifconfig()[0], "ch:", _canal)
                return True
    print("[WIFI] ninguna red conocida — modo offline")
    _wifi_ok = False
    return False

# ════════════════════════════════════════════════
#  ESP-NOW
# ════════════════════════════════════════════════
def init_espnow():
    if not _wifi_ok:
        _sta.active(True)
        try: _sta.config(channel=CANAL_FALLBACK)
        except: pass
        time.sleep_ms(150)
    en = espnow.ESPNow()
    en.active(True)
    en.add_peer(BROADCAST_MAC)
    return en

# ════════════════════════════════════════════════
#  ESTADO
# ════════════════════════════════════════════════
_nodos   = {}
_cola_tg = []
_mid     = 0
def next_mid():
    global _mid; _mid += 1; return _mid

# ════════════════════════════════════════════════
#  WAVE / BEACON
# ════════════════════════════════════════════════
def enviar_wave(en, cmd="REQ:ALL", target="ALL"):
    pkt = json.dumps({
        "type": "WAVE", "net": NET_ID, "cmd": cmd, "from": MASTER_ID,
        "target": target, "ttl": 6, "ch": _canal, "mid": next_mid(), "ts": "",
    })
    for _ in range(3):
        try: en.send(BROADCAST_MAC, pkt.encode())
        except OSError: pass
        time.sleep_ms(150)
    print("[WAVE TX] mid:{} cmd:{}".format(_mid, cmd))

def enviar_beacon(en):
    pkt = json.dumps({
        "type": "WAVE", "net": NET_ID, "cmd": "BEACON", "from": MASTER_ID,
        "target": "NONE", "ttl": 3, "ch": _canal, "mid": next_mid(), "ts": "",
    })
    try: en.send(BROADCAST_MAC, pkt.encode())
    except: pass

# ════════════════════════════════════════════════
#  FB -> linea legible
# ════════════════════════════════════════════════
def fb_a_texto(d):
    partes = []
    for m in d.get("pl", []):
        t, v = m.get("t"), m.get("v")
        partes.append(("ACK:" + str(v)) if t == "ACK" else "{}:{}".format(t, v))
    linea = "{}  {}".format(d.get("id", "?"), " ".join(partes))
    if d.get("alert"):
        linea += "  [{}]".format(d["alert"])
    return linea

# ════════════════════════════════════════════════
#  TELEGRAM
# ════════════════════════════════════════════════
def flush_telegram():
    global _cola_tg
    if not _cola_tg:
        return
    if not (TELEGRAM and _wifi_ok and urequests):
        _cola_tg = []                      # TG apagado: descarta para no acumular
        return
    if TG_TOKEN.startswith("PON_AQUI"):
        print("[TG] falta TOKEN/CHAT_ID")
        _cola_tg = []
        return
    texto = "Master prueba\n" + "\n".join(_cola_tg[-15:])
    url = "https://api.telegram.org/bot{}/sendMessage".format(TG_TOKEN)
    try:
        r = urequests.post(url, json={"chat_id": TG_CHAT, "text": texto})
        print("[TG] code:", r.status_code)
        ok = (r.status_code == 200)
        r.close()
        if ok:
            _cola_tg = []
    except Exception as e:
        print("[TG ERR]", e)
    gc.collect()

# ════════════════════════════════════════════════
#  ARRANQUE
# ════════════════════════════════════════════════
ui("Iniciando", C.CYAN)
conectar_wifi()
en = init_espnow()
ui("Listo", C.GREEN, "esperando nodos")
print("[OK] Master prueba activo. WAVE {}s, BEACON {}s".format(
    T_WAVE_MS // 1000, T_BEACON_MS // 1000))

ultimo_wave   = 0
ultimo_beacon = 0
ultimo_tg     = time.ticks_ms()

# ════════════════════════════════════════════════
#  BUCLE
# ════════════════════════════════════════════════
while True:
    # Boton P0: alternar Telegram
    if btn_tg.value() == 0 and time.ticks_diff(time.ticks_ms(), _ult_btn) > 400:
        _ult_btn = time.ticks_ms()
        TELEGRAM = not TELEGRAM
        ui("TG: " + ("ON" if TELEGRAM else "OFF"), C.GREEN if TELEGRAM else C.RED)
        print("[TG] envio:", "ON" if TELEGRAM else "OFF")

    # Boton P35: forzar REQ:ALL ya (sin esperar el ciclo)
    if btn_req.value() == 0 and time.ticks_diff(time.ticks_ms(), _ult_btn) > 400:
        _ult_btn = time.ticks_ms()
        enviar_wave(en)
        ultimo_wave = time.ticks_ms()
        ui("REQ enviado", C.CYAN)

    # Purga de nodos que ya no reportan (para que el conteo sea real)
    for _id in [k for k, val in _nodos.items()
                if time.ticks_diff(time.ticks_ms(), val[1]) > T_OFFLINE_MS]:
        del _nodos[_id]
        print("[HC] quitado del conteo:", _id)

    # BEACON (sincroniza canal de los nodos)
    if time.ticks_diff(time.ticks_ms(), ultimo_beacon) >= T_BEACON_MS:
        ultimo_beacon = time.ticks_ms()
        enviar_beacon(en)

    # WAVE periodica (pide mediciones)
    if time.ticks_diff(time.ticks_ms(), ultimo_wave) >= T_WAVE_MS:
        ultimo_wave = time.ticks_ms()
        enviar_wave(en)

    # Recibir FB
    try: host, msg = en.recv(100)
    except: msg = None
    if msg:
        try:
            d = json.loads(msg.decode())
            if d.get("net") == NET_ID and d.get("type") == "FB":
                linea = fb_a_texto(d)
                print("[FB RX]", linea)
                _nodos[d.get("id", "?")] = (linea, time.ticks_ms())
                _cola_tg.append(linea)
                ui("RX " + d.get("id", "?"), C.GREEN, linea)
        except Exception as e:
            print("[RX ERR]", e)

    # Vaciar a Telegram
    if time.ticks_diff(time.ticks_ms(), ultimo_tg) >= T_TG_MS:
        ultimo_tg = time.ticks_ms()
        flush_telegram()

    time.sleep_ms(20)
    gc.collect()