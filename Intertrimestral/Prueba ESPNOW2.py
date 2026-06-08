import network, espnow, gc
sta = network.WLAN(network.STA_IF)
sta.active(True)
e = espnow.ESPNow()
e.active(True)

gc.collect()
print("libre:", gc.mem_free())

# Buscar el bloque contiguo más grande posible
for kb in [60, 50, 40, 32, 28, 24, 20, 16]:
    try:
        b = bytearray(kb * 1024)
        del b
        gc.collect()
        print("max bloque contiguo:", kb, "KB")
        break
    except:
        pass