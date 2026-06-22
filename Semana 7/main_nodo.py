# main.py — Plantilla unificada de NODO (PIFNET)
# Junta: sensores.py + malla.py + st7789.py + fuentes.py
#
# Modos (boton izquierdo 3s para ciclar y reiniciar):
#   DESPIERTO  -> radio siempre activa, responde al instante, hace relay
#   LIGHT      -> lightsleep ciclico (balance bateria/latencia), puede relay
#   DEEP       -> deepsleep ciclico, minimo consumo, NO hace relay
#
# Compatible con el MASTER del companero: mismo protocolo PIFNET.

import gc, time, json, machine
from machine import Pin, lightsleep, deepsleep
import ui
from ui import NEGRO, BLANCO, ROJO, VERDE, AMARILLO, CYAN, MAGENTA, GRIS
from sensores import Sensores
from malla import Malla

gc.collect()

# ═══════════════════════════════════════════════
#  CONFIG  ← lo unico a tocar por nodo
# ═══════════════════════════════════════════════
NODE_ID = "SLAVE_07"

# Que sensores tiene ESTE nodo:
SEN = Sensores(usar_dht=True, usar_mq=False, usar_gy=False, usar_mpu=True,
               umbrales=ui.UMBRALES)

MODO_DEFAULT = ui.MODO_DEFAULT          # DESPIERTO / LIGHT / DEEP
SLEEP_MS     = ui.SLEEP_MS           # ciclo de sueno (sube a 300_000 = 5 min en produccion)
VENTANA_WAVE_MS  = ui.VENTANA_WAVE_MS
ALERTA_PERIODO_MS = ui.ALERTA_PERIODO_MS
T_LONG_PRESS_MS  = ui.T_LONG_PRESS_MS
CONFIG_FILE = ui.CONFIG_FILE

# Umbrales y modo por defecto vienen de ui.py
# Las alertas se evalúan con SEN.evaluar_alertas(med) → (nivel, afectados)
# El estado persiste en SEN (histéresis): consultar con SEN.estado_actual()
# (ver bloque CONFIG más abajo donde se instancia SEN con umbrales=ui.UMBRALES)

# ═══════════════════════════════════════════════
#  PANTALLA
# ═══════════════════════════════════════════════
ui.init()

def ui_msg(l1, l2="", c1=BLANCO, c2=GRIS):
    ui.msg(NODE_ID, l1, l2, c1, c2)

def ui_nodo(lec, estado="", ec=VERDE):
    ui.nodo(NODE_ID, MODO, lec, estado, ec)

def ui_alerta(nivel, lec, sensores):
    ui.alerta(NODE_ID, nivel, sensores, lec)

def ui_sleep():
    ui.dormido(NODE_ID, M.conectado)

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
    ui.luz(True)
    ui_msg("Modo:", nuevo, CYAN, VERDE)
    time.sleep(1.5)
    machine.reset()

def revisar_boton_modo():
    if btn_izq.value() != 0:
        return
    t0 = time.ticks_ms()
    ui.luz(True)
    while btn_izq.value() == 0:
        held = time.ticks_diff(time.ticks_ms(), t0)
        if held >= T_LONG_PRESS_MS:
            cambiar_modo()
        if ui.tft: ui.tft.fill_rect(0, 128, int(held * 240 / T_LONG_PRESS_MS), 6, VERDE)
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
    nivel, afect = SEN.evaluar_alertas(med)
    M.mandar_fb(med, mid=mid, alerta=nivel,
                a_t=afect if nivel else None)

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
            med, lec = medir(); SEN.evaluar_alertas(med)
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
                    med, lec = medir(); nivel, afect = SEN.evaluar_alertas(med)
                    responder(med, mid=d.get("mid"))
                    if nivel: ui_alerta(nivel, lec, afect)
                    else:     ui_nodo(lec, "FB enviado", VERDE)
            elif d["type"] == "FB":
                M.relay_fb(d)

        if time.ticks_diff(time.ticks_ms(), ult_auto) > SLEEP_MS:
            ult_auto = time.ticks_ms()
            med, lec = medir(); nivel, afect = SEN.evaluar_alertas(med)
            if nivel: ui_alerta(nivel, lec, afect)

        if SEN.estado_actual() == "ALERTA" and time.ticks_diff(time.ticks_ms(), ult_alerta) > ALERTA_PERIODO_MS:
            ult_alerta = time.ticks_ms()
            med, _ = medir(); SEN.evaluar_alertas(med)
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
        med, lec = medir(); nivel, afect = SEN.evaluar_alertas(med)
        if not M.conectado:
            M.escanear_canal(1800)          # ventana > intervalo de BEACON
        if nivel: ui_alerta(nivel, lec, afect)
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
    med, lec = medir(); nivel, afect = SEN.evaluar_alertas(med)
    if nivel: ui_alerta(nivel, lec, afect)
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
ui.luz(True)
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
    ui.luz(True)
    ui_msg("ERROR", str(e)[:24], ROJO, AMARILLO)
    time.sleep(3)
    machine.reset()
