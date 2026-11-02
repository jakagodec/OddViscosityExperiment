"""Live camera display with overlays (gravity line at the camera tilt, scale bar, REC)."""
from __future__ import annotations

import math

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PyQt6.QtWidgets import QWidget


class CameraView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 200)
        self.setMouseTracking(True)
        self._array = None
        self._image = None
        self.overlay = True
        self.tilt_deg = 0.0
        self.um_per_px = 1.0
        self.info = ''
        self.rec_text = ''
        self._cursor = ''

    def clear(self):
        self._array = self._image = None
        self.update()

    def set_frame(self, frame, auto_contrast=False):
        if auto_contrast:
            lo, hi = np.percentile(frame[::8, ::8], (1, 99))
            if hi > lo:
                frame = np.clip((frame.astype(np.float32) - lo) * (255.0 / (hi - lo)), 0, 255).astype(np.uint8)
        frame = np.ascontiguousarray(frame, dtype=np.uint8)
        self._array = frame  # QImage does not copy; keep the buffer alive
        h, w = frame.shape
        self._image = QImage(frame.data, w, h, w, QImage.Format.Format_Grayscale8)
        self.update()

    def _target(self):
        h, w = self._array.shape
        scale = min(self.width() / w, self.height() / h)
        tw, th = w * scale, h * scale
        return QRectF((self.width() - tw) / 2, (self.height() - th) / 2, tw, th), scale

    def mouseMoveEvent(self, event):
        if self._array is not None:
            rect, scale = self._target()
            x = int((event.position().x() - rect.left()) / scale)
            y = int((event.position().y() - rect.top()) / scale)
            h, w = self._array.shape
            self._cursor = f'x={x} y={y} I={self._array[y, x]}' if 0 <= x < w and 0 <= y < h else ''
            self.update()

    def leaveEvent(self, event):
        self._cursor = ''
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(20, 20, 20))
        if self._image is None:
            p.setPen(QColor(150, 150, 150))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, 'Camera not connected')
            return
        rect, scale = self._target()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, scale < 1)
        p.drawImage(rect, self._image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.overlay:
            self._draw_overlay(p, rect, scale)
        p.setFont(QFont('Monospace', 9))
        self._label(p, QPointF(8, 18), '  '.join(filter(None, (self.info, self._cursor))))
        if self.rec_text:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(220, 30, 30))
            p.drawEllipse(QPointF(self.width() - 120, 14), 6, 6)
            p.setPen(QColor(255, 80, 80))
            p.drawText(QPointF(self.width() - 108, 19), self.rec_text)

    def _draw_overlay(self, p, rect, scale):
        # Gravity direction: vertical line rotated by the (counter-clockwise) camera tilt.
        c = rect.center()
        a = math.radians(self.tilt_deg)
        half = rect.height() / 2
        dx, dy = -math.sin(a) * half, math.cos(a) * half
        p.setPen(QPen(QColor(0, 200, 255, 160), 1, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(c.x() - dx, c.y() - dy), QPointF(c.x() + dx, c.y() + dy))
        p.drawLine(QPointF(c.x() - 10, c.y()), QPointF(c.x() + 10, c.y()))
        self._label(p, QPointF(c.x() + dx + 4, min(c.y() + dy, rect.bottom() - 4)), f'g  tilt {self.tilt_deg:g}°')
        # Scale bar
        length_um = 100.0
        length = length_um / self.um_per_px * scale
        while length > rect.width() / 3 and length_um > 1:
            length_um /= 10
            length = length_um / self.um_per_px * scale
        x0, y0 = rect.right() - 20 - length, rect.bottom() - 20
        p.setPen(QPen(QColor(255, 220, 0), 3))
        p.drawLine(QPointF(x0, y0), QPointF(x0 + length, y0))
        self._label(p, QPointF(x0, y0 - 6), f'{length_um:g} µm')

    @staticmethod
    def _label(p, pos, text):
        if not text:
            return
        p.setPen(QColor(0, 0, 0, 200))
        p.drawText(pos + QPointF(1, 1), text)
        p.setPen(QColor(240, 240, 240))
        p.drawText(pos, text)
