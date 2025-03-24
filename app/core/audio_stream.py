import sounddevice as sd
import numpy as np

from .audio_options import audio_mix_options


def audio_callback(indata, outdata, frames, time, status):
    global audio_mix_options
    if status:
        print(status)

    device = audio_mix_options["devices"][0]
    num_channels = min(len(device["channels"]), indata.shape[1])

    processed_channels = []
    for i in range(num_channels):
        channel_options = device["channels"][i]["options"]
        channel_data = indata[:, i]

        if channel_options.get("is_muted", False):
            channel_data[:] = 0
        else:
            volume = channel_options.get("volume", 1.0)
            channel_data *= volume

        processed_channels.append(channel_data)

    mixed_stream = np.mean(processed_channels, axis=0)
    outdata[:] = mixed_stream[:, None]


stream = sd.Stream(callback=audio_callback)


def start_stream():
    stream.start()


def stop_stream():
    stream.stop()
