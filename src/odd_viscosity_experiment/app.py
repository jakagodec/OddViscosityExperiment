"""Application entry point."""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime

from PyQt6.QtCore import QLocale
from PyQt6.QtWidgets import QApplication

from .protocols import output_folder
from .settings import CONFIG_DIR, AppSettings
from .ui.logview import QtLogHandler
from .ui.main_window import MainWindow


def setup_logging(settings):
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter('%(asctime)s %(name)s %(levelname)s: %(message)s'))
    root.addHandler(console)
    gui_handler = QtLogHandler()
    root.addHandler(gui_handler)
    # A log file next to the day's recordings (fallback: app folder).
    try:
        folder = output_folder(settings.run_settings)
    except OSError:
        folder = os.path.join(CONFIG_DIR, 'logs')
        os.makedirs(folder, exist_ok=True)
    file_handler = logging.FileHandler(os.path.join(folder, f'experiment_log_{datetime.now():%Y-%m-%d}.txt'),
                                       encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s %(name)s %(levelname)s: %(message)s'))
    root.addHandler(file_handler)
    logging.getLogger('gui').info('Log file: %s', file_handler.baseFilename)
    return gui_handler


def _qt_plugin_path():
    # Some installs (e.g. Anaconda on macOS) do not find PyQt6's own platform plugins.
    import PyQt6
    path = os.path.join(os.path.dirname(PyQt6.__file__), 'Qt6', 'plugins')
    if os.path.isdir(path):
        os.environ.setdefault('QT_PLUGIN_PATH', path)


def main():
    _qt_plugin_path()
    QLocale.setDefault(QLocale(QLocale.Language.English, QLocale.Country.UnitedStates))  # '.' as decimal point
    app = QApplication(sys.argv)
    settings = AppSettings.load()
    gui_handler = setup_logging(settings)
    window = MainWindow(settings, gui_handler)
    window.resize(1600, 950)
    window.show()
    return app.exec()
