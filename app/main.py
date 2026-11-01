import argparse
import logging
import os
import sys
from threading import Thread

import pyo
from libs.audio_stream import AudioStream  # noqa: F401 - Used by server.server via sys.modules

# Add app directory to path for server.server import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from libs.utils import (
    APP_BASE_FOLDER,
    _check_and_create_app_folders,
)

# Configure logging early
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

parser = argparse.ArgumentParser()
parser.add_argument("--with_api", action="store_true")

args = parser.parse_args()

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

# Pyo v0.8.x: create server with stereo channels
# Note: Pyo uses PortAudio to access audio devices, which may not list ALSA devices correctly in containers
# We create the server without specifying devices and let Pyo use default devices
# Creating with nchnls=2 for stereo (required by pyo)
s = pyo.Server(nchnls=2)

logger.info("Booting Pyo Server...")
try:
    s.boot()
    logger.info("Pyo Server booted successfully!")
except Exception as e:
    logger.error(f"Failed to boot Pyo Server: {e}")
    raise

logger.info("Starting Pyo Server...")
s.start()
logger.info("Pyo server started. You can now interact with Pyo objects.")

# Give the server time to initialize
import time
time.sleep(0.5)

# Prepare audio input handles (create only when Server exists and channels)
# Note: Input() uses the server's configured input device, not a parameter
inputs = [pyo.Input(i) for i in range(input_nbchannels)]

# Detect and expose audio devices to __main__ for MCP server
try:
    import sounddevice as sd
    logger.info("Detecting audio devices...")
    
    # Get input devices
    input_devices = {}
    try:
        for i, dev in enumerate(sd.query_devices()):
            if dev['max_input_channels'] > 0:
                input_devices[i] = {
                    'index': i,
                    'name': dev['name'],
                    'channels': dev['max_input_channels'],
                    'hostapi': dev['hostapi'],
                    'sample_rate': dev['default_samplerate']
                }
        logger.info(f"Found {len(input_devices)} input device(s): {list(input_devices.keys())}")
    except Exception as e:
        logger.warning(f"Could not query input devices: {e}")
    
    # Get output devices
    output_devices = {}
    try:
        for i, dev in enumerate(sd.query_devices()):
            if dev['max_output_channels'] > 0:
                output_devices[i] = {
                    'index': i,
                    'name': dev['name'],
                    'channels': dev['max_output_channels'],
                    'hostapi': dev['hostapi'],
                    'sample_rate': dev['default_samplerate']
                }
        logger.info(f"Found {len(output_devices)} output device(s): {list(output_devices.keys())}")
    except Exception as e:
        logger.warning(f"Could not query output devices: {e}")
    
except ImportError:
    logger.warning("sounddevice not available, using pyo device detection")
    input_devices = {}
    output_devices = {}

# Store audio_devices in __main__ for MCP server to access
import sys
import types

# Create a __main__ module to hold our variables
if '__main__' not in sys.modules:
    main_module = types.ModuleType('__main__')
    sys.modules['__main__'] = main_module
else:
    main_module = sys.modules['__main__']

# Expose all necessary variables to __main__ for MCP access
main_module.AudioStream = AudioStream
main_module.audio_devices = (input_devices, output_devices)
main_module.inputs = inputs
main_module.pyo_server = s

logger.info("Audio devices exposed to __main__: audio_devices = (inputs, outputs)")
logger.info(f"  Input devices: {len(input_devices)}")
logger.info(f"  Output devices: {len(output_devices)}")

# Always start MCP server by default
logger.info("Starting MCP server")

def run_mcp():
    from server.server import start_mcp
    start_mcp()

# Start the MCP server in the main thread to keep it alive
run_mcp()

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
