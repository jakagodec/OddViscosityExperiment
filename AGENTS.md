# Notes for coding agents

Control GUI for a physics experiment (odd viscosity in a chiral nanoplatelet
fluid). It drives real lab hardware: magnetic coils, a stepper motor that
rotates a glass capillary, and a scientific camera. Read `README.md` for usage
and `docs/hardware.md` for the device protocols and the `.twv` format.

## Commands

```bash
uv sync                      # environment (Python 3.10, see .python-version)
uv run pytest                # all tests; simulated devices only, ~10 s
uv run odd-viscosity-gui     # start the GUI (tick "Simulate" for devices without hardware)
uv add <pkg>                 # dependencies only via uv (pyproject.toml + uv.lock)
```

The repository may live on an SMB network drive shared by macOS and Windows.
A `.venv` there fails (permission errors) and clashes between the systems, so
put the environment on local disk:
`UV_PROJECT_ENVIRONMENT=~/Library/Caches/OddViscosityExperiment/venv` (macOS),
`%LOCALAPPDATA%\OddViscosityExperiment\venv` (Windows) – the launchers do this.

## Layout

- `src/odd_viscosity_experiment/` – `settings.py` (dataclasses ↔ JSON), `magnet.py`,
  `motor.py`, `camera.py`, `twv.py`, `protocols.py` are **Qt-free**; keep them that
  way so they can be scripted and tested headless. Qt code lives only in `ui/`.
- `tests/` – pytest; every test must run without hardware (`simulate=True`).

## Conventions

- New options: add a dataclass field with `opt(default, 'Label', 'tooltip', min=…, max=…,
  suffix=…)` in `settings.py`; the settings dialogs are generated from that metadata.
  Fields without a label are hidden. `_update` must keep loading older JSON files.
- Device calls from the GUI go through `MainWindow.bg()` (worker thread); the GUI
  thread must never block on TCP/serial. Device objects report state via attributes
  that `refresh()` polls; logging (`logging.getLogger('magnet'|'motor'|'camera'|'run'|'gui')`)
  is the user-facing log.
- Protocols: every wait goes through `Context.wait()` (abortable), and
  `Context.cleanup()` must always stop the recording and switch the field off.
- Match the existing style: 4 spaces, single quotes, short docstrings, ~120 columns.

## Do not break

- **Recording file names** (`<prefix>cycle=<n>_field=<cw|ccw|none>…`, `_cntrl`,
  `_control-before-<n>_field=cntrl`): the downstream tracking/analysis parses them.
- **`.twv` layout** (58-byte video header, 60-byte frame headers, uint8 pixels) must
  stay readable by the existing Tracker2026 reader; `tests/test_twv.py` guards it.
- **Magnet command sequences**: `tests/test_magnet.py` pins them to what the original
  lab scripts sent. Change only deliberately.
- Field mode names `cw`/`ccw` are historical: `cw` turns counter-clockwise *as seen
  on the camera*. Do not "fix" the names; existing data use them.
- The motor command `GX <steps>` is an absolute position; position 0 = orientation at
  connect.

## Hardware safety

Never leave a field on or a recording open after an error or abort. Do not run
anything against real devices (non-simulated) unless the user asks; coils at
amplitude ≳ 0.8 heat up and stir the sample.

PySpin (FLIR Spinnaker) is not on PyPI and is absent on most machines; camera code
must import it lazily and the rest of the app must work without it.
