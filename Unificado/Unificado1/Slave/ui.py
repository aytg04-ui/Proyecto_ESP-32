# ui.py — Capa visual + configuración unificada PIFNET
# Pantalla TTGO T-Display (ST7789 135x240).
#
# Absorbe config.py: todas las constantes de red, pines, tiempos y umbrales
# están aquí. Un archivo menos en cada dispositivo.
#
# Uso desde cualquier archivo principal:
#   import ui
#   from ui import ROJO, VERDE, ...   # colores
#   ui.init()                         # inicializa pantalla
#   ui.luz(True/False)                # backlight
#   ui.nodo(...)  ui.alerta(...)  etc.
#
# Constantes de config accesibles como ui.NET_ID, ui.UMBRALES, etc.

from machine import Pin, SPI
import st7789
from fuentes import sm, md    # re-exportados: ui.sm / ui.md

# ══════════════════════════════════════════════
#  CONFIGURACIÓN — lo único que cambia por entorno
# ══════════════════════════════════════════════

# ── Red / protocolo ───────────────────────────
NET_ID    = "PIFNET"
MASTER_ID = "MASTER_TTGO_GATEWAY"
CANALES   = [1, 6, 11, 4, 8, 2, 3, 5, 7, 9, 10]

# ── WiFi (para gateway Telegram) ──────────────
REDES = [
    ("Arte_Tenda2.4",  "password_lab"),    # laboratorio
    ("Totalplay-C5AC", "password_comp"),   # casa
    ("Xiaomi_667C",    "password_ana"),    # casa
]

# ── Telegram ──────────────────────────────────
TG_TOKEN = "PON_AQUI_TU_TOKEN"
TG_CHAT  = "PON_AQUI_TU_CHAT_ID"

# ── Pines TTGO T-Display ──────────────────────
PIN_SPI_SCK  = 18
PIN_SPI_MOSI = 19
PIN_DC       = 16
PIN_CS       = 5
PIN_RESET    = 23
PIN_BL       = 4

PIN_BTN_LEFT  = 0    # P0  — pull-up interno, puede despertar de lightsleep
PIN_BTN_RIGHT = 35   # P35 — input only, sin pull-up interno

PIN_DHT = 25         # DHT11  (Ricardo usa 15; cambiar si se unifica hardware)
PIN_MQ  = 33         # MQ135 ADC1_CH5
PIN_SCL = 22         # I2C clock
PIN_SDA = 21         # I2C data

# ── Tiempos — nodo ────────────────────────────
SLEEP_MS          = 30_000   # ciclo de sueño (300_000 = 5 min en producción)
VENTANA_WAVE_MS   = 8_000
ALERTA_PERIODO_MS = 10_000
T_LONG_PRESS_MS   = 3_000
MODO_DEFAULT      = "LIGHT"  # DESPIERTO | LIGHT | DEEP
CONFIG_FILE       = "node_config.json"

# ── Tiempos — Central B ───────────────────────
T_SENSOR_MS   = 30_000
T_TG_MS       = 30_000
CICLO_MONITOR = 5_000
ACTIVAR_REPS  = 5
T_OFFLINE_MS  = 90_000    # → OFFLINE + aviso TG  (ajustar en producción)
T_PURGE_MS    = 900_000   # → borrar nodo          (ajustar en producción)

# ── Tiempos — Master prueba ───────────────────
T_WAVE_MS           = 15_000
T_BEACON_MS         = 2_000
T_TG_MASTER_MS      = 30_000
T_OFFLINE_MASTER_MS = 90_000
CANAL_FALLBACK      = 1

# ── Umbrales de alerta ────────────────────────
# "bajo"  → alerta al BAJAR (Hum)
# sin "bajo" → alerta al SUBIR (Temp, MQ135, TempObj)
UMBRALES = {
    "Temp":    {"warn": 45.0, "warn_sale": 42.0, "crit": 60.0,  "crit_sale": 55.0},
    "Hum":     {"bajo": 15.0, "bajo_sale": 18.0, "bajo_crit": 8.0, "bajo_crit_sale": 11.0},
    "MQ135":   {"warn": 2500, "warn_sale": 2200,  "crit": 3500,  "crit_sale": 3200},
    "TempObj": {"warn": 38.0, "warn_sale": 37.0,  "crit": 39.5,  "crit_sale": 38.5},
}

# ══════════════════════════════════════════════
#  COLORES
# ══════════════════════════════════════════════
NEGRO    = st7789.BLACK
BLANCO   = st7789.WHITE
ROJO     = st7789.RED
VERDE    = st7789.GREEN
AMARILLO = st7789.YELLOW
CYAN     = st7789.CYAN
MAGENTA  = st7789.MAGENTA
NARANJA  = st7789.color565(255, 128, 0)
AZUL     = st7789.color565(80, 160, 255)
GRIS     = st7789.color565(120, 120, 120)

PALETA = [AMARILLO, MAGENTA, VERDE, CYAN, NARANJA, AZUL]  # nodos en Central B

# ══════════════════════════════════════════════
#  ESTADO INTERNO
# ══════════════════════════════════════════════
tft = None
bl  = None

# ══════════════════════════════════════════════
#  INICIALIZACIÓN
# ══════════════════════════════════════════════
def init(rotation=1, encendida=True):
    """Inicializa pantalla y backlight. Llamar una vez al arrancar."""
    global tft, bl
    spi = SPI(1, baudrate=20_000_000,
              sck=Pin(PIN_SPI_SCK), mosi=Pin(PIN_SPI_MOSI))
    bl = Pin(PIN_BL, Pin.OUT)
    tft = st7789.ST7789(
        spi, 135, 240,
        dc=Pin(PIN_DC, Pin.OUT),
        cs=Pin(PIN_CS, Pin.OUT),
        reset=Pin(PIN_RESET, Pin.OUT),
        backlight=bl,
        rotation=rotation,
    )
    luz(encendida)
    return tft


def luz(on=True):
    """Enciende o apaga el backlight."""
    if bl:
        bl.value(1 if on else 0)


# ══════════════════════════════════════════════
#  PANTALLAS — NODO  (main_nodo.py)
# ══════════════════════════════════════════════
def msg(node_id, l1, l2="", c1=BLANCO, c2=GRIS):
    """Mensaje genérico: node_id arriba, l1 grande centrado, l2 pequeño opcional."""
    if not tft: return
    tft.fill(NEGRO)
    tft.write(sm, node_id, CYAN, x=4, y=2)
    tft.write(md, l1, c1, y=42, center=True)
    if l2:
        tft.write(sm, l2, c2, y=84, center=True)


def nodo(node_id, modo, lec, estado="", ec=VERDE):
    """Pantalla normal: lecturas de sensores + línea de estado.

    lec: dict con subconjunto de {t, h, obj, amb, mq, ax, ay, az}.
    estado: texto corto ("Enviado", "Midiendo...", etc.)."""
    if not tft: return
    tft.fill(NEGRO)
    tft.cursor(4, 2)
    tft.write(sm, node_id + "  " + modo[:4], CYAN)
    if "t"   in lec: tft.write(sm, "T:{} H:{}".format(lec["t"], lec["h"]), BLANCO)
    if "obj" in lec:
        fiebre = isinstance(lec["obj"], (int, float)) and lec["obj"] >= 38
        tft.write(sm, "GY {}/{}C".format(lec.get("amb"), lec["obj"]),
                  ROJO if fiebre else MAGENTA)
    if "mq"  in lec: tft.write(sm, "MQ:{}".format(lec["mq"]), CYAN)
    if "ax"  in lec: tft.write(sm, "Ax:{} Az:{}".format(lec["ax"], lec["az"]), AMARILLO)
    if estado:       tft.write(sm, estado, ec)


def alerta(node_id, nivel, sensores, lec):
    """Pantalla de alerta: fondo rojo (CRIT) o negro con texto naranja (WARN)."""
    if not tft: return
    luz(True)
    fondo = ROJO   if nivel == "CRIT" else NEGRO
    ctxt  = BLANCO if nivel == "CRIT" else AMARILLO
    tft.fill(fondo)
    tft.write(sm, node_id, BLANCO if nivel == "CRIT" else CYAN, x=4, y=2)
    tft.write(md, "ALERTA" if nivel == "CRIT" else "ATENCION", ctxt, y=26, center=True)
    tft.write(sm, (",".join(sensores))[:24], ctxt, y=64, center=True)
    tft.write(sm, "T:{} H:{}".format(lec.get("t", "--"), lec.get("h", "--")),
              ctxt, y=88, center=True)


def dormido(node_id, conectado):
    """Pantalla de sueño: muestra estado de conexión y apaga backlight."""
    if not tft: return
    tft.fill(NEGRO)
    tft.write(sm, node_id, CYAN, x=4, y=40)
    tft.write(sm, "conectado" if conectado else "sin senal",
              VERDE if conectado else GRIS, x=4, y=66)
    tft.write(sm, "durmiendo...", GRIS, x=4, y=92)
    luz(False)


# ══════════════════════════════════════════════
#  PANTALLAS — CENTRAL B  (central_b.py)
# ══════════════════════════════════════════════
def central_simple(l1, l2="", color=BLANCO):
    """Mensaje simple de dos líneas (arranque, confirmaciones)."""
    if not tft: return
    tft.fill(NEGRO)
    tft.write(md, l1, color, y=30, center=True)
    if l2:
        tft.write(md, l2, BLANCO, y=70, center=True)


def central_monitor(node_id, ids, nodos, pag, telegram_ok):
    """Monitor paginado: muestra hasta 3 nodos con estado y lecturas."""
    if not tft: return
    import time as _t
    tft.fill(NEGRO)
    tft.header(sm, [(node_id, CYAN), ("P0:menu" + (" TG" if telegram_ok else ""), BLANCO, "right")])
    tft.cursor(2, tft._cy)
    if not ids:
        tft.write(md, "Sin nodos", ROJO, center=True)
        tft.write(sm, "Escuchando malla...", BLANCO, center=True)
        return
    for nid in ids[pag:pag + 3]:
        info  = nodos.get(nid, {})
        color = PALETA[ids.index(nid) % len(PALETA)]
        if info.get("offline"):
            tft.write(sm, "[ {} OFFLINE ]".format(nid), GRIS)
        elif info.get("dormido"):
            tft.write(sm, "[ {} ZZZ ]".format(nid), AZUL)
        else:
            tft.write(sm, "[ {} ]".format(nid), color)
        datos = info.get("datos", {})
        al    = info.get("alerta")
        if datos:
            tft.write(sm, _resumen_lec(datos),
                      ROJO if al == "CRIT" else AMARILLO if al else color)
        else:
            tft.write(sm, "Sin datos aun", ROJO)
    tft.write(sm, "{}/{} {}".format(pag + 1, len(ids), _tiempo_txt(nodos.get(ids[pag], {}))),
              BLANCO, x=2, y=tft.height - 18)


# ══════════════════════════════════════════════
#  PANTALLAS — MASTER PRUEBA  (master_prueba.py)
# ══════════════════════════════════════════════
def master(estado, color=BLANCO, extra="", canal=0, wifi_ok=False, tg_on=False, n_nodos=0):
    """Pantalla del master: barra de info + estado principal + conteo de nodos."""
    if not tft: return
    tft.fill(NEGRO)
    tft.write(sm, "MASTER prueba", VERDE, x=4, y=2)
    tft.write(sm, "ch:{} wifi:{} TG:{}".format(
        canal, "OK" if wifi_ok else "--", "ON" if tg_on else "OFF"),
        CYAN, x=4, y=20)
    tft.write(md, estado, color, x=4, y=42)
    if extra:
        tft.write(sm, extra[:30], BLANCO, x=4, y=80)
    tft.write(sm, "nodos:{}".format(n_nodos), AMARILLO, x=4, y=110)


# ══════════════════════════════════════════════
#  HELPERS INTERNOS
# ══════════════════════════════════════════════
def _tiempo_txt(info):
    import time as _t
    u = info.get("ultimo", 0)
    return "{}s".format(_t.ticks_diff(_t.ticks_ms(), u) // 1000) if u else "?"


def _resumen_lec(lec):
    p = []
    if "t"   in lec: p.append("T:{}".format(lec["t"]))
    if "h"   in lec: p.append("H:{}".format(lec["h"]))
    if "obj" in lec: p.append("GY:{}C".format(lec["obj"]))
    if "mq"  in lec: p.append("MQ:{}".format(lec["mq"]))
    if "ax"  in lec: p.append("|a|:{}".format(
        round((lec["ax"]**2 + lec["ay"]**2 + lec["az"]**2) ** 0.5, 1)))
    return "  ".join(p) if p else "(sin datos)"


def _lineas_detalle(lec, nivel_alerta):
    al = nivel_alerta
    c_al = lambda: (ROJO if al == "CRIT" else AMARILLO) if al else BLANCO
    lineas = []
    if "t"   in lec: lineas.append(("Temp: {}C".format(lec["t"]),   c_al()))
    if "h"   in lec: lineas.append(("Hum:  {}%".format(lec["h"]),   c_al()))
    if "obj" in lec: lineas.append(("TObj: {}C".format(lec["obj"]), c_al()))
    if "amb" in lec: lineas.append(("TAmb: {}C".format(lec["amb"]), BLANCO))
    if "mq"  in lec: lineas.append(("MQ135: {}".format(lec["mq"]),  c_al()))
    if "ax"  in lec: lineas.append(
        ("Ax:{} Ay:{} Az:{}".format(lec["ax"], lec["ay"], lec["az"]), AMARILLO))
    return lineas
