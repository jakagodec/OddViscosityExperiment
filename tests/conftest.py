import pytest

from odd_viscosity_experiment.settings import AppSettings


@pytest.fixture
def sim_settings(tmp_path):
    """All devices simulated, fast timings, output in a temporary folder."""
    s = AppSettings()
    s.magnet.simulate = s.motor.simulate = s.camera.simulate = True
    rs = s.run_settings
    rs.output_root = str(tmp_path / 'out')
    rs.start_delay_s = rs.bubble_wait_s = rs.magnet_wait_s = 0.0
    rs.bust_time_s = 0.05
    s.run.measure_time = 0.3
    s.run.settle_time = 0.05
    return s
