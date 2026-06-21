# Central B — Nodo Supervisor (main.py)
# Antes era "master". Ahora es un nodo más de la malla PIFNET:
#   - ESCUCHA las WAVEs del master del compañero y los FB de los slaves.
#   - MUESTRA monitor / menú / detalle con el driver st7789 unificado.
#   - DA ÓRDENES mandando WAVEs en broadcast (Solicitar / Dormir / Activar).
#   - Hace RELAY básico de WAVE y FB para extender el alcance de la malla.
#
# Compatible con MASTER_TTGO v18.7 y los slaves MicroPython v12.4 / Nodo A.
# Siempre despierto (USB o batería grande): un menú no sirve si duerme.

import gc
from machine import Pin, SPI
import network, espnow, time, json
import st7789
from fuentes import font_sm, font_md

gc.collect()

# ───────────────────────────────────────────────
#  ★ ÚNICO PARÁMETRO A CAMBIAR POR EQUIPO ★
#  SUPER_NUM: 0,1,2,3...  (un supervisor por piso, p. ej.)
#  De él se derivan el ID y el rango de 'mid' para no chocar con
#  el master (mid 1+) ni con otros supervisores.
# ───────────────────────────────────────────────
SUPER_NUM = 0

NODE_ID   = "SUPER_P{}".format(SUPER_NUM)
NET_ID    = "PIFNET"
MASTER_ID = "MASTER_TTGO_GATEWAY"
MID_BASE  = 1_000_000 * (SUPER_NUM + 1)   # P0:1M+  P1:2M+  P2:3M+ ...

RELAY = True   # retransmitir WAVE/FB para extender alcance entre pisos

# ───────────────────────────────────────────────
#  TIEMPOS
# ───────────────────────────────────────────────
CANALES_SCAN   = [1, 6, 11, 4, 8, 2, 3, 5, 7, 9, 10]
SCAN_MS        = 1_200      # por canal al buscar master
TIMEOUT_FRESH  = 60_000     # datos "frescos" si < 1 min
DEDUP_TTL_MS   = 30_000
CICLO_MONITOR  = 5_000      # auto-avance de página en monitor
ACTIVAR_REPS   = 5          # cuántas WAVEs ACTIVAR mandar
BROADCAST_MAC  = b'\xff\xff\xff\xff\xff\xff'

# ───────────────────────────────────────────────
#  PANTALLA
# ───────────────────────────────────────────────
spi = SPI(1, baudrate=20000000, polarity=0, phase=0,
          sck=Pin(18), mosi=Pin(19))
tft = st7789.ST7789(spi, 135, 240,
                    dc=Pin(16, Pin.OUT), cs=Pin(5, Pin.OUT),
                    reset=Pin(23, Pin.OUT), backlight=Pin(4, Pin.OUT),
                    rotation=1)   # landscape: width=240, height=135

C = st7789  # atajo para colores
PALETA = [C.YELLOW, C.MAGENTA, C.GREEN, C.CYAN, C.ORANGE, C.BLUE]

# ───────────────────────────────────────────────
#  BOTONES
# ───────────────────────────────────────────────
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

btn_ok  = Boton(0)    # confirmar
btn_nav = Boton(35)   # navegar

# ───────────────────────────────────────────────
#  ESP-NOW (permanente, nunca se cierra → evita NO_MEM)
# ───────────────────────────────────────────────
sta = network.WLAN(network.STA_IF)
sta.active(True)
sta.config(channel=CANALES_SCAN[0])
time.sleep_ms(150)
en = espnow.ESPNow()
en.active(True)
en.add_peer(BROADCAST_MAC)

canal_actual = CANALES_SCAN[0]
conectado    = False

# ───────────────────────────────────────────────
#  ESTADO
# ───────────────────────────────────────────────
# nodos descubiertos dinámicamente:
#   {id: {"pl":{t:v}, "ultimo":ticks, "alert":None/"WARN"/"CRIT",
#         "color":c, "dormido":False}}
nodos = {}

_mid = MID_BASE
def next_mid():
    global _mid
    _mid += 1
    return _mid

_waves_vistas = {}   # mid -> ticks  (dedup de WAVE)
_fb_vistos    = {}   # "id|mid" -> ticks  (dedup de FB para relay)

def _dedup(d, clave):
    ahora = time.ticks_ms()
    for k in [k for k, v in d.items() if time.ticks_diff(ahora, v) > DEDUP_TTL_MS]:
        del d[k]
    if clave in d:
        return True
    d[clave] = ahora
    return False

# ───────────────────────────────────────────────
#  MENÚ
# ───────────────────────────────────────────────
MONITOR, NIVEL1, NIVEL2, DETALLE = 0, 1, 2, 3
modo        = MONITOR
pag         = 0           # página del monitor
op1 = op2   = 0           # opción seleccionada en cada nivel
sel_nodo    = None        # nodo elegido en NIVEL1
ultimo_ciclo = time.ticks_ms()
sucia        = True       # pantalla necesita redibujo

# ───────────────────────────────────────────────
#  CANAL — buscar master sin cerrar ESP-NOW (in-situ)
# ───────────────────────────────────────────────
def escanear_canal():
    global canal_actual, conectado
    tft.fill(C.BLACK)
    tft.write(font_md, "Buscando\nMaster...", C.YELLOW, y=30, center=True)
    for ch in CANALES_SCAN:
        try: sta.config(channel=ch)
        except: continue
        time.sleep_ms(150)
        fin = time.ticks_add(time.ticks_ms(), SCAN_MS)
        while time.ticks_diff(fin, time.ticks_ms()) > 0:
            try: _, msg = en.recv(50)
            except: continue
            if not msg: continue
            try:
                d = json.loads(msg.decode())
                if (d.get("type") == "WAVE" and d.get("net") == NET_ID
                        and d.get("from") == MASTER_ID):
                    canal_actual = d.get("ch", ch)
                    try: sta.config(channel=canal_actual)
                    except: pass
                    conectado = True
                    return True
            except: pass
    return False

# ───────────────────────────────────────────────
#  ENVIAR ÓRDENES (WAVE en broadcast, igual que el master)
# ───────────────────────────────────────────────
def enviar_wave(cmd, target):
    pkt = json.dumps({
        "type": "WAVE", "net": NET_ID, "cmd": cmd, "from": NODE_ID,
        "target": target, "ttl": 6, "ch": canal_actual,
        "mid": next_mid(), "ts": "",
    })
    for _ in range(3):                 # 3 ráfagas como el master
        try: en.send(BROADCAST_MAC, pkt.encode())
        except OSError: pass
        time.sleep_ms(120)
    print("[WAVE TX]", cmd, "->", target)

def orden(accion, nombre):
    # 'nombre' puede ser un id concreto o "Todos"
    target = "ALL" if nombre == "Todos" else nombre
    if accion in ("Solicitar", "Solicitar todos"):
        enviar_wave("REQ:" + target, target)
    elif accion in ("Dormir", "Dormir todos"):
        enviar_wave("DORMIR", target)
        for n in (nodos if nombre == "Todos" else [nombre]):
            if n in nodos: nodos[n]["dormido"] = True
    elif accion in ("Activar", "Activar todos"):
        _pantalla_simple("Activando", nombre, C.CYAN)
        for _ in range(ACTIVAR_REPS):
            enviar_wave("ACTIVAR", target)
            time.sleep_ms(400)
        for n in (nodos if nombre == "Todos" else [nombre]):
            if n in nodos: nodos[n]["dormido"] = False

# ───────────────────────────────────────────────
#  RELAY — extender alcance
# ───────────────────────────────────────────────
def relay_wave(d):
    if not RELAY or d.get("ttl", 0) <= 1: return
    nuevo = dict(d)
    nuevo["from"] = NODE_ID
    nuevo["ttl"]  = d["ttl"] - 1
    try: en.send(BROADCAST_MAC, json.dumps(nuevo).encode())
    except: pass

def relay_fb(d, raw):
    if not RELAY: return
    via = d.get("via", [])
    if NODE_ID in via: return
    via.append(NODE_ID)
    d["via"] = via
    try:
        s = json.dumps(d)
        if len(s) < 248:
            en.send(BROADCAST_MAC, s.encode())
    except: pass

# ───────────────────────────────────────────────
#  REGISTRAR FB
# ───────────────────────────────────────────────
def registrar_fb(d):
    nid = d.get("id")
    if not nid or nid == NODE_ID: return
    pl_dict = {}
    for m in d.get("pl", []):
        t, v = m.get("t"), m.get("v")
        if t == "ACK":                 # ACK no es medición
            continue
        pl_dict[t] = v
    if nid not in nodos:
        nodos[nid] = {"color": PALETA[len(nodos) % len(PALETA)]}
    info = nodos[nid]
    if pl_dict:                        # solo pisar datos si traía sensores
        info["pl"] = pl_dict
    info["ultimo"]  = time.ticks_ms()
    info["alert"]   = d.get("alert")
    info["dormido"] = False

# ───────────────────────────────────────────────
#  RESUMEN DE SENSORES → líneas (texto, color)
# ───────────────────────────────────────────────
def resumen(pl):
    L = []
    if "AccX" in pl:
        ax, az = pl.get("AccX", 0), pl.get("AccZ", 1)
        mov = abs(az - 1.0) > 0.3 or abs(ax) > 0.3
        L.append(("MPU X:{:.2f} Z:{:.2f}".format(ax, az), C.WHITE))
        L.append(("MOV!" if mov else "Reposo", C.RED if mov else C.GREEN))
    if "TempObj" in pl:
        amb, obj = pl.get("TempAmb", 0), pl["TempObj"]
        fiebre = isinstance(obj, (int, float)) and obj >= 38
        L.append(("GY {:.1f}/{:.1f}C".format(amb, obj),
                  C.RED if fiebre else C.MAGENTA))
    if "Temp" in pl:
        t, h = pl.get("Temp"), pl.get("Hum")
        L.append(("DHT {}C {}%".format(t, h), C.GREEN))
    if "MQ135" in pl:
        v = pl["MQ135"]
        try:
            v = int(v)
            cal = ("Limpio" if v < 1200 else "Regular" if v < 2000
                   else "Malo" if v < 2500 else "Peligroso")
        except: cal = "?"
        L.append(("MQ:{} {}".format(v, cal), C.CYAN))
    return L or [("Sin sensores", C.RED)]

def lista_nodos():
    return sorted(nodos.keys())

# ───────────────────────────────────────────────
#  PANTALLAS
# ───────────────────────────────────────────────
def _pantalla_simple(l1, l2, color):
    tft.fill(C.BLACK)
    tft.write(font_md, l1, color, y=30, center=True)
    if l2:
        tft.write(font_md, l2, C.WHITE, y=70, center=True)

def edad_txt(info):
    seg = time.ticks_diff(time.ticks_ms(), info.get("ultimo", 0)) // 1000
    return "{}s".format(seg)

def pantalla_monitor():
    global pag
    tft.fill(C.BLACK)
    tft.header(font_sm, [(NODE_ID, C.CYAN), ("P0:menu", C.WHITE, "right")])
    ids = lista_nodos()
    if not ids:
        tft.write(font_md, "Sin nodos", C.RED, center=True)
        tft.write(font_sm, "Escuchando malla...", C.WHITE, center=True)
        return
    if pag >= len(ids): pag = 0
    nid  = ids[pag]
    info = nodos[nid]
    col  = info["color"]
    tft.cursor(2, tft._cy)
    enc = nid + (" ZZZ" if info.get("dormido") else "")
    if info.get("alert"):
        enc += "  !" + info["alert"]
    tft.write(font_sm, enc, col)
    if info.get("pl"):
        for txt, c in resumen(info["pl"])[:3]:
            tft.write(font_sm, txt, c)
    else:
        tft.write(font_sm, "Sin datos aun", C.RED)
    # pie: página y edad
    tft.write(font_sm, "{}/{} {}".format(pag + 1, len(ids), edad_txt(info)),
              C.WHITE, x=2, y=tft.height - 18)

def pantalla_nivel1():
    ids = lista_nodos() + ["Todos"]
    tft.fill(C.BLACK)
    tft.header(font_sm, [("Elegir nodo", C.CYAN), ("P35:nav P0:ok", C.WHITE, "right")])
    tft.cursor(4, tft._cy)
    # ventana de 4 visibles alrededor de op1
    ini = max(0, min(op1 - 1, len(ids) - 4))
    for i in range(ini, min(ini + 4, len(ids))):
        nombre = ids[i]
        col = nodos[nombre]["color"] if nombre in nodos else C.WHITE
        pre = "> " if i == op1 else "  "
        tft.write(font_sm, pre + nombre, C.YELLOW if i == op1 else col)

def acciones_de(nombre):
    if nombre == "Todos":
        return ["Solicitar todos", "Dormir todos", "Activar todos", "Volver"]
    dormido = nodos.get(nombre, {}).get("dormido")
    return (["Activar", "Volver"] if dormido
            else ["Solicitar", "Dormir", "Volver"])

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

# ───────────────────────────────────────────────
#  ARRANQUE
# ───────────────────────────────────────────────
_pantalla_simple("Central B", NODE_ID, C.CYAN)
time.sleep(1)
escanear_canal()
sucia = True

# ───────────────────────────────────────────────
#  BUCLE PRINCIPAL
# ───────────────────────────────────────────────
while True:
    # ── recibir ──
    try: _, msg = en.recv(50)
    except: msg = None
    if msg:
        try:
            d = json.loads(msg.decode())
            if d.get("net") == NET_ID:
                tipo = d.get("type")
                if tipo == "WAVE":
                    if not _dedup(_waves_vistas, d.get("mid")):
                        if d.get("from") == MASTER_ID:
                            canal_actual = d.get("ch", canal_actual)
                            conectado = True
                        relay_wave(d)
                elif tipo == "FB":
                    clave = "{}|{}".format(d.get("id"), d.get("mid"))
                    if not _dedup(_fb_vistos, clave):
                        registrar_fb(d)
                        relay_fb(d, msg)
                        sucia = True
                        if modo == DETALLE and sel_nodo == d.get("id"):
                            pantalla_detalle(sel_nodo)
        except: pass

    # ── botón OK ──
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
                if acc in ("Solicitar",):
                    modo = DETALLE; time.sleep_ms(400)
                else:
                    modo = MONITOR
            sucia = True
        elif modo == DETALLE:
            modo = MONITOR; sucia = True

    # ── botón NAV ──
    if btn_nav.presionado():
        if modo == MONITOR:
            ids = lista_nodos()
            if len(ids) > 1: pag = (pag + 1) % len(ids)
            ultimo_ciclo = time.ticks_ms(); sucia = True
        elif modo == NIVEL1:
            op1 = (op1 + 1) % (len(lista_nodos()) + 1); sucia = True
        elif modo == NIVEL2:
            op2 = (op2 + 1) % len(acciones_de(sel_nodo)); sucia = True

    # ── auto-avance del monitor ──
    if modo == MONITOR and time.ticks_diff(time.ticks_ms(), ultimo_ciclo) >= CICLO_MONITOR:
        ids = lista_nodos()
        if len(ids) > 1: pag = (pag + 1) % len(ids)
        ultimo_ciclo = time.ticks_ms(); sucia = True

    # ── redibujo ──
    if sucia:
        dibujar(); sucia = False

    time.sleep_ms(30)