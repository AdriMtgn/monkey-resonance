import pyo

audio_devices = pyo.pa_get_devices_infos()
midi_input_devices = pyo.pm_get_input_devices()
midi_output_devices = pyo.pm_get_output_devices()


num_devices = pyo.pm_count_devices()
input_devices = pyo.pm_get_input_devices()
output_devices = pyo.pm_get_output_devices()

print(f"Number of MIDI devices: {num_devices}")
print("Input devices:", input_devices)
print("Output devices:", output_devices)

s = pyo.Server()

input_audio_device = 0
output_audio_device = 0

pyo.pa_get_input_max_channels(0)

s.setInputDevice(input_audio_device)
s.setOutputDevice(output_audio_device)
s.setMidiInputDevice(3)
s.setMidiOutputDevice(2)

s.setNchnls(2)
s.setIchnls(2)

s.boot()
s.start()


s.getNchnls()
s._nchnls

input1 = pyo.Input(0)
input2 = pyo.Input(1)
input3 = pyo.Input(2)
input4 = pyo.Input(3)


# Auto Pan
def auto_pan(input_stream, freq=0.5, depth=0.5):
    return pyo.Pan(input_stream, pan=pyo.Sine(freq=freq, mul=depth, add=0.5))


# Multiband Dynamics
def multiband_dynamics(input_stream, thresholds=[-20, -20, -20], ratios=[2, 2, 2]):
    return pyo.MultiBand(
        input_stream, num=3, freq=[250, 2500], q=1, thresh=thresholds, ratio=ratios
    )


# Phaser
def phaser(input_stream, freq=1, q=10, feedback=0.5):
    return pyo.Phaser(input_stream, freq=freq, q=q, feedback=feedback)


# Delay with LFO
def delay_with_lfo(input_stream, delay_time=0.5, feedback=0.5, lfo_freq=4):
    lfo = pyo.Sine(freq=lfo_freq, phase=0.5, mul=0.5, add=0.3)
    return pyo.Delay(input_stream, delay=delay_time, feedback=lfo, maxdelay=3)


# Wah-wah effect
def wah_wah(input_stream):
    fol = pyo.Follower(input_stream, freq=30, mul=4000, add=40)
    return pyo.Biquad(input_stream, freq=fol, q=5, type=2)


# Chorus
def chorus(input_stream, depth=1, feedback=0.5, bal=0.5):
    return pyo.Chorus(input_stream, depth=depth, feedback=feedback, bal=bal)


effect_chain = [pyo.Chorus, pyo.Phaser, pyo.Delay, pyo.Pan]


def create_stream(input_channel, effects):
    stream = pyo.Input(input_channel)
    for effect in effect_chain:
        stream = effect(stream)
    return stream


stream = create_stream(0, effect_chain)

rms_input = pyo.RMS(stream)

stream2 = create_stream(0, effect_chain)

# Example usage:
# effect = auto_pan(input_multi)
# effect = multiband_dynamics(input_multi)
# effect = phaser(input_multi)
# effect = delay_with_lfo(input_multi)
# effect = wah_wah(input_multi)
# effect = chorus(input_multi)

# Create a recorder object
rec = pyo.Record(input1, filename="recorded_audio.wav", chnls=2)

# Start recording
rec.play()


[
    {
        "id": stream.getId(),
        "output": stream.getOutputChannel(),
        "is_out": stream.isOutputting(),
        "is_playing": stream.isPlaying(),
    }
    for stream in s.getStreams()
]

[stream.getStreamObject().stop() for stream in s.getStreams()]

test_stream_object = s.getStreams()[3].getStreamObject()

dir(test_stream_object)

input1.out()
input1.stop()

rec.stop()

s.stop()

s.shutdown()
