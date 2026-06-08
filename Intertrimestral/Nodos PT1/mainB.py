# B
from machine import Pin, SPI
import network, espnow, ubinascii, time
import st7789

# --- Pantalla ---
spi = SPI(1, baudrate=20000000, polarity=0, phase=0,
          sck=Pin(18), mosi=Pin(19))
display = st7789.Display(spi, Pin(16, Pin.OUT), Pin(5,  Pin.OUT),
                              Pin(23, Pin.OUT), Pin(4,  Pin.OUT))
display.init()

# --- Botones ---
class Boton:
    def __init__(self, pin):
        self.pin = Pin(pin, Pin.IN, Pin.PULL_UP)
        self.ultimo = 0

    def presionado(self):
        ahora = time.ticks_ms()
        if self.pin.value() == 0 and time.ticks_diff(ahora, self.ultimo) > 300:
            self.ultimo = ahora
            return True
        return False

btn_confirmar = Boton(0)
btn_navegar   = Boton(35)

# --- ESP-NOW ---
sta = network.WLAN(network.STA_IF)
sta.active(True)
e = espnow.ESPNow()
e.active(True)

MAC_A = ubinascii.unhexlify('ac15186f7ccc'.replace(':', ''))
MAC_C = ubinascii.unhexlify('ac15186f790c'.replace(':', ''))
MAC_D = ubinascii.unhexlify('ac15186f8124'.replace(':', ''))
MAC_E = ubinascii.unhexlify('ac15186f7c14'.replace(':', ''))

e.add_peer(MAC_A)
e.add_peer(MAC_C)
e.add_peer(MAC_D)
e.add_peer(MAC_E)

# --- Estado de nodos ---
nodos = {
    "A": {"datos": None, "ultimo": 0, "activo": False,
          "mac": MAC_A, "dormido": False, "nombre": "Nodo A"},
    "C": {"datos": None, "ultimo": 0, "activo": False,
          "mac": MAC_C, "dormido": False, "nombre": "Nodo C"},
    "D": {"datos": None, "ultimo": 0, "activo": False,
          "mac": MAC_D, "dormido": False, "nombre": "Nodo D"},
    "E": {"datos": None, "ultimo": 0, "activo": False,
          "mac": MAC_E, "dormido": False, "nombre": "Nodo E"},
}

TIMEOUT    = 15000
NODOS_MENU = ["A", "C", "D", "E", "Todos"]

colores = {
    "A": st7789.YELLOW,
    "C": st7789.MAGENTA,
    "D": st7789.GREEN,
    "E": st7789.CYAN,
    "Todos": st7789.WHITE,
}

# --- Estados ---
MODO_MONITOR = 0
MODO_NIVEL1  = 1
MODO_NIVEL2  = 2
MODO_DETALLE = 3

modo           = MODO_MONITOR
opcion_n1      = 0
opcion_n2      = 0
nodo_activo    = None
nodo_detalle   = None
tiempo_detalle = 0
pantalla_sucia = True
ultimo_render  = 0
INTERVALO_MS   = 1000   # refresca monitor solo cada 1 segundo

# -------------------------------------------------
# Procesar mensajes
# Formato: "X:ax:ay:az:tamb:tobj:tdht:hdht:mq:pct"
# -1 en cualquier campo = sensor no disponible
# -------------------------------------------------
def procesar_mensaje(origen, partes):
    try:
        if origen in ("A", "C", "D", "E"):
            ax       = float(partes[1])
            ay       = float(partes[2])
            az       = float(partes[3])
            temp_amb = float(partes[4])
            temp_obj = float(partes[5])
            temp_dht = int(partes[6])
            hum_dht  = int(partes[7])
            valor_mq = int(partes[8])
            pct_mq   = float(partes[9])
            return {
                "mpu": (ax, ay, az)         if not (ax == 0.0 and ay == 0.0 and az == 0.0) else None,
                "gy":  (temp_amb, temp_obj) if temp_amb != -1.0 else None,
                "dht": (temp_dht, hum_dht)  if temp_dht != -1   else None,
                "mq":  (valor_mq, pct_mq)   if valor_mq != -1   else None,
            }
    except:
        return None

# -------------------------------------------------
# Pantallas  (todo va al framebuffer, show() al final)
# -------------------------------------------------
def pantalla_monitor():
    display.fb.fill(st7789.BLACK)
    display.fb.text("Central B", 5, 2, st7789.YELLOW)
    display.fb.text("P0:menu", 90, 2, st7789.WHITE)
    ahora = time.ticks_ms()
    y = 20
    for nombre, info in nodos.items():
        sin_datos = time.ticks_diff(ahora, info["ultimo"]) > TIMEOUT
        activo    = info["activo"] and not sin_datos
        color     = colores.get(nombre, st7789.WHITE)

        if info["dormido"]:
            display.fb.text(nombre + " ZZZ", 5, y, st7789.RED)
            y += 28
        elif activo and info["datos"]:
            display.fb.text(nombre, 5, y, color)
            lineas = _resumen_corto(nombre, info["datos"])
            if lineas:
                display.fb.text(lineas[0], 22, y + 14, st7789.WHITE)
            if len(lineas) > 1:
                display.fb.text(lineas[1], 22, y + 27, st7789.WHITE)
            y += 44
        else:
            display.fb.text(nombre + " ---", 5, y, st7789.RED)
            y += 28
    display.show()

def _resumen_corto(nombre, datos):
    try:
        lineas = []
        if datos.get("mpu"):
            ax, ay, az = datos["mpu"]
            mov = abs(az - 1.0) > 0.3 or abs(ax) > 0.3 or abs(ay) > 0.3
            lineas.append("MPU X:{:.2f} Z:{:.2f}".format(ax, az))
            lineas.append("MOV!" if mov else "Reposo")
        if datos.get("gy"):
            amb, obj = datos["gy"]
            lineas.append("GY {:.1f}/{:.1f}C".format(amb, obj))
            lineas.append("FIEBRE" if obj >= 38 else "Normal")
        if datos.get("dht"):
            t, h = datos["dht"]
            lineas.append("DHT {}C {}%".format(t, h))
            ok = 18 <= t <= 26 and 30 <= h <= 60
            lineas.append("OK" if ok else "Fuera rango")
        if datos.get("mq"):
            v, pct = datos["mq"]
            if v < 1200:   cal = "Limpio"
            elif v < 2000: cal = "Regular"
            elif v < 2500: cal = "Malo"
            else:          cal = "Peligroso"
            lineas.append("MQ:{} {}".format(v, cal))
        return lineas if lineas else ["Sin sensores"]
    except:
        return ["Error datos"]

def pantalla_nivel1():
    display.fb.fill(st7789.BLACK)
    display.fb.text("Elegir nodo:", 5, 2, st7789.CYAN)
    display.fb.text("P35:nav P0:ok", 5, 15, st7789.WHITE)
    y = 40
    for i, nombre in enumerate(NODOS_MENU):
        color = colores.get(nombre, st7789.WHITE)
        if nombre != "Todos":
            info = nodos[nombre]
            if info["dormido"]:
                estado = " [ZZZ]"
            elif info["activo"]:
                estado = " [OK]"
            else:
                estado = " [---]"
        else:
            estado = ""
        if i == opcion_n1:
            display.fb.text("> Nodo " + nombre + estado, 5, y, st7789.YELLOW)
        else:
            display.fb.text("  Nodo " + nombre + estado, 5, y, color)
        y += 26
    display.show()

def pantalla_nivel2(nombre):
    display.fb.fill(st7789.BLACK)
    color = colores.get(nombre, st7789.WHITE)
    if nombre == "Todos":
        display.fb.text("-- Todos --", 5, 5, color)
    else:
        display.fb.text("-- Nodo " + nombre + " --", 5, 5, color)
    display.fb.text("P35:nav P0:ok", 5, 18, st7789.WHITE)
    acciones = _acciones_para(nombre)
    y = 50
    for i, accion in enumerate(acciones):
        if i == opcion_n2:
            display.fb.text("> " + accion, 10, y, st7789.YELLOW)
        else:
            display.fb.text("  " + accion, 10, y, st7789.WHITE)
        y += 30
    display.show()

def _acciones_para(nombre):
    if nombre == "Todos":
        return ["Solicitar todos", "Dormir todos", "Activar todos", "Volver"]
    dormido = nodos[nombre]["dormido"]
    if dormido:
        return ["Activar", "Volver"]
    else:
        return ["Solicitar medicion", "Dormir", "Volver"]

def pantalla_detalle(nombre):
    info  = nodos[nombre]
    datos = info["datos"]
    color = colores.get(nombre, st7789.WHITE)
    display.fb.fill(st7789.BLACK)
    display.fb.text("-- Nodo {} --".format(nombre), 5, 2, color)
    if not datos:
        display.fb.text("Sin datos aun", 5, 80, st7789.RED)
    else:
        y = 22
        if datos.get("mpu"):
            ax, ay, az = datos["mpu"]
            mov = abs(az - 1.0) > 0.3 or abs(ax) > 0.3 or abs(ay) > 0.3
            display.fb.text("MPU-6050", 5, y, st7789.YELLOW)
            y += 14
            display.fb.text("X:{:.2f} Y:{:.2f} Z:{:.2f}".format(ax, ay, az), 5, y, st7789.WHITE)
            y += 14
            display.fb.text("MOV!" if mov else "Reposo", 5, y,
                            st7789.RED if mov else st7789.GREEN)
            y += 18
        if datos.get("gy"):
            amb, obj = datos["gy"]
            display.fb.text("GY-906", 5, y, st7789.MAGENTA)
            y += 14
            display.fb.text("Amb:{:.1f} Obj:{:.1f}C".format(amb, obj), 5, y, st7789.WHITE)
            y += 14
            fiebre = obj >= 38
            display.fb.text("FIEBRE!" if fiebre else "Normal", 5, y,
                            st7789.RED if fiebre else st7789.GREEN)
            y += 18
        if datos.get("dht"):
            t, h = datos["dht"]
            ok = 18 <= t <= 26 and 30 <= h <= 60
            display.fb.text("DHT11", 5, y, st7789.GREEN)
            y += 14
            display.fb.text("{}C  {}%".format(t, h), 5, y, st7789.WHITE)
            y += 14
            display.fb.text("OK" if ok else "Fuera rango", 5, y,
                            st7789.GREEN if ok else st7789.RED)
            y += 18
        if datos.get("mq"):
            v, pct = datos["mq"]
            if v < 1200:   cal, c2 = "Limpio",    st7789.GREEN
            elif v < 2000: cal, c2 = "Regular",   st7789.YELLOW
            elif v < 2500: cal, c2 = "Malo",      st7789.RED
            else:          cal, c2 = "Peligroso", st7789.RED
            display.fb.text("MQ-135", 5, y, st7789.CYAN)
            y += 14
            display.fb.text("ADC:{}  {:.1f}%".format(v, pct), 5, y, st7789.WHITE)
            y += 14
            display.fb.text(cal, 5, y, c2)
            y += 18
        if not any(datos.get(k) for k in ("mpu", "gy", "dht", "mq")):
            display.fb.text("Sin sensores", 5, 80, st7789.RED)
    restante = 30 - (time.ticks_diff(time.ticks_ms(), tiempo_detalle) // 1000)
    display.fb.text("Vuelve en {}s".format(max(0, restante)), 5, 195, st7789.WHITE)
    display.fb.text("P0: salir ya", 5, 213, st7789.WHITE)
    display.show()

# -------------------------------------------------
# Enviar comandos
# -------------------------------------------------
def enviar_comando(accion, nombre):
    if accion == "Solicitar medicion":
        e.send(nodos[nombre]["mac"], b'SOLICITUD')
        print("Solicitud ->", nombre)
    elif accion == "Solicitar todos":
        for n, info in nodos.items():
            e.send(info["mac"], b'SOLICITUD')
    elif accion == "Dormir":
        e.send(nodos[nombre]["mac"], b'DORMIR')
        nodos[nombre]["dormido"] = True
        print("Dormir ->", nombre)
    elif accion == "Dormir todos":
        for n, info in nodos.items():
            e.send(info["mac"], b'DORMIR')
            nodos[n]["dormido"] = True
    elif accion == "Activar":
        print("Enviando ACTIVAR repetidamente a", nombre, "durante 35s...")
        display.fb.fill(st7789.BLACK)
        display.fb.text("Activando", 5, 60, st7789.CYAN)
        display.fb.text(nombre + "...", 5, 90, st7789.WHITE)
        display.fb.text("Espera 35s", 5, 120, st7789.WHITE)
        display.show()
        inicio   = time.ticks_ms()
        activado = False
        while time.ticks_diff(time.ticks_ms(), inicio) < 35000:
            e.send(nodos[nombre]["mac"], b'ACTIVAR')
            sender, resp = e.recv(200)
            if resp and resp == b'ACK:ACTIVAR':
                activado = True
                print("Confirmacion recibida de", nombre)
                break
            time.sleep_ms(500)
        nodos[nombre]["dormido"] = False
        if activado:
            display.fb.fill(st7789.BLACK)
            display.fb.text(nombre + " activado!", 5, 80, st7789.GREEN)
            display.show()
            time.sleep(1)
        else:
            display.fb.fill(st7789.BLACK)
            display.fb.text("Comando enviado", 5, 70, st7789.YELLOW)
            display.fb.text("Sin confirmacion", 5, 90, st7789.YELLOW)
            display.fb.text("Deberia activar", 5, 110, st7789.WHITE)
            display.show()
            time.sleep(2)
    elif accion == "Activar todos":
        display.fb.fill(st7789.BLACK)
        display.fb.text("Activando todos", 5, 60, st7789.CYAN)
        display.fb.text("Espera 35s", 5, 90, st7789.WHITE)
        display.show()
        inicio = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), inicio) < 35000:
            for n, info in nodos.items():
                if nodos[n]["dormido"]:
                    e.send(info["mac"], b'ACTIVAR')
            time.sleep_ms(500)
        for n in nodos:
            nodos[n]["dormido"] = False

# -------------------------------------------------
# Arranque
# -------------------------------------------------
display.fb.fill(st7789.BLACK)
display.fb.text("Central B", 5, 60, st7789.CYAN)
display.fb.text("Iniciando...", 5, 90, st7789.WHITE)
display.show()
time.sleep(1)
print("TTGO B lista.")

# -------------------------------------------------
# Bucle principal
# -------------------------------------------------
while True:

    # --- Recibir mensajes ESP-NOW ---
    sender, msg = e.recv(100)
    if msg:
        try:
            texto  = msg.decode()
            partes = texto.split(":")
            origen = partes[0]

            if origen == "ACK":
                cmd_confirmado = partes[1] if len(partes) > 1 else "?"
                print("Confirmacion recibida:", cmd_confirmado)
                for n, info in nodos.items():
                    if info["mac"] == sender:
                        if cmd_confirmado == "ACTIVAR":
                            nodos[n]["dormido"] = False
                        elif cmd_confirmado == "DORMIR":
                            nodos[n]["dormido"] = True
                        break

            elif origen == "DORMIDO":
                for n, info in nodos.items():
                    if info["mac"] == sender:
                        nodos[n]["dormido"] = True
                        print("Nodo", n, "confirmo que esta dormido")
                        break

            elif origen in nodos:
                datos = procesar_mensaje(origen, partes)
                if datos:
                    nodos[origen]["datos"]   = datos
                    nodos[origen]["ultimo"]  = time.ticks_ms()
                    nodos[origen]["activo"]  = True
                    nodos[origen]["dormido"] = False
                    pantalla_sucia = True
                    if modo == MODO_DETALLE and nodo_detalle == origen:
                        pantalla_detalle(origen)

        except Exception as err:
            print("Error:", err)

    # --- Botón confirmar (Pin 0) ---
    if btn_confirmar.presionado():

        if modo == MODO_MONITOR:
            modo      = MODO_NIVEL1
            opcion_n1 = 0
            pantalla_nivel1()

        elif modo == MODO_NIVEL1:
            nodo_activo = NODOS_MENU[opcion_n1]
            opcion_n2   = 0
            modo        = MODO_NIVEL2
            pantalla_nivel2(nodo_activo)

        elif modo == MODO_NIVEL2:
            acciones = _acciones_para(nodo_activo)
            accion   = acciones[opcion_n2]

            if accion == "Volver":
                modo      = MODO_NIVEL1
                opcion_n2 = 0
                pantalla_nivel1()

            elif accion in ("Solicitar medicion", "Solicitar todos"):
                enviar_comando(accion, nodo_activo)
                if nodo_activo != "Todos":
                    nodo_detalle   = nodo_activo
                    tiempo_detalle = time.ticks_ms()
                    modo           = MODO_DETALLE
                    time.sleep_ms(500)
                    pantalla_detalle(nodo_activo)
                else:
                    modo           = MODO_MONITOR
                    pantalla_sucia = True

            else:
                enviar_comando(accion, nodo_activo)
                modo           = MODO_MONITOR
                pantalla_sucia = True

        elif modo == MODO_DETALLE:
            modo           = MODO_MONITOR
            pantalla_sucia = True

    # --- Botón navegar (Pin 35) ---
    if btn_navegar.presionado():
        if modo == MODO_NIVEL1:
            opcion_n1 = (opcion_n1 + 1) % len(NODOS_MENU)
            pantalla_nivel1()
        elif modo == MODO_NIVEL2:
            acciones  = _acciones_para(nodo_activo)
            opcion_n2 = (opcion_n2 + 1) % len(acciones)
            pantalla_nivel2(nodo_activo)

    # --- Actualizar pantalla según modo ---
    ahora_ms = time.ticks_ms()
    if modo == MODO_MONITOR:
        if pantalla_sucia or time.ticks_diff(ahora_ms, ultimo_render) >= INTERVALO_MS:
            pantalla_monitor()
            pantalla_sucia = False
            ultimo_render  = ahora_ms
    elif modo == MODO_DETALLE:
        transcurrido = time.ticks_diff(ahora_ms, tiempo_detalle)
        if transcurrido >= 30000:
            modo           = MODO_MONITOR
            pantalla_sucia = True
        else:
            pantalla_detalle(nodo_detalle)

    time.sleep_ms(50)