# sensores.py — 

from machine import Pin, I2C, ADC
import time, dht

ADDR_MPU = 0x68
ADDR_GY  = 0x5A

# Rangos MQ135 (12 bits, 0-4095)
# MQ_MIN=600 para distinguir un pin al aire (~470) de un MQ real conectado.
MQ_MIN, MQ_MAX, MQ_VARIANZA = 600, 3800, 300

# ===============================================
#  MPU-6050
# ===============================================
class MPU6050:
    def __init__(self, i2c, address=ADDR_MPU):
        self.i2c = i2c
        self.address = address
        self.i2c.writeto_mem(address, 0x6B, b'\x00')
        self.i2c.writeto_mem(address, 0x1B, b'\x00')
        self.i2c.writeto_mem(address, 0x1C, b'\x00')
        self.i2c.writeto_mem(address, 0x1A, b'\x06')
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
#  MLX90614 / GY-906
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
#  RECUPERACION DE BUS I2C
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
#  DETECCION DE PRESENCIA DEL MQ (por hardware)
#  Un pin al aire "sigue al pull" (lee 0 con pull-down y 1 con pull-up).
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
        flotante = (bajo == 0 and alto == 1)   # obedecio a ambos pulls -> al aire
        return not flotante
    except Exception as e:
        print("[SENS] _mq_presente err:", e)
        return False

# ===============================================
#  CLASE PRINCIPAL — autodeteccion + lectura
# ===============================================
class Sensores:
    def __init__(self, pin_dht=25, pin_mq=33, scl=22, sda=21,
                 usar_dht="auto", usar_mq="auto", usar_mpu="auto", usar_gy="auto"):
        self.pin_dht, self.pin_mq = pin_dht, pin_mq
        self.scl, self.sda = scl, sda
        self.f_dht, self.f_mq = usar_dht, usar_mq
        self.f_mpu, self.f_gy = usar_mpu, usar_gy
        self.i2c = None
        self.mpu = self.gy = self.dht = self.adc = None
        self.mq_estado = "ausente"      # ausente / sano / danado
        self.activos = []

    def detectar(self):
        self.activos = []
        disp = []
        if self.f_mpu is not False or self.f_gy is not False:
            self.i2c, disp = escanear_con_recuperacion(scl=self.scl, sda=self.sda)
            print("[SENS] I2C:", [hex(d) for d in disp])

        # ── MPU6050 (I2C) ──
        if self.f_mpu is not False:
            presente = (ADDR_MPU in disp) or (self.f_mpu is True)
            if presente and self.i2c:
                try:
                    self.mpu = MPU6050(self.i2c); self.activos.append("MPU")
                except Exception as e:
                    print("[SENS] MPU err:", e); self.mpu = None

        # ── GY906 (I2C) ──
        if self.f_gy is not False:
            presente = (ADDR_GY in disp) or (self.f_gy is True)
            if presente and self.i2c:
                try:
                    self.gy = MLX90614(self.i2c)
                    _ = self.gy.objeto()         # verificar que lee
                    self.activos.append("GY906")
                except Exception as e:
                    print("[SENS] GY err:", e); self.gy = None

        # ── DHT11 (digital) ──
        if self.f_dht is not False:
            try:
                self.dht = dht.DHT11(Pin(self.pin_dht))
                if self.f_dht is True:
                    self.activos.append("DHT11")          # forzado
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

        # ── MQ135 (analogico) — presencia por HARDWARE + clasificacion por rango ──
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
                        vals = [self.adc.read() for _ in range(5)]
                        media = sum(vals) // len(vals)
                        var   = max(vals) - min(vals)
                        if MQ_MIN <= media <= MQ_MAX and var <= MQ_VARIANZA:
                            self.mq_estado = "sano"
                        else:
                            self.mq_estado = "danado"     # conectado pero fuera de rango
                        self.activos.append("MQ135")
                        print("[SENS] MQ media:{} var:{} -> {}".format(media, var, self.mq_estado))
            except Exception as e:
                print("[SENS] MQ err:", e); self.adc = None

        print("[SENS] activos:", self.activos)
        return self.activos

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
                mq = "ERR"                       # presente pero fuera de rango
            else:
                try:
                    vals = [self.adc.read() for _ in range(5)]
                    mq = sum(vals) // len(vals)
                except Exception:
                    mq = "ERR"
            lec["mq"] = mq
            med.append({"t": "MQ135", "v": mq})

        return med, lec

# ===============================================
#  COMPATIBILIDAD — Nodo A antiguo
# ===============================================
def leer_todo(pin_dht=25, pin_mq=33, scl=22, sda=21):
    sen = Sensores(pin_dht, pin_mq, scl, sda)
    sen.detectar()
    med, lec = sen.leer()
    t  = lec.get("t", "ERR")
    h  = lec.get("h", "ERR")
    mq = lec.get("mq", "ERR")
    return {
        "ax": lec.get("ax"), "ay": lec.get("ay"), "az": lec.get("az"),
        "amb": lec.get("amb"), "obj": lec.get("obj"),
        "tdht": t if isinstance(t, int) else -1,
        "hdht": h if isinstance(h, int) else -1,
        "mq":  mq if isinstance(mq, int) else -1,
        "pl": [m for m in med if m["v"] != "ERR"],
    }