import pyo
import datetime
import atexit
from libs.utils import _check_and_create_app_folders, APP_BASE_FOLDER,APP_FOLDERS,help,os,_cleanup
from libs.audio_stream import AudioStream
import libs.effect_lib as eff

_check_and_create_app_folders(APP_BASE_FOLDER)
audio_devices = pyo.pa_get_devices_infos()

input_audio_device = 0
output_audio_device = 0

print(
    f"Selected input device : {audio_devices[0].get(input_audio_device).get('name')}"
)
print(
    f"Selected output device : {audio_devices[1].get(output_audio_device).get('name')}"
)

s = pyo.Server()
atexit.register(_cleanup, s)    

input_nbchannels = pyo.pa_get_input_max_channels(input_audio_device)
output_nbchannels = pyo.pa_get_output_max_channels(output_audio_device)

s.setInputDevice(input_audio_device)
s.setOutputDevice(output_audio_device)
s.setIchnls(2)
s.setNchnls(2)
s.boot()
s.start()

print("Pyo server started. You can now interact with Pyo objects.")


inputs = [AudioStream(i) for i in range(input_nbchannels)]
input1 = AudioStream(0)
input2 = AudioStream(1)

print("Pour plus d'infos : help()")

   