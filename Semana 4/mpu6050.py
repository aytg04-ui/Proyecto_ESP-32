# mp6050.py

from machine import I2C
import ustruct
import time

class MPU6050:
    def __init__(self, i2c, address=0x68):
        self.i2c = i2c
        self.address = address
        self._init_sensor()

    def _write_byte(self, reg, value):
        self.i2c.writeto_mem(self.address, reg, bytearray([value]))

    def _read_bytes(self, reg, length=1):
        return self.i2c.readfrom_mem(self.address, reg, length)

    def _init_sensor(self):
        self._write_byte(0x6B, 0x00)  # salir del modo sleep
        self._write_byte(0x1B, 0x00)  # giroscopio ±250°/s
        self._write_byte(0x1C, 0x00)  # acelerómetro ±2g
        self._write_byte(0x1A, 0x06)  # filtro paso bajo
        time.sleep_ms(100)

    def bytes_toint(self, hi, lo):
        val = (hi << 8) | lo
        if val >= 0x8000:
            val = -((65535 - val) + 1)
        return val

    def get_values(self):
        raw = self._read_bytes(0x3B, 14)
        return {
            "AcX": self.bytes_toint(raw[0],  raw[1]),
            "AcY": self.bytes_toint(raw[2],  raw[3]),
            "AcZ": self.bytes_toint(raw[4],  raw[5]),
            "Tmp": self.bytes_toint(raw[6],  raw[7]) / 340.0 + 36.53,
            "GyX": self.bytes_toint(raw[8],  raw[9]),
            "GyY": self.bytes_toint(raw[10], raw[11]),
            "GyZ": self.bytes_toint(raw[12], raw[13]),
        }