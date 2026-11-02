import numpy as np

from odd_viscosity_experiment.twv import FRAME_HEADER, VIDEO_HEADER, TwvWriter, read_frame, read_header


def test_header_sizes_match_flycapture_files():
    assert VIDEO_HEADER.size == 58
    assert FRAME_HEADER.size == 60


def test_roundtrip(tmp_path):
    path = tmp_path / 'test.twv'
    frames = [np.full((12, 16), i, dtype=np.uint8) for i in range(5)]
    writer = TwvWriter(str(path), 16, 12, frame_rate=15, exposure_ms=20, gain_db=1, um_per_px=0.456)
    for i, frame in enumerate(frames):
        writer.add(frame, 100.0 + i * 0.1)
    stats = writer.close()

    assert stats == {'frames': 5, 'dropped_buffer_full': 0, 'error': None}
    header = read_header(str(path))
    assert header['video_id'] == 0x1A57 and header['frames'] == 5
    assert (header['width'], header['height'], header['bytes_per_pixel']) == (16, 12, 1)
    assert abs(header['um_per_px'] - 0.456) < 1e-6
    assert path.stat().st_size == 58 + 5 * (60 + 16 * 12)
    image, t = read_frame(str(path), 3)
    assert (image == 3).all()
    assert abs(t - 0.3) < 1e-5  # times are relative to the first frame


def test_wrong_frame_shape_is_reported(tmp_path):
    writer = TwvWriter(str(tmp_path / 'bad.twv'), 16, 12)
    writer.add(np.zeros((10, 10), dtype=np.uint8), 0.0)
    stats = writer.close()
    assert stats['frames'] == 0 and stats['error']
