# Hardware, protocols and file format

Reference for the devices the software talks to. Values marked *(setting)* can
be changed in the GUI.

## Magnetic tweezers

- 4 coils, two per in-plane axis, wired in series per axis. Driven by the
  *pinceta* program on a Linux PC (version **7a** or newer for `set_bank`).
  Start it, then *settings → server → magtweez server*, and load **sine into
  bank 0** (*settings → memory*).
- TCP, port 2222 *(setting)*. The PC's IP can change – `hostname -I` on it.
- One TCP connection per command, command terminated by `\r\n`, one reply line.
  Nothing changes on the coils until `synchronize`.

| Command | Meaning |
|---|---|
| `test` | connection test |
| `waveform <ch>` / `setdc <ch>` | waveform / DC mode |
| `set_bank <ch> <bank>` | waveform memory bank to play |
| `scale <ch> <value>` | amplitude (the GUI sends amp / *amplitude divisor*, default 2) |
| `setfreq <ch> <Hz>` | frequency |
| `setphase <ch> <deg>` | phase |
| `setoffset <ch> <A>`, `dc_value <ch> <A>` | offset, DC value |
| `disable <ch>` | channel off |
| `synchronize` | apply pending settings |
| `reset` | reset phases |

- Channels *(setting)*: x = (0, 1), y = (4, 5). As the coils are in series only
  the primary channel is driven and the secondary disabled (option to drive both,
  secondary phase-shifted by 180°).
- Orientation (calibration 27.5.2026): **ch0 = x = horizontal**, **ch4 = y =
  vertical**. Positive current gives B along the arrows on the coils (vertical:
  up; horizontal: away from the motor = left on the camera). Phase 90° = cosine.
  Consequently the mode called `cw` (phases x 0°, y 90°) turns
  **counter-clockwise as seen on the camera**, and `ccw` clockwise. The names are
  kept for continuity with existing data.
- Waveform banks: 0 = sine; 1 = sine that reverses sign after one period
  (`waveforms/CW_CCW/ch0.dat`); 2 = cosine over two periods (`ch2.dat`). Bank 1
  on x and bank 2 on y gives one turn each way starting vertical – the `none`
  mode. The waveform spans two periods, hence f/2 and 2·amp.

| Mode | bank x / y | phase x / y | freq | amp |
|---|---|---|---|---|
| `cw` | 0 / 0 | 0 / 90 | f | a |
| `ccw` | 0 / 0 | 90 / 0 | f | a |
| `none` | 1 / 2 | 0 / 0 | f/2 | 2a |
| `none_x` | 2 / 1 | 0 / 0 | f/2 | 2a |

- Field calibration (Hall probe): ≈ 1.7 mT per amplitude unit (30.6.2025), ≈ 300 µT
  at 100 mA DC. Background ≈ 60 µT; the stepper motor's magnet makes the field
  slightly inhomogeneous. Amplitudes ≳ 0.8 drive convection vortices in the
  capillary. A 1 Hz CW/CCW field for a few seconds ("bust") breaks up platelet
  aggregates.

## Capillary rotator

- Arduino + NEMA stepper (12 V), serial 115200 baud *(setting)*.
- `GX <steps>\n` moves to an **absolute** position. The position resets to 0 when
  the serial port is opened (the Arduino reboots), so 0 = orientation at connect.
- Steps per turn *(setting)*: 400 in the original scripts, 800 according to older
  notes – check with one *Flip* (should be exactly half a turn).

## Camera

- Point Grey / FLIR Grasshopper, 1920 × 1200, Mono8, via PySpin. The GUI sets
  exposure, gain and frame rate (auto modes off) and reads the device timestamp
  of every frame. Frame-rate node names differ between models
  (`AcquisitionFrameRateEnable` vs `AcquisitionFrameRateEnabled` +
  `AcquisitionFrameRateAuto`); both are tried.
- Pixel size ≈ 0.456 µm/px (from bead size) *(setting)*. Camera tilt ≈ 2.88°
  counter-clockwise (measured with a thread, 4.5.2026) *(setting)*.
- Particle tracking needed ≥ 15 Hz.

## `.twv` video format

Little-endian, packed, written by `twv.TwvWriter`, identical in layout to the files
of the FlyCapture2-based tool.

Video header, 58 bytes:

| Field | Type | Value |
|---|---|---|
| VideoID | u16 | 0x1A57 |
| VideoVersion | u16 | 20 |
| VideoLicence | u16 | 0 |
| VideoHeaderSize | u32 | 58 |
| RecordedFrames | u32 | number of frames |
| FrameHeaderSize | u16 | 60 |
| FrameDataIncl | u16 | 0 |
| ROI left, top, width, height | 4 × u16 | 0, 0, W, H |
| BytesPerPixel | u16 | 1 |
| FrameRate, Exposure [ms], Gain [dB] | 3 × f64 | camera settings (0 in old files) |
| RecTrapDataNo | u16 | 0 |
| ImageToSampleScale | f32 | µm/px (1.0 in old files) |

Then for every frame a 60-byte header – FrameNumber (u32), FrameTime [s] (f32,
relative to the first frame), LaserPower (f32), 4 × (x, y, intensity) f32 – followed
by W × H uint8 pixels.

## File naming

Analysis tools classify recordings by their names:

```
<prefix>cycle=<n>_field=<cw|ccw|none>[_start=<x|y>].twv
<prefix>cycle=<n>_cntrl.twv
<prefix>_control-<before|after>-<n>_field=cntrl.twv
```
