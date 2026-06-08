# Central Bx

from machine import Pin, SPI
import network, espnow, ubinascii, time
import st7789

# ── Pantalla ──────────────────────────────────────────────────────────────────
spi = SPI(1, baudrate=20000000, polarity=0, phase=0,
          sck=Pin(18), mosi=Pin(19))
display = st7789.Display(spi, Pin(16, Pin.OUT), Pin(5, Pin.OUT),
                              Pin(23, Pin.OUT), Pin(4, Pin.OUT), rotation=1)

# ── Botones ───────────────────────────────────────────────────────────────────
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

# ── ESP-NOW ───────────────────────────────────────────────────────────────────
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

# ── Estado de nodos ───────────────────────────────────────────────────────────
# Para agregar más nodos en el futuro: añade su entrada aquí y su MAC arriba.
nodos = {
    "A": {"datos": None, "ultimo": 0, "activo": False, "mac": MAC_A, "dormido": False, "nombre": "Nodo A"},
    "C": {"datos": None, "ultimo": 0, "activo": False, "mac": MAC_C, "dormido": False, "nombre": "Nodo C"},
    "D": {"datos": None, "ultimo": 0, "activo": False, "mac": MAC_D, "dormido": False, "nombre": "Nodo D"},
    "E": {"datos": None, "ultimo": 0, "activo": False, "mac": MAC_E, "dormido": False, "nombre": "Nodo E"},
}

TIMEOUT    = 15000
NODOS_MENU = list(nodos.keys()) + ["Todos"]

colores = {
    "A":    st7789.YELLOW,
    "C":    st7789.MAGENTA,
    "D":    st7789.GREEN,
    "E":    st7789.CYAN,
    "Todos":st7789.WHITE,
}

# ── Configuración del monitor dinámico ────────────────────────────────────────
INTERVALO_CICLO_MS = 5000
ultimo_ciclo_ms    = 0
pagina_monitor     = 0

# ── Estados de la interfaz ────────────────────────────────────────────────────
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
INTERVALO_MS   = 1000

# ── Nodos visibles (dinámico) ─────────────────────────────────────────────────
def get_nodos_visibles():
    ahora    = time.ticks_ms()
    visibles = []
    for nombre in nodos:
        info      = nodos[nombre]
        reciente  = time.ticks_diff(ahora, info["ultimo"]) <= TIMEOUT
        con_datos = info["activo"] and reciente
        if con_datos or info["dormido"]:
            visibles.append(nombre)
    return visibles

# ── Procesar mensaje ESP-NOW ──────────────────────────────────────────────────
# Formato: "X:ax:ay:az:tamb:tobj:tdht:hdht:mq:pct"
# -1 en cualquier campo = sensor no disponible
def procesar_mensaje(origen, partes):
    try:
        if origen in nodos:
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

# ── Resumen corto de datos de un nodo ────────────────────────────────────────
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
            lineas.append("FIEBRE!" if obj >= 38 else "Normal")
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

# ── PANTALLAS ─────────────────────────────────────────────────────────────────

def pantalla_monitor():
    global pagina_monitor

    display.fb.fill(st7789.BLACK)

    visibles = get_nodos_visibles()
    total    = len(visibles)

    # ── Header ────────────────────────────────────────────────────────────────
    # Antes: dos text_clipped con coordenadas manuales
    # Ahora: una sola llamada a header()
    display.header("Central B", "P35:sig P0:menu", st7789.YELLOW)

    if total == 0:
        display.text_big("ESPERA", 10, 40, st7789.WHITE, scale=2)
        display.text_wrap("Sin nodos activos. Esperando datos...", 4, 80, st7789.RED)
        display.show()
        return

    if pagina_monitor >= total:
        pagina_monitor = 0

    nombre = visibles[pagina_monitor]
    info   = nodos[nombre]
    color  = colores.get(nombre, st7789.WHITE)
    ahora  = time.ticks_ms()

    sin_datos = time.ticks_diff(ahora, info["ultimo"]) > TIMEOUT

    display.text_big("Nodo " + nombre, 2, 14, color, scale=2)

    y_ini = 38

    if info["dormido"]:
        display.text_big("ZZZ", 2, y_ini, st7789.RED, scale=2)
        display.text_wrap("Dormido", 2, y_ini + 20, st7789.RED)

    elif not sin_datos and info["datos"]:
        lineas = _resumen_corto(nombre, info["datos"])
        y = y_ini
        for linea in lineas[:6]:
            display.text_clipped(linea, 2, y, st7789.WHITE)
            y += 16

    else:
        display.text_wrap("Sin datos recientes", 2, y_ini, st7789.RED)

    if total > 1:
        transcurrido = time.ticks_diff(ahora, ultimo_ciclo_ms)
        seg_restante = max(0, (INTERVALO_CICLO_MS - transcurrido) // 1000)
        pag_txt = "{}/{} {}s".format(pagina_monitor + 1, total, seg_restante)
        display.text_clipped(pag_txt, display.width - len(pag_txt)*8 - 2,
                             display.height - 10, st7789.WHITE)
    else:
        display.text_clipped("1/1", display.width - 26, display.height - 10, st7789.WHITE)

    display.show()

def pantalla_nivel1():
    visibles = get_nodos_visibles()
    display.fb.fill(st7789.BLACK)
    # Header unificado
    display.header("Elegir nodo:", "P35:nav P0:ok", st7789.CYAN)
    y = 30
    for i, nombre in enumerate(NODOS_MENU):
        color = colores.get(nombre, st7789.WHITE)
        if nombre != "Todos":
            info = nodos[nombre]
            if info["dormido"]:
                estado = " [ZZZ]"
            elif nombre in visibles:
                estado = " [OK]"
            else:
                estado = " [---]"
        else:
            estado = " ({})".format(len(visibles))
        prefijo = "> " if i == opcion_n1 else "  "
        txt = prefijo + "Nodo " + nombre + estado
        display.text_clipped(txt, 5, y, st7789.YELLOW if i == opcion_n1 else color)
        y += 20
    display.show()

def pantalla_nivel2(nombre):
    display.fb.fill(st7789.BLACK)
    color = colores.get(nombre, st7789.WHITE)
    titulo = "Todos" if nombre == "Todos" else "Nodo " + nombre
    # Header unificado
    display.header(titulo, "P35:nav P0:ok", color)
    acciones = _acciones_para(nombre)
    y = 30
    for i, accion in enumerate(acciones):
        prefijo = "> " if i == opcion_n2 else "  "
        display.text_clipped(prefijo + accion, 10, y,
                             st7789.YELLOW if i == opcion_n2 else st7789.WHITE)
        y += 28
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

    display.text_big("Nodo " + nombre, 5, 2, color, scale=2)

    if not datos:
        display.text_wrap("Sin datos aun", 5, 80, st7789.RED)
    else:
        y = 22
        if datos.get("mpu"):
            ax, ay, az = datos["mpu"]
            mov = abs(az - 1.0) > 0.3 or abs(ax) > 0.3 or abs(ay) > 0.3
            display.fb.text("MPU-6050", 5, y, st7789.YELLOW); y += 14
            display.fb.text("X:{:.2f} Y:{:.2f} Z:{:.2f}".format(ax, ay, az), 5, y, st7789.WHITE); y += 14
            display.fb.text("MOV!" if mov else "Reposo", 5, y,
                            st7789.RED if mov else st7789.GREEN); y += 18
        if datos.get("gy"):
            amb, obj = datos["gy"]
            display.fb.text("GY-906", 5, y, st7789.MAGENTA); y += 14
            display.fb.text("Amb:{:.1f} Obj:{:.1f}C".format(amb, obj), 5, y, st7789.WHITE); y += 14
            fiebre = obj >= 38
            display.fb.text("FIEBRE!" if fiebre else "Normal", 5, y,
                            st7789.RED if fiebre else st7789.GREEN); y += 18
        if datos.get("dht"):
            t, h = datos["dht"]
            ok = 18 <= t <= 26 and 30 <= h <= 60
            display.fb.text("DHT11", 5, y, st7789.GREEN); y += 14
            display.fb.text("{}C  {}%".format(t, h), 5, y, st7789.WHITE); y += 14
            display.fb.text("OK" if ok else "Fuera rango", 5, y,
                            st7789.GREEN if ok else st7789.RED); y += 18
        if datos.get("mq"):
            v, pct = datos["mq"]
            if v < 1200:   cal, c2 = "Limpio",    st7789.GREEN
            elif v < 2000: cal, c2 = "Regular",   st7789.YELLOW
            elif v < 2500: cal, c2 = "Malo",      st7789.RED
            else:          cal, c2 = "Peligroso", st7789.RED
            display.fb.text("MQ-135", 5, y, st7789.CYAN); y += 14
            display.fb.text("ADC:{}  {:.1f}%".format(v, pct), 5, y, st7789.WHITE); y += 14
            display.fb.text(cal, 5, y, c2); y += 18
        if not any(datos.get(k) for k in ("mpu", "gy", "dht", "mq")):
            display.text_wrap("Sin sensores activos", 5, 80, st7789.RED)

    restante = 30 - (time.ticks_diff(time.ticks_ms(), tiempo_detalle) // 1000)
    display.fb.text("Vuelve en {}s".format(max(0, restante)), 5, 118, st7789.WHITE)
    display.fb.text("P0: salir ya", 5, display.height - 10, st7789.WHITE)
    display.show()

# ── Enviar comandos ───────────────────────────────────────────────────────────
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
        print("Enviando ACTIVAR a", nombre, "durante 35s...")
        display.fb.fill(st7789.BLACK)
        display.text_big("Activando", 5, 50, st7789.CYAN, scale=2)
        display.text_wrap(nombre + "... Espera 35s", 5, 80, st7789.WHITE)
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
        display.fb.fill(st7789.BLACK)
        if activado:
            display.text_big("OK!", 30, 50, st7789.GREEN, scale=3)
            display.text_wrap(nombre + " activado!", 5, 90, st7789.GREEN)
        else:
            display.text_wrap("Cmd enviado. Sin confirmacion. Deberia activar.", 5, 60, st7789.YELLOW)
        display.show()
        time.sleep(1 if activado else 2)
    elif accion == "Activar todos":
        display.fb.fill(st7789.BLACK)
        display.text_big("Activando", 5, 40, st7789.CYAN, scale=2)
        display.text_wrap("todos... Espera 35s", 5, 74, st7789.WHITE)
        display.show()
        inicio = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), inicio) < 35000:
            for n, info in nodos.items():
                if nodos[n]["dormido"]:
                    e.send(info["mac"], b'ACTIVAR')
            time.sleep_ms(500)
        for n in nodos:
            nodos[n]["dormido"] = False

# ── Pantalla de inicio ────────────────────────────────────────────────────────
display.fb.fill(st7789.BLACK)
display.text_big("Central B", 5, 45, st7789.CYAN, scale=2)
display.text_wrap("Iniciando...", 5, 80, st7789.WHITE)
display.show()
time.sleep(1)
print("Central B lista.")

# ── Bucle principal ───────────────────────────────────────────────────────────
while True:

    # ── Recibir mensajes ESP-NOW ──────────────────────────────────────────────
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

    # ── Botón confirmar (Pin 0) ───────────────────────────────────────────────
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

    # ── Botón navegar (Pin 35) ────────────────────────────────────────────────
    if btn_navegar.presionado():
        if modo == MODO_MONITOR:
            visibles = get_nodos_visibles()
            if len(visibles) > 1:
                pagina_monitor = (pagina_monitor + 1) % len(visibles)
            ultimo_ciclo_ms = time.ticks_ms()
            pantalla_sucia  = True
        elif modo == MODO_NIVEL1:
            opcion_n1 = (opcion_n1 + 1) % len(NODOS_MENU)
            pantalla_nivel1()
        elif modo == MODO_NIVEL2:
            acciones  = _acciones_para(nodo_activo)
            opcion_n2 = (opcion_n2 + 1) % len(acciones)
            pantalla_nivel2(nodo_activo)

    # ── Actualizar pantalla según modo ────────────────────────────────────────
    ahora_ms = time.ticks_ms()

    if modo == MODO_MONITOR:
        ciclo_elapsed = time.ticks_diff(ahora_ms, ultimo_ciclo_ms)
        if ciclo_elapsed >= INTERVALO_CICLO_MS:
            visibles = get_nodos_visibles()
            if len(visibles) > 1:
                pagina_monitor = (pagina_monitor + 1) % len(visibles)
            ultimo_ciclo_ms = ahora_ms
            pantalla_sucia  = True

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