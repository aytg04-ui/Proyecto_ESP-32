# i2c_recovery.py

from machine import Pin, I2C
import time


def reset_bus_i2c(scl_pin=22, sda_pin=21, freq=100000):

    scl = Pin(scl_pin, Pin.OUT, value=1)
    sda = Pin(sda_pin, Pin.IN)   # Solo escucha, no fuerza el pin

    # Si SDA ya está en alto, el bus estaba libre desde el inicio
    if sda.value() == 1:
        # Igual se reconstruye el objeto I2C para limpiar estado interno
        I2C(0, scl=Pin(scl_pin), sda=Pin(sda_pin), freq=freq)
        return True

    print("[I2C Recovery] SDA en bajo — enviando 9 pulsos SCL...")

    # 9 pulsos de reloj para terminar cualquier transacción colgada
    for i in range(9):
        scl.value(0)
        time.sleep_us(5)
        scl.value(1)
        time.sleep_us(5)
        if sda.value() == 1:
            print("[I2C Recovery] SDA liberado en pulso {}".format(i + 1))
            break

    # Condición STOP: con SCL en alto, SDA sube de 0 a 1
    sda = Pin(sda_pin, Pin.OUT, value=0)
    time.sleep_us(5)
    scl.value(1)
    time.sleep_us(5)
    sda.value(1)
    time.sleep_us(5)

    # Reconstruir el objeto I2C en modo normal
    I2C(0, scl=Pin(scl_pin), sda=Pin(sda_pin), freq=freq)
    time.sleep_ms(100)

    # Verificar resultado
    sda_check = Pin(sda_pin, Pin.IN)
    if sda_check.value() == 1:
        print("[I2C Recovery] Bus liberado correctamente.")
        return True
    else:
        print("[I2C Recovery] ADVERTENCIA: bus sigue bloqueado. Revisa hardware.")
        return False


def escanear_con_recuperacion(intentos=3, scl=22, sda=21, freq=100000):
  
    for intento in range(1, intentos + 1):
        i2c = I2C(0, scl=Pin(scl), sda=Pin(sda), freq=freq)
        time.sleep_ms(100)
        dispositivos = i2c.scan()

        if dispositivos:
            print("[I2C Recovery] Intento {}/{}: encontrados {}".format(
                intento, intentos, [hex(d) for d in dispositivos]))
            return i2c, dispositivos

        print("[I2C Recovery] Intento {}/{}: bus vacío, recuperando...".format(
            intento, intentos))
        reset_bus_i2c(scl, sda, freq)
        time.sleep_ms(500)

    print("[I2C Recovery] Sin respuesta tras {} intentos.".format(intentos))
    return None, []
