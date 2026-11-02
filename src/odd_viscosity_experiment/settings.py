"""Persistent settings for the devices and the experiment, stored as JSON.

Every option is a dataclass field. The `label`/`tip` metadata is used by the
GUI to build the settings forms automatically; fields without a label are not
shown in the generic forms.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field, fields

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform.startswith('win')


def _config_dir():
    """Per-user settings folder (kept out of the repository, separate on every computer)."""
    if os.environ.get('ODD_VISCOSITY_CONFIG_DIR'):
        return os.environ['ODD_VISCOSITY_CONFIG_DIR']
    home = os.path.expanduser('~')
    if IS_WINDOWS:
        base = os.environ.get('APPDATA', home)
    elif sys.platform == 'darwin':
        base = os.path.join(home, 'Library', 'Application Support')
    else:
        base = os.environ.get('XDG_CONFIG_HOME', os.path.join(home, '.config'))
    return os.path.join(base, 'OddViscosityExperiment')


CONFIG_DIR = _config_dir()
SETTINGS_FILE = os.path.join(CONFIG_DIR, 'settings.json')
# Away from the lab PC (no Windows) start with simulated devices.
DEFAULT_SIMULATE = not IS_WINDOWS
DEFAULT_OUTPUT = ('C:\\MagnetneNanoploscice-posnetki' if IS_WINDOWS
                  else os.path.join(os.path.expanduser('~'), 'MagnetneNanoploscice-posnetki'))


def opt(default, label='', tip='', **meta):
    meta.update(label=label, tip=tip)
    if isinstance(default, (list, dict)):
        return field(default_factory=lambda d=default: copy.deepcopy(d), metadata=meta)
    return field(default=default, metadata=meta)


# ---------------------------------------------------------------- magnet ----

@dataclass
class FieldMode:
    """How one field mode is produced: waveform bank, phase and scaling per axis."""
    bank_x: int = 0
    bank_y: int = 0
    phase_x: float = 0.0
    phase_y: float = 90.0
    freq_factor: float = 1.0
    amp_factor: float = 1.0


def default_modes():
    # See README §1.1. 'none' plays bank 1 (sine with reversal) on x and bank 2
    # (cosine) on y: one turn each way, starting vertical. The waveform is two
    # periods long, hence f/2 and 2*amp. 'none_x' swaps the banks (start at x).
    return {
        'cw': FieldMode(0, 0, 0.0, 90.0, 1.0, 1.0),
        'ccw': FieldMode(0, 0, 90.0, 0.0, 1.0, 1.0),
        'none': FieldMode(1, 2, 0.0, 0.0, 0.5, 2.0),
        'none_x': FieldMode(2, 1, 0.0, 0.0, 0.5, 2.0),
    }


@dataclass
class MagnetSettings:
    simulate: bool = opt(DEFAULT_SIMULATE, 'Simulate', 'Do not connect; only log the commands.')
    host: str = opt('141.255.216.102', 'Host / IP', 'Run "hostname -I" on the pinceta PC if it changed.')
    port: int = opt(2222, 'Port', min=1, max=65535)
    timeout_s: float = opt(5.0, 'Timeout', suffix=' s', min=0.5, max=60)
    channels_x: list = opt([0, 1], 'Channels x (primary, secondary)', 'ch0 = horizontal (27.5.2026 calibration)')
    channels_y: list = opt([4, 5], 'Channels y (primary, secondary)', 'ch4 = vertical (27.5.2026 calibration)')
    drive_secondary: bool = opt(False, 'Drive secondary channels',
                                'Coils are in series, so normally only the primary channel is driven '
                                'and the secondary is disabled.')
    secondary_phase_shift: float = opt(180.0, 'Secondary phase shift', suffix=' °', min=-360, max=360)
    amplitude_divisor: float = opt(2.0, 'Amplitude divisor',
                                   'Value sent to "scale" is amp / divisor (as in tweezersTCP.setAmplitude).',
                                   min=0.01, max=100)
    use_banks: bool = opt(True, 'Use set_bank (pinceta 7a+)')
    field_per_amp_uT: float = opt(1700.0, 'Field per amp unit', 'Hall probe calibration (30.6.2025). Display only.',
                                  suffix=' µT', min=0, max=1e5, decimals=0)
    modes: dict = field(default_factory=default_modes)


# ----------------------------------------------------------------- motor ----

@dataclass
class MotorSettings:
    simulate: bool = opt(DEFAULT_SIMULATE, 'Simulate')
    port: str = opt('COM4', 'Serial port', choices_fn='serial_ports')
    baudrate: int = opt(115200, 'Baud rate', min=300, max=2000000)
    timeout_s: float = opt(4.0, 'Timeout', suffix=' s', min=0.1, max=60)
    connect_delay_s: float = opt(1.0, 'Delay after connect', 'The Arduino resets when the port opens.',
                                 suffix=' s', min=0, max=10)
    steps_per_turn: int = opt(400, 'Steps per full turn', 'Code used 400, the 2025 notes say 800 - verify!',
                              min=1, max=1000000)
    command: str = opt('GX {steps}', 'Move command', '{steps} = absolute target position in steps.')
    flip_turns: float = opt(0.5, 'Flip angle', 'Rotation that turns the capillary upside down.',
                            suffix=' turns', min=-10, max=10, decimals=3)
    jog_turns: float = opt(0.05, 'Jog step', suffix=' turns', min=0.0001, max=10, decimals=4)


# ---------------------------------------------------------------- camera ----

@dataclass
class CameraSettings:
    simulate: bool = opt(DEFAULT_SIMULATE, 'Simulate', 'Synthetic sedimenting beads instead of a real camera.')
    serial: str = opt('', 'Camera serial', 'Empty = first camera found.', choices_fn='cameras')
    exposure_ms: float = opt(20.0, 'Exposure', suffix=' ms', min=0.01, max=10000, decimals=3)
    gain_db: float = opt(0.0, 'Gain', suffix=' dB', min=0, max=48, decimals=1)
    frame_rate: float = opt(15.0, 'Frame rate', 'PartTracker needed >= 15 Hz.', suffix=' Hz', min=0.1, max=500,
                            decimals=2)
    pixel_size_um: float = opt(0.456, 'Pixel size', 'Stored in the .twv header and sidecar.', suffix=' µm/px',
                               min=0.0001, max=100, decimals=4)
    tilt_deg: float = opt(2.88, 'Camera tilt', 'Counter-clockwise tilt; drawn as the gravity line.',
                          suffix=' °', min=-45, max=45, decimals=2)
    show_overlay: bool = opt(True, 'Show overlay (gravity line, scale bar)')
    auto_contrast: bool = opt(False, 'Display auto-contrast', 'Display only, recordings are raw.')
    display_fps: float = opt(15.0, 'Display refresh', suffix=' Hz', min=1, max=60, decimals=0)
    write_buffer_frames: int = opt(64, 'Recording buffer', 'Frames queued for the disk writer.', min=4, max=2000)


# ------------------------------------------------------------ experiment ----

PROTOCOLS = [
    ('cycles', 'Cycles (flip, settle, measure)'),
    ('control', 'Control (flip, settle, measure; no magnet)'),
    ('scan', 'Frequency/amplitude scan'),
    ('flow', 'Flow (no motor)'),
    ('flip', 'Flip only (keep sample alive)'),
]


@dataclass
class RunParams:
    """Main commands shown below the devices."""
    protocol: str = opt('cycles', 'Protocol', choices=PROTOCOLS)
    freq: float = opt(120.0, 'Frequency', suffix=' Hz', min=0, max=5000, decimals=2,
                      protocols=['cycles', 'flow'])
    amp: float = opt(0.6, 'Amplitude', '>= ~0.8 tends to drive vortices in the capillary.', min=0, max=5,
                     decimals=3, step=0.05, protocols=['cycles', 'flow'])
    cycles: int = opt(3, 'Cycles', min=1, max=100000, protocols=['cycles', 'control', 'scan', 'flow'])
    sequence: str = opt('cw,ccw,none', 'Field sequence',
                        'Repeated cyclically. Tokens: cw, ccw, none, none_x, none_y, cntrl (field off).',
                        protocols=['cycles', 'scan', 'flow'])
    measure_time: float = opt(50.0, 'Measure time', suffix=' s', min=0.1, max=100000,
                              protocols=['cycles', 'control', 'scan', 'flow'])
    settle_time: float = opt(60.0, 'Settle time', 'Time after flipping for the beads to cross the channel.',
                             suffix=' s', min=0, max=100000, protocols=['cycles', 'control', 'scan'])
    prefix: str = opt('', 'File prefix', protocols=['cycles', 'control', 'scan', 'flow'])
    start_focused: bool = opt(True, 'Start focused',
                              'Checked: beads lie on the bottom wall in the measuring orientation -> '
                              'flip, settle, flip back before the 1st cycle.\n'
                              'Unchecked: capillary is upside down with beads settled -> '
                              'one flip starts the 1st measurement.',
                              protocols=['cycles', 'control', 'scan'])
    bust: bool = opt(False, 'Bust aggregates', 'Before every cycle (flip protocol: while in focus).',
                     protocols=['cycles', 'scan', 'flip'])
    scan_freqs: str = opt('40,80,120', 'Scan frequencies', suffix=' Hz', protocols=['scan'])
    scan_amps: str = opt('0.3,0.6', 'Scan amplitudes', protocols=['scan'])
    scan_control: bool = opt(True, 'Control run after scan', protocols=['scan'])
    controls_before: int = opt(0, 'Controls before', min=0, max=1000, protocols=['flow'])
    controls_after: int = opt(0, 'Controls after', min=0, max=1000, protocols=['flow'])
    flip_interval: float = opt(40.0, 'Flip interval', suffix=' s', min=1, max=100000, protocols=['flip'])


@dataclass
class RunSettings:
    """Less frequently changed experiment settings (own dialog)."""
    output_root: str = opt(DEFAULT_OUTPUT, 'Output folder', browse='dir')
    date_subfolder: bool = opt(True, 'Create YYYY-MM-DD subfolder')
    start_delay_s: float = opt(5.0, 'Delay before start', suffix=' s', min=0, max=3600)
    bubble_wait_s: float = opt(2.0, 'Wait after motor move', suffix=' s', min=0, max=3600)
    magnet_wait_s: float = opt(2.0, 'Wait after field on', suffix=' s', min=0, max=3600)
    first_cycle_extra_wait_s: float = opt(0.0, 'Extra settle (1st cycle)', suffix=' s', min=0, max=3600)
    proxy_field: bool = opt(True, 'Weak field while settling', 'Same mode as the next cycle, at the proxy amplitude.')
    proxy_amp: float = opt(0.05, 'Proxy amplitude', min=0, max=5, decimals=3)
    proxy_record: bool = opt(False, 'Record settling as proxy.twv', 'The old scripts did; overwritten every cycle.')
    bust_freq: float = opt(1.0, 'Bust frequency', suffix=' Hz', min=0, max=1000, decimals=2)
    bust_amp: float = opt(0.5, 'Bust amplitude', min=0, max=5, decimals=3)
    bust_time_s: float = opt(5.0, 'Bust time per direction', suffix=' s', min=0, max=3600)
    write_sidecar: bool = opt(True, 'Write .json sidecar per recording')


@dataclass
class AppSettings:
    magnet: MagnetSettings = field(default_factory=MagnetSettings)
    motor: MotorSettings = field(default_factory=MotorSettings)
    camera: CameraSettings = field(default_factory=CameraSettings)
    run: RunParams = field(default_factory=RunParams)
    run_settings: RunSettings = field(default_factory=RunSettings)

    def to_dict(self):
        return asdict(self)

    def save(self, path=None):
        path = path or SETTINGS_FILE
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(self.to_dict(), fh, indent=2)
        os.replace(tmp, path)

    @classmethod
    def load(cls, path=None):
        path = path or SETTINGS_FILE
        settings = cls()
        if not os.path.exists(path):
            return settings
        try:
            with open(path, encoding='utf-8') as fh:
                data = json.load(fh)
            for f in fields(settings):
                _update(getattr(settings, f.name), data.get(f.name, {}))
        except Exception:
            log.exception('Could not read %s, using defaults', path)
        return settings


def _update(obj, data):
    """Copy known keys from a dict into a settings dataclass, keeping types."""
    for f in fields(obj):
        if f.name not in data:
            continue
        current, value = getattr(obj, f.name), data[f.name]
        if f.name == 'modes':
            modes = default_modes()
            for key, mode in value.items():
                known = {k: v for k, v in mode.items() if k in FieldMode.__dataclass_fields__}
                modes[key] = FieldMode(**{**asdict(modes.get(key, FieldMode())), **known})
            value = modes
        elif isinstance(current, bool):
            value = bool(value)
        elif isinstance(current, int):
            value = int(value)
        elif isinstance(current, float):
            value = float(value)
        elif isinstance(current, list):
            value = list(value)
        setattr(obj, f.name, value)
