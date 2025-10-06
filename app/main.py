import pyo
import datetime
import atexit
from libs.utils import _check_and_create_app_folders, APP_BASE_FOLDER,APP_FOLDERS,help,os,_cleanup
from libs.audio_stream import AudioStream
import libs.effect_lib as eff
import logging
from threading import Thread

logger = logging.getLogger()

_check_and_create_app_folders(APP_BASE_FOLDER)

if not os.path.exists('/dev/snd'):

    logger.error("No audio shared with docker")
    raise(Exception)


available_audio_devices = pyo.pa_list_devices()

logger.info(str(available_audio_devices))

input_audio_device = 0
output_audio_device = 0

try:
    audio_devices = pyo.pa_get_devices_infos()
except Exception:
    audio_devices = ([], [])

logger.info(str(audio_devices))    
if len(audio_devices[0]) == 0:
    logger.warning("Aucun input audio trouvé!")
else:
    logger.info(f"Selected input device : {audio_devices[0].get(input_audio_device).get('name')}")
if len(audio_devices[1]) == 0:
    logger.warning("Aucun output audio trouvé!")
else:
    logger.info(f"Selected output device : {audio_devices[1].get(output_audio_device).get('name')}")


logger.info("Starting Pyo Server...")
s = pyo.Server()

atexit.register(_cleanup, s)

try:
    input_nbchannels = pyo.pa_get_input_max_channels(input_audio_device)
except Exception:
    input_nbchannels = 0
try:
    output_nbchannels = pyo.pa_get_output_max_channels(output_audio_device)
except Exception:
    output_nbchannels = 0

# Configure devices only if portaudio reports channels
if input_nbchannels > 0 and output_nbchannels > 0:
    s.setInputDevice(input_audio_device)
    s.setOutputDevice(output_audio_device)
    s.setIchnls(2)
    s.setNchnls(2)
else:
    logger.error("Aucune carte son detectée")
    raise(Exception)
s.boot()
s.start()

logger.info("Pyo server started. You can now interact with Pyo objects.")


# Prepare audio input handles (create only when Server exists and channels)
inputs = [AudioStream(i) for i in range(input_nbchannels)]

# Start MCP server
logger.info("Starting mpc server")

def run_mcp():
    from monkey_mcp.mcp import start_mcp
    start_mcp()

# Start the MCP server in a non-daemon thread so the process will stay alive.
mcp_thread = Thread(target=run_mcp, daemon=False)
mcp_thread.start()

print("MCP server started. Pour plus d'infos : help()")

# Block the main thread to keep the service alive. If RUN_MCP_ONLY is set we
# already skipped Pyo; otherwise we still keep the process running so that
# the MCP server and Pyo remain available in the container.
try:
    while True:
        import time
        time.sleep(1)
except KeyboardInterrupt:
    print('Shutting down')

   