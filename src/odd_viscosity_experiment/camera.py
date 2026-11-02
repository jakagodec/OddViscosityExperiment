"""Camera acquisition through PySpin (FLIR Spinnaker SDK), replacing FlyCapture2Natan.

A background thread grabs frames continuously. The GUI polls `latest()` for
display; while recording, every frame also goes to a TwvWriter.
"""
from __future__ import annotations

import logging
import threading
import time

import numpy as np

from .twv import TwvWriter

log = logging.getLogger('camera')


def list_cameras():
    """Return serial numbers of connected Spinnaker cameras (empty if PySpin is missing)."""
    try:
        import PySpin
    except ImportError:
        return []
    system = PySpin.System.GetInstance()
    cam_list = system.GetCameras()
    serials = []
    try:
        for i in range(cam_list.GetSize()):
            cam = cam_list.GetByIndex(i)
            node = PySpin.CStringPtr(cam.GetTLDeviceNodeMap().GetNode('DeviceSerialNumber'))
            if PySpin.IsReadable(node):
                serials.append(node.GetValue())
            del cam
    finally:
        cam_list.Clear()
        system.ReleaseInstance()
    return serials


class SpinnakerBackend:
    def open(self, s):
        import PySpin
        self.PySpin = PySpin
        self.system = PySpin.System.GetInstance()
        self.cam_list = self.system.GetCameras()
        if self.cam_list.GetSize() == 0:
            self._release()
            raise RuntimeError('No Spinnaker camera found')
        self.cam = self.cam_list.GetBySerial(s.serial) if s.serial else self.cam_list.GetByIndex(0)
        self.cam.Init()
        self.nodemap = self.cam.GetNodeMap()
        tl = self.cam.GetTLDeviceNodeMap()
        self.info = ' '.join(filter(None, (self._get_str(tl, 'DeviceModelName'),
                                           self._get_str(tl, 'DeviceSerialNumber'))))
        self._set_enum(self.cam.GetTLStreamNodeMap(), 'StreamBufferHandlingMode', 'OldestFirst')
        self._set_enum(self.nodemap, 'AcquisitionMode', 'Continuous')
        self._set_enum(self.nodemap, 'PixelFormat', 'Mono8')
        self.configure(s)
        self.width = int(self.PySpin.CIntegerPtr(self.nodemap.GetNode('Width')).GetValue())
        self.height = int(self.PySpin.CIntegerPtr(self.nodemap.GetNode('Height')).GetValue())
        self._last_frame_id = None
        self.missed_frames = 0
        self.cam.BeginAcquisition()

    def configure(self, s):
        nm = self.nodemap
        self._set_enum(nm, 'ExposureAuto', 'Off')
        self._set_enum(nm, 'GainAuto', 'Off')
        # Frame rate first: exposure is limited by 1/frame rate.
        self._set_enum(nm, 'AcquisitionFrameRateAuto', 'Off')      # Grasshopper3 / older SFNC
        for name in ('AcquisitionFrameRateEnable', 'AcquisitionFrameRateEnabled'):
            self._set_bool(nm, name, True)
        fps = self._set_float(nm, 'AcquisitionFrameRate', s.frame_rate)
        exposure = self._set_float(nm, 'ExposureTime', s.exposure_ms * 1000.0)
        gain = self._set_float(nm, 'Gain', s.gain_db)
        log.info('Camera configured: %s Hz, exposure %s ms, gain %s dB',
                 _fmt(fps), _fmt(exposure and exposure / 1000.0), _fmt(gain))

    def grab(self, timeout_ms):
        try:
            image = self.cam.GetNextImage(int(timeout_ms))
        except self.PySpin.SpinnakerException:
            return None
        try:
            if image.IsIncomplete():
                log.warning('Incomplete image (status %s)', image.GetImageStatus())
                return None
            frame_id = image.GetFrameID()
            if self._last_frame_id is not None and frame_id > self._last_frame_id + 1:
                self.missed_frames += frame_id - self._last_frame_id - 1
            self._last_frame_id = frame_id
            return image.GetNDArray().copy(), image.GetTimeStamp() * 1e-9
        finally:
            image.Release()

    def close(self):
        try:
            self.cam.EndAcquisition()
            self.cam.DeInit()
        finally:
            del self.cam
            self._release()

    def _release(self):
        self.cam_list.Clear()
        self.system.ReleaseInstance()

    # GenICam node helpers: settings that a model does not have are skipped.
    def _get_str(self, nodemap, name):
        node = self.PySpin.CStringPtr(nodemap.GetNode(name))
        return node.GetValue() if self.PySpin.IsReadable(node) else ''

    def _set_enum(self, nodemap, name, entry):
        node = self.PySpin.CEnumerationPtr(nodemap.GetNode(name))
        if not self.PySpin.IsWritable(node):
            log.debug('Node %s not writable, skipped', name)
            return False
        item = node.GetEntryByName(entry)
        if not self.PySpin.IsReadable(item):
            log.warning('Node %s has no entry %s', name, entry)
            return False
        node.SetIntValue(item.GetValue())
        return True

    def _set_bool(self, nodemap, name, value):
        node = self.PySpin.CBooleanPtr(nodemap.GetNode(name))
        if self.PySpin.IsWritable(node):
            node.SetValue(value)

    def _set_float(self, nodemap, name, value):
        node = self.PySpin.CFloatPtr(nodemap.GetNode(name))
        if not self.PySpin.IsWritable(node):
            log.warning('Camera setting %s not writable', name)
            return None
        clipped = min(max(value, node.GetMin()), node.GetMax())
        if clipped != value:
            log.warning('%s limited to %.4g (allowed %.4g - %.4g)', name, clipped, node.GetMin(), node.GetMax())
        node.SetValue(clipped)
        return node.GetValue()


class SimulatedBackend:
    """Beads sedimenting downwards with a little drift and noise."""

    def open(self, s):
        self.info = 'simulated camera'
        self.width, self.height = 1920, 1200
        self.missed_frames = 0
        rng = np.random.default_rng()
        self._rng = rng
        yy, xx = np.mgrid[0:self.height, 0:self.width]
        self._background = 170 + 20 * np.exp(-((xx - 960) ** 2 + (yy - 600) ** 2) / 8e5)
        self._background += rng.normal(0, 3, self._background.shape)
        r = 11
        y, x = np.mgrid[-r:r + 1, -r:r + 1]
        self._r = r
        self._bead = np.clip(1.2 - np.hypot(x, y) / r, 0, 1) * 120
        n = 50
        self._pos = np.column_stack([rng.uniform(r, self.width - r - 1, n), rng.uniform(r, self.height - r - 1, n)])
        self._next = time.monotonic()
        self.configure(s)

    def configure(self, s):
        self._fps = s.frame_rate
        self._brightness = s.exposure_ms / 20.0 * 10 ** (s.gain_db / 20.0)
        log.info('Simulated camera configured: %g Hz', s.frame_rate)

    def grab(self, timeout_ms):
        now = time.monotonic()
        if self._next > now:
            time.sleep(min(self._next - now, timeout_ms / 1000.0))
        self._next = max(self._next + 1.0 / self._fps, time.monotonic())
        r = self._r
        self._pos += np.column_stack([self._rng.normal(0.3, 0.5, len(self._pos)),
                                      self._rng.normal(20.0 / self._fps, 0.5, len(self._pos))])
        self._pos[:, 0] %= self.width - 2 * r - 1
        self._pos[:, 1] %= self.height - 2 * r - 1
        img = self._background.copy()
        for x, y in self._pos.astype(int) + r:
            img[y - r:y + r + 1, x - r:x + r + 1] -= self._bead
        img = np.clip(img * self._brightness, 0, 255).astype(np.uint8)
        return img, time.monotonic()

    def close(self):
        pass


class Camera:
    def __init__(self, settings):
        self.s = settings
        self.info = ''
        self.fps = 0.0
        self._backend = None
        self._thread = None
        self._stop = threading.Event()
        self._reconfigure = threading.Event()
        self._lock = threading.Lock()
        self._latest = None
        self._latest_id = 0
        self._recorder = None
        self._rec_started = None

    @property
    def connected(self):
        return self._thread is not None and self._thread.is_alive()

    @property
    def recording(self):
        return self._recorder is not None

    @property
    def recording_elapsed(self):
        return time.monotonic() - self._rec_started if self._recorder else 0.0

    @property
    def frame_size(self):
        return (self._backend.width, self._backend.height) if self._backend else None

    @property
    def missed_frames(self):
        return self._backend.missed_frames if self._backend else 0

    def connect(self):
        if self.connected:
            return
        backend = SimulatedBackend() if self.s.simulate else SpinnakerBackend()
        backend.open(self.s)
        self._backend = backend
        self.info = backend.info
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name='camera', daemon=True)
        self._thread.start()
        log.info('Camera connected: %s (%dx%d)', self.info, backend.width, backend.height)

    def disconnect(self):
        self.stop_recording()
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._thread = None
        if self._backend is not None:
            try:
                self._backend.close()
            except Exception:
                log.exception('Error while closing camera')
        self._backend = None
        self.fps = 0.0
        log.info('Camera disconnected')

    def reconfigure(self):
        """Apply changed settings (done by the acquisition thread between frames)."""
        self._reconfigure.set()

    def latest(self):
        with self._lock:
            return self._latest, self._latest_id

    def start_recording(self, path):
        if not self.connected:
            raise RuntimeError('Camera not connected')
        width, height = self.frame_size
        writer = TwvWriter(path, width, height, self.s.frame_rate, self.s.exposure_ms, self.s.gain_db,
                           self.s.pixel_size_um, self.s.write_buffer_frames)
        with self._lock:
            if self._recorder is not None:
                writer.close()
                raise RuntimeError('Already recording')
            self._recorder = writer
            self._rec_started = time.monotonic()
        log.info('Recording -> %s', path)

    def stop_recording(self):
        with self._lock:
            writer, self._recorder = self._recorder, None
        if writer is None:
            return None
        stats = writer.close()
        stats['duration_s'] = round(time.monotonic() - self._rec_started, 3)
        level = logging.WARNING if stats['dropped_buffer_full'] or stats['error'] else logging.INFO
        log.log(level, 'Recording stopped: %d frames in %.1f s, %d dropped (buffer full)%s',
                stats['frames'], stats['duration_s'], stats['dropped_buffer_full'],
                f", error: {stats['error']}" if stats['error'] else '')
        return stats

    def snapshot(self, path):
        """Save the latest frame as binary PGM (like the old umeritev_*.pgm files)."""
        frame, _ = self.latest()
        if frame is None:
            raise RuntimeError('No frame available')
        with open(path, 'wb') as fh:
            fh.write(f'P5\n{frame.shape[1]} {frame.shape[0]}\n255\n'.encode())
            fh.write(np.ascontiguousarray(frame, dtype=np.uint8).tobytes())
        log.info('Snapshot -> %s', path)

    def _loop(self):
        count, t_count = 0, time.monotonic()
        try:
            while not self._stop.is_set():
                if self._reconfigure.is_set():
                    self._reconfigure.clear()
                    self._backend.configure(self.s)
                grabbed = self._backend.grab(500)
                if grabbed is None:
                    continue
                image, timestamp = grabbed
                with self._lock:
                    self._latest = image
                    self._latest_id += 1
                    recorder = self._recorder
                if recorder is not None:
                    recorder.add(image, timestamp)
                count += 1
                now = time.monotonic()
                if now - t_count >= 1.0:
                    self.fps = count / (now - t_count)
                    count, t_count = 0, now
        except Exception:
            log.exception('Camera acquisition stopped')


def _fmt(value):
    return '?' if value is None else f'{value:.4g}'
