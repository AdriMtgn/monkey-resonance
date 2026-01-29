import pyo
import datetime
import atexit
from libs.utils import _check_and_create_app_folders, APP_BASE_FOLDER,APP_FOLDERS,os,_cleanup
from libs.audio_stream import AudioStream
import libs.effect_lib as eff
import logging
from threading import Thread
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--with_mcp", action="store_true")
parser.add_argument("--with_api", action="store_true")

args = parser.parse_args()

if args.with_mcp and args.with_api:
    raise("Impossible de lancer le mcp et l'api en même temps")

logger = logging.getLogger()
logging.basicConfig(level=logging.DEBUG)
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
s.boot()

try:
    input_nbchannels = pyo.pa_get_input_max_channels(input_audio_device)
except Exception:
    input_nbchannels = 0

try:
    output_nbchannels = pyo.pa_get_output_max_channels(output_audio_device)
except Exception:
    output_nbchannels = 0

# Configure devices only if portaudio reports channels
#if input_nbchannels > 0 and output_nbchannels > 0:
#    s.setInputDevice(input_audio_device)
#    s.setOutputDevice(output_audio_device)
#    s.setIchnls(2)
#    s.setNchnls(2)
#else:
#    logger.error("Aucune carte son detectée")
#    raise(Exception)
s.start()

logger.info("Pyo server started. You can now interact with Pyo objects.")

# Prepare audio input handles (create only when Server exists and channels)
inputs = [AudioStream(i) for i in range(input_nbchannels)]

if args.with_mcp:
    # Start MCP server
    logger.info("Starting mpc server")

    def run_mcp():
        from monkey_mcp.mcp import start_mcp
        start_mcp()

    # Start the MCP server in a non-daemon thread so the process will stay alive.
    mcp_thread = Thread(target=run_mcp, daemon=False)
    mcp_thread.start()

if args.with_api:    
    # Start the REST API server
    logger.info("Starting REST API server")

    def run_api():
        from monkey_api.api import start_api
        start_api()


    # Start the REST API server in a non-daemon thread
    api_thread = Thread(target=run_api, daemon=False)
    api_thread.start()

    # print("MCP server started. Pour plus d'infos : help()")
    print("REST API server started. Documentation disponible sur /docs")
