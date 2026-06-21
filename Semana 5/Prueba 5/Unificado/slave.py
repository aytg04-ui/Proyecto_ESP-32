# main.py 

import gc, time, json, machine
from machine import Pin, SPI, lightsleep, deepsleep
import st7789
from fuentes import font_sm, font_md
from sensores import Sensores
from malla import Malla

gc.collect()

# ═══════════════════════════════════════════════
#  CONFIG  
# ═══════════════════════════════════════════════
NODE_ID = "SLAVE_07"

# Que sensores tiene ESTE nodo:
# SEN = Sensores(usar_dht=True, usar_mq=False, usar_gy=False, usar_mpu=True)
SEN = Sensores()   # todo "auto"

MODO_DEFAULT = "LIGHT"          # DESPIERTO / LIGHT / DEEP
SLEEP_MS     = 30_000           # ciclo de sueno (sube a 300_000 = 5 min en produccion)
VENTANA_WAVE_MS  = 8_000
ALERTA_PERIODO_MS = 10_000
T_LONG_PRESS_MS  = 3_000
CONFIG_FILE = "node_config.json"

# ═══════════════════════════════════════════════
#  COLORES
# ═══════════════════════════════════════════════
C = st7789
NEGRO, BLANCO = C.BLACK, C.WHITE
ROJO, VERDE   = C.RED, C.GREEN
AMARILLO, CYAN = C.YELLOW, C.CYAN
MAGENTA = C.MAGENTA
GRIS = C.color565(120, 120, 120)

# ═══════════════════════════════════════════════
#  UMBRALES DE ALERTA (con histeresis)
# ═══════════════════════════════════════════════
UMBRALES = {
    "Temp":    {"warn_hi": 45, "warn_hi_sale": 42, "crit_hi": 60, "crit_hi_sale": 55},
    "Hum":     {"warn_lo": 15, "warn_lo_sale": 18, "crit_lo": 8,  "crit_lo_sale": 11},
    "TempObj": {"warn_hi": 38, "warn_hi_sale": 37.5, "crit_hi": 39.5, "crit_hi_sale": 39},
    "MQ135":   {"warn_hi": 2500, "warn_hi_sale": 2200, "crit_hi": 3500, "crit_hi_sale": 3200},
}
alertas = {}   # {tipo: "warn"|"crit"}

def _num(v):
    try: return float(v)
    except: return None

def _nivel(v, c, actual):
    if (c.get("crit_hi") is not None and v >= c["crit_hi"]) or \
       (c.get("crit_lo") is not None and v <= c["crit_lo"]):
        return "crit"
    if actual == "crit":
        if c.get("crit_hi_sale") is not None and v >= c["crit_hi_sale"]: return "crit"
        if c.get("crit_lo_sale") is not None and v <= c["crit_lo_sale"]: return "crit"
    if (c.get("warn_hi") is not None and v >= c["warn_hi"]) or \
       (c.get("warn_lo") is not None and v <= c["warn_lo"]):
        return "warn"
    if actual in ("warn", "crit"):
        if c.get("warn_hi_sale") is not None and v >= c["warn_hi_sale"]: return "warn"
        if c.get("warn_lo_sale") is not None and v <= c["warn_lo_sale"]: return "warn"
    return None

def evaluar(med):
    for m_ in med:
        t = m_.get("t"); c = UMBRALES.get(t)
        if not c: continue
        v = _num(m_.get("v"))
        if v is None: continue
        n = _nivel(v, c, alertas.get(t))
        if n: alertas[t] = n
        elif t in alertas: del alertas[t]
    return nivel_global()

def nivel_global():
    vals = list(alertas.values())
    if "crit" in vals: return "CRIT"
    if "warn" in vals: return "WARN"
    return None

# ═══════════════════════════════════════════════
#  PANTALLA
# ═══════════════════════════════════════════════
spi = SPI(1, baudrate=20000000, sck=Pin(18), mosi=Pin(19))
tft = st7789.ST7789(spi, 135, 240, dc=Pin(16, Pin.OUT), cs=Pin(5, Pin.OUT),
                    reset=Pin(23, Pin.OUT), backlight=Pin(4, Pin.OUT), rotation=1)
bl = Pin(4, Pin.OUT)

def luz(on=True):
    bl.value(1 if on else 0)

def ui_msg(l1, l2="", c1=BLANCO, c2=GRIS):
    tft.fill(NEGRO)
    tft.write(font_sm, NODE_ID, CYAN, x=4, y=2)
    tft.write(font_md, l1, c1, y=42, center=True)
    if l2:
        tft.write(font_sm, l2, c2, y=84, center=True)

def ui_nodo(lec, estado="", ec=VERDE):
    tft.fill(NEGRO)
    tft.cursor(4, 2)
    tft.write(font_sm, NODE_ID + "  " + MODO[:4], CYAN)
    if "t" in lec:
        tft.write(font_sm, "T:{} H:{}".format(lec["t"], lec["h"]), BLANCO)
    if "obj" in lec:
        fb = isinstance(lec["obj"], (int, float)) and lec["obj"] >= 38
        tft.write(font_sm, "GY {}/{}C".format(lec.get("amb"), lec["obj"]),
                  ROJO if fb else MAGENTA)
    if "mq" in lec:
        tft.write(font_sm, "MQ:{}".format(lec["mq"]), CYAN)
    if "ax" in lec:
        tft.write(font_sm, "Ax:{} Az:{}".format(lec["ax"], lec["az"]), AMARILLO)
    if estado:
        tft.write(font_sm, estado, ec)

def ui_alerta(nivel, lec, sensores):
    luz(True)
    fondo = ROJO if nivel == "CRIT" else NEGRO
    ctxt  = BLANCO if nivel == "CRIT" else AMARILLO
    tft.fill(fondo)
    tft.write(font_sm, NODE_ID, BLANCO if nivel == "CRIT" else CYAN, x=4, y=2)
    tft.write(font_md, "ALERTA" if nivel == "CRIT" else "ATENCION", ctxt, y=26, center=True)
    tft.write(font_sm, (",".join(sensores))[:24], ctxt, y=64, center=True)
    tft.write(font_sm, "T:{} H:{}".format(lec.get("t", "--"), lec.get("h", "--")),
              ctxt, y=88, center=True)

def ui_sleep():
    tft.fill(NEGRO)
    tft.write(font_sm, NODE_ID, CYAN, x=4, y=40)
    con = "conectado" if M.conectado else "sin senal"
    tft.write(font_sm, con, VERDE if M.conectado else GRIS, x=4, y=66)
    tft.write(font_sm, "durmiendo...", GRIS, x=4, y=92)
    luz(False)

# ═══════════════════════════════════════════════
#  CONFIG PERSISTENTE (modo, dormido, canal)
# ═══════════════════════════════════════════════
def cargar_cfg():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except:
        return {"modo": MODO_DEFAULT, "dormido": False, "canal": 1}

def guardar_cfg(c):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(c, f)
    except Exception as e:
        print("[CFG ERR]", e)

CFG  = cargar_cfg()
MODO = CFG.get("modo", MODO_DEFAULT)
if MODO not in ("DESPIERTO", "LIGHT", "DEEP"):
    MODO = MODO_DEFAULT

# ═══════════════════════════════════════════════
#  BOTONES + cambio de modo
# ═══════════════════════════════════════════════
btn_izq = Pin(0, Pin.IN, Pin.PULL_UP)
btn_der = Pin(35, Pin.IN)
ORDEN_MODOS = ["DESPIERTO", "LIGHT", "DEEP"]

def cambiar_modo():
    i = ORDEN_MODOS.index(MODO) if MODO in ORDEN_MODOS else 1
    nuevo = ORDEN_MODOS[(i + 1) % len(ORDEN_MODOS)]
    CFG["modo"] = nuevo
    guardar_cfg(CFG)
    luz(True)
    ui_msg("Modo:", nuevo, CYAN, VERDE)
    time.sleep(1.5)
    machine.reset()

def revisar_boton_modo():
    if btn_izq.value() != 0:
        return
    t0 = time.ticks_ms()
    luz(True)
    while btn_izq.value() == 0:
        held = time.ticks_diff(time.ticks_ms(), t0)
        if held >= T_LONG_PRESS_MS:
            cambiar_modo()
        tft.fill_rect(0, 128, int(held * 240 / T_LONG_PRESS_MS), 6, VERDE)
        time.sleep_ms(40)

# ═══════════════════════════════════════════════
#  MALLA
# ═══════════════════════════════════════════════
M = Malla(NODE_ID, canales=[1, 6, 11, 4, 8, 2, 3, 5, 7, 9, 10],
          relay=(MODO != "DEEP"))   # DEEP no puede hacer relay (duerme apagado)

_lec = {}

# ═══════════════════════════════════════════════
#  MEDICION + ENVIO
# ═══════════════════════════════════════════════
def medir():
    global _lec
    med, _lec = SEN.leer()
    return med, _lec

def responder(med, mid=None):
    nivel = nivel_global()
    M.mandar_fb(med, mid=mid, alerta=nivel,
                a_t=list(alertas.keys()) if nivel else None)

def dormir():
    M.mandar_ack("DORMIR")
    ui_msg("Durmiendo", "", ROJO)
    time.sleep(1)
    CFG["dormido"] = True
    CFG["canal"]   = M.canal
    guardar_cfg(CFG)
    M.cerrar()
    deepsleep(SLEEP_MS)

# ═══════════════════════════════════════════════
#  ESTADO DORMIDO (espera ACTIVAR)
# ═══════════════════════════════════════════════
def revisar_dormido():
    if not CFG.get("dormido"):
        return
    ui_msg("Dormido", "esperando ACTIVAR", ROJO)
    M.iniciar(canal=CFG.get("canal", 1))
    fin = time.ticks_add(time.ticks_ms(), 35_000)
    while time.ticks_diff(fin, time.ticks_ms()) > 0:
        d = M.recibir(200)
        if d and d.get("type") == "WAVE" and d.get("cmd") == "ACTIVAR" \
                and d.get("target") in ("ALL", NODE_ID):
            M.mandar_ack("ACTIVAR")
            CFG["dormido"] = False
            guardar_cfg(CFG)
            ui_msg("Activado!", "", VERDE)
            time.sleep(1)
            return          # sigue al modo normal
    # nadie activo: vuelve a dormir
    CFG["canal"] = M.canal
    guardar_cfg(CFG)
    M.cerrar()
    deepsleep(SLEEP_MS)

# ═══════════════════════════════════════════════
#  MODO DESPIERTO
# ═══════════════════════════════════════════════
def correr_despierto():
    M.iniciar()
    for _ in range(3):
        if M.escanear_canal(): break
    med, lec = medir()
    ui_nodo(lec, "escuchando", GRIS)
    ult_auto = time.ticks_ms()
    ult_alerta = 0
    while True:
        revisar_boton_modo()
        if btn_der.value() == 0:
            med, lec = medir(); evaluar(med)
            responder(med); ui_nodo(lec, "FB (boton)", VERDE)
            while btn_der.value() == 0: time.sleep_ms(50)

        d = M.recibir(50)
        if d:
            if d["type"] == "WAVE":
                cmd = d.get("cmd", "")
                resp = M.manejar_wave(d)
                if cmd == "DORMIR" and d.get("target") in ("ALL", NODE_ID):
                    dormir()
                elif resp:
                    med, lec = medir(); nivel = evaluar(med)
                    responder(med, mid=d.get("mid"))
                    if nivel: ui_alerta(nivel, lec, list(alertas.keys()))
                    else:     ui_nodo(lec, "FB enviado", VERDE)
            elif d["type"] == "FB":
                M.relay_fb(d)

        if time.ticks_diff(time.ticks_ms(), ult_auto) > SLEEP_MS:
            ult_auto = time.ticks_ms()
            med, lec = medir(); nivel = evaluar(med)
            if nivel: ui_alerta(nivel, lec, list(alertas.keys()))

        if alertas and time.ticks_diff(time.ticks_ms(), ult_alerta) > ALERTA_PERIODO_MS:
            ult_alerta = time.ticks_ms()
            med, _ = medir(); evaluar(med)
            responder(med)
        time.sleep_ms(20)
        gc.collect()

# ═══════════════════════════════════════════════
#  MODO LIGHT (lightsleep)
# ═══════════════════════════════════════════════
def correr_light():
    while True:
        revisar_boton_modo()
        M.iniciar()
        med, lec = medir(); nivel = evaluar(med)
        if not M.conectado:
            M.escanear_canal(1800)          # ventana > intervalo de BEACON
        if nivel: ui_alerta(nivel, lec, list(alertas.keys()))
        else:     ui_nodo(lec, "enviando", GRIS)

        responder(med)                       # reporta SIEMPRE, no depende de la WAVE

        fin = time.ticks_add(time.ticks_ms(), VENTANA_WAVE_MS)
        while time.ticks_diff(fin, time.ticks_ms()) > 0:
            d = M.recibir(50)
            if not d: continue
            if d["type"] == "WAVE":
                cmd = d.get("cmd", "")
                resp = M.manejar_wave(d)
                if cmd == "DORMIR" and d.get("target") in ("ALL", NODE_ID):
                    dormir()
                elif resp:
                    responder(med, mid=d.get("mid"))
                    ui_nodo(lec, "FB enviado", VERDE)
                    break
            elif d["type"] == "FB":
                M.relay_fb(d)

        M.cerrar()
        ui_sleep()
        time.sleep_ms(50)
        lightsleep(SLEEP_MS)

# ═══════════════════════════════════════════════
#  MODO DEEP (deepsleep; el programa reinicia cada ciclo)
# ═══════════════════════════════════════════════
def correr_deep():
    M.iniciar(canal=CFG.get("canal", 1))
    med, lec = medir(); nivel = evaluar(med)
    if nivel: ui_alerta(nivel, lec, list(alertas.keys()))
    else:     ui_nodo(lec, "buscando", GRIS)

    wave = None
    fin = time.ticks_add(time.ticks_ms(), VENTANA_WAVE_MS)
    while time.ticks_diff(fin, time.ticks_ms()) > 0:
        d = M.recibir(100)
        if d and d.get("type") == "WAVE" and d.get("from") == M.master_id:
            wave = d; break
    if wave is None:
        M.escanear_canal()

    if wave and M.manejar_wave(wave):
        if wave.get("cmd") == "DORMIR" and wave.get("target") in ("ALL", NODE_ID):
            dormir()
        responder(med, mid=wave.get("mid"))
        ui_nodo(lec, "FB enviado", VERDE)
    else:
        responder(med)          # broadcast por si alguien escucha

    CFG["canal"] = M.canal
    guardar_cfg(CFG)
    M.cerrar()
    ui_sleep()
    deepsleep(SLEEP_MS)

# ═══════════════════════════════════════════════
#  ARRANQUE
# ═══════════════════════════════════════════════
luz(True)
ui_msg("PIF NODE", NODE_ID + "  " + MODO, VERDE, CYAN)
time.sleep(1.5)
SEN.detectar()
gc.collect()

revisar_dormido()          # si estaba dormido, espera ACTIVAR antes de seguir

try:
    if MODO == "DESPIERTO":
        correr_despierto()
    elif MODO == "DEEP":
        correr_deep()
    else:
        correr_light()
except Exception as e:
    print("[FATAL]", e)
    luz(True)
    ui_msg("ERROR", str(e)[:24], ROJO, AMARILLO)
    time.sleep(3)
    machine.reset()