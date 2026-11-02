"""Client for the magnetic tweezers server (pinceta, TCP port 2222).

Same protocol as Scripts/tweezersTCP.py: one TCP connection per command,
command terminated by CRLF, one reply read back. Nothing changes on the
coils until `synchronize` is sent.
"""
from __future__ import annotations

import logging
import socket
import threading

log = logging.getLogger('magnet')


class Magnet:
    def __init__(self, settings):
        self.s = settings
        self.connected = False
        self.state = 'off'
        self._lock = threading.Lock()

    # ------------------------------------------------------------ transport
    def query(self, command):
        if self.s.simulate:
            log.debug('sim > %s', command)
            return 'ok'
        with self._lock:
            with socket.create_connection((self.s.host, self.s.port), timeout=self.s.timeout_s) as sock:
                sock.sendall(f'{command}\r\n'.encode())
                reply = sock.recv(1024).decode(errors='replace').strip()
        log.debug('> %s  < %s', command, reply)
        return reply

    def connect(self):
        reply = self.query('test')
        self.connected = True
        where = 'simulated' if self.s.simulate else f'{self.s.host}:{self.s.port}'
        log.info('Magnet connected (%s), test reply: %r', where, reply)
        self.disable()

    def disconnect(self):
        if self.connected:
            try:
                self.disable()
            except Exception as exc:
                log.warning('Could not disable field on disconnect: %s', exc)
        self.connected = False
        log.info('Magnet disconnected')

    # -------------------------------------------------------------- control
    def _axes(self):
        return (('x', self.s.channels_x), ('y', self.s.channels_y))

    def set_field(self, mode, freq, amp):
        """Set a rotating field mode ('cw', 'ccw', 'none', 'none_x', ...) and apply it."""
        if mode not in self.s.modes:
            raise ValueError(f'Unknown field mode {mode!r}')
        m = self.s.modes[mode]
        f = freq * m.freq_factor
        scale = amp * m.amp_factor / self.s.amplitude_divisor
        for axis, (primary, secondary) in self._axes():
            bank = m.bank_x if axis == 'x' else m.bank_y
            phase = m.phase_x if axis == 'x' else m.phase_y
            channels = [(primary, phase)]
            if self.s.drive_secondary:
                channels.append((secondary, (phase + self.s.secondary_phase_shift) % 360))
            for ch, ph in channels:
                self.query(f'waveform {ch}')
                if self.s.use_banks:
                    self.query(f'set_bank {ch} {bank}')
                self.query(f'scale {ch} {scale:g}')
                self.query(f'setfreq {ch} {f:g}')
                self.query(f'setphase {ch} {ph:g}')
            if not self.s.drive_secondary:
                self.query(f'disable {secondary}')
        self.query('synchronize')
        self.state = f'{mode} · {freq:g} Hz · amp {amp:g}'
        log.info('Field %s', self.state)

    def disable(self):
        for _axis, channels in self._axes():
            for ch in channels:
                self.query(f'disable {ch}')
        self.query('synchronize')
        if self.state != 'off':
            log.info('Field off')
        self.state = 'off'
