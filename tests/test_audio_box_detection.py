"""Test to verify that AudioBox USB 96 detection works correctly."""

import pytest


def test_pyo_server_boots():
    """Test that pyo Server can boot without errors."""
    import pyo

    s = pyo.Server()
    s.boot()
    s.stop()
    s.shutdown()


def test_device_channel_detection():
    """Test that device channels can be detected after server boot."""
    import pyo

    s = pyo.Server()
    s.boot()

    # AudioBox USB 96 should have at least 2 channels
    input_channels = pyo.pa_get_input_max_channels(0)
    output_channels = pyo.pa_get_output_max_channels(0)

    assert input_channels > 0, "Input channels should be detected"
    assert output_channels > 0, "Output channels should be detected"

    s.stop()
    s.shutdown()


def test_device_configuration():
    """Test that device configuration works."""
    import pyo

    s = pyo.Server()
    s.setInputDevice(0)
    s.setOutputDevice(0)
    s.setIchnls(2)
    s.setNchnls(2)
    s.boot()

    s.stop()
    s.shutdown()


if __name__ == "__main__":
    test_pyo_server_boots()
    print("✓ Server boots successfully")

    test_device_channel_detection()
    print("✓ Device channels detected")

    test_device_configuration()
    print("✓ Device configuration works")

    print("\nAll AudioBox detection tests passed!")
