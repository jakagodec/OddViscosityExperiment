"""Log box fed by the standard logging module (thread-safe via a Qt signal)."""
from __future__ import annotations

import html
import logging

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QCheckBox, QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

COLORS = {logging.DEBUG: '#888888', logging.WARNING: '#d08000', logging.ERROR: '#e03030',
          logging.CRITICAL: '#e03030'}


class _Emitter(QObject):
    record = pyqtSignal(str, int)


class QtLogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.emitter = _Emitter()
        self.setFormatter(logging.Formatter('%(asctime)s  %(name)-7s %(message)s', '%H:%M:%S'))

    def emit(self, record):
        try:
            self.emitter.record.emit(self.format(record), record.levelno)
        except RuntimeError:
            pass  # widget already destroyed at shutdown


class LogView(QWidget):
    def __init__(self, handler, parent=None):
        super().__init__(parent)
        self.text = QPlainTextEdit(readOnly=True)
        self.text.setMaximumBlockCount(5000)
        self.text.setFont(QFont('Monospace', 9))
        self.debug = QCheckBox('Show device commands (debug)')
        clear = QPushButton('Clear')
        clear.clicked.connect(self.text.clear)
        bar = QHBoxLayout()
        bar.addWidget(self.debug)
        bar.addStretch(1)
        bar.addWidget(clear)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.text, 1)
        lay.addLayout(bar)
        handler.emitter.record.connect(self.append)

    def append(self, message, level):
        if level < logging.INFO and not self.debug.isChecked():
            return
        color = COLORS.get(level)
        text = html.escape(message)
        self.text.appendHtml(f'<span style="color:{color}">{text}</span>' if color else text)
