# sensores.py 

from machine import Pin, I2C, ADC
import time, dht

# ───────────────────────────────────────────────
#  DIRECCIONES I2C
# ───────────────────────────────────────────────
ADDR_MPU = 0x68
ADDR_GY  = 0x5A

# ===============================================
#  MPU-6050 (acelerometro / giroscopio)
# ===============================================
class MPU6050:
    def __init__(self, i2c, address=ADDR_MPU):
        self.i2c = i2c
        self.address = address
        self.i2c.writeto_mem(address, 0x6B, b'\x00')  # salir de sleep
        self.i2c.writeto_mem(address, 0x1B, b'\x00')  # giro +-250
        self.i2c.writeto_mem(address, 0x1C, b'\x00')  # accel +-2g
        self.i2c.writeto_mem(address, 0x1A, b'\x06')  # filtro paso bajo
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
#  MLX90614 / GY-906 (temperatura sin contacto)
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
#  RECUPERACION DE BUS I2C (si se cuelga el SDA)
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
#  CLASE PRINCIPAL — autodeteccion + lectura
# ===============================================
class Sensores:
    def __init__(self, pin_dht=25, pin_mq=33, scl=22, sda=21,
                 usar_dht=True, usar_mq=True, usar_mpu=True, usar_gy=True):
        self.pin_dht, self.pin_mq = pin_dht, pin_mq
        self.scl, self.sda = scl, sda
        self.f_dht, self.f_mq = usar_dht, usar_mq
        self.f_mpu, self.f_gy = usar_mpu, usar_gy
        self.i2c = None
        self.mpu = self.gy = self.dht = self.adc = None
        self.activos = []

    # -- Deteccion: confirma que sensores responden --
    def detectar(self):
        self.activos = []
        disp = []
        if self.f_mpu or self.f_gy:
            self.i2c, disp = escanear_con_recuperacion(scl=self.scl, sda=self.sda)
            print("[SENS] I2C:", [hex(d) for d in disp])

        if self.f_mpu and self.i2c and ADDR_MPU in disp:
            try:
                self.mpu = MPU6050(self.i2c); self.activos.append("MPU")
            except Exception as e:
                print("[SENS] MPU err:", e)

        if self.f_gy and self.i2c and ADDR_GY in disp:
            self.gy = MLX90614(self.i2c); self.activos.append("GY906")

        if self.f_dht:
            try:
                self.dht = dht.DHT11(Pin(self.pin_dht))
                time.sleep(1)
                ok = False
                for _ in range(3):
                    try:
                        self.dht.measure()
                        if not (self.dht.temperature() == 0 and self.dht.humidity() == 0):
                            ok = True; break
                    except OSError:
                        time.sleep(1)
                if ok:
                    self.activos.append("DHT11")
                else:
                    self.dht = None
            except Exception as e:
                print("[SENS] DHT err:", e); self.dht = None

        if self.f_mq:                       # el MQ es analogico: no se "detecta",
            try:                            # se asume presente si el flag esta activo
                self.adc = ADC(Pin(self.pin_mq))
                self.adc.atten(ADC.ATTN_11DB)
                self.adc.width(ADC.WIDTH_12BIT)
                self.activos.append("MQ135")
            except Exception as e:
                print("[SENS] MQ err:", e); self.adc = None

        print("[SENS] activos:", self.activos)
        return self.activos

    # -- Lectura: solo los sensores activos --
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
            try:
                vals = [self.adc.read() for _ in range(5)]
                mq = sum(vals) // len(vals)
            except Exception:
                mq = "ERR"
            lec["mq"] = mq
            med.append({"t": "MQ135", "v": mq})

        return med, lec

# ===============================================
#  COMPATIBILIDAD — para el Nodo A actual
#  Devuelve el mismo formato que la version anterior.
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