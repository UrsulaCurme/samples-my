# ascend_mic — Ascend 200 DK Microphone Python Library

`ascend_mic` wraps the Ascend 200 DK peripheral microphone C API
(`peripheral_api.h` / `libmedia_mini`) and exposes it through a
**sounddevice-compatible** `InputStream` interface so that audio-processing
code written for `sounddevice` can be adapted with minimal changes.

## Quick start

```python
import ascend_mic as sd

sample_rate = 16000

with sd.InputStream(channels=1, dtype="float32", samplerate=sample_rate) as s:
    while True:
        data, overflowed = s.read(1024)   # data: ndarray (1024, 1) float32
        if overflowed:
            print("Warning: audio overflow")
        process(data)
```

## Requirements

| Component | Version |
|-----------|---------|
| Python    | ≥ 3.6   |
| numpy     | ≥ 1.16  |
| pybind11  | ≥ 2.6   |
| Ascend 200 DK toolkit (`media_mini`, `ascend_hal`, …) | as installed |

## Build and install

### Option A – pip (recommended)

```bash
export INSTALL_DIR=/usr/local/Ascend/ascend-toolkit/latest
pip install -r requirements.txt
pip install .
```

### Option B – CMake

```bash
export INSTALL_DIR=/usr/local/Ascend/ascend-toolkit/latest
export THIRDPART_PATH=/home/HwHiAiUser/HIAI_PROJECTS/ascend_lib

mkdir build && cd build
cmake ..
make -j4
# optionally install the package in editable mode:
make pip_install
```

After the build the shared library `_ascend_mic_ext.<cpython>.so` is placed
inside `src/ascend_mic/` so the package can be imported from the source tree
without an install step.

## API reference

### `InputStream`

```python
class InputStream:
    def __init__(
        self,
        channels:   int = 1,        # 1 = mono, 2 = stereo
        dtype:      str = "float32",# "float32", "float64", "int16", "int32"
        samplerate: int = 16000,    # Hz – must be a supported rate (see below)
        blocksize:  int = 1024,     # samples/frame/channel – must be supported
    ): ...

    # Context-manager protocol
    def __enter__(self) -> "InputStream": ...
    def __exit__(self, *args): ...

    # Explicit lifecycle
    def start(self) -> None: ...
    def stop(self)  -> None: ...

    # Audio I/O
    def read(self, frames: int) -> tuple[np.ndarray, bool]:
        """Return (data, overflowed).

        data        – ndarray of shape (frames, channels) in the requested dtype.
                      float32/float64 values are in [-1.0, 1.0].
        overflowed  – True if data was lost or the read was short.
        """

    # Read-only properties
    @property def active(self) -> bool: ...
    @property def closed(self) -> bool: ...
    @property def channels(self) -> int: ...
    @property def dtype(self) -> str: ...
    @property def samplerate(self) -> int: ...
    @property def blocksize(self) -> int: ...
```

### Supported sample rates (Hz)

8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000, 64000, 96000

### Supported frame sizes (blocksize, samples/frame/channel)

80, 160, 240, 320, 480, 1024, 2048

> If *blocksize* is not in the supported set, the closest value is selected
> automatically and a `UserWarning` is emitted.

### `MicDevice` (low-level)

For advanced use (e.g. passive/callback-based capture) import `MicDevice`
directly:

```python
from ascend_mic import MicDevice, MIC_CAP_PASSIVE, MIC_AUDIO_SAMPLE_RATE_16000, \
    MIC_SAMPLE_NUM_1024, MIC_AUDIO_BIT_WIDTH_16, MIC_AUDIO_SOUND_MODE_MONO

def my_callback(data, overflowed):
    ...  # process each frame as it arrives

mic = MicDevice()
mic.open()
mic.set_property(
    sample_rate=MIC_AUDIO_SAMPLE_RATE_16000,
    frame_sample_rate=MIC_SAMPLE_NUM_1024,
    cap_mode=MIC_CAP_PASSIVE,
    bit_width=MIC_AUDIO_BIT_WIDTH_16,
    sound_mode=MIC_AUDIO_SOUND_MODE_MONO,
)
mic.start_capture()      # registers internal C callback

try:
    while True:
        raw_bytes, overflowed = mic.read_passive()  # blocks until next frame
        # ... decode / process raw_bytes
finally:
    mic.close()
```

## File structure

```
python/level1_single_api/5_200dk_peripheral/mic/
├── src/
│   ├── _ascend_mic_ext.cpp        # pybind11 C++ extension source
│   └── ascend_mic/
│       └── __init__.py            # sounddevice-like Python API
├── CMakeLists.txt                 # CMake build
├── setup.py                       # pip build
├── requirements.txt
└── README.md                      # this file
```

## Relationship to the C++ sample

This library wraps the same underlying C functions used by the C++ sample at
`cplusplus/level1_single_api/5_200dk_peripheral/mic/`:

| C++ API function   | Python equivalent                  |
|--------------------|------------------------------------|
| `MediaLibInit()`   | called in `MicDevice.__init__()`   |
| `OpenMIC()`        | `MicDevice.open()`                 |
| `CloseMIC()`       | `MicDevice.close()`                |
| `SetMICProperty()` | `MicDevice.set_property()`         |
| `GetMICProperty()` | `MicDevice.get_property()`         |
| `ReadMicSound()`   | `MicDevice.read_sound()` (active)  |
| `CapMIC()`         | `MicDevice.start_capture()` (passive) |
| `QueryMICStatus()` | `MicDevice.query_status()`         |
