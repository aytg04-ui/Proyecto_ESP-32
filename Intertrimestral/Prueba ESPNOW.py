import network, espnow
sta = network.WLAN(network.STA_IF)
sta.active(True)
e = espnow.ESPNow()
e.active(True)
print("ESP-NOW OK")