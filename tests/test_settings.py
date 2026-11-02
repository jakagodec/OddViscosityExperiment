import json

from odd_viscosity_experiment.settings import AppSettings


def test_save_and_load_roundtrip(tmp_path):
    path = str(tmp_path / 'settings.json')
    s = AppSettings()
    s.run.freq = 160.0
    s.motor.steps_per_turn = 800
    s.magnet.modes['cw'].phase_y = 270.0
    s.save(path)

    loaded = AppSettings.load(path)
    assert loaded.run.freq == 160.0
    assert loaded.motor.steps_per_turn == 800
    assert loaded.magnet.modes['cw'].phase_y == 270.0


def test_old_or_partial_files_keep_defaults(tmp_path):
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps({'run': {'cycles': 7, 'unknown_option': 1},
                                'magnet': {'modes': {'cw': {'bank_x': 0}}}}))
    loaded = AppSettings.load(str(path))
    assert loaded.run.cycles == 7
    assert set(loaded.magnet.modes) == {'cw', 'ccw', 'none', 'none_x'}
