import sounddevice as sd
import numpy as np


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

