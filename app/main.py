import argparse
import logging
import os
from threading import Thread

import pyo
from libs.audio_stream import AudioStream  # noqa: F401 - Used by mcp.py and api.py via sys.modules
from libs.utils import (
    APP_BASE_FOLDER,
    _check_and_create_app_folders,
)

# Configure logging early
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

parser = argparse.ArgumentParser()
parser.add_argument("--with_mcp", action="store_true")
parser.add_argument("--with_api", action="store_true")

args = parser.parse_args()

if args.with_mcp and args.with_api:
    raise SystemExit("Impossible de lancer le mcp et l'api en même temps")

_check_and_create_app_folders(APP_BASE_FOLDER)

if not os.path.exists('/dev/snd'):
    logger.error("No audio shared with docker")
    raise RuntimeError("No audio shared with docker")

# Detect audio devices using hardcoded values for AudioBox USB 96 (hw:0,0)
# Note: We use device 0 which corresponds to hw:0,0 in ALSA
logger.info("Using AudioBox USB 96 configuration (hw:0,0)...")
input_audio_device = 0
output_audio_device = 0
input_nbchannels = 2  # AudioBox USB 96 is stereo
output_nbchannels = 2  # AudioBox USB 96 is stereo

logger.info(f"  Input device: {input_audio_device} ({input_nbchannels} channels)")
logger.info(f"  Output device: {output_audio_device} ({output_nbchannels} channels)")

# Create and boot the pyo server with correct settings
logger.info("Creating and booting Pyo Server...")
s = pyo.Server()

# Configure device and channels BEFORE booting (required by pyo)
s.setInputDevice(input_audio_device)
s.setOutputDevice(output_audio_device)
s.setIchnls(input_nbchannels)  # stereo input channels
s.setNchnls(output_nbchannels)  # 2 output channels
logger.info(f"Server configured with device {input_audio_device}:{output_audio_device}")

s.boot()
logger.info("Pyo Server booted successfully!")

s.start()

logger.info("Pyo server started. You can now interact with Pyo objects.")

# Prepare audio input handles (create only when Server exists and channels)
# Note: Input() uses the server's configured input device, not a parameter
inputs = [pyo.Input(i) for i in range(input_nbchannels)]

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
