# sensores.py — Módulo de sensores unificado con AUTODETECCIÓN
# Reemplaza a: mpu6050.py, mlx90614.py, i2c_recovery.py
#
# Fusión de sensores.py + sens.py:
#   + evaluar_alertas(med)  →  histéresis por sensor, dentro de la clase
#   + estado_actual()       →  "NORMAL" | "ALERTA"
#   + set_umbrales(u)       →  cambia umbrales en caliente
#   Conservado de Ana:
#   + GY906 / MLX90614 (sensor de temperatura objeto/ambiente)
#   + usar_gy flag
#   + pin_dht default = 25  (el del Ricardo usa 15; se pasa en config)
#   + leer_todo(...)        →  compatibilidad con Nodo A antiguo
#
# Umbrales (se pasan al constructor; cada nodo/config define los suyos):
#   UMBRALES = {
#       "Temp":     {"warn": 45.0, "warn_sale": 42.0, "crit": 60.0, "crit_sale": 55.0},
#       "Hum":      {"bajo": 15.0, "bajo_sale": 18.0, "bajo_crit": 8.0, "bajo_crit_sale": 11.0},
#       "MQ135":    {"warn": 2500, "warn_sale": 2200, "crit": 3500, "crit_sale": 3200},
#       "TempObj":  {"warn": 38.0, "warn_sale": 37.0, "crit": 39.5, "crit_sale": 38.5},
#   }
#
# Uso:
#   from sensores import Sensores
#   sen = Sensores(umbrales=UMBRALES)   # todo "auto" por default
#   sen.detectar()
#   med, lec = sen.leer()
#   nivel, afectados = sen.evaluar_alertas(med)   # "WARN"/"CRIT"/None
#   print(sen.estado_actual())                    # "NORMAL" o "ALERTA"

from machine import Pin, I2C, ADC
import time, dht

ADDR_MPU = 0x68
ADDR_GY  = 0x5A

# Rangos MQ135 (12 bits, 0-4095)
# MQ_MIN=600 para distinguir un pin al aire (~470) de un MQ real conectado.
MQ_MIN, MQ_MAX, MQ_VARIANZA = 600, 3800, 300

# Mapeo nombre de medición -> clave en UMBRALES
# (permite que el dict de umbrales use claves legibles independientes del "t" del payload)
_MAP_UMBRAL = {
    "Temp":    "Temp",
    "Hum":     "Hum",
    "MQ135":   "MQ135",
    "TempObj": "TempObj",
    "TempAmb": None,    # temperatura ambiente del GY906 — no tiene umbral propio
    "AccX":    None,
    "AccY":    None,
    "AccZ":    None,
}


# ── helpers de evaluación (módulo, no métodos, para que sean reutilizables) ──

def _num(v):
    """Convierte a float o None (maneja "ERR" y None)."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _eval_alto(prev, v, u):
    """Histéresis para sensores que alertan cuando SUBEN (Temp, MQ135).
    Entran con warn/crit, salen con warn_sale/crit_sale."""
    if prev == "CRIT":
        if v < u["crit_sale"]:
            return "WARN" if v >= u["warn"] else "OK"
        return "CRIT"
    if prev == "WARN":
        if v >= u["crit"]:     return "CRIT"
        if v <= u["warn_sale"]: return "OK"
        return "WARN"
    if v >= u["crit"]: return "CRIT"
    if v >= u["warn"]: return "WARN"
    return "OK"


def _eval_bajo(prev, v, u):
    """Histéresis para sensores que alertan cuando BAJAN (Hum).
    Entran con bajo/bajo_crit, salen con bajo_sale/bajo_crit_sale."""
    if prev == "CRIT":
        if v > u["bajo_crit_sale"]:
            return "WARN" if v <= u["bajo"] else "OK"
        return "CRIT"
    if prev == "WARN":
        if v <= u["bajo_crit"]:   return "CRIT"
        if v >= u["bajo_sale"]:   return "OK"
        return "WARN"
    if v <= u["bajo_crit"]: return "CRIT"
    if v <= u["bajo"]:      return "WARN"
    return "OK"


# ===============================================
#  MPU-6050
# ===============================================
class MPU6050:
    def __init__(self, i2c, address=ADDR_MPU):
        self.i2c = i2c
        self.address = address
        self.i2c.writeto_mem(address, 0x6B, b'\x00')   # despertar
        self.i2c.writeto_mem(address, 0x1B, b'\x00')   # gyro ±250
        self.i2c.writeto_mem(address, 0x1C, b'\x00')   # accel ±2g
        self.i2c.writeto_mem(address, 0x1A, b'\x06')   # filtro
        time.sleep_ms(100)

    @staticmethod
    def _i16(hi, lo):
        v = (hi << 8) | lo
        return v - 65536 if v >= 0x8000 else v

    def accel_g(self):
        raw = self.i2c.readfrom_mem(self.address, 0x3B, 6)
        return (round(self._i16(raw[0], raw[1]) / 16384.0, 2),
                round(self._i16(raw[2], raw[3]) / 16384.0, 2),
                round(self._i16(raw[4], raw[5]) / 16384.0, 2))


# ===============================================
#  MLX90614 / GY-906  (temperatura objeto/ambiente)
# ===============================================
class MLX90614:
    def __init__(self, i2c, address=ADDR_GY):
        self.i2c = i2c
        self.address = address

    def _temp(self, reg):
        d = self.i2c.readfrom_mem(self.address, reg, 2)
        return ((d[1] << 8 | d[0]) * 0.02) - 273.15

    def ambiente(self): return self._temp(0x06)
    def objeto(self):   return self._temp(0x07)


# ===============================================
#  RECUPERACIÓN DE BUS I2C
# ===============================================
def reset_bus_i2c(scl_pin=22, sda_pin=21, freq=100000):
    scl = Pin(scl_pin, Pin.OUT, value=1)
    sda = Pin(sda_pin, Pin.IN)
    if sda.value() == 1:
        I2C(0, scl=Pin(scl_pin), sda=Pin(sda_pin), freq=freq)
        return True
    for _ in range(9):
        scl.value(0); time.sleep_us(5)
        scl.value(1); time.sleep_us(5)
        if sda.value() == 1: break
    sda = Pin(sda_pin, Pin.OUT, value=0)
    time.sleep_us(5); scl.value(1)
    time.sleep_us(5); sda.value(1); time.sleep_us(5)
    I2C(0, scl=Pin(scl_pin), sda=Pin(sda_pin), freq=freq)
    time.sleep_ms(100)
    return Pin(sda_pin, Pin.IN).value() == 1


def escanear_con_recuperacion(intentos=3, scl=22, sda=21, freq=100000):
    for _ in range(intentos):
        i2c = I2C(0, scl=Pin(scl), sda=Pin(sda), freq=freq)
        time.sleep_ms(100)
        disp = i2c.scan()
        if disp:
            return i2c, disp
        reset_bus_i2c(scl, sda, freq)
        time.sleep_ms(500)
    return None, []


# ===============================================
#  DETECCIÓN DE PRESENCIA DEL MQ (por hardware)
#  Un pin al aire "sigue al pull": 0 con pull-down, 1 con pull-up.
#  Un MQ conectado y alimentado MANDA sobre el pin y no obedece al pull.
# ===============================================
def _mq_presente(pin_num):
    try:
        p = Pin(pin_num, Pin.IN, Pin.PULL_DOWN)
        time.sleep_ms(20)
        bajo = p.value()
        p = Pin(pin_num, Pin.IN, Pin.PULL_UP)
        time.sleep_ms(20)
        alto = p.value()
        flotante = (bajo == 0 and alto == 1)   # obedeció a ambos pulls -> al aire
        return not flotante
    except Exception as e:
        print("[SENS] _mq_presente err:", e)
        return False


# ===============================================
#  CLASE PRINCIPAL — autodetección + lectura + alertas
# ===============================================
class Sensores:
    def __init__(self, pin_dht=25, pin_mq=33, scl=22, sda=21,
                 usar_dht="auto", usar_mq="auto", usar_mpu="auto", usar_gy="auto",
                 umbrales=None):
        self.pin_dht, self.pin_mq = pin_dht, pin_mq
        self.scl, self.sda = scl, sda
        self.f_dht, self.f_mq = usar_dht, usar_mq
        self.f_mpu, self.f_gy = usar_mpu, usar_gy
        self.i2c = None
        self.mpu = self.gy = self.dht = self.adc = None
        self.mq_estado = "ausente"      # ausente / sano / danado
        self.activos   = []

        # ── alertas con histéresis ──────────────────────
        self.umbrales = umbrales or {}
        self._nivel   = {}      # {nombre_sensor: "OK" | "WARN" | "CRIT"}
        self._estado  = "NORMAL"

    # ── DETECCIÓN ──────────────────────────────────────
    def detectar(self):
        self.activos = []
        disp = []
        if self.f_mpu is not False or self.f_gy is not False:
            self.i2c, disp = escanear_con_recuperacion(scl=self.scl, sda=self.sda)
            print("[SENS] I2C:", [hex(d) for d in disp])

        # MPU6050
        if self.f_mpu is not False:
            presente = (ADDR_MPU in disp) or (self.f_mpu is True)
            if presente and self.i2c:
                try:
                    self.mpu = MPU6050(self.i2c); self.activos.append("MPU")
                except Exception as e:
                    print("[SENS] MPU err:", e); self.mpu = None

        # GY906 / MLX90614
        if self.f_gy is not False:
            presente = (ADDR_GY in disp) or (self.f_gy is True)
            if presente and self.i2c:
                try:
                    self.gy = MLX90614(self.i2c)
                    _ = self.gy.objeto()         # verificar que lee
                    self.activos.append("GY906")
                except Exception as e:
                    print("[SENS] GY err:", e); self.gy = None

        # DHT11
        if self.f_dht is not False:
            try:
                self.dht = dht.DHT11(Pin(self.pin_dht))
                if self.f_dht is True:
                    self.activos.append("DHT11")
                else:
                    time.sleep(1); ok = False
                    for _ in range(3):
                        try:
                            self.dht.measure()
                            if not (self.dht.temperature() == 0 and self.dht.humidity() == 0):
                                ok = True; break
                        except OSError:
                            time.sleep(1)
                    if ok: self.activos.append("DHT11")
                    else:  self.dht = None
            except Exception as e:
                print("[SENS] DHT err:", e); self.dht = None

        # MQ135 — presencia por hardware + clasificación por rango
        self.mq_estado = "ausente"
        if self.f_mq is not False:
            try:
                presente = True if self.f_mq is True else _mq_presente(self.pin_mq)
                if not presente:
                    self.adc = None
                    print("[SENS] MQ: pin al aire (ausente)")
                else:
                    self.adc = ADC(Pin(self.pin_mq))
                    self.adc.atten(ADC.ATTN_11DB)
                    self.adc.width(ADC.WIDTH_12BIT)
                    if self.f_mq is True:
                        self.mq_estado = "sano"; self.activos.append("MQ135")
                    else:
                        vals  = [self.adc.read() for _ in range(5)]
                        media = sum(vals) // len(vals)
                        var   = max(vals) - min(vals)
                        if MQ_MIN <= media <= MQ_MAX and var <= MQ_VARIANZA:
                            self.mq_estado = "sano"
                        else:
                            self.mq_estado = "danado"
                        self.activos.append("MQ135")
                        print("[SENS] MQ media:{} var:{} -> {}".format(media, var, self.mq_estado))
            except Exception as e:
                print("[SENS] MQ err:", e); self.adc = None

        print("[SENS] activos:", self.activos)
        return self.activos

    # ── LECTURA ────────────────────────────────────────
    def leer(self):
        med, lec = [], {}

        if self.mpu:
            try:
                ax, ay, az = self.mpu.accel_g()
                lec["ax"], lec["ay"], lec["az"] = ax, ay, az
                med += [{"t": "AccX", "v": ax}, {"t": "AccY", "v": ay},
                        {"t": "AccZ", "v": az}]
            except Exception as e:
                print("[SENS] MPU leer:", e)

        if self.gy:
            try:
                amb = round(self.gy.ambiente(), 1)
                obj = round(self.gy.objeto(), 1)
                lec["amb"], lec["obj"] = amb, obj
                med += [{"t": "TempAmb", "v": amb}, {"t": "TempObj", "v": obj}]
            except Exception as e:
                print("[SENS] GY leer:", e)

        if self.dht:
            t, h = "ERR", "ERR"
            for _ in range(3):
                try:
                    self.dht.measure()
                    tv, hv = self.dht.temperature(), self.dht.humidity()
                    if not (tv == 0 and hv == 0):
                        t, h = tv, hv; break
                except OSError:
                    time.sleep_ms(300)
            lec["t"], lec["h"] = t, h
            med += [{"t": "Temp", "v": t}, {"t": "Hum", "v": h}]

        if self.adc:
            if self.mq_estado == "danado":
                mq = "ERR"
            else:
                try:
                    vals = [self.adc.read() for _ in range(5)]
                    mq = sum(vals) // len(vals)
                except Exception:
                    mq = "ERR"
            lec["mq"] = mq
            med.append({"t": "MQ135", "v": mq})

        return med, lec

    # ── ALERTAS CON HISTÉRESIS ─────────────────────────
    def set_umbrales(self, umbrales):
        """Cambia umbrales en caliente y reinicia el estado de alertas."""
        self.umbrales = umbrales or {}
        self._nivel   = {}
        self._estado  = "NORMAL"

    def estado_actual(self):
        """'NORMAL' o 'ALERTA'. El nodo puede consultarlo sin recalcular."""
        return self._estado

    def evaluar_alertas(self, med):
        """Evalúa med = [{"t":.., "v":..}] con histéresis por sensor.

        Devuelve (nivel_global, sensores_afectados):
          nivel_global:      None | "WARN" | "CRIT"
          sensores_afectados: lista de nombres en alerta (e.g. ["Temp", "MQ135"])

        El estado persiste entre llamadas (histéresis): un sensor no sale de
        WARN hasta que baje de warn_sale, no solo de warn. Esto evita que la
        alerta parpadee cerca del umbral.

        Si no se pasaron umbrales al constructor, devuelve (None, []).
        """
        for m in med:
            nombre = m.get("t")
            clave  = _MAP_UMBRAL.get(nombre)
            if not clave or clave not in self.umbrales:
                continue
            v = _num(m.get("v"))
            if v is None:               # "ERR" u otro no numérico → conserva estado previo
                continue
            u    = self.umbrales[clave]
            prev = self._nivel.get(nombre, "OK")
            if "bajo" in u:
                self._nivel[nombre] = _eval_bajo(prev, v, u)
            else:
                self._nivel[nombre] = _eval_alto(prev, v, u)

        afectados = [t for t, s in self._nivel.items() if s in ("WARN", "CRIT")]
        if any(s == "CRIT" for s in self._nivel.values()):
            nivel = "CRIT"
        elif afectados:
            nivel = "WARN"
        else:
            nivel = None

        self._estado = "ALERTA" if nivel else "NORMAL"
        return nivel, afectados


# ===============================================
#  COMPATIBILIDAD — Nodo A antiguo
# ===============================================
def leer_todo(pin_dht=25, pin_mq=33, scl=22, sda=21):
    sen = Sensores(pin_dht, pin_mq, scl, sda)
    sen.detectar()
    med, lec = sen.leer()
    t  = lec.get("t",   "ERR")
    h  = lec.get("h",   "ERR")
    mq = lec.get("mq",  "ERR")
    return {
        "ax":  lec.get("ax"),  "ay": lec.get("ay"), "az": lec.get("az"),
        "amb": lec.get("amb"), "obj": lec.get("obj"),
        "tdht": t  if isinstance(t,  int) else -1,
        "hdht": h  if isinstance(h,  int) else -1,
        "mq":   mq if isinstance(mq, int) else -1,
        "pl": [m for m in med if m["v"] != "ERR"],
    }
