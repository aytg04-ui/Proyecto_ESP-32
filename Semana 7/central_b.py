# central_b.py — Nodo Supervisor + gateway Telegram (sobre malla.py)
# - Supervisa: pantalla + menu + ordenes (Solicitar/Dormir/Activar).
# - Mide sus propios sensores y reporta (automatico + al recibir WAVE).
# - Gateway Telegram: si TELEGRAM esta ON y hay WiFi conocido, reenvia los FB
#   a Telegram EN PARALELO a la malla (sirve junto al master del companero,
#   siempre que ambos esten en la MISMA red WiFi).
# Siempre despierto.
#
# Necesita: st7789.py, fuentes.py, malla.py, sensores.py

import gc, time
from machine import Pin
import ui
from ui import NEGRO, BLANCO, ROJO, VERDE, AMARILLO, CYAN, MAGENTA, GRIS, AZUL, NARANJA, PALETA
from malla import Malla
from sensores import Sensores
try:
    import urequests
except:
    urequests = None

gc.collect()

# ═══════════════════════════════════════════════
#  CONFIG  ← un supervisor por piso: cambia SUPER_NUM
# ═══════════════════════════════════════════════
SUPER_NUM = 0
NODE_ID   = "SUPER_P{}".format(SUPER_NUM)
MID_BASE  = 1_000_000 * (SUPER_NUM + 1)
RELAY     = True

# Sensores de ESTE supervisor (False los que no tenga)
SEN = Sensores(usar_dht=True, usar_mq=True, usar_mpu=True, usar_gy=True)
T_SENSOR_MS = ui.T_SENSOR_MS

# Telegram (gateway secundario). Requiere estar en la MISMA red que el master.
TELEGRAM = True
TG_TOKEN = ui.TG_TOKEN
TG_CHAT  = ui.TG_CHAT
T_TG_MS  = ui.T_TG_MS
REDES = ui.REDES

CANALES   = ui.CANALES
CICLO_MONITOR = ui.CICLO_MONITOR
ACTIVAR_REPS  = ui.ACTIVAR_REPS


# Healthcheck (ajusta segun el SLEEP_MS de los nodos: deben superar su ciclo de sueno)
T_OFFLINE_MS = ui.T_OFFLINE_MS   # sin reportar este tiempo -> OFFLINE + aviso TG
T_PURGE_MS   = ui.T_PURGE_MS     # sin reportar este tiempo -> se borra (vuelve solo si reaparece)

# ═══════════════════════════════════════════════
#  PANTALLA
# ═══════════════════════════════════════════════
ui.init()
ui_sm = ui.sm    # alias local para las funciones de menú que usan ui.tft directamente

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
#  WIFI (para Telegram) — usa el STA de la malla
# ═══════════════════════════════════════════════
_wifi_ok = False

def conectar_wifi():
    global _wifi_ok
    sta = M.sta
    sta.active(True)
    try: sta.config(pm=0xa11140)            # power-save off (coexistir con ESP-NOW)
    except: pass
    try: vistas = [s[0].decode() for s in sta.scan()]
    except: vistas = []
    for ssid, pwd in REDES:
        if ssid in vistas:
            print("[WIFI] conectando a", ssid)
            sta.connect(ssid, pwd)
            t = time.ticks_ms()
            while not sta.isconnected() and time.ticks_diff(time.ticks_ms(), t) < 9000:
                time.sleep_ms(200)
            if sta.isconnected():
                _wifi_ok = True
                try: M.canal = sta.config('channel')   # malla usa el canal del router
                except: pass
                print("[WIFI] OK", ssid, "ch:", M.canal)
                return True
    print("[WIFI] sin red conocida")
    _wifi_ok = False
    return False

# ═══════════════════════════════════════════════
#  TELEGRAM
# ═══════════════════════════════════════════════
_cola_tg = []

def fb_linea(d):
    p = []
    for m_ in d.get("pl", []):
        t, v = m_.get("t"), m_.get("v")
        p.append(("ACK:" + str(v)) if t == "ACK" else "{}:{}".format(t, v))
    l = "{}  {}".format(d.get("id", "?"), " ".join(p))
    if d.get("alert"):
        l += "  [{}]".format(d["alert"])
    return l

def flush_telegram():
    global _cola_tg
    if not _cola_tg:
        return
    if not (TELEGRAM and _wifi_ok and urequests):
        _cola_tg = []
        return
    if TG_TOKEN.startswith("PON_AQUI"):
        _cola_tg = []
        return
    texto = "Central B\n" + "\n".join(_cola_tg[-15:])
    try:
        r = urequests.post("https://api.telegram.org/bot{}/sendMessage".format(TG_TOKEN),
                           json={"chat_id": TG_CHAT, "text": texto})
        print("[TG] code:", r.status_code)
        if r.status_code == 200:
            _cola_tg = []
        r.close()
    except Exception as e:
        print("[TG ERR]", e)
    gc.collect()

# ═══════════════════════════════════════════════
#  ESTADO
# ═══════════════════════════════════════════════
nodos = {}
pend_dormir  = set()
pend_activar = set()
_proc = {}

MONITOR, NIVEL1, NIVEL2, DETALLE = 0, 1, 2, 3
modo = MONITOR
pag  = 0
op1 = op2 = 0
sel_nodo = None
ultimo_ciclo  = time.ticks_ms()
ultimo_sensor = time.ticks_ms()
ultimo_tg     = time.ticks_ms()
ultimo_hc     = time.ticks_ms()
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
    info["offline"] = False
    if nid not in pend_dormir:
        info["dormido"] = False

def lista_nodos():
    return sorted(nodos.keys())

def nodos_menu():
    return [n for n in lista_nodos() if n != NODE_ID] + ["Todos", "Telegram"]

def healthcheck():
    ahora = time.ticks_ms()
    borrar = []
    for nid, info in nodos.items():
        if nid == NODE_ID:
            continue
        edad = time.ticks_diff(ahora, info.get("ultimo", 0))
        if edad > T_PURGE_MS:
            borrar.append(nid)
        elif edad > T_OFFLINE_MS:
            if not info.get("offline"):
                info["offline"] = True                 # transicion online -> offline
                print("[HC] OFFLINE:", nid)
                if TELEGRAM and _wifi_ok:
                    _cola_tg.append("[OFFLINE] {} dejo de reportar".format(nid))
        else:
            info["offline"] = False
    for nid in borrar:
        print("[HC] borrado:", nid)
        nodos.pop(nid, None)
        pend_dormir.discard(nid); pend_activar.discard(nid)
    return bool(borrar)

def resumen(pl):
    L = []
    if "AccX" in pl:
        ax, az = pl.get("AccX", 0), pl.get("AccZ", 1)
        mov = abs(az - 1.0) > 0.3 or abs(ax) > 0.3
        L.append(("MPU X:{:.2f} Z:{:.2f}".format(ax, az), BLANCO))
        L.append(("MOV!" if mov else "Reposo", ROJO if mov else VERDE))
    if "TempObj" in pl:
        amb, obj = pl.get("TempAmb", 0), pl["TempObj"]
        fb = isinstance(obj, (int, float)) and obj >= 38
        L.append(("GY {}/{}C".format(amb, obj), ROJO if fb else MAGENTA))
    if "Temp" in pl:
        L.append(("DHT {}C {}%".format(pl.get("Temp"), pl.get("Hum")), VERDE))
    if "MQ135" in pl:
        v = pl["MQ135"]
        try:
            v = int(v)
            cal = ("Limpio" if v < 1200 else "Regular" if v < 2000
                   else "Malo" if v < 2500 else "Peligroso")
        except: cal = "?"
        L.append(("MQ:{} {}".format(v, cal), CYAN))
    return L or [("Sin sensores", ROJO)]

# ═══════════════════════════════════════════════
#  SENSORES PROPIOS
# ═══════════════════════════════════════════════
def medir_y_reportar(mid=None):
    med, lec = SEN.leer()
    if not med:
        return
    M.mandar_fb(med, mid=mid)
    pl = {m["t"]: m["v"] for m in med if m["t"] != "ACK"}
    if NODE_ID not in nodos:
        nodos[NODE_ID] = {"color": BLANCO}
    nodos[NODE_ID].update({"pl": pl, "ultimo": time.ticks_ms(),
                           "alert": None, "dormido": False})
    if TELEGRAM and _wifi_ok:
        _cola_tg.append("{}  {}".format(
            NODE_ID, " ".join("{}:{}".format(k, v) for k, v in pl.items())))

# ═══════════════════════════════════════════════
#  ORDENES
# ═══════════════════════════════════════════════
def orden(accion, nombre):
    objetivos = [n for n in nodos if n != NODE_ID] if nombre == "Todos" else [nombre]
    target    = "ALL" if nombre == "Todos" else nombre
    if accion.startswith("Solicitar"):
        M.mandar_wave("REQ:" + target, target)
    elif accion.startswith("Dormir"):
        for n in objetivos:
            pend_dormir.add(n); pend_activar.discard(n)
            if n in nodos: nodos[n]["dormido"] = True
        M.mandar_wave("DORMIR", target)
        _pantalla_simple("Dormir", "al despertar", ROJO)
        time.sleep_ms(800)
    elif accion.startswith("Activar"):
        for n in objetivos:
            pend_activar.add(n); pend_dormir.discard(n)
            if n in nodos: nodos[n]["dormido"] = False
        _pantalla_simple("Activando", nombre, CYAN)
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
    ui.central_simple(l1, l2, color)

def edad_txt(info):
    return "{}s".format(time.ticks_diff(time.ticks_ms(), info.get("ultimo", 0)) // 1000)

def pantalla_monitor():
    global pag
    ui.central_monitor(NODE_ID, lista_nodos(), nodos, pag,
                       telegram_ok=(TELEGRAM and _wifi_ok))

def pantalla_nivel1():
    ids = nodos_menu()
    ini = max(0, min(op1 - 1, len(ids) - 4))
    # Construir lista de (etiqueta, color) para el rango visible
    etiquetas = []
    for i in range(ini, min(ini + 4, len(ids))):
        nombre = ids[i]
        if nombre == "Telegram":
            etiquetas.append(("Telegram: " + ("ON" if TELEGRAM else "OFF"),
                              VERDE if TELEGRAM else GRIS))
        else:
            col = nodos[nombre]["color"] if nombre in nodos else BLANCO
            etiquetas.append((nombre, col))
    # Dibujar
    if not ui.tft: return
    ui.tft.fill(NEGRO)
    ui.tft.header(ui_sm, [("Elegir", CYAN), ("P35:nav P0:ok", BLANCO, "right")])
    ui.tft.cursor(4, ui.tft._cy)
    for j, (etiqueta, col) in enumerate(etiquetas):
        i_real = ini + j
        pre = "> " if i_real == op1 else "  "
        ui.tft.write(ui_sm, pre + etiqueta, AMARILLO if i_real == op1 else col)

def pantalla_nivel2():
    col = nodos[sel_nodo]["color"] if sel_nodo in nodos else BLANCO
    if not ui.tft: return
    ui.tft.fill(NEGRO)
    ui.tft.header(ui_sm, [(sel_nodo, col), ("P35:nav P0:ok", BLANCO, "right")])
    ui.tft.cursor(8, ui.tft._cy)
    for i, a in enumerate(acciones_de(sel_nodo)):
        pre = "> " if i == op2 else "  "
        ui.tft.write(ui_sm, pre + a, AMARILLO if i == op2 else BLANCO)

def pantalla_detalle(nombre):
    info = nodos.get(nombre)
    col  = info["color"] if info else BLANCO
    if not ui.tft: return
    ui.tft.fill(NEGRO)
    ui.tft.header(ui_sm, [(nombre, col), ("P0:salir", BLANCO, "right")])
    ui.tft.cursor(4, ui.tft._cy)
    if not info or not info.get("pl"):
        ui.tft.write(ui_sm, "Sin datos", ROJO)
        return
    for txt, c in resumen(info["pl"])[:4]:
        ui.tft.write(ui_sm, txt, c)

def dibujar():
    if modo == MONITOR:   pantalla_monitor()
    elif modo == NIVEL1:  pantalla_nivel1()
    elif modo == NIVEL2:  pantalla_nivel2()
    elif modo == DETALLE: pantalla_detalle(sel_nodo)

# ═══════════════════════════════════════════════
#  ARRANQUE
# ═══════════════════════════════════════════════
_pantalla_simple("Central B", NODE_ID, CYAN)
time.sleep(1)
SEN.detectar()

if TELEGRAM and conectar_wifi():
    M.iniciar()              # ESP-NOW en el canal del router (mismo que el master)
    M.conectado = True
else:
    M.iniciar()
    M.escanear_canal(1800)   # sin WiFi: busca el canal del master
sucia = True

# ═══════════════════════════════════════════════
#  BUCLE
# ═══════════════════════════════════════════════
while True:
    d = M.recibir(50)
    if d:
        tipo = d.get("type")
        if tipo == "WAVE":
            if M.manejar_wave(d):              # REQ/WAVE para mi -> mido y reporto
                medir_y_reportar(mid=d.get("mid"))
                sucia = True
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
                    if TELEGRAM and _wifi_ok:
                        _cola_tg.append(fb_linea(d))
                    if idn in pend_dormir:
                        t0 = time.ticks_ms()
                        while time.ticks_diff(time.ticks_ms(), t0) < 3000:
                            M.mandar_wave("DORMIR", idn, reps=1)
                M.relay_fb(d)
                sucia = True
                if modo == DETALLE and sel_nodo == idn:
                    pantalla_detalle(sel_nodo)

    # Medicion propia automatica
    if time.ticks_diff(time.ticks_ms(), ultimo_sensor) >= T_SENSOR_MS:
        ultimo_sensor = time.ticks_ms()
        medir_y_reportar()
        if modo == MONITOR: sucia = True

    # Vaciar a Telegram
    if time.ticks_diff(time.ticks_ms(), ultimo_tg) >= T_TG_MS:
        ultimo_tg = time.ticks_ms()
        flush_telegram()

    # Healthcheck: marcar OFFLINE / borrar caidos
    if time.ticks_diff(time.ticks_ms(), ultimo_hc) >= 5_000:
        ultimo_hc = time.ticks_ms()
        if healthcheck():
            if pag >= len(lista_nodos()): pag = 0
        if modo == MONITOR: sucia = True

    if btn_ok.presionado():
        if modo == MONITOR:
            modo, op1 = NIVEL1, 0; sucia = True
        elif modo == NIVEL1:
            elegido = nodos_menu()[op1]
            if elegido == "Telegram":
                TELEGRAM = not TELEGRAM
                if TELEGRAM and not _wifi_ok:
                    conectar_wifi()
                modo = MONITOR
            else:
                sel_nodo = elegido; modo, op2 = NIVEL2, 0
            sucia = True
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
            op1 = (op1 + 1) % len(nodos_menu()); sucia = True
        elif modo == NIVEL2:
            op2 = (op2 + 1) % len(acciones_de(sel_nodo)); sucia = True

    if modo == MONITOR and time.ticks_diff(time.ticks_ms(), ultimo_ciclo) >= CICLO_MONITOR:
        ids = lista_nodos()
        if len(ids) > 1: pag = (pag + 1) % len(ids)
        ultimo_ciclo = time.ticks_ms(); sucia = True

    if sucia:
        dibujar(); sucia = False
    time.sleep_ms(30)
