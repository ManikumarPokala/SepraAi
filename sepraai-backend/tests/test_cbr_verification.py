"""
SepraAI v2.7 — CBR & Time Scaler Verification Tests

Tests the time scale duration checks (Patch #6):
- Verifies sample-count / rate duration calculation.
- Verifies that container-reported vs sample duration drift >= 1ms raises a ValueError.
"""

import pytest
from unittest.mock import patch, MagicMock
from orchestration.time_scaler import verify_cbr_audio_sync, get_wav_sample_duration


@pytest.mark.parametrize(
    "container_dur, sample_dur, should_raise",
    [
        (30.000, 30.000, False),  # 0ms drift -> Passes
        (30.0005, 30.000, False), # 0.5ms drift -> Passes
        (30.001, 30.000, True),   # 1.0ms drift -> Raises ValueError
        (30.005, 30.000, True),   # 5.0ms drift -> Raises ValueError
    ]
)
@patch("orchestration.time_scaler.get_wav_sample_duration")
@patch("orchestration.time_scaler.get_container_duration")
def test_cbr_audio_sync_drift(
    container_dur,
    sample_dur,
    should_raise,
    mock_get_container,
    mock_get_sample,
):
    """Asserts that verify_cbr_audio_sync enforces the 1ms drift limit boundary (Patch #6)."""
    mock_get_container.return_value = container_dur
    mock_get_sample.return_value = sample_dur

    filepath = "mock_file.wav"

    if should_raise:
        with pytest.raises(ValueError) as exc_info:
            verify_cbr_audio_sync(filepath)
        assert "VBR Drift Detected" in str(exc_info.value)
    else:
        verified_duration = verify_cbr_audio_sync(filepath)
        assert verified_duration == sample_dur


@patch("wave.open")
def test_wav_sample_duration_success(mock_wave_open):
    """Asserts that WAV duration is accurately determined from decoded frames and sample rate."""
    mock_wav = MagicMock()
    mock_wav.getnframes.return_value = 960000
    mock_wav.getframerate.return_value = 48000
    mock_wav.getsampwidth.return_value = 2  # 16-bit PCM

    mock_wave_open.return_value.__enter__.return_value = mock_wav

    duration = get_wav_sample_duration("clean_cbr.wav")
    # 960000 / 48000 = 20.0 seconds
    assert duration == 20.0


@patch("wave.open")
def test_wav_sample_duration_invalid_rate(mock_wave_open):
    """Asserts that non-48kHz sample rate is immediately rejected."""
    mock_wav = MagicMock()
    mock_wav.getframerate.return_value = 44100
    mock_wav.getsampwidth.return_value = 2

    mock_wave_open.return_value.__enter__.return_value = mock_wav

    with pytest.raises(ValueError) as exc_info:
        get_wav_sample_duration("invalid_rate.wav")
    assert "CBR Sample Rate Mismatch" in str(exc_info.value)
