# %% [markdown]
# Connected to venv (Python 3.12.3)

# %%
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import sounddevice as sd
import os

# %%
devices = sd.query_devices()

# %%
devices = sd.query_devices()

# %% [markdown]
# Connected to venv (Python 3.12.3)

# %%
import sounddevice as sd

# %%
devices = sd.query_devices()

# %%
devices 

# %%
from pipewire_python import link

inputs = link.list_inputs()
outputs = link.list_outputs()

# %%
# Midi channel is normally listed first, so this avoids that.
source = outputs[-1]
sink = inputs[-1]

# %%
source.connect(sink)

# %%
sd.qu

# %%
sd.query_devices()

# %%
input

# %%
inputs

# %%
from pipewire_python import link

inputs = link.list_inputs()
outputs = link.list_outputs()

# %%
import sounddevice as sd

devices_infos = sd.query_devices()

[devc for devc in devices_infos]

# %%
import sounddevice as sd
import numpy as np

def callback(indata, frames, time, status):
    if status:
        print(status)
    
    volume_norm = np.linalg.norm(indata) * 10
    if volume_norm > 0.5:  # Adjust this threshold as needed
        print(f"Sound detected! Volume: {volume_norm:.2f}")

try:
    with sd.InputStream(callback=callback, blocksize=1024, samplerate=44100, channels=1):
        print("Stream is open. Press Ctrl+C to stop.")
        while True:
            sd.sleep(1000)
except KeyboardInterrupt:
    print("\nStream closed.")



# %%
def callback(indata, frames, time, status):
    if status:
        print(status)
    
    volume_norm = np.linalg.norm(indata) * 10
    if volume_norm > 0.5:  # Adjust this threshold as needed
        print(f"{time} Sound detected! Volume: {volume_norm:.2f}")
        print(indata)


try:
    with sd.InputStream(callback=callback, blocksize=1024, samplerate=44100, channels=1):
        print("Stream is open. Press Ctrl+C to stop.")
        while True:
            sd.sleep(1000)
except KeyboardInterrupt:
    print("\nStream closed.")

# %%
import sounddevice as sd
import numpy as np

def print_devices():
    print("\nAvailable devices:")
    print(sd.query_devices())

def select_device(io_type):
    print_devices()
    while True:
        try:
            device = int(input(f"Select {io_type} device number: "))
            sd.query_devices(device)
            return device
        except (ValueError, sd.PortAudioError):
            print("Invalid device. Please try again.")

def callback(indata, outdata, frames, time, status):
    if status:
        print(status)
    outdata[:] = indata
    volume_norm = np.linalg.norm(indata) * 10
    if volume_norm > 0.5:
        print(f"Sound level: {volume_norm:.2f}")

# Select input and output devices
input_device = select_device("input")
output_device = select_device("output")

# Set up stream parameters
samplerate = 44100
blocksize = 1024
channels = 1

try:
    with sd.Stream(callback=callback, 
                   samplerate=samplerate, 
                   blocksize=blocksize, 
                   channels=channels, 
                   dtype='float32',
                   device=(input_device, output_device)):
        
        print("\nStream is open. Press Ctrl+C to stop.")
        
        while True:
            sd.sleep(1000)
            print(f"\nInput device: {sd.query_devices(input_device)['name']}")
            print(f"Output device: {sd.query_devices(output_device)['name']}")
            print(f"Sample rate: {samplerate} Hz")
            print(f"Channels: {channels}")

except KeyboardInterrupt:
    print("\nStream closed.")



# %%
sd.default

# %%
sd.default.device

# %%
sd.default.channels

# %%
import sounddevice as sd
import numpy as np

def print_devices():
    print("\nAvailable devices:")
    print(sd.query_devices())

def select_device(io_type):
    print_devices()
    while True:
        try:
            device = int(input(f"Select {io_type} device number: "))
            sd.query_devices(device)
            return device
        except (ValueError, sd.PortAudioError):
            print("Invalid device. Please try again.")

def callback(indata, outdata, frames, time, status):
    if status:
        print(status)
    outdata[:] = indata
    volume_norm = np.linalg.norm(indata) * 100



# Set up stream parameters
samplerate = 44100
blocksize = 1024
channels = 1

try:
    with sd.Stream(callback=callback, 
                   samplerate=samplerate, 
                   blocksize=blocksize, 
                   channels=channels, 
                   dtype='float32',
                   device=(input_device, output_device)):
        
        print("\nStream is open. Press Ctrl+C to stop.")
        
        while True:
            sd.sleep(1000)
            print(f"\nInput device: {sd.query_devices(input_device)['name']}")
            print(f"Output device: {sd.query_devices(output_device)['name']}")
            print(f"Sample rate: {samplerate} Hz")
            print(f"Channels: {channels}")

except KeyboardInterrupt:
    print("\nStream closed.")



# %%
import sounddevice as sd
import numpy as np

def callback(indata, frames, time, status):
    if status:
        print(status)
    recording.extend(indata[:, 0])

recording = []
samplerate = 44100

print("Recording... Press Ctrl+C to stop.")
try:
    with sd.InputStream(callback=callback, channels=1, samplerate=samplerate):
        sd.sleep(1000000)  # Record indefinitely until interrupted
except KeyboardInterrupt:
    print("\nRecording stopped.")

# Convert recording to numpy array
recording = np.array(recording)



# %%
print("Playing recorded audio...")
sd.play(recording, samplerate)
sd.wait()  # Wait until playback is finished



# %%
print("Playing recorded audio...")

sd.play(recording, samplerate)


sd.wait()  # Wait until playback is finished



# %%
# Callback function to handle both input and output
def callback(indata, outdata, frames, time, status):
    if status:
        print(status)
    
    # Copy input data to output buffer
    outdata[:] = indata

    # Calculate and print volume (optional)
    volume_norm = np.linalg.norm(indata) * 10
    if volume_norm > 0.5:  # Adjust threshold as needed
        print(f"Sound level: {volume_norm:.2f}")

# Set up stream parameters
samplerate = 44100
blocksize = 1024
channels = 1

try:
    with sd.Stream(callback=callback, 
                   samplerate=samplerate, 
                   blocksize=blocksize, 
                   channels=channels, 
                   dtype='float32'):
        
        print("Stream is open. Press Ctrl+C to stop.")
        
        while True:
            sd.sleep(1000)
            
            # Print stream info (optional)
            print(f"\nSample rate: {sd.default.samplerate} Hz")
            print(f"Channels: {sd.default.channels}")
            print(f"Device: {sd.default.device}")

except KeyboardInterrupt:
    print("\nStream closed.")

# %%
sd.default.latency

# %%
recor

# %%
recording   

# %%
recording.sha   

# %%
recording.shape      

# %%
print("Number of dimensions:", recording.ndim)
print("Total number of elements:", recording.size)
print("Shape of the array:", recording.shape)



# %% [markdown]
# No kernel connected


