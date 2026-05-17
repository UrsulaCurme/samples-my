# Copyright 2020 Huawei Technologies Co., Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
ascend_mic – Ascend 200 DK microphone library with a sounddevice-compatible
interface.

Typical usage
-------------
::

    import ascend_mic as sd

    sample_rate = 16000
    with sd.InputStream(channels=1, dtype="float32", samplerate=sample_rate) as s:
        while True:
            data, overflowed = s.read(1024)  # data: ndarray (1024, 1), float32
            if overflowed:
                print("Warning: audio overflow")
            process(data)

The module intentionally mirrors the ``sounddevice.InputStream`` API so that
code originally written for ``sounddevice`` can be adapted to run on the
Ascend 200 DK hardware with minimal changes.
"""

import numpy as np

from ._ascend_mic_ext import (  # noqa: F401  (re-export for advanced users)
    MicDevice,
    MIC_AUDIO_SAMPLE_RATE_8000,
    MIC_AUDIO_SAMPLE_RATE_11025,
    MIC_AUDIO_SAMPLE_RATE_12000,
    MIC_AUDIO_SAMPLE_RATE_16000,
    MIC_AUDIO_SAMPLE_RATE_22050,
    MIC_AUDIO_SAMPLE_RATE_24000,
    MIC_AUDIO_SAMPLE_RATE_32000,
    MIC_AUDIO_SAMPLE_RATE_44100,
    MIC_AUDIO_SAMPLE_RATE_48000,
    MIC_AUDIO_SAMPLE_RATE_64000,
    MIC_AUDIO_SAMPLE_RATE_96000,
    MIC_SAMPLE_NUM_80,
    MIC_SAMPLE_NUM_160,
    MIC_SAMPLE_NUM_240,
    MIC_SAMPLE_NUM_320,
    MIC_SAMPLE_NUM_480,
    MIC_SAMPLE_NUM_1024,
    MIC_SAMPLE_NUM_2048,
    MIC_CAP_ACTIVE,
    MIC_CAP_PASSIVE,
    MIC_AUDIO_BIT_WIDTH_16,
    MIC_AUDIO_BIT_WIDTH_24,
    MIC_AUDIO_SOUND_MODE_MONO,
    MIC_AUDIO_SOUND_MODE_STEREO,
    MIC_STATUS_OPEN,
    MIC_STATUS_CLOSED,
    MIC_NOT_EXISTS,
)

__all__ = ["InputStream"]

# ---------------------------------------------------------------------------
# Mapping tables
# ---------------------------------------------------------------------------

# Supported sample rates: Python int → API constant
_SAMPLE_RATE_MAP: dict = {
    8000:  MIC_AUDIO_SAMPLE_RATE_8000,
    11025: MIC_AUDIO_SAMPLE_RATE_11025,
    12000: MIC_AUDIO_SAMPLE_RATE_12000,
    16000: MIC_AUDIO_SAMPLE_RATE_16000,
    22050: MIC_AUDIO_SAMPLE_RATE_22050,
    24000: MIC_AUDIO_SAMPLE_RATE_24000,
    32000: MIC_AUDIO_SAMPLE_RATE_32000,
    44100: MIC_AUDIO_SAMPLE_RATE_44100,
    48000: MIC_AUDIO_SAMPLE_RATE_48000,
    64000: MIC_AUDIO_SAMPLE_RATE_64000,
    96000: MIC_AUDIO_SAMPLE_RATE_96000,
}

# Supported frame sizes (samples per frame per channel): int → API constant
_FRAME_SIZE_MAP: dict = {
    80:   MIC_SAMPLE_NUM_80,
    160:  MIC_SAMPLE_NUM_160,
    240:  MIC_SAMPLE_NUM_240,
    320:  MIC_SAMPLE_NUM_320,
    480:  MIC_SAMPLE_NUM_480,
    1024: MIC_SAMPLE_NUM_1024,
    2048: MIC_SAMPLE_NUM_2048,
}

# dtype string → (numpy output dtype, bytes per PCM input sample)
# The hardware always captures 16-bit PCM, so all entries share 2 bytes per
# input sample regardless of the Python-side output dtype.
_DTYPE_INFO: dict = {
    "float32": (np.float32, 2),
    "float64": (np.float64, 2),
    "int16":   (np.int16,   2),
    "int32":   (np.int32,   2),
}


def _nearest_frame_size(blocksize: int) -> int:
    """Return the closest supported MIC frame size for the requested blocksize."""
    sizes = sorted(_FRAME_SIZE_MAP.keys())
    return min(sizes, key=lambda s: abs(s - blocksize))


def _pcm16_to_dtype(raw: np.ndarray, dtype: str) -> np.ndarray:
    """Convert a int16 PCM array to the requested output dtype."""
    if dtype == "int16":
        return raw
    if dtype == "float32":
        return (raw.astype(np.float32) / 32768.0)
    if dtype == "float64":
        return (raw.astype(np.float64) / 32768.0)
    if dtype == "int32":
        return raw.astype(np.int32) * 65536  # scale int16 → int32 range
    raise ValueError(f"Unsupported dtype: {dtype!r}")


# ---------------------------------------------------------------------------
# InputStream
# ---------------------------------------------------------------------------

class InputStream:
    """Ascend 200 DK microphone input stream.

    Compatible with the ``sounddevice.InputStream`` context-manager interface:

    .. code-block:: python

        import ascend_mic as sd

        sample_rate = 16000
        with sd.InputStream(channels=1, dtype="float32", samplerate=sample_rate) as s:
            data, overflowed = s.read(1024)

    Parameters
    ----------
    channels : int, optional
        Number of input channels. ``1`` for mono, ``2`` for stereo.
        Default: ``1``.
    dtype : str, optional
        NumPy dtype for the returned audio data.  Supported values:
        ``"float32"`` (default), ``"float64"``, ``"int16"``, ``"int32"``.
        Raw PCM data is always captured at 16-bit depth and converted.
    samplerate : int, optional
        Sampling rate in Hz.  Must be one of: 8000, 11025, 12000, 16000,
        22050, 24000, 32000, 44100, 48000, 64000, 96000.
        Default: ``16000``.
    blocksize : int, optional
        Number of samples per frame per channel used when configuring the
        hardware.  Must be one of: 80, 160, 240, 320, 480, 1024, 2048.
        If the value is not in the supported set the closest one is selected
        automatically.  Default: ``1024``.

    Notes
    -----
    * The ``read()`` method requests *exactly* ``frames`` samples from the
      hardware.  If the hardware returns fewer samples the remaining entries
      are zero-padded and ``overflowed`` is set to ``True``.
    * The underlying hardware always captures 16-bit PCM.  The ``bit_width``
      is therefore fixed at ``MIC_AUDIO_BIT_WIDTH_16``; the ``dtype``
      parameter only controls the Python-side representation.
    * Capture mode is set to ``MIC_CAP_ACTIVE``.  For callback-based passive
      capture use ``MicDevice`` directly.
    """

    _SUPPORTED_DTYPES = frozenset(_DTYPE_INFO.keys())

    def __init__(
        self,
        channels: int = 1,
        dtype: str = "float32",
        samplerate: int = 16000,
        blocksize: int = 1024,
    ):
        if channels not in (1, 2):
            raise ValueError(f"channels must be 1 or 2, got {channels!r}")
        if dtype not in self._SUPPORTED_DTYPES:
            raise ValueError(
                f"dtype must be one of {sorted(self._SUPPORTED_DTYPES)}, got {dtype!r}"
            )
        if samplerate not in _SAMPLE_RATE_MAP:
            raise ValueError(
                f"samplerate must be one of {sorted(_SAMPLE_RATE_MAP.keys())}, "
                f"got {samplerate!r}"
            )

        actual_blocksize = _nearest_frame_size(blocksize)
        if actual_blocksize != blocksize:
            import warnings
            warnings.warn(
                f"blocksize {blocksize} is not supported; using {actual_blocksize} instead.",
                stacklevel=2,
            )

        self._channels    = channels
        self._dtype       = dtype
        self._samplerate  = samplerate
        self._blocksize   = actual_blocksize
        self._np_dtype, self._bytes_per_sample = _DTYPE_INFO[dtype]

        self._mic: MicDevice | None = None
        self._active = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Open and configure the microphone, begin streaming."""
        if self._active:
            return

        mic = MicDevice()
        mic.open()

        sound_mode = (
            MIC_AUDIO_SOUND_MODE_MONO
            if self._channels == 1
            else MIC_AUDIO_SOUND_MODE_STEREO
        )
        mic.set_property(
            sample_rate=_SAMPLE_RATE_MAP[self._samplerate],
            frame_sample_rate=_FRAME_SIZE_MAP[self._blocksize],
            cap_mode=MIC_CAP_ACTIVE,
            bit_width=MIC_AUDIO_BIT_WIDTH_16,
            sound_mode=sound_mode,
        )
        self._mic = mic
        self._active = True

    def stop(self) -> None:
        """Stop streaming and close the microphone."""
        if not self._active:
            return
        if self._mic is not None:
            self._mic.close()
            self._mic = None
        self._active = False

    # ------------------------------------------------------------------
    # Context-manager protocol
    # ------------------------------------------------------------------

    def __enter__(self) -> "InputStream":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False

    # ------------------------------------------------------------------
    # Audio I/O
    # ------------------------------------------------------------------

    def read(self, frames: int):
        """Read audio frames from the microphone.

        Parameters
        ----------
        frames : int
            Number of audio frames to read.

        Returns
        -------
        data : numpy.ndarray, shape ``(frames, channels)``
            Audio samples in the dtype specified at construction time.
            Values for ``"float32"``/``"float64"`` are in the range
            ``[-1.0, 1.0]``.
        overflowed : bool
            ``True`` if the hardware returned fewer samples than requested
            (the missing samples are zero-padded) or if the driver signalled
            an overflow condition.

        Raises
        ------
        RuntimeError
            If the stream is not active.
        ValueError
            If *frames* is not a positive integer.
        """
        if not self._active or self._mic is None:
            raise RuntimeError(
                "Stream is not active. "
                "Use as a context manager or call start() first."
            )
        if frames <= 0:
            raise ValueError(f"frames must be a positive integer, got {frames!r}")

        num_bytes = frames * self._channels * self._bytes_per_sample
        raw_bytes, overflowed = self._mic.read_sound(num_bytes)

        # Decode raw bytes as int16 PCM
        pcm = np.frombuffer(raw_bytes, dtype=np.int16)

        # Handle short reads (zero-pad)
        expected_samples = frames * self._channels
        if len(pcm) < expected_samples:
            padded = np.zeros(expected_samples, dtype=np.int16)
            padded[: len(pcm)] = pcm
            pcm = padded
            overflowed = True
        elif len(pcm) > expected_samples:
            pcm = pcm[:expected_samples]

        # Reshape to (frames, channels)
        pcm = pcm.reshape(frames, self._channels)

        # Convert to the requested output dtype
        data = _pcm16_to_dtype(pcm, self._dtype)
        return data, bool(overflowed)

    # ------------------------------------------------------------------
    # Properties (read-only, mirrors sounddevice.InputStream)
    # ------------------------------------------------------------------

    @property
    def active(self) -> bool:
        """True if the stream is currently active."""
        return self._active

    @property
    def closed(self) -> bool:
        """True if the stream is closed (not active)."""
        return not self._active

    @property
    def channels(self) -> int:
        """Number of input channels."""
        return self._channels

    @property
    def dtype(self) -> str:
        """NumPy dtype string for the returned audio data."""
        return self._dtype

    @property
    def samplerate(self) -> int:
        """Sample rate in Hz."""
        return self._samplerate

    @property
    def blocksize(self) -> int:
        """Hardware frame size (samples per frame per channel)."""
        return self._blocksize

    def __repr__(self) -> str:
        state = "active" if self._active else "stopped"
        return (
            f"InputStream(channels={self._channels}, dtype={self._dtype!r}, "
            f"samplerate={self._samplerate}, blocksize={self._blocksize}, "
            f"state={state!r})"
        )
