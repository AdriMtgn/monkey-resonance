import pyo
from audio_stream import AudioStream  # Assuming your AudioStream class is in audio_stream.py

# Start the server
s = pyo.Server().boot()
s.start()

# Create an AudioStream object for the input channel
guitar_stream = AudioStream(input_channel=0)

# Add effects to the chain
# Compression to enhance attack
guitar_stream.add_effect(0, pyo.Compress, thresh=-30, ratio=4, risetime=0.01, falltime=0.05, knee=0.5, mul=1.2)

# Distortion
guitar_stream.add_effect(1, pyo.Disto, drive=0.95, slope=0.8, mul=0.7)

# Highpass to clean up lows
guitar_stream.add_effect(2, pyo.ButHP, freq=120)

# Lowpass with higher cutoff for more brightness
guitar_stream.add_effect(3, pyo.ButLP, freq=7000)

# Optional: gentle high-shelf boost for extra sparkle
guitar_stream.add_effect(4, pyo.Biquad, freq=3000, q=10, type=2, mul=1.5)

# Chorus for width
guitar_stream.add_effect(5, pyo.Chorus, depth=1.5, feedback=0.25, bal=0.5, mul=0.8)

# Start the output
guitar_stream.start()

# Open the GUI for interaction


s.gui(locals())



# Create an AudioStream object for the input channel
guitar_stream = AudioStream(input_channel=0)

# Add effects to the chain
# Distortion (waveshaping)
guitar_stream.add_effect(0, pyo.Disto, drive=0.95, slope=0.8, mul=0.7)

# Highpass to remove mud
guitar_stream.add_effect(1, pyo.ButHP, freq=150)

# Lowpass to mimic guitar speaker roll-off
guitar_stream.add_effect(2, pyo.ButLP, freq=4000)

# Chorus for stereo width and thickness
guitar_stream.add_effect(3, pyo.Chorus, depth=1.5, feedback=0.25, bal=0.5, mul=0.8)

# Start the output
guitar_stream.start()




# Create an AudioStream object for the input channel (chnl=0)
guitar_stream = AudioStream(input_channel=0)  # Increased mul for a stronger input

# Add effects in the desired order
guitar_stream.add_effect(0, pyo.Compress, thresh=-30, ratio=4, risetime=0.01, falltime=0.05, knee=0.5, mul=1.2)
guitar_stream.add_effect(1, pyo.Gate, thresh=-70, risetime=0.001, falltime=0.2, lookahead=5)
guitar_stream.add_effect(2, pyo.Disto, drive=0.95, slope=0.8, mul=1.0)
guitar_stream.add_effect(3, pyo.ButHP, freq=180)
guitar_stream.add_effect(4, pyo.ButLP, freq=6500)
guitar_stream.add_effect(5, pyo.Chorus, depth=1.5, feedback=0.25, bal=0.5, mul=1.5)

guitar_stream.global_volume = 2.0
