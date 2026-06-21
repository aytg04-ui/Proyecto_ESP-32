# malla.py — Núcleo de red ESP-NOW (PIFNET unificado)
# Protocolo idéntico al MASTER (WAVE/FB en JSON, broadcast).
#
#   + dist_master / campo "uh" en FB  →  relay direccional por gradiente
#   + relay_fb inteligente: solo reenvía quien está MÁS CERCA del master
#   + fijar_canal(ch)  →  fija canal sin escanear (modo bajo consumo)
#   + reactivar()      →  re-asegura radio tras lightsleep
#   + beacon_reciente(ms)  →  True si oí beacon del master en los últimos ms
#   + hora_hhmmss()    →  HH:MM:SS (para UI, sin fecha)
#   + relay_wave incluye campo "h" (distancia) para que el receptor actualice
#     su dist_master
#
# API
#   Malla(node_id, net_id, master_id, canales, relay, mid_base)
#   .iniciar(canal)   .cerrar()
#   .escanear_canal(ms)
#   .recibir(timeout)  → dict o None
#   .manejar_wave(d)   → True si debo responder
#   .mandar_fb(payload, parent, mid, alerta, a_t, reps)
#   .mandar_ack(cmd)
#   .mandar_wave(cmd, target, reps)   .next_mid()
#   .relay_fb(d)       → True si retransmití
#   .ts_actual()       .hora_hhmmss()
#
# NUEVO (del  ):
#   .fijar_canal(ch)   .reactivar()   .beacon_reciente(ms)
#   .dist_master       .ultimo_beacon

import gc, network, espnow, json, time
from machine import RTC
from time import ticks_ms, ticks_add, ticks_diff

BROADCAST     = b'\xff\xff\xff\xff\xff\xff'
CANALES_DEFAULT = [1, 6, 11, 4, 8, 2, 3, 5, 7, 9, 10]
DEDUP_TTL_MS  = 30_000


class Malla:
    def __init__(self, node_id, net_id="PIFNET",
                 master_id="MASTER_TTGO_GATEWAY",
                 canales=None, relay=True, mid_base=0):
        self.node_id   = node_id
        self.net_id    = net_id
        self.master_id = master_id
        self.canales   = canales or CANALES_DEFAULT
        self.relay     = relay
        self._mid      = mid_base   # base de mid para originar WAVEs (supervisor/master)

        self.sta = network.WLAN(network.STA_IF)
        self.en  = None
        self.canal        = self.canales[0]
        self.conectado    = False
        self.ultimo_padre = master_id

        # ── NUEVO: gradiente de routing ───────────────────
        self.dist_master   = 99     # saltos al master (99 = aún desconocido; 0 = soy master)
        self.ultimo_beacon = 0      # ticks_ms() del último beacon recibido del master

        self._waves = {}     # dedup WAVE  {mid: ticks}
        self._fbs   = {}     # dedup FB    {"id|mid": ticks}

        self.rtc    = RTC()
        self.hora_ok = False

    # ── RADIO ─────────────────────────────────────────────
    def iniciar(self, canal=None):
        """Abre STA + ESP-NOW. Idempotente: reusa 'en' si ya existe."""
        self.sta.active(True)
        try:
            self.sta.config(pm=0xa11140)   # apagar power-save (coexistir con ESP-NOW)
        except Exception:
            pass
        if canal is not None:
            try:
                self.sta.config(channel=canal)
                self.canal = canal
            except Exception:
                pass
        if self.en is None:
            self.en = espnow.ESPNow()
            self.en.active(True)
            self.en.add_peer(BROADCAST)
        return self.en

    def cerrar(self):
        """Cierra ESP-NOW + STA. Usar solo antes de lightsleep/deepsleep."""
        if self.en:
            try: self.en.active(False)
            except Exception: pass
            self.en = None
        try: self.sta.active(False)
        except Exception: pass
        gc.collect()

    # ── NUEVO: fijar canal sin escanear ───────────────────
    def fijar_canal(self, ch):
        """Fija el canal directamente (sin escanear). Útil en modo bajo
        consumo cuando el canal del master ya se conoce de arranques
        anteriores (guardarlo en node_config.json y pasar aquí al inicio)."""
        if self.en is None:
            self.iniciar()
        try:
            self.sta.config(channel=ch)
            self.canal = ch
        except Exception:
            pass

    # ── NUEVO: reactivar radio tras lightsleep ─────────────
    def reactivar(self):
        """Re-asegura la radio después de un lightsleep (best-effort).
        El comportamiento de ESP-NOW tras lightsleep depende del firmware;
        verificar en hardware."""
        try:
            self.sta.active(True)
            self.sta.config(channel=self.canal)
        except Exception:
            pass
        if self.en is None:
            self.iniciar()
        else:
            try:
                self.en.active(True)
            except Exception:
                pass

    # ── ESCANEO DE CANAL (in-situ, no reabre 'en') ────────
    def escanear_canal(self, ms=1200):
        """Recorre canales buscando una WAVE del master REAL. True si lo halla."""
        if self.en is None:
            self.iniciar()
        for ch in self.canales:
            try: self.sta.config(channel=ch)
            except Exception: continue
            time.sleep_ms(120)
            fin = ticks_add(ticks_ms(), ms)
            while ticks_diff(fin, ticks_ms()) > 0:
                d = self.recibir(50)
                if (d and d.get("type") == "WAVE"
                        and d.get("from") == self.master_id):
                    self.canal = d.get("ch", ch)
                    try: self.sta.config(channel=self.canal)
                    except Exception: pass
                    self.conectado    = True
                    self.ultimo_beacon = ticks_ms()
                    self._sync_rtc(d.get("ts"))
                    print("[MALLA] master en canal", self.canal)
                    return True
            gc.collect()
        print("[MALLA] master no encontrado, ch:", self.canal)
        return False

    # ── RECEPCIÓN ──────────────────────────────────────────
    def recibir(self, timeout=50):
        """Devuelve un dict (ya filtrado por net) o None."""
        if self.en is None:
            return None
        try:
            _, msg = self.en.recv(timeout)
        except Exception:
            return None
        if not msg:
            return None
        try:
            d = json.loads(msg.decode())
        except Exception:
            return None
        if d.get("net") != self.net_id:
            return None
        return d

    # ── DEDUP ──────────────────────────────────────────────
    def _visto(self, tabla, clave):
        ahora = ticks_ms()
        for k in [k for k, v in tabla.items()
                  if ticks_diff(ahora, v) > DEDUP_TTL_MS]:
            del tabla[k]
        if clave in tabla:
            return True
        tabla[clave] = ahora
        return False

    # ── MANEJO DE WAVE ─────────────────────────────────────
    def manejar_wave(self, d):
        """Dedup + distancia en saltos + canal del master + relay.
        True si debo responder (REQ para mí / ALL)."""
        mid = d.get("mid")
        if self._visto(self._waves, mid):
            return False
        self._sync_rtc(d.get("ts"))
        frm = d.get("from", self.master_id)

        # ── NUEVO: actualizar dist_master por gradiente ──
        # El campo "h" lleva la distancia del emisor; yo estoy a h+1 saltos.
        h = d.get("h")
        if h is not None and (h + 1) < self.dist_master:
            self.dist_master = h + 1

        # Adoptar canal SOLO si viene del master real (fix anti-confusión v12.3)
        if frm == self.master_id:
            self.ultimo_beacon = ticks_ms()    # ← NUEVO: marcar beacon
            ch = d.get("ch", self.canal)
            if ch != self.canal:
                self.canal = ch
                try: self.sta.config(channel=ch)
                except Exception: pass

        self.conectado    = True
        self.ultimo_padre = frm

        if self.relay and d.get("ttl", 0) > 1:
            self._relay_wave(d)

        target = d.get("target", "ALL")
        return target == "ALL" or target == self.node_id

    def _relay_wave(self, d):
        nuevo = dict(d)
        nuevo["from"] = self.node_id
        nuevo["ttl"]  = d["ttl"] - 1
        nuevo["h"]    = self.dist_master   # ← NUEVO: propago mi distancia
        try: self.en.send(BROADCAST, json.dumps(nuevo).encode())
        except Exception: pass

    # ── ENVÍO DE FB ────────────────────────────────────────
    def mandar_fb(self, payload, parent=None, mid=None,
                  alerta=None, a_t=None, reps=2):
        pkt = {"type": "FB", "net": self.net_id, "id": self.node_id,
               "par": parent or self.ultimo_padre, "pl": payload,
               "uh": self.dist_master}     # ← NUEVO: gradiente para relay inteligente
        if mid is not None:
            pkt["mid"] = mid
        if alerta:
            pkt["alert"] = alerta
            pkt["a_t"]   = a_t or []
        s = json.dumps(pkt)
        if len(s) > 248:                   # recortar si excede el límite ESP-NOW
            pkt["pl"] = payload[:3]
            s = json.dumps(pkt)
        ok = False
        for _ in range(reps):
            try: ok = bool(self.en.send(BROADCAST, s.encode())) or ok
            except Exception: pass
            time.sleep_ms(120)
        flag = " [" + alerta + "]" if alerta else ""
        print("[>>> FB TX] {} -> {}  mid:{}  bytes:{}  hw:{}{}".format(
            self.node_id, pkt["par"], mid, len(s), "OK" if ok else "FALLO", flag))
        return ok

    def mandar_ack(self, cmd, parent=None):
        """Confirma un comando (DORMIR/ACTIVAR) al master."""
        return self.mandar_fb([{"t": "ACK", "v": cmd}], parent=parent, reps=2)

    # ── ENVÍO DE WAVE (supervisor / master que origina órdenes) ──
    def next_mid(self):
        self._mid += 1
        return self._mid

    def mandar_wave(self, cmd="REQ:ALL", target="ALL", reps=3):
        pkt = {"type": "WAVE", "net": self.net_id, "cmd": cmd,
               "from": self.node_id, "target": target, "ttl": 6,
               "ch": self.canal, "mid": self.next_mid(), "ts": self.ts_actual()}
        s = json.dumps(pkt)
        for _ in range(reps):
            try: self.en.send(BROADCAST, s.encode())
            except Exception: pass
            time.sleep_ms(120)
        return pkt["mid"]

    # ── RELAY DE FB AJENO (direccional por gradiente) ──────
    def relay_fb(self, d):
        """Retransmite un FB ajeno SOLO si estoy más cerca del master que
        quien lo emitió (campo 'uh'). Así el relay sigue el gradiente hacia
        el master en lugar de retransmitir a ciegas.
        Devuelve True si retransmití, False si no."""
        if not self.relay:
            return False
        idn = d.get("id")
        mid = d.get("mid")
        if idn == self.node_id:
            return False

        # ── NUEVO: gradiente — solo reenvío si me acerco al master ──
        uh = d.get("uh", 99)
        if self.dist_master >= uh:
            return False

        if self._visto(self._fbs, "{}|{}".format(idn, mid)):
            return False
        via = d.get("via", [])
        if self.node_id in via:
            return False
        via.append(self.node_id)
        d["via"] = via
        d["uh"]  = self.dist_master    # actualizo gradiente para el siguiente salto
        try:
            s = json.dumps(d)
            if len(s) < 248:
                self.en.send(BROADCAST, s.encode())
                return True
        except Exception:
            pass
        return False

    # ── NUEVO: sincronía de beacon ──────────────────────────
    def beacon_reciente(self, ms):
        """True si oí un beacon del master en los últimos 'ms' milisegundos.
        Útil para decidir si entrar en lightsleep o esperar un poco más."""
        return (self.ultimo_beacon != 0 and
                ticks_diff(ticks_ms(), self.ultimo_beacon) < ms)

    # ── HORA / RTC ─────────────────────────────────────────
    def _sync_rtc(self, ts):
        if not ts or not isinstance(ts, str):
            return
        try:
            f, h = ts.split(" ")
            a, m, d = [int(x) for x in f.split("-")]
            hh, mm, ss = [int(x) for x in h.split(":")]
            self.rtc.datetime((a, m, d, 0, hh, mm, ss, 0))
            self.hora_ok = True
        except Exception:
            pass

    def ts_actual(self):
        """Timestamp completo YYYY-MM-DD HH:MM:SS (para campo 'ts' del WAVE)."""
        lt = time.localtime()
        if self.hora_ok:
            return "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(*lt[:6])
        return "{:02d}:{:02d}:{:02d}".format(lt[3], lt[4], lt[5])

    def hora_hhmmss(self):
        """Solo HH:MM:SS (para mostrar en pantalla)."""
        lt = time.localtime()
        return "{:02d}:{:02d}:{:02d}".format(lt[3], lt[4], lt[5])
