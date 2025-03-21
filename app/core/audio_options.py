# core/audio_options.py
OPTIONS_DEFAULT_VALUES = {
    "muted":True,
    "volume":0.5
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