# sensores.py — Nodo A

from machine import Pin, I2C, ADC
import time, dht

# ───────────────────────────────────────────────
#  MPU-6050
# ───────────────────────────────────────────────
class MPU6050:
    def __init__(self, i2c, address=0x68):
        self.i2c = i2c
        self.address = address
        self.i2c.writeto_mem(address, 0x6B, b'\x00')  # salir de sleep
        self.i2c.writeto_mem(address, 0x1B, b'\x00')  # giro ±250
        self.i2c.writeto_mem(address, 0x1C, b'\x00')  # accel ±2g
        self.i2c.writeto_mem(address, 0x1A, b'\x06')  # filtro
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

# ───────────────────────────────────────────────
#  MLX90614 (GY-906)
# ───────────────────────────────────────────────
class MLX90614:
    def __init__(self, i2c, address=0x5A):
        self.i2c = i2c
        self.address = address

    def _temp(self, reg):
        d = self.i2c.readfrom_mem(self.address, reg, 2)
        return ((d[1] << 8 | d[0]) * 0.02) - 273.15

    def ambiente(self): return self._temp(0x06)
    def objeto(self):   return self._temp(0x07)

# ───────────────────────────────────────────────
#  RECUPERACIÓN DE BUS I2C
# ───────────────────────────────────────────────
def reset_bus_i2c(scl_pin=22, sda_pin=21, freq=100000):
    scl = Pin(scl_pin, Pin.OUT, value=1)
    sda = Pin(sda_pin, Pin.IN)
    if sda.value() == 1:
        I2C(0, scl=Pin(scl_pin), sda=Pin(sda_pin), freq=freq)
        return True
    for _ in range(9):                       # 9 pulsos para liberar
        scl.value(0); time.sleep_us(5)
        scl.value(1); time.sleep_us(5)
        if sda.value() == 1: break
    sda = Pin(sda_pin, Pin.OUT, value=0)     # condición STOP
    time.sleep_us(5); scl.value(1)
    time.sleep_us(5); sda.value(1); time.sleep_us(5)
    I2C(0, scl=Pin(scl_pin), sda=Pin(sda_pin), freq=freq)
    time.sleep_ms(100)
    return Pin(sda_pin, Pin.IN).value() == 1

def escanear_con_recuperacion(intentos=3, scl=22, sda=21, freq=100000):
    for n in range(intentos):
        i2c = I2C(0, scl=Pin(scl), sda=Pin(sda), freq=freq)
        time.sleep_ms(100)
        disp = i2c.scan()
        if disp:
            return i2c, disp
        reset_bus_i2c(scl, sda, freq)
        time.sleep_ms(500)
    return None, []

# ───────────────────────────────────────────────
#  UMBRALES MQ-135
# ───────────────────────────────────────────────
MQ_MIN, MQ_MAX, MQ_VARIANZA = 400, 3800, 300

# ───────────────────────────────────────────────
#  LECTURA COMPLETA — todo lo que antes vivía en main
# ───────────────────────────────────────────────
def leer_todo(pin_dht=25, pin_mq=33, scl=22, sda=21):
    res = {"ax": None, "ay": None, "az": None,
           "amb": None, "obj": None,
           "tdht": -1, "hdht": -1, "mq": -1, "pl": []}

    # I2C con recuperación
    i2c, disp = escanear_con_recuperacion(intentos=3, scl=scl, sda=sda)
    tiene_mpu = i2c is not None and 0x68 in disp
    tiene_gy  = i2c is not None and 0x5A in disp

    # DHT11
    try:
        d = dht.DHT11(Pin(pin_dht))
        time.sleep(2)
        for _ in range(3):
            try:
                d.measure()
                t, h = d.temperature(), d.humidity()
                if 0 <= t <= 60 and 0 <= h <= 100:
                    res["tdht"], res["hdht"] = t, h
                    break
            except OSError:
                time.sleep(2)
    except Exception as e:
        print("DHT11:", e)

    # MPU-6050
    if tiene_mpu:
        try:
            time.sleep_ms(200)
            res["ax"], res["ay"], res["az"] = MPU6050(i2c).accel_g()
        except Exception as e:
            print("MPU:", e)

    # GY-906
    if tiene_gy:
        try:
            gy = MLX90614(i2c)
            res["amb"] = round(gy.ambiente(), 1)
            res["obj"] = round(gy.objeto(), 1)
        except Exception as e:
            print("GY906:", e)

    # MQ-135
    try:
        adc = ADC(Pin(pin_mq))
        adc.atten(ADC.ATTN_11DB)
        adc.width(ADC.WIDTH_12BIT)
        lec = [adc.read() for _ in range(5)]
        time.sleep_ms(100)
        cruda = sum(lec) // len(lec)
        if MQ_MIN <= cruda <= MQ_MAX and (max(lec) - min(lec)) <= MQ_VARIANZA:
            res["mq"] = cruda
    except Exception as e:
        print("MQ135:", e)

    # Armar payload JSON (pl)
    pl = []
    if res["ax"] is not None:
        pl += [{"t": "AccX", "v": res["ax"]},
               {"t": "AccY", "v": res["ay"]},
               {"t": "AccZ", "v": res["az"]}]
    if res["amb"] is not None:
        pl += [{"t": "TempAmb", "v": res["amb"]},
               {"t": "TempObj", "v": res["obj"]}]
    if res["tdht"] != -1:
        pl += [{"t": "Temp", "v": res["tdht"]},
               {"t": "Hum",  "v": res["hdht"]}]
    if res["mq"] != -1:
        pl.append({"t": "MQ135", "v": res["mq"]})
    res["pl"] = pl
    return res