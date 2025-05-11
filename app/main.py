import pyo
import datetime
import atexit

audio_devices = pyo.pa_get_devices_infos()

input_audio_device = 0
output_audio_device = 0


def help():
    print("Pour enregistrer : rec.play()")
    print("Pour arreter d'enregistrer : rec.stop()")


def cleanup(s):
    print("Cleaning up...")
    s.stop()
    s.shutdown()
    print("Cleanup complete.")



print(
    f"Selected input device : {audio_devices[0].get(input_audio_device).get('name')}"
)
print(
    f"Selected output device : {audio_devices[1].get(output_audio_device).get('name')}"
)

s = pyo.Server()
atexit.register(cleanup, s)    

s.setInputDevice(input_audio_device)
s.setOutputDevice(output_audio_device)
s.setIchnls(2)
s.setNchnls(2)
s.boot()
s.start()

print("Pyo server started. You can now interact with Pyo objects.")

input1 = pyo.Input(0)
input2 = pyo.Input(1)

rec1 = pyo.Record(
    input1,
    f"/records/input1_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.wav",
)
rec2 = pyo.Record(
    input2,
    f"/records/input2_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.wav",
)

print("Pour manipuler l'entrée 1 : input1, rec1")
print("Pour manipuler l'entrée 2 : input2, rec2")
print("Pour plus d'infos : help()")

   