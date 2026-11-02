"""Stepper motor that rotates the capillary (Arduino on a serial port).

The Arduino takes `GX <steps>` as an absolute target position and resets its
position to 0 whenever the port is opened, so position 0 is wherever the
capillary was when connecting.
"""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger('motor')


def serial_ports():
    try:
        from serial.tools import list_ports
        return [p.device for p in list_ports.comports()]
    except Exception:
        return []


class Motor:
    def __init__(self, settings):
        self.s = settings
        self._ser = None
        self._sim = False
        self.position = 0.0  # turns
        self._lock = threading.Lock()

    @property
    def connected(self):
        return self._sim or (self._ser is not None and self._ser.is_open)

    def connect(self):
        if self.connected:
            return
        if self.s.simulate:
            self._sim = True
        else:
            import serial
            self._ser = serial.Serial(port=self.s.port, baudrate=self.s.baudrate, timeout=self.s.timeout_s)
            time.sleep(self.s.connect_delay_s)
            self._ser.reset_input_buffer()
        self.position = 0.0
        log.info('Motor connected (%s), position set to 0', 'simulated' if self._sim else self.s.port)

    def disconnect(self):
        if self._ser is not None:
            self._ser.close()
        self._ser = None
        self._sim = False
        log.info('Motor disconnected')

    def move_to(self, turns):
        steps = int(round(self.s.steps_per_turn * turns))
        command = self.s.command.format(steps=steps)
        with self._lock:
            if not self.connected:
                raise RuntimeError('Motor not connected')
            if not self._sim:
                self._ser.write(f'{command}\n'.encode())
                time.sleep(0.05)
                if self._ser.in_waiting:
                    reply = self._ser.read(self._ser.in_waiting).decode(errors='replace').strip()
                    log.debug('reply: %s', reply)
            self.position = turns
        log.info('Motor -> %.4g turns (%s)', turns, command)

    def move_by(self, turns):
        self.move_to(self.position + turns)
