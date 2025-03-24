import sounddevice as sd
import numpy as np

import logging
import json
from datetime import datetime
import copy


threshold_db = -40
threshold_rms = 10 ** (threshold_db / 20)


def file_logger(path):
    logger = logging.getLogger(path)  # Use path as a unique name
    logger.setLevel(logging.DEBUG)
    logger.handlers = []  # Clear any existing handlers

    file_handler = logging.FileHandler(path, mode="w")
    file_handler.setLevel(logging.DEBUG)

    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    file_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.propagate = False  # Prevent propagation to root logger

    return logger


logger_data = file_logger("/root/log_datas.log")
logger_settings = file_logger("/root/log_settings.log")


def audio_callback(indata, outdata, frames, time, status):
    global audio_mix_options
    options_print = json.dumps(audio_mix_options)
    logger_settings.info(options_print)
    time_print = json.dumps(
        {
            "inputBufferAdcTime": time.inputBufferAdcTime,
            "outputBufferDacTime": time.outputBufferDacTime,
            "currentTime": time.currentTime,
        }
    )

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
    logger_data.info(
        (
            f"indata : {indata}",
            f"outdata : {outdata}",
            f"fraMe : {frames}",
            f"tieme : {time_print}",
            f"status: {status}",
        )
    )


devices = sd.query_devices()


def callback(indata, outdata, frames, time, status):
    print(f"indata : {indata}")
    outdata[:] = indata[:]
    print(f"outdata : {outdata}")
    if status:
        print(status)


OPTIONS_DEFAULT_VALUES = {"muted": True, "volume": 0.5}

audio_mix_options = {
    "devices": [
        {
            "index": device.get("index"),
            "name": device.get("name"),
            "channels": [
                {"channel_number": channel + 1, "options": copy.deepcopy(OPTIONS_DEFAULT_VALUES)}
                for channel in range(device.get("max_input_channels", 0))
            ],
        }
        for device in devices
        if device.get("max_input_channels", 0) > 0
    ]
}


""" try:
    with sd.Stream(callback=audio_callback) as stream_test:
        
        print("Stream is open. Press Ctrl+C to stop.")
        
        while True:
            sd.sleep(1000)
            print(stream_test)
            # Print stream info (optional)
            print(f"\nSample rate: {sd.default.samplerate} Hz")
            print(f"Channels: {sd.default.channels}")
            print(f"Device: {sd.default.device}")

except KeyboardInterrupt:
    print("\nStream closed.")
 """


def update_options(device_index: int, channel_number: int, new_options: dict):
    global audio_mix_options
    for device in audio_mix_options["devices"]:
        if device["index"] == device_index:
            for channel in device["channels"]:
                if channel["channel_number"] == channel_number:
                    print(
                        f"Updating options for device {device_index} and channel {channel_number} : new options : {new_options}"
                    )
                    channel["options"].update(new_options)
                    break
            break


test_stream_object = sd.Stream(callback=audio_callback)

test_stream_object.start()
update_options(device_index=0, channel_number=1, new_options={"muted": False})
update_options(device_index=0, channel_number=2, new_options={"volume": 1})
update_options(device_index=0, channel_number=1, new_options={"muted": True})

test_stream_object.stop()
test_stream_object.close()
