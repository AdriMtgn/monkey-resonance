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

s.setInputDevice(0)
s.setOutputDevice(0)
s.setMidiInputDevice(3)
s.setMidiOutputDevice(2)

s.boot()
s.start()


s.getNchnls()
s._nchnls

input1 = pyo.Input(0)
input2 = pyo.Input(1)
input3 = pyo.Input(2)
input4 = pyo.Input(3)


test = input1.out()
