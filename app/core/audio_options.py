import sounddevice as sd

devices = sd.query_devices()



OPTIONS_DEFAULT_VALUES = {
    "muted":True,
    "volume":0.5
}

audio_mix_options = {
    "devices": [
        {
            "index": device.get("index"),
            "name": device.get("name"),
            "channels": [
                {
                    "channel_number": channel + 1,
                    "options": OPTIONS_DEFAULT_VALUES
                }
                for channel in range(device.get("max_input_channels", 0))
            ]
        }
        for device in devices if device.get("max_input_channels", 0) > 0
    ]
}

def update_options(device_index: int, channel_number: int, new_options: dict):
    global audio_mix_options
    for device in audio_mix_options["devices"]:
        if device["index"] == device_index:
            for channel in device["channels"]:
                if channel["channel_number"] == channel_number:
                    channel["options"].update(new_options)
                    break
            break