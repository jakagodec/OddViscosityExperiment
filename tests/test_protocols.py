import glob
import json
import os
import time
from dataclasses import replace

import pytest

from odd_viscosity_experiment.camera import Camera
from odd_viscosity_experiment.magnet import Magnet
from odd_viscosity_experiment.motor import Motor
from odd_viscosity_experiment.protocols import Runner, parse_sequence, required_devices
from odd_viscosity_experiment.twv import read_header


@pytest.fixture
def rig(sim_settings):
    devices = Magnet(sim_settings.magnet), Motor(sim_settings.motor), Camera(sim_settings.camera)
    results = []
    runner = Runner(*devices, on_finished=lambda ok, message: results.append((ok, message)))
    yield sim_settings, devices, runner, results
    devices[2].disconnect()


def connect(devices):
    for device in devices:
        device.connect()


def recordings(settings):
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(settings.run_settings.output_root, '*', '*.twv')))


def test_refuses_to_start_without_devices(rig):
    settings, _devices, runner, _results = rig
    with pytest.raises(RuntimeError, match='Connect first'):
        runner.start(settings)


def test_bad_sequence():
    with pytest.raises(ValueError):
        parse_sequence('cw,sideways')


def test_cycles_names_files_like_the_old_scripts(rig):
    settings, devices, runner, results = rig
    connect(devices)
    settings.run.cycles = 4
    settings.run.sequence = 'cw,ccw,none,cntrl'
    settings.run.prefix = 'k1_'
    runner.start(settings)
    runner.wait()

    assert results == [(True, 'Finished')]
    assert recordings(settings) == ['k1_cycle=1_field=cw.twv', 'k1_cycle=2_field=ccw.twv',
                                    'k1_cycle=3_field=none.twv', 'k1_cycle=4_cntrl.twv']
    sidecar = glob.glob(os.path.join(settings.run_settings.output_root, '*', 'k1_cycle=1_field=cw.json'))[0]
    with open(sidecar) as fh:
        info = json.load(fh)
    assert info['field'] == 'cw' and info['amp'] == settings.run.amp and info['recording']['frames'] > 0
    magnet, motor, _camera = devices
    assert magnet.state == 'off' and motor.position == 0


def test_scan_and_control(rig):
    settings, devices, runner, results = rig
    connect(devices)
    settings.run.protocol = 'scan'
    settings.run.cycles = 1
    settings.run.scan_freqs = '40,80'
    settings.run.scan_amps = '0.6'
    runner.start(settings)
    runner.wait()
    assert results[-1][0]
    assert recordings(settings) == ['control_cycle=1_cntrl.twv', 'freq=40_amp=06_cycle=1_field=cw.twv',
                                    'freq=80_amp=06_cycle=1_field=cw.twv']


def test_flow_controls(rig):
    settings, devices, runner, results = rig
    connect(devices)
    settings.run.protocol = 'flow'
    settings.run.cycles = 1
    settings.run.controls_before = settings.run.controls_after = 1
    settings.run.prefix = 'flow_'
    runner.start(settings)
    runner.wait()
    assert recordings(settings) == ['flow__control-after-0_field=cntrl.twv', 'flow__control-before-0_field=cntrl.twv',
                                    'flow_cycle=1_field=cw.twv']


def test_stop_closes_recording_and_switches_field_off(rig):
    settings, devices, runner, results = rig
    connect(devices)
    settings.run.measure_time = 30
    runner.start(settings)
    time.sleep(1.0)
    runner.stop()
    runner.wait(5)

    magnet, _motor, camera = devices
    assert results == [(False, 'Stopped by user')]
    assert not camera.recording and magnet.state == 'off'
    path = glob.glob(os.path.join(settings.run_settings.output_root, '*', '*.twv'))[0]
    assert read_header(path)['frames'] > 0


@pytest.mark.parametrize('protocol, bust, sequence, needs', [
    ('cycles', False, 'cw,cntrl', {'magnet', 'motor', 'camera'}),
    ('cycles', False, 'cntrl', {'motor', 'camera'}),
    ('control', True, 'cw', {'motor', 'camera'}),
    ('scan', False, 'cntrl', {'magnet', 'motor', 'camera'}),
    ('flow', False, 'cw', {'magnet', 'camera'}),
    ('flow', False, 'cntrl', {'camera'}),
    ('flip', False, 'cw', {'motor'}),
    ('flip', True, 'cw', {'magnet', 'motor'}),
])
def test_required_devices(sim_settings, protocol, bust, sequence, needs):
    p = replace(sim_settings.run, protocol=protocol, bust=bust, sequence=sequence)
    assert required_devices(p) == needs


def test_control_runs_without_magnet(rig):
    settings, devices, runner, results = rig
    magnet, motor, camera = devices
    connect((motor, camera))
    settings.run.protocol = 'control'
    settings.run.cycles = 2
    settings.run.sequence = 'cw,ccw'
    settings.run.bust = True
    settings.run.prefix = 'c_'
    runner.start(settings)
    runner.wait()
    assert results == [(True, 'Finished')]
    assert recordings(settings) == ['c_cycle=1_cntrl.twv', 'c_cycle=2_cntrl.twv']
    assert not magnet.connected and motor.position == 0


def test_flow_runs_without_motor(rig):
    settings, devices, runner, results = rig
    magnet, motor, camera = devices
    connect((magnet, camera))
    settings.run.protocol = 'flow'
    settings.run.cycles = 1
    runner.start(settings)
    runner.wait()
    assert results == [(True, 'Finished')]
    assert not motor.connected and magnet.state == 'off'


def test_flip_runs_without_magnet(rig):
    settings, devices, runner, results = rig
    magnet, motor, _camera = devices
    motor.connect()
    settings.run.protocol = 'flip'
    settings.run.flip_interval = 1
    runner.start(settings)
    time.sleep(1.5)
    runner.stop()
    runner.wait(5)
    assert results == [(False, 'Stopped by user')]
    assert not magnet.connected and motor.position != 0
