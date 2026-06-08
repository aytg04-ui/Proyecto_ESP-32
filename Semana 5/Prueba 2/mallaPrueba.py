from malla import Malla
m = Malla("PRUEBA_1")
m.iniciar()
print("canal:", m.escanear_canal())   # debe encontrar el master
import time
while True:
    d = m.recibir(100)
    if d and d["type"] == "WAVE":
        if m.manejar_wave(d):
            m.mandar_fb([{"t":"Test","v":1}], mid=d.get("mid"))
            print("respondí FB")