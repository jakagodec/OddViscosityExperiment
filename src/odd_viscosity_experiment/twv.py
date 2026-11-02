"""Writer for .twv videos, byte-compatible with the files FlyCapture2Natan wrote.

Layout (little-endian, packed), matching Tracker2026/app/twv.py:
  video header (58 B): VideoID, VideoVersion, VideoLicence (u16), VideoHeaderSize,
      RecordedFrames (u32), frame header size, FrameDataIncl, ROI L/T/W/H,
      BytesPerPixel (u16), FrameRate, Exposure, Gain (f64), RecTrapDataNo (u16),
      ImageToSampleScale (f32)
  per frame: header (60 B): FrameNumber (u32), FrameTime [s] (f32), LaserPower (f32),
      4 x trap data (3 x f32), then W*H uint8 pixels.
"""
from __future__ import annotations

import logging
import queue
import struct
import threading

import numpy as np

log = logging.getLogger('twv')

VIDEO_HEADER = struct.Struct('<3H2I2H4HH3dHf')
FRAME_HEADER = struct.Struct('<I2f12f')
VIDEO_ID = 0x1A57
VIDEO_VERSION = 20
assert VIDEO_HEADER.size == 58 and FRAME_HEADER.size == 60


class TwvWriter:
    """Writes frames from a background thread so acquisition never waits for the disk."""

    def __init__(self, path, width, height, frame_rate=0.0, exposure_ms=0.0, gain_db=0.0,
                 um_per_px=1.0, buffer_frames=64):
        self.path = path
        self.width, self.height = int(width), int(height)
        self._meta = (float(frame_rate), float(exposure_ms), float(gain_db), float(um_per_px))
        self.frames_written = 0
        self.dropped = 0
        self.error = None
        self._t0 = None
        self._closed = False
        self._f = open(path, 'wb')
        self._write_header()
        self._queue = queue.Queue(maxsize=buffer_frames)
        self._thread = threading.Thread(target=self._run, name='twv-writer', daemon=True)
        self._thread.start()

    def _write_header(self):
        rate, exposure, gain, scale = self._meta
        self._f.write(VIDEO_HEADER.pack(
            VIDEO_ID, VIDEO_VERSION, 0, VIDEO_HEADER.size, self.frames_written,
            FRAME_HEADER.size, 0, 0, 0, self.width, self.height, 1,
            rate, exposure, gain, 0, scale))

    def add(self, image, timestamp):
        """Queue a frame; `timestamp` in seconds (any origin, stored relative to the first frame)."""
        if self._closed:
            return
        if self._t0 is None:
            self._t0 = timestamp
        try:
            self._queue.put_nowait((image, timestamp - self._t0))
        except queue.Full:
            self.dropped += 1

    def _run(self):
        while True:
            item = self._queue.get()
            if item is None:
                return
            image, t = item
            if self.error is not None:
                continue
            try:
                if image.shape != (self.height, self.width):
                    raise ValueError(f'frame shape {image.shape} != {(self.height, self.width)}')
                self._f.write(FRAME_HEADER.pack(self.frames_written, t, 0.0, *([0.0] * 12)))
                self._f.write(np.ascontiguousarray(image, dtype=np.uint8).tobytes())
                self.frames_written += 1
            except Exception as exc:
                self.error = exc
                log.error('Writing %s failed: %s', self.path, exc)

    def close(self):
        """Flush, write the final frame count and close. Returns a stats dict."""
        if not self._closed:
            self._closed = True
            self._queue.put(None)
            self._thread.join()
            self._f.seek(0)
            self._write_header()
            self._f.close()
        return {'frames': self.frames_written, 'dropped_buffer_full': self.dropped,
                'error': None if self.error is None else str(self.error)}


def read_header(path):
    """Return the video header of a .twv file as a dict."""
    with open(path, 'rb') as fh:
        values = VIDEO_HEADER.unpack(fh.read(VIDEO_HEADER.size))
    keys = ('video_id', 'version', 'licence', 'header_size', 'frames', 'frame_header_size', 'frame_data_incl',
            'roi_left', 'roi_top', 'width', 'height', 'bytes_per_pixel', 'frame_rate', 'exposure', 'gain',
            'trap_data_no', 'um_per_px')
    return dict(zip(keys, values))


def read_frame(path, index):
    """Return (image, frame_time_s) of frame `index`."""
    header = read_header(path)
    if not 0 <= index < header['frames']:
        raise IndexError(f'frame {index} out of range ({header["frames"]} frames)')
    size = header['width'] * header['height']
    with open(path, 'rb') as fh:
        fh.seek(header['header_size'] + index * (header['frame_header_size'] + size))
        frame_header = FRAME_HEADER.unpack(fh.read(header['frame_header_size'])[:FRAME_HEADER.size])
        image = np.frombuffer(fh.read(size), dtype=np.uint8).reshape(header['height'], header['width'])
    return image, frame_header[1]
