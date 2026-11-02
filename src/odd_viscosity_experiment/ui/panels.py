"""Left-hand panels: one box per device (status, connect, settings, quick actions) and the experiment box."""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime

from PyQt6.QtWidgets import (
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QProgressBar, QPushButton, QSizePolicy, QVBoxLayout,
)

from ..protocols import output_folder, unique_path
from .forms import DataclassForm, ModeTable, SettingsDialog, raw_command_widget

log = logging.getLogger('gui')

LED_STYLE = 'border-radius: 6px; background: {};'


class DevicePanel(QGroupBox):
    title = ''
    settings_note = ''

    def __init__(self, window, device, settings):
        super().__init__(self.title)
        self.win = window
        self.device = device
        self.settings = settings
        self.led = QLabel()
        self.led.setFixedSize(12, 12)
        self.status = QLabel()
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.connect_btn = QPushButton('Connect')
        self.connect_btn.clicked.connect(self.toggle_connection)
        self.settings_btn = QPushButton('Settings…')
        self.settings_btn.clicked.connect(self.open_settings)
        top = QHBoxLayout()
        top.addWidget(self.led)
        top.addWidget(self.status, 1)
        top.addWidget(self.connect_btn)
        top.addWidget(self.settings_btn)
        self.actions = QGridLayout()
        self.action_buttons = []
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addLayout(self.actions)

    def add_action(self, text, callback, row, col, tip=''):
        button = QPushButton(text)
        button.clicked.connect(callback)
        button.setToolTip(tip)
        self.actions.addWidget(button, row, col)
        self.action_buttons.append(button)
        return button

    def toggle_connection(self):
        if self.device.connected:
            self.win.bg(self.device.disconnect)
        else:
            self.win.bg(self.device.connect)

    def status_text(self):
        return ''

    def refresh(self, running):
        connected = self.device.connected
        self.led.setStyleSheet(LED_STYLE.format('#2ecc40' if connected else '#888'))
        sim = ' (sim)' if self.settings.simulate else ''
        self.status.setText((self.status_text() if connected else 'disconnected') + sim)
        self.connect_btn.setText('Disconnect' if connected else 'Connect')
        self.connect_btn.setEnabled(not running)
        for button in self.action_buttons:
            button.setEnabled(connected and not running)

    def make_dialog(self):
        return SettingsDialog(f'{self.title} settings', self.settings, self, self.settings_note)

    def open_settings(self):
        dialog = self.make_dialog()
        if dialog.exec():
            self.win.settings.save()
            self.settings_changed()

    def settings_changed(self):
        if self.device.connected:
            log.info('%s settings saved; some changes apply only after reconnecting', self.title)


class MagnetPanel(DevicePanel):
    title = 'Magnetic tweezers'
    settings_note = ('Start ./pinceta7a on the Linux PC, start the magtweez server and load "sine" into bank 0. '
                     "Note: 'cw' in these modes turns counter-clockwise on the camera (27.5.2026 calibration).")

    def __init__(self, window, device, settings):
        super().__init__(window, device, settings)
        for col, mode in enumerate(('cw', 'ccw', 'none')):
            self.add_action(mode.upper() if mode != 'none' else 'CW↔CCW', lambda _=False, m=mode: self.set(m), 0, col,
                            'Uses frequency and amplitude from the experiment box')
        self.add_action('Field off', lambda: self.win.bg(self.device.disable), 1, 0)
        self.add_action('Bust', self.bust, 1, 1, 'CW then CCW at the bust settings (experiment settings)')

    def set(self, mode):
        params = self.win.current_params()
        self.win.bg(self.device.set_field, mode, params.freq, params.amp)

    def bust(self):
        rs = self.win.settings.run_settings

        def run():
            for mode in ('cw', 'ccw'):
                self.device.set_field(mode, rs.bust_freq, rs.bust_amp)
                time.sleep(rs.bust_time_s)
            self.device.disable()
        self.win.bg(run)

    def status_text(self):
        return f'field: {self.device.state}'

    def make_dialog(self):
        dialog = super().make_dialog()
        table = ModeTable(self.settings.modes)
        dialog.add_section('Field modes (sequence tokens none_y -> none, cntrl -> field off)', table,
                           lambda: setattr(self.settings, 'modes', table.modes()))
        dialog.add_section('Raw command', raw_command_widget(
            lambda cmd: self.win.bg(lambda: log.info('%s -> %r', cmd, self.device.query(cmd)))))
        dialog.add_action('Test connection', lambda: self.win.bg(
            lambda: log.info('Magnet test reply: %r', self.device.query('test'))))
        return dialog


class MotorPanel(DevicePanel):
    title = 'Capillary motor'
    settings_note = 'Position 0 is wherever the capillary is when connecting (the Arduino resets).'

    def __init__(self, window, device, settings):
        super().__init__(window, device, settings)
        self.add_action('◀ Jog', lambda: self.win.bg(self.device.move_by, -self.settings.jog_turns), 0, 0)
        self.add_action('Jog ▶', lambda: self.win.bg(self.device.move_by, self.settings.jog_turns), 0, 1)
        self.add_action('Flip', lambda: self.win.bg(self.device.move_by, self.settings.flip_turns), 0, 2)
        self.add_action('Go to 0', lambda: self.win.bg(self.device.move_to, 0.0), 0, 3)

    def status_text(self):
        steps = round(self.device.position * self.settings.steps_per_turn)
        return f'position {self.device.position:.4g} turns ({steps} steps)'


class CameraPanel(DevicePanel):
    title = 'Camera'
    settings_note = 'FLIR Spinnaker (PySpin). Exposure, gain and frame rate apply immediately.'

    def __init__(self, window, device, settings):
        super().__init__(window, device, settings)
        self.add_action('Snapshot', self.snapshot, 0, 0, 'Save the current frame as .pgm')
        self.record_btn = self.add_action('● Record', self.toggle_record, 0, 1, 'Manual recording (.twv)')

    def _folder(self):
        return output_folder(self.win.settings.run_settings)

    def snapshot(self):
        name = f'{self.win.current_params().prefix}snapshot_{datetime.now():%Y-%m-%d-%H%M%S}'
        self.win.bg(lambda: self.device.snapshot(unique_path(self._folder(), name, '.pgm')))

    def toggle_record(self):
        if self.device.recording:
            self.win.bg(self.device.stop_recording)
        else:
            name = f'{self.win.current_params().prefix}manual_{datetime.now():%H%M%S}'
            self.win.bg(lambda: self.device.start_recording(unique_path(self._folder(), name, '.twv')))

    def refresh(self, running):
        super().refresh(running)
        self.record_btn.setText('■ Stop' if self.device.recording else '● Record')

    def status_text(self):
        size = self.device.frame_size
        missed = self.device.missed_frames
        text = f'{self.device.fps:.1f} fps · {size[0]}×{size[1]}' if size else ''
        return text + (f' · {missed} missed' if missed else '')

    def settings_changed(self):
        if self.device.connected:
            self.device.reconfigure()


class ExperimentPanel(QGroupBox):
    def __init__(self, window):
        super().__init__('Experiment')
        self.win = window
        self.form = DataclassForm(window.settings.run)
        self.field_label = QLabel()
        self.form.layout_.insertRow(3, 'Field ≈', self.field_label)
        self.form.widget('protocol').currentIndexChanged.connect(self.update_visibility)
        self.form.widget('amp').valueChanged.connect(self.update_field_label)

        self.folder_label = QLabel()
        self.folder_label.setWordWrap(True)
        settings_btn = QPushButton('Settings…')
        settings_btn.setToolTip('Output folder, waiting times, proxy field, bust parameters')
        settings_btn.clicked.connect(self.open_settings)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.folder_label, 1)
        folder_row.addWidget(settings_btn)

        self.start_btn = QPushButton('▶ Start')
        self.stop_btn = QPushButton('■ Stop')
        self.start_btn.setStyleSheet('font-weight: bold; padding: 6px;')
        self.stop_btn.setStyleSheet('font-weight: bold; padding: 6px;')
        self.start_btn.clicked.connect(window.start_run)
        self.stop_btn.clicked.connect(window.stop_run)
        buttons = QHBoxLayout()
        buttons.addWidget(self.start_btn)
        buttons.addWidget(self.stop_btn)

        self.status = QLabel('Idle')
        self.status.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.progress.setFormat('')

        lay = QVBoxLayout(self)
        lay.addWidget(self.form)
        lay.addLayout(folder_row)
        lay.addLayout(buttons)
        lay.addWidget(self.status)
        lay.addWidget(self.progress)
        self.update_visibility()
        self.update_field_label()
        self.update_folder_label()

    def update_visibility(self):
        protocol = self.form.editors['protocol'][1]()
        for name, (_w, _g, _s, meta) in self.form.editors.items():
            if 'protocols' in meta:
                self.form.set_row_visible(name, protocol in meta['protocols'])
        self.form.layout_.setRowVisible(self.field_label, protocol in ('cycles', 'flow'))

    def update_field_label(self):
        amp = self.form.editors['amp'][1]()
        self.field_label.setText(f'{amp * self.win.settings.magnet.field_per_amp_uT / 1000:.2f} mT '
                                 '(cw/ccw, Hall calibration)')

    def update_folder_label(self):
        rs = self.win.settings.run_settings
        folder = os.path.join(rs.output_root, 'YYYY-MM-DD') if rs.date_subfolder else rs.output_root
        self.folder_label.setText(f'Output: {folder}')

    def open_settings(self):
        dialog = SettingsDialog('Experiment settings', self.win.settings.run_settings, self)
        if dialog.exec():
            self.win.settings.save()
            self.update_folder_label()

    def set_running(self, running):
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.form.setEnabled(not running)

    def show_progress(self, label, done, total):
        self.progress.setMaximum(1000)
        self.progress.setValue(int(1000 * done / total) if total else 0)
        self.progress.setFormat(f'{label}: {done:.0f} / {total:.0f} s')
