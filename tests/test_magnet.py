from odd_viscosity_experiment.magnet import Magnet
from odd_viscosity_experiment.settings import MagnetSettings


def commands(mode, freq=120, amp=0.6, **settings):
    magnet = Magnet(MagnetSettings(simulate=True, **settings))
    sent = []
    magnet.query = lambda command: sent.append(command) or 'ok'
    if mode == 'off':
        magnet.disable()
    else:
        magnet.set_field(mode, freq, amp)
    return sent


def test_cw_matches_old_set_magnet():
    assert commands('cw') == [
        'waveform 0', 'set_bank 0 0', 'scale 0 0.3', 'setfreq 0 120', 'setphase 0 0', 'disable 1',
        'waveform 4', 'set_bank 4 0', 'scale 4 0.3', 'setfreq 4 120', 'setphase 4 90', 'disable 5',
        'synchronize']


def test_alternating_mode_uses_banks_half_frequency_double_amplitude():
    sent = commands('none')
    assert 'set_bank 0 1' in sent and 'set_bank 4 2' in sent
    assert 'setfreq 0 60' in sent and 'scale 0 0.6' in sent


def test_secondary_channels_get_phase_shift():
    sent = commands('ccw', drive_secondary=True)
    assert 'setphase 1 270' in sent and 'setphase 5 180' in sent
    assert 'disable 1' not in sent


def test_disable_all_channels():
    assert commands('off') == ['disable 0', 'disable 1', 'disable 4', 'disable 5', 'synchronize']
