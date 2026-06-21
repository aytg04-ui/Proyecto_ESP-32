# master_prueba.py — Master de pruebas (otro TTGO, NO el Nodo A ni Central B)
#
# Hace lo mismo que el master del compañero, en mínimo:
#   - Conecta a WiFi eligiendo SOLA entre varias redes conocidas.
#   - Manda WAVE (REQ:ALL) en broadcast PIFNET  → los nodos responden con FB.
#   - Recibe los FB, los muestra en CONSOLA y PANTALLA.
#   - Reenvía los datos a TELEGRAM.
#
# Para tus nodos es indistinguible del master real: mismo NET_ID,
# mismo from="MASTER_TTGO_GATEWAY", mismo formato WAVE/FB.
# El día que tengas el master real, apagas este y ya.
#
# Necesita en el dispositivo: st7789.py, fuentes.py (y urequests para Telegram).

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
#  CONFIGURACIÓN  ← edita esto
# ════════════════════════════════════════════════
NET_ID    = "PIFNET"
MASTER_ID = "MASTER_TTGO_GATEWAY"

# Redes conocidas (casa, uni, etc.). Se conecta a la PRIMERA disponible.
REDES = [
    ("Totalplay-C5AC", ""),
    ("Arte_Tenda2.4",  ""),
    ("Xiaomi_667C",  ""),
    # ("RedUni",       "claveuni"),
]
CANAL_FALLBACK = 1     # si no hay WiFi, ESP-NOW corre en este canal

# Telegram: crea un bot con @BotFather (te da el TOKEN) y obtén tu CHAT_ID
# escribiéndole a tu bot y revisando:
#   https://api.telegram.org/bot<TOKEN>/getUpdates  → busca "chat":{"id":...}
TELEGRAM = True #False
TG_TOKEN = "PON_AQUI_TU_TOKEN"
TG_CHAT  = "PON_AQUI_TU_CHAT_ID"

# Tiempos
T_WAVE_MS = 15_000     # cada cuánto pedir mediciones (WAVE REQ:ALL)
T_TG_MS   = 10_000     # cada cuánto vaciar la cola a Telegram
T_BEACON_MS = 2000
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
    tft.write(font_sm, "ch:{} wifi:{}".format(_canal, "OK" if _wifi_ok else "--"),
              C.GRIS if hasattr(C, "GRIS") else C.CYAN, x=4, y=20)
    tft.write(font_md, estado, color, x=4, y=42)
    if extra:
        tft.write(font_sm, extra[:30], C.WHITE, x=4, y=80)
    tft.write(font_sm, "nodos:{}".format(len(_nodos)), C.YELLOW, x=4, y=110)

# ════════════════════════════════════════════════
#  WIFI — elige sola entre las redes conocidas
# ════════════════════════════════════════════════
_sta     = network.WLAN(network.STA_IF)
_wifi_ok = False
_canal   = CANAL_FALLBACK

def conectar_wifi():
    global _wifi_ok, _canal
    _sta.active(True)
    try:                                   # apagar power-save (coexistir con ESP-NOW)
        _sta.config(pm=0xa11140)
    except: pass
    try:
        vistas = [s[0].decode() for s in _sta.scan()]
    except:
        vistas = []
    print("[WIFI] redes a la vista:", vistas)
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
    print("[WIFI] ninguna red conocida disponible — modo offline")
    _wifi_ok = False
    return False

# ════════════════════════════════════════════════
#  ESP-NOW
# ════════════════════════════════════════════════
def init_espnow():
    if not _wifi_ok:                       # sin WiFi: fijar canal manual
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
_nodos    = {}          # id -> última línea de datos
_cola_tg  = []          # líneas pendientes de mandar a Telegram
_mid      = 0
def next_mid():
    global _mid; _mid += 1; return _mid

# ════════════════════════════════════════════════
#  WAVE — pedir mediciones a todos
# ════════════════════════════════════════════════
def enviar_wave(en, cmd="REQ:ALL", target="ALL"):
    pkt = json.dumps({
        "type": "WAVE", "net": NET_ID, "cmd": cmd, "from": MASTER_ID,
        "target": target, "ttl": 6, "ch": _canal,
        "mid": next_mid(), "ts": "",
    })
    for _ in range(3):
        try: en.send(BROADCAST_MAC, pkt.encode())
        except OSError: pass
        time.sleep_ms(150)
    print("[WAVE TX] mid:{} cmd:{}".format(_mid, cmd))

def enviar_beacon(en):
    pkt = json.dumps({"type":"WAVE","net":NET_ID,"cmd":"BEACON","from":MASTER_ID,
                      "target":"NONE","ttl":3,"ch":_canal,"mid":next_mid(),"ts":""})
    try: en.send(BROADCAST_MAC, pkt.encode())
    except: pass

# ════════════════════════════════════════════════
#  FB → línea legible
# ════════════════════════════════════════════════
def fb_a_texto(d):
    partes = []
    for m in d.get("pl", []):
        t, v = m.get("t"), m.get("v")
        if t == "ACK":
            partes.append("ACK:" + str(v))
        else:
            partes.append("{}:{}".format(t, v))
    linea = "{}  {}".format(d.get("id", "?"), " ".join(partes))
    nivel = d.get("alert")
    if nivel:
        linea += "  [{}]".format(nivel)
    return linea

# ════════════════════════════════════════════════
#  TELEGRAM
# ════════════════════════════════════════════════
def flush_telegram():
    global _cola_tg
    if not (TELEGRAM and _wifi_ok and urequests and _cola_tg):
        return
    if TG_TOKEN.startswith("PON_AQUI"):
        print("[TG] falta configurar TOKEN/CHAT_ID")
        _cola_tg = []
        return
    texto = "Master prueba\n" + "\n".join(_cola_tg[-15:])   # sin emoji
    url = "https://api.telegram.org/bot{}/sendMessage".format(TG_TOKEN)
    try:
        r = urequests.post(url, json={"chat_id": TG_CHAT, "text": texto})
        print("[TG] code:", r.status_code, "resp:", r.text[:120])   # ← muestra el motivo
        r.close()
        if r.status_code == 200:
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
print("[OK] Master prueba activo. WAVE cada {}s".format(T_WAVE_MS // 1000))

ultimo_wave = 0
ultimo_beacon = 0
ultimo_tg   = time.ticks_ms()

# ════════════════════════════════════════════════
#  BUCLE
# ════════════════════════════════════════════════
while True:
    # WAVE periódica
    if time.ticks_diff(time.ticks_ms(), ultimo_beacon) >= T_BEACON_MS:
        ultimo_beacon = time.ticks_ms()
        enviar_beacon(en)

    # Recibir FB
    try: host, msg = en.recv(100)
    except: msg = None
    if msg:
        try:
            d = json.loads(msg.decode())
            if d.get("net") == NET_ID and d.get("type") == "FB":
                linea = fb_a_texto(d)
                print("[FB RX]", linea)
                _nodos[d.get("id", "?")] = linea
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

