from machine import I2C, Pin
import time

for freq in [100000, 50000, 10000]:
    try:
        i2c = I2C(0, scl=Pin(22), sda=Pin(21), freq=freq)
        time.sleep_ms(300)
        found = i2c.scan()
        print("Freq {}: {}".format(freq, found))
    except Exception as e:
        print("Freq {}: ERROR - {}".format(freq, e))