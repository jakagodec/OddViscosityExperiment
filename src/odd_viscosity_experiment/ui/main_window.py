"""Main window: devices + experiment on the left third, camera and log on the right two thirds."""
from __future__ import annotations

import logging
import threading

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QMainWindow, QMessageBox, QScrollArea, QSplitter, QVBoxLayout, QWidget

from ..camera import Camera
from ..magnet import Magnet
from ..motor import Motor
from ..protocols import Runner
from .camera_view import CameraView
from .logview import LogView
from .panels import CameraPanel, ExperimentPanel, MagnetPanel, MotorPanel

log = logging.getLogger('gui')


class RunSignals(QObject):
    status = pyqtSignal(str)
    progress = pyqtSignal(str, float, float)
    finished = pyqtSignal(bool, str)


class MainWindow(QMainWindow):
    def __init__(self, settings, log_handler):
        super().__init__()
        self.setWindowTitle('Odd viscosity experiment')
        self.settings = settings
        self.magnet = Magnet(settings.magnet)
        self.motor = Motor(settings.motor)
        self.camera = Camera(settings.camera)

        self.signals = RunSignals()
        self.runner = Runner(self.magnet, self.motor, self.camera,
                             on_status=self.signals.status.emit,
                             on_progress=self.signals.progress.emit,
                             on_finished=self.signals.finished.emit)

        # left: devices, then the experiment commands
        self.device_panels = [MagnetPanel(self, self.magnet, settings.magnet),
                              MotorPanel(self, self.motor, settings.motor),
                              CameraPanel(self, self.camera, settings.camera)]
        self.experiment = ExperimentPanel(self)
        left = QWidget()
        left_lay = QVBoxLayout(left)
        for panel in self.device_panels:
            left_lay.addWidget(panel)
        left_lay.addWidget(self.experiment)
        left_lay.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(left)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # right: camera with the log below
        self.view = CameraView()
        self.log_view = LogView(log_handler)
        right = QSplitter(Qt.Orientation.Vertical)
        right.addWidget(self.view)
        right.addWidget(self.log_view)
        right.setStretchFactor(0, 4)
        right.setStretchFactor(1, 1)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(scroll)
        self.splitter.addWidget(right)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 2)
        self.setCentralWidget(self.splitter)

        self.signals.status.connect(self.experiment.status.setText)
        self.signals.progress.connect(self.experiment.show_progress)
        self.signals.finished.connect(self.run_finished)

        self._last_frame_id = 0
        self.frame_timer = QTimer(self)
        self.frame_timer.timeout.connect(self.update_frame)
        self.frame_timer.start(int(1000 / settings.camera.display_fps))
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.refresh)
        self.status_timer.start(300)
        self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        width = self.splitter.width()
        self.splitter.setSizes([width // 3, width - width // 3])

    # ------------------------------------------------------------ helpers
    def bg(self, fn, *args):
        """Run a device action off the GUI thread; errors go to the log."""
        def run():
            try:
                fn(*args)
            except Exception as exc:
                log.error('%s: %s', getattr(fn, '__name__', 'action'), exc)
        threading.Thread(target=run, daemon=True).start()

    def current_params(self):
        self.experiment.form.apply()
        return self.settings.run

    # --------------------------------------------------------------- run
    def start_run(self):
        self.experiment.form.apply()
        self.settings.save()
        try:
            self.runner.start(self.settings)
        except Exception as exc:
            log.error('Cannot start: %s', exc)
            QMessageBox.warning(self, 'Cannot start', str(exc))
            return
        self.experiment.status.setText('Starting…')
        self.refresh()

    def stop_run(self):
        self.runner.stop()

    def run_finished(self, ok, message):
        self.experiment.status.setText(message)
        self.experiment.progress.setValue(0)
        self.experiment.progress.setFormat('')
        self.refresh()

    # ----------------------------------------------------------- refresh
    def refresh(self):
        running = self.runner.running
        for panel in self.device_panels:
            panel.refresh(running)
        self.experiment.set_running(running)

    def update_frame(self):
        cs = self.settings.camera
        interval = int(1000 / cs.display_fps)
        if self.frame_timer.interval() != interval:
            self.frame_timer.setInterval(interval)
        self.view.overlay = cs.show_overlay
        self.view.tilt_deg = cs.tilt_deg
        self.view.um_per_px = cs.pixel_size_um
        if not self.camera.connected:
            if self.view._image is not None:
                self.view.clear()
            return
        frame, frame_id = self.camera.latest()
        self.view.rec_text = f'REC {self.camera.recording_elapsed:.1f} s' if self.camera.recording else ''
        self.view.info = f'{self.camera.fps:.1f} fps'
        if frame is not None and frame_id != self._last_frame_id:
            self._last_frame_id = frame_id
            self.view.set_frame(frame, cs.auto_contrast)
        else:
            self.view.update()

    # ------------------------------------------------------------- close
    def closeEvent(self, event):
        if self.runner.running:
            answer = QMessageBox.question(self, 'Experiment running', 'Stop the experiment and quit?')
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.runner.stop()
            self.runner.wait(10)
        self.experiment.form.apply()
        self.settings.save()
        for device in (self.camera, self.magnet, self.motor):
            if device.connected:
                try:
                    device.disconnect()
                except Exception as exc:
                    log.error('Disconnect failed: %s', exc)
        event.accept()
