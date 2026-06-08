import gc
gc.collect()

import network, espnow
print("antes wifi:", gc.mem_free())

sta = network.WLAN(network.STA_IF)
sta.active(True)
print("despues wifi:", gc.mem_free())

e = espnow.ESPNow()
e.active(True)
print("despues espnow:", gc.mem_free())

import st7789
print("despues import st7789:", gc.mem_free())

from machine import Pin, SPI
spi = SPI(1, baudrate=20000000, polarity=0, phase=0, sck=Pin(18), mosi=Pin(19))
display = st7789.Display(spi, Pin(16, Pin.OUT), Pin(5, Pin.OUT),
                         Pin(23, Pin.OUT), Pin(4, Pin.OUT), rotation=1)
print("despues display:", gc.mem_free())