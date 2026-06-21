# central_b.py — Nodo Supervisor (sobre malla.py)
# Ya no tiene su propia logica ESP-NOW: usa el nucleo comun malla.Malla.
# Sigue siendo el de control: pantalla + menu + ordenes (Solicitar/Dormir/Activar).
# Siempre despierto.
#
# Necesita: st7789.py, fuentes.py, malla.py
# (mismo st7789.py corregido que los nodos: fill_rect con CS + BGR)

import gc, time
from machine import Pin, SPI
import st7789
from fuentes import font_sm, font_md
from malla import Malla

gc.collect()

# ═══════════════════════════════════════════════
#  CONFIG  ← un supervisor por piso: cambia SUPER_NUM
# ═══════════════════════════════════════════════
SUPER_NUM = 0
NODE_ID   = "SUPER_P{}".format(SUPER_NUM)
MID_BASE  = 1_000_000 * (SUPER_NUM + 1)   # mid propio, no choca con master ni otros super
RELAY     = True                          # retransmitir para extender alcance

CANALES   = [1, 6, 11, 4, 8, 2, 3, 5, 7, 9, 10]
TIMEOUT_FRESH = 60_000
CICLO_MONITOR = 5_000
ACTIVAR_REPS  = 5

C = st7789
PALETA = [C.YELLOW, C.MAGENTA, C.GREEN, C.CYAN, C.ORANGE, C.BLUE]

# ═══════════════════════════════════════════════
#  PANTALLA
# ═══════════════════════════════════════════════
spi = SPI(1, baudrate=20000000, sck=Pin(18), mosi=Pin(19))
tft = st7789.ST7789(spi, 135, 240, dc=Pin(16, Pin.OUT), cs=Pin(5, Pin.OUT),
                    reset=Pin(23, Pin.OUT), backlight=Pin(4, Pin.OUT), rotation=1)

# ═══════════════════════════════════════════════
#  BOTONES
# ═══════════════════════════════════════════════
class Boton:
    def __init__(self, pin):
        self.pin = Pin(pin, Pin.IN, Pin.PULL_UP)
        self.ult = 0
    def presionado(self):
        ahora = time.ticks_ms()
        if self.pin.value() == 0 and time.ticks_diff(ahora, self.ult) > 300:
            self.ult = ahora
            return True
        return False

btn_ok  = Boton(0)
btn_nav = Boton(35)

# ═══════════════════════════════════════════════
#  MALLA
# ═══════════════════════════════════════════════
M = Malla(NODE_ID, canales=CANALES, relay=RELAY, mid_base=MID_BASE)

# ═══════════════════════════════════════════════
#  ESTADO
# ═══════════════════════════════════════════════
nodos = {}            # id -> {"pl":{t:v},"ultimo","alert","color","dormido"}
pend_dormir  = set()
pend_activar = set()
_proc = {}            # dedup de FB para procesar (aparte del relay)

MONITOR, NIVEL1, NIVEL2, DETALLE = 0, 1, 2, 3
modo = MONITOR
pag  = 0
op1 = op2 = 0
sel_nodo = None
ultimo_ciclo = time.ticks_ms()
sucia = True

# ═══════════════════════════════════════════════
#  REGISTRO DE NODOS
# ═══════════════════════════════════════════════
def registrar_fb(d):
    nid = d.get("id")
    if not nid or nid == NODE_ID:
        return
    pl = {}
    for m_ in d.get("pl", []):
        t, v = m_.get("t"), m_.get("v")
        if t == "ACK":
            continue
        pl[t] = v
    if nid not in nodos:
        nodos[nid] = {"color": PALETA[len(nodos) % len(PALETA)]}
    info = nodos[nid]
    if pl:
        info["pl"] = pl
    info["ultimo"] = time.ticks_ms()
    info["alert"]  = d.get("alert")
    if nid not in pend_dormir:        # no pisar el estado si lo estamos durmiendo
        info["dormido"] = False

def lista_nodos():
    return sorted(nodos.keys())

def resumen(pl):
    L = []
    if "AccX" in pl:
        ax, az = pl.get("AccX", 0), pl.get("AccZ", 1)
        mov = abs(az - 1.0) > 0.3 or abs(ax) > 0.3
        L.append(("MPU X:{:.2f} Z:{:.2f}".format(ax, az), C.WHITE))
        L.append(("MOV!" if mov else "Reposo", C.RED if mov else C.GREEN))
    if "TempObj" in pl:
        amb, obj = pl.get("TempAmb", 0), pl["TempObj"]
        fb = isinstance(obj, (int, float)) and obj >= 38
        L.append(("GY {}/{}C".format(amb, obj), C.RED if fb else C.MAGENTA))
    if "Temp" in pl:
        L.append(("DHT {}C {}%".format(pl.get("Temp"), pl.get("Hum")), C.GREEN))
    if "MQ135" in pl:
        v = pl["MQ135"]
        try:
            v = int(v)
            cal = ("Limpio" if v < 1200 else "Regular" if v < 2000
                   else "Malo" if v < 2500 else "Peligroso")
        except: cal = "?"
        L.append(("MQ:{} {}".format(v, cal), C.CYAN))
    return L or [("Sin sensores", C.RED)]

# ═══════════════════════════════════════════════
#  ORDENES (WAVE via malla)
# ═══════════════════════════════════════════════
def orden(accion, nombre):
    objetivos = list(nodos.keys()) if nombre == "Todos" else [nombre]
    target    = "ALL" if nombre == "Todos" else nombre
    if accion.startswith("Solicitar"):
        M.mandar_wave("REQ:" + target, target)
    elif accion.startswith("Dormir"):
        for n in objetivos:
            pend_dormir.add(n); pend_activar.discard(n)
            if n in nodos: nodos[n]["dormido"] = True
        M.mandar_wave("DORMIR", target)
        _pantalla_simple("Dormir", "al despertar", C.RED)
        time.sleep_ms(800)
    elif accion.startswith("Activar"):
        for n in objetivos:
            pend_activar.add(n); pend_dormir.discard(n)
            if n in nodos: nodos[n]["dormido"] = False
        _pantalla_simple("Activando", nombre, C.CYAN)
        for _ in range(ACTIVAR_REPS):
            M.mandar_wave("ACTIVAR", target, reps=1)
            time.sleep_ms(400)

def acciones_de(nombre):
    if nombre == "Todos":
        return ["Solicitar todos", "Dormir todos", "Activar todos", "Volver"]
    dormido = nodos.get(nombre, {}).get("dormido")
    return (["Activar", "Volver"] if dormido
            else ["Solicitar", "Dormir", "Volver"])

# ═══════════════════════════════════════════════
#  PANTALLAS
# ═══════════════════════════════════════════════
def _pantalla_simple(l1, l2, color):
    tft.fill(C.BLACK)
    tft.write(font_md, l1, color, y=30, center=True)
    if l2:
        tft.write(font_md, l2, C.WHITE, y=70, center=True)

def edad_txt(info):
    return "{}s".format(time.ticks_diff(time.ticks_ms(), info.get("ultimo", 0)) // 1000)

def pantalla_monitor():
    global pag
    tft.fill(C.BLACK)
    tft.header(font_sm, [(NODE_ID, C.CYAN),
                         ("P0:menu" + (" *" if M.conectado else ""), C.WHITE, "right")])
    ids = lista_nodos()
    if not ids:
        tft.write(font_md, "Sin nodos", C.RED, center=True)
        tft.write(font_sm, "Escuchando malla...", C.WHITE, center=True)
        return
    if pag >= len(ids): pag = 0
    nid  = ids[pag]
    info = nodos[nid]
    tft.cursor(2, tft._cy)
    enc = nid + (" ZZZ" if info.get("dormido") else "")
    if info.get("alert"):
        enc += " !" + info["alert"]
    tft.write(font_sm, enc, info["color"])
    if info.get("pl"):
        for txt, col in resumen(info["pl"])[:3]:
            tft.write(font_sm, txt, col)
    else:
        tft.write(font_sm, "Sin datos aun", C.RED)
    tft.write(font_sm, "{}/{} {}".format(pag + 1, len(ids), edad_txt(info)),
              C.WHITE, x=2, y=tft.height - 18)

def pantalla_nivel1():
    ids = lista_nodos() + ["Todos"]
    tft.fill(C.BLACK)
    tft.header(font_sm, [("Elegir nodo", C.CYAN), ("P35:nav P0:ok", C.WHITE, "right")])
    tft.cursor(4, tft._cy)
    ini = max(0, min(op1 - 1, len(ids) - 4))
    for i in range(ini, min(ini + 4, len(ids))):
        nombre = ids[i]
        col = nodos[nombre]["color"] if nombre in nodos else C.WHITE
        pre = "> " if i == op1 else "  "
        tft.write(font_sm, pre + nombre, C.YELLOW if i == op1 else col)

def pantalla_nivel2():
    tft.fill(C.BLACK)
    col = nodos[sel_nodo]["color"] if sel_nodo in nodos else C.WHITE
    tft.header(font_sm, [(sel_nodo, col), ("P35:nav P0:ok", C.WHITE, "right")])
    tft.cursor(8, tft._cy)
    for i, a in enumerate(acciones_de(sel_nodo)):
        pre = "> " if i == op2 else "  "
        tft.write(font_sm, pre + a, C.YELLOW if i == op2 else C.WHITE)

def pantalla_detalle(nombre):
    info = nodos.get(nombre)
    tft.fill(C.BLACK)
    col = info["color"] if info else C.WHITE
    tft.header(font_sm, [(nombre, col), ("P0:salir", C.WHITE, "right")])
    tft.cursor(4, tft._cy)
    if not info or not info.get("pl"):
        tft.write(font_sm, "Sin datos", C.RED)
        return
    for txt, c in resumen(info["pl"])[:4]:
        tft.write(font_sm, txt, c)

def dibujar():
    if modo == MONITOR:   pantalla_monitor()
    elif modo == NIVEL1:  pantalla_nivel1()
    elif modo == NIVEL2:  pantalla_nivel2()
    elif modo == DETALLE: pantalla_detalle(sel_nodo)

# ═══════════════════════════════════════════════
#  ARRANQUE
# ═══════════════════════════════════════════════
_pantalla_simple("Central B", NODE_ID, C.CYAN)
time.sleep(1)
M.iniciar()
M.escanear_canal(1800)
sucia = True

# ═══════════════════════════════════════════════
#  BUCLE
# ═══════════════════════════════════════════════
while True:
    d = M.recibir(50)
    if d:
        tipo = d.get("type")
        if tipo == "WAVE":
            M.manejar_wave(d)              # adopta canal del master + relay (ignora respuesta)
        elif tipo == "FB":
            idn   = d.get("id")
            clave = "{}|{}".format(idn, d.get("mid"))
            if not M._visto(_proc, clave):
                ack = None
                for m_ in d.get("pl", []):
                    if m_.get("t") == "ACK":
                        ack = m_.get("v")
                if ack == "DORMIR":
                    pend_dormir.discard(idn)
                    if idn in nodos: nodos[idn]["dormido"] = True
                elif ack == "ACTIVAR":
                    pend_activar.discard(idn)
                    if idn in nodos: nodos[idn]["dormido"] = False
                else:
                    registrar_fb(d)
                    if idn in pend_dormir:     # esta despierto -> insistir DORMIR ~3s
                        t0 = time.ticks_ms()
                        while time.ticks_diff(time.ticks_ms(), t0) < 3000:
                            M.mandar_wave("DORMIR", idn, reps=1)
                M.relay_fb(d)
                sucia = True
                if modo == DETALLE and sel_nodo == idn:
                    pantalla_detalle(sel_nodo)

    if btn_ok.presionado():
        if modo == MONITOR:
            modo, op1 = NIVEL1, 0; sucia = True
        elif modo == NIVEL1:
            sel_nodo = (lista_nodos() + ["Todos"])[op1]
            modo, op2 = NIVEL2, 0; sucia = True
        elif modo == NIVEL2:
            acc = acciones_de(sel_nodo)[op2]
            if acc == "Volver":
                modo = NIVEL1
            else:
                orden(acc, sel_nodo)
                modo = DETALLE if acc == "Solicitar" else MONITOR
                if acc == "Solicitar": time.sleep_ms(400)
            sucia = True
        elif modo == DETALLE:
            modo = MONITOR; sucia = True

    if btn_nav.presionado():
        if modo == MONITOR:
            ids = lista_nodos()
            if len(ids) > 1: pag = (pag + 1) % len(ids)
            ultimo_ciclo = time.ticks_ms(); sucia = True
        elif modo == NIVEL1:
            op1 = (op1 + 1) % (len(lista_nodos()) + 1); sucia = True
        elif modo == NIVEL2:
            op2 = (op2 + 1) % len(acciones_de(sel_nodo)); sucia = True

    if modo == MONITOR and time.ticks_diff(time.ticks_ms(), ultimo_ciclo) >= CICLO_MONITOR:
        ids = lista_nodos()
        if len(ids) > 1: pag = (pag + 1) % len(ids)
        ultimo_ciclo = time.ticks_ms(); sucia = True

    if sucia:
        dibujar(); sucia = False
    time.sleep_ms(30)