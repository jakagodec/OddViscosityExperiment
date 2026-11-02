"""Experiment protocols, ported from Scripts/experiment.py.

A protocol runs in a worker thread. Every wait checks the abort flag, and
whatever happens the run ends with the recording stopped and the field off.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import re
import sys
import threading
import time
from dataclasses import asdict, replace
from datetime import datetime

log = logging.getLogger('run')

# sequence token -> (magnet mode or None for field off, filename tag)
# Tags keep the names the analysis scripts parse (README §3).
FIELD_TOKENS = {
    'cw': ('cw', 'field=cw'),
    'ccw': ('ccw', 'field=ccw'),
    'none': ('none', 'field=none'),
    'none_y': ('none', 'field=none_start=y'),
    'none_x': ('none_x', 'field=none_start=x'),
    'cntrl': (None, 'cntrl'),
}


class Aborted(Exception):
    pass


def parse_sequence(text):
    tokens = [t.strip().lower() for t in text.replace(';', ',').split(',') if t.strip()]
    unknown = [t for t in tokens if t not in FIELD_TOKENS]
    if unknown or not tokens:
        raise ValueError(f'Bad field sequence {text!r}; allowed: {", ".join(FIELD_TOKENS)}')
    return tokens


def parse_floats(text):
    return [float(v) for v in text.replace(';', ',').split(',') if v.strip()]


def output_folder(run_settings):
    folder = run_settings.output_root
    if not sys.platform.startswith('win') and re.match(r'^[A-Za-z]:[\\/]|^\\\\', folder):
        raise OSError(f'Output folder {folder!r} is a Windows path; choose a folder valid on this computer')
    if run_settings.date_subfolder:
        folder = os.path.join(folder, datetime.now().strftime('%Y-%m-%d'))
    os.makedirs(folder, exist_ok=True)
    return folder


def unique_path(folder, name, ext):
    path = os.path.join(folder, name + ext)
    n = 2
    while os.path.exists(path):
        path = os.path.join(folder, f'{name}_{n}{ext}')
        n += 1
    return path


class Context:
    """What a protocol may do. Keeps track of state so cleanup is always possible."""

    def __init__(self, devices, settings, abort, on_status, on_progress):
        self.magnet, self.motor, self.camera = devices
        self.settings = settings
        self.rs = settings.run_settings
        self.abort = abort
        self.on_status = on_status
        self.on_progress = on_progress
        self.folder = output_folder(self.rs)
        self.focus = 0.0
        self.field_on = False
        self._recording = None

    def check(self):
        if self.abort.is_set():
            raise Aborted()

    def status(self, text):
        log.info(text)
        self.on_status(text)

    def wait(self, seconds, label='wait'):
        self.check()
        if seconds <= 0:
            return
        start = time.monotonic()
        while True:
            elapsed = time.monotonic() - start
            self.on_progress(label, min(elapsed, seconds), seconds)
            if elapsed >= seconds:
                return
            if self.abort.wait(min(0.1, seconds - elapsed)):
                raise Aborted()

    # devices
    def motor_to(self, turns):
        self.check()
        self.motor.move_to(turns)

    def flip(self):
        self.motor_to(self.focus + self.settings.motor.flip_turns)

    def to_focus(self):
        self.motor_to(self.focus)

    def field(self, mode, freq, amp):
        self.check()
        if mode is None:
            self.field_off()
            return
        self.magnet.set_field(mode, freq, amp)
        self.field_on = True

    def field_off(self):
        if self.field_on:
            self.magnet.disable()
            self.field_on = False

    def bust(self):
        rs = self.rs
        self.status('Busting aggregates')
        self.field('cw', rs.bust_freq, rs.bust_amp)
        self.wait(rs.bust_time_s, 'bust cw')
        self.field('ccw', rs.bust_freq, rs.bust_amp)
        self.wait(rs.bust_time_s, 'bust ccw')
        self.field_off()

    def record_start(self, name, meta, overwrite=False):
        self.check()
        path = os.path.join(self.folder, name + '.twv') if overwrite else unique_path(self.folder, name, '.twv')
        self.camera.start_recording(path)
        self._recording = {'file': os.path.basename(path), 'path': path,
                           'started': datetime.now().isoformat(timespec='seconds'), **meta}

    def record_stop(self):
        info, self._recording = self._recording, None
        stats = self.camera.stop_recording()
        if info is None or not self.rs.write_sidecar:
            return
        info['stopped'] = datetime.now().isoformat(timespec='seconds')
        info['recording'] = stats
        info['camera_missed_frames_total'] = self.camera.missed_frames
        info['settings'] = {k: v for k, v in self.settings.to_dict().items() if k != 'run'}
        path = info.pop('path')
        try:
            with open(os.path.splitext(path)[0] + '.json', 'w', encoding='utf-8') as fh:
                json.dump(info, fh, indent=2)
        except OSError as exc:
            log.warning('Could not write sidecar: %s', exc)

    def record(self, name, seconds, meta):
        self.record_start(name, meta)
        try:
            self.wait(seconds, f'recording {name}')
        finally:
            self.record_stop()

    def cleanup(self):
        if self._recording is not None or self.camera.recording:
            self.record_stop()
        try:
            if self.field_on or self.magnet.connected:
                self.magnet.disable()
        except Exception as exc:
            log.error('Could not disable the field: %s', exc)
        self.field_on = False


# ------------------------------------------------------------- protocols ---

def run_cycles(ctx, p, prefix=None, start_focused=None):
    """run_new: flip, settle (weak field), flip back, measure with the field on."""
    rs = ctx.rs
    sequence = parse_sequence(p.sequence)
    prefix = p.prefix if prefix is None else prefix
    start_focused = p.start_focused if start_focused is None else start_focused
    ctx.focus = ctx.motor.position if start_focused else ctx.motor.position + ctx.settings.motor.flip_turns
    ctx.wait(rs.start_delay_s, 'start delay')
    for i in range(p.cycles):
        token = sequence[i % len(sequence)]
        mode, tag = FIELD_TOKENS[token]
        ctx.status(f'{prefix}cycle {i + 1}/{p.cycles}: {token}')
        if p.bust:
            ctx.bust()
        if i > 0 or start_focused:
            ctx.flip()
            ctx.wait(rs.bubble_wait_s, 'after flip')
            if mode and rs.proxy_field:
                ctx.field(mode, p.freq, rs.proxy_amp)
                ctx.wait(rs.magnet_wait_s, 'field on')
            if rs.proxy_record:
                ctx.record_start('proxy', {'proxy': True}, overwrite=True)
            ctx.wait(p.settle_time + (rs.first_cycle_extra_wait_s if i == 0 else 0), 'settling')
            if rs.proxy_record:
                ctx.record_stop()
            ctx.field_off()
        ctx.to_focus()
        ctx.wait(rs.bubble_wait_s, 'after flip back')
        if mode:
            ctx.field(mode, p.freq, p.amp)
            ctx.wait(rs.magnet_wait_s, 'field on')
        meta = {'protocol': p.protocol, 'cycle': i + 1, 'cycles': p.cycles, 'field': token,
                'freq_hz': p.freq if mode else 0, 'amp': p.amp if mode else 0,
                'measure_time_s': p.measure_time, 'settle_time_s': p.settle_time}
        ctx.record(f'{prefix}cycle={i + 1}_{tag}', p.measure_time, meta)
        ctx.field_off()


def run_scan(ctx, p):
    freqs, amps = parse_floats(p.scan_freqs), parse_floats(p.scan_amps)
    first = True
    for f in freqs:
        for a in amps:
            block = replace(p, freq=f, amp=a)
            ctx.status(f'Scan block freq={f:g} Hz, amp={a:g}')
            run_cycles(ctx, block, prefix=f'{p.prefix}freq={f:g}_amp={round(a * 10):02d}_',
                       start_focused=p.start_focused if first else True)
            first = False
    if p.scan_control:
        run_cycles(ctx, replace(p, sequence='cntrl', bust=False), prefix=f'{p.prefix}control_',
                   start_focused=True)


def run_flow(ctx, p):
    """run_flow: no motor; field cycles bracketed by field-off controls."""
    sequence = parse_sequence(p.sequence)
    ctx.wait(ctx.rs.start_delay_s, 'start delay')
    base = {'protocol': 'flow', 'measure_time_s': p.measure_time}
    for i in range(p.controls_before):
        ctx.status(f'Control before {i + 1}/{p.controls_before}')
        ctx.record(f'{p.prefix}_control-before-{i}_field=cntrl', p.measure_time, {**base, 'field': 'cntrl'})
    for i in range(p.cycles):
        token = sequence[i % len(sequence)]
        mode, tag = FIELD_TOKENS[token]
        ctx.status(f'Flow cycle {i + 1}/{p.cycles}: {token}')
        if mode:
            ctx.field(mode, p.freq, p.amp)
            ctx.wait(ctx.rs.magnet_wait_s, 'field on')
        ctx.record(f'{p.prefix}cycle={i + 1}_{tag}', p.measure_time,
                   {**base, 'cycle': i + 1, 'field': token, 'freq_hz': p.freq if mode else 0,
                    'amp': p.amp if mode else 0})
        ctx.field_off()
    for i in range(p.controls_after):
        ctx.status(f'Control after {i + 1}/{p.controls_after}')
        ctx.record(f'{p.prefix}_control-after-{i}_field=cntrl', p.measure_time, {**base, 'field': 'cntrl'})


def run_flip(ctx, p):
    """sleep / sleep_buster: keep flipping (always the same direction) until stopped."""
    in_focus = True
    n = 0
    while True:
        n += 1
        ctx.status(f'Flip mode: interval {n} ({"focus" if in_focus else "flipped"})')
        if p.bust and in_focus:
            end = time.monotonic() + p.flip_interval
            while time.monotonic() < end:
                ctx.bust()
        else:
            ctx.wait(p.flip_interval, 'until next flip')
        ctx.motor_to(ctx.motor.position + ctx.settings.motor.flip_turns)
        in_focus = not in_focus


PROTOCOL_FUNCS = {'cycles': run_cycles, 'scan': run_scan, 'flow': run_flow, 'flip': run_flip}


def required_devices(p):
    """Which devices a protocol needs: subset of {'magnet', 'motor', 'camera'}."""
    needs = set()
    if p.protocol in ('cycles', 'scan', 'flow'):
        needs.add('camera')
        if p.bust or p.protocol == 'scan' or any(FIELD_TOKENS[t][0] for t in parse_sequence(p.sequence)):
            needs.add('magnet')
    if p.protocol in ('cycles', 'scan', 'flip'):
        needs.add('motor')
    if p.protocol == 'flip' and p.bust:
        needs.add('magnet')
    return needs


class Runner:
    def __init__(self, magnet, motor, camera, on_status=None, on_progress=None, on_finished=None):
        self.devices = (magnet, motor, camera)
        self.on_status = on_status or (lambda text: None)
        self.on_progress = on_progress or (lambda label, done, total: None)
        self.on_finished = on_finished or (lambda ok, message: None)
        self._abort = threading.Event()
        self._thread = None

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, settings):
        """Validate and start in a worker thread. Raises ValueError/RuntimeError on bad input."""
        if self.running:
            raise RuntimeError('A protocol is already running')
        settings = copy.deepcopy(settings)
        p = settings.run
        if p.protocol in ('cycles', 'scan', 'flow'):
            parse_sequence(p.sequence)
        if p.protocol == 'scan' and not (parse_floats(p.scan_freqs) and parse_floats(p.scan_amps)):
            raise ValueError('Scan needs at least one frequency and one amplitude')
        names = dict(zip(('magnet', 'motor', 'camera'), self.devices))
        missing = [n for n in sorted(required_devices(p)) if not names[n].connected]
        if missing:
            raise RuntimeError(f'Connect first: {", ".join(missing)}')
        self._abort.clear()
        self._thread = threading.Thread(target=self._run, args=(settings,), name='protocol', daemon=True)
        self._thread.start()

    def stop(self):
        if self.running:
            log.warning('Stop requested')
        self._abort.set()

    def wait(self, timeout=None):
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self, settings):
        p = settings.run
        ok, message = False, ''
        ctx = None
        try:
            ctx = Context(self.devices, settings, self._abort, self.on_status, self.on_progress)
            log.info('=== Start %s: %s', p.protocol, json.dumps(asdict(p)))
            log.info('Output folder: %s', ctx.folder)
            PROTOCOL_FUNCS[p.protocol](ctx, p)
            ok, message = True, 'Finished'
        except Aborted:
            message = 'Stopped by user'
        except Exception as exc:
            log.exception('Protocol failed')
            message = f'Failed: {exc}'
        finally:
            if ctx is not None:
                ctx.cleanup()
            log.log(logging.INFO if ok else logging.WARNING, '=== %s', message)
            self.on_finished(ok, message)
