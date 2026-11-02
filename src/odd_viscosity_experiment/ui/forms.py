"""Forms generated from the settings dataclasses, and the settings dialogs."""
from __future__ import annotations

import logging
from dataclasses import fields

from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..camera import list_cameras
from ..motor import serial_ports
from ..settings import FieldMode

log = logging.getLogger('gui')

CHOICE_FUNCS = {'serial_ports': serial_ports, 'cameras': list_cameras}


class NoWheelMixin:
    """Spin boxes/combos only react to the wheel when focused (avoids accidental changes while scrolling)."""

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class SpinBox(NoWheelMixin, QSpinBox):
    pass


class DoubleSpinBox(NoWheelMixin, QDoubleSpinBox):
    pass


class ComboBox(NoWheelMixin, QComboBox):
    pass


def make_editor(value, meta):
    """Return (widget, getter, setter) for one setting value."""
    if isinstance(value, bool):
        w = QCheckBox()
        w.setChecked(value)
        return w, w.isChecked, w.setChecked
    if 'choices' in meta:
        w = ComboBox()
        for key, label in meta['choices']:
            w.addItem(label, key)
        w.setCurrentIndex(max(0, w.findData(value)))
        return w, w.currentData, lambda v: w.setCurrentIndex(max(0, w.findData(v)))
    if isinstance(value, int):
        w = SpinBox()
        w.setRange(int(meta.get('min', -10 ** 9)), int(meta.get('max', 10 ** 9)))
        w.setValue(value)
        w.setSuffix(meta.get('suffix', ''))
        return w, w.value, w.setValue
    if isinstance(value, float):
        w = DoubleSpinBox()
        w.setDecimals(meta.get('decimals', 3))
        w.setRange(meta.get('min', -1e9), meta.get('max', 1e9))
        w.setSingleStep(meta.get('step', 1.0))
        w.setValue(value)
        w.setSuffix(meta.get('suffix', ''))
        w.setKeyboardTracking(False)
        return w, w.value, w.setValue
    if isinstance(value, list):
        w = QLineEdit(', '.join(str(v) for v in value))
        return w, lambda: [int(v) for v in w.text().replace(';', ',').split(',') if v.strip()], \
            lambda v: w.setText(', '.join(str(x) for x in v))
    if 'choices_fn' in meta:
        return _choice_editor(value, CHOICE_FUNCS[meta['choices_fn']])
    if meta.get('browse') == 'dir':
        return _dir_editor(value)
    w = QLineEdit(value)
    if meta.get('suffix'):
        w.setPlaceholderText(meta['suffix'].strip())
    return w, w.text, w.setText


def _choice_editor(value, choices_fn):
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    combo = ComboBox()
    combo.setEditable(True)
    refresh = QPushButton('↻')
    refresh.setFixedWidth(30)
    refresh.setToolTip('Refresh list')

    def fill():
        current = combo.currentText() or value
        combo.clear()
        try:
            items = choices_fn()
        except Exception as exc:
            log.warning('Could not list devices: %s', exc)
            items = []
        combo.addItems(items)
        combo.setCurrentText(current)

    refresh.clicked.connect(fill)
    lay.addWidget(combo, 1)
    lay.addWidget(refresh)
    combo.setCurrentText(value)
    fill()
    return box, lambda: combo.currentText().strip(), combo.setCurrentText


def _dir_editor(value):
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    edit = QLineEdit(value)
    browse = QPushButton('…')
    browse.setFixedWidth(30)

    def pick():
        folder = QFileDialog.getExistingDirectory(box, 'Output folder', edit.text())
        if folder:
            edit.setText(folder)

    browse.clicked.connect(pick)
    lay.addWidget(edit, 1)
    lay.addWidget(browse)
    return box, edit.text, edit.setText


class DataclassForm(QWidget):
    """Form with one row per labelled field of a settings dataclass."""

    def __init__(self, obj, parent=None):
        super().__init__(parent)
        self.obj = obj
        self.layout_ = QFormLayout(self)
        self.layout_.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.editors = {}   # name -> (widget, getter, setter, meta)
        for f in fields(obj):
            meta = dict(f.metadata)
            if not meta.get('label'):
                continue
            widget, getter, setter = make_editor(getattr(obj, f.name), meta)
            if meta.get('tip'):
                widget.setToolTip(meta['tip'])
            self.layout_.addRow(meta['label'], widget)
            self.editors[f.name] = (widget, getter, setter, meta)

    def widget(self, name):
        return self.editors[name][0]

    def apply(self):
        """Write the widget values back into the dataclass."""
        for name, (_w, getter, _s, _m) in self.editors.items():
            setattr(self.obj, name, getter())

    def reload(self):
        for name, (_w, _g, setter, _m) in self.editors.items():
            setter(getattr(self.obj, name))

    def set_row_visible(self, name, visible):
        self.layout_.setRowVisible(self.editors[name][0], visible)


class ModeTable(QTableWidget):
    """Editable table of magnet field modes (bank, phase, scaling per axis)."""

    COLUMNS = ['bank_x', 'bank_y', 'phase_x', 'phase_y', 'freq_factor', 'amp_factor']
    HEADERS = ['bank x', 'bank y', 'phase x °', 'phase y °', 'freq ×', 'amp ×']

    def __init__(self, modes, parent=None):
        super().__init__(len(modes), len(self.COLUMNS), parent)
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.setVerticalHeaderLabels(list(modes))
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for row, mode in enumerate(modes.values()):
            for col, name in enumerate(self.COLUMNS):
                self.setItem(row, col, QTableWidgetItem(f'{getattr(mode, name):g}'))
        self.setMinimumHeight(self.verticalHeader().length() + self.horizontalHeader().height() + 8)

    def modes(self):
        result = {}
        for row in range(self.rowCount()):
            values = {name: float(self.item(row, col).text().replace(',', '.'))
                      for col, name in enumerate(self.COLUMNS)}
            values['bank_x'], values['bank_y'] = int(values['bank_x']), int(values['bank_y'])
            result[self.verticalHeaderItem(row).text()] = FieldMode(**values)
        return result


class SettingsDialog(QDialog):
    """Generic dialog: a DataclassForm plus optional extra sections and test buttons."""

    def __init__(self, title, obj, parent=None, note=''):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        self.form = DataclassForm(obj)
        self.main = QVBoxLayout(self)
        if note:
            label = QLabel(note)
            label.setWordWrap(True)
            label.setStyleSheet('color: palette(mid);')
            self.main.addWidget(label)
        self.main.addWidget(self.form)
        self.extra = QVBoxLayout()
        self.main.addLayout(self.extra)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.main.addWidget(self.buttons)
        self._appliers = [self.form.apply]

    def add_section(self, title, widget, applier=None):
        group = QGroupBox(title)
        QVBoxLayout(group).addWidget(widget)
        self.extra.addWidget(group)
        if applier:
            self._appliers.append(applier)

    def add_action(self, text, callback):
        button = self.buttons.addButton(text, QDialogButtonBox.ButtonRole.ActionRole)
        button.clicked.connect(lambda: (self.apply(), callback()))
        return button

    def apply(self):
        for applier in self._appliers:
            applier()

    def accept(self):
        try:
            self.apply()
        except ValueError as exc:
            log.error('Invalid setting: %s', exc)
            return
        super().accept()


def raw_command_widget(send):
    """Line edit + button to send an arbitrary command to the magnet server."""
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    edit = QLineEdit()
    edit.setPlaceholderText('e.g. setfreq 0 80   (remember: synchronize)')
    button = QPushButton('Send')
    button.clicked.connect(lambda: send(edit.text().strip()) if edit.text().strip() else None)
    edit.returnPressed.connect(button.click)
    lay.addWidget(edit, 1)
    lay.addWidget(button)
    return box
