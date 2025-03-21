from fastapi import FastAPI
from fastapi.websockets import WebSocket
from core.audio_stream import start_stream, stop_stream
from core.audio_options import update_options, OPTIONS_DEFAULT_VALUES
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

import sounddevice as sd
import os


# Set default options for sounddevice
sd.default.latency = "low"

devices = sd.query_devices()
global audio_mix_options
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

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def read_index():
    return FileResponse('static/mix_table.html')

@app.get("/devices")
def get_devices():
    devices = sd.query_devices()
    return devices

@app.get("/devices_page", response_class=HTMLResponse)
def get_devices_page():
    with open(os.path.join("static", "index.html")) as f:
        return HTMLResponse(content=f.read(), status_code=200)
    

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = await websocket.receive_json()
        device_index = data.get("device_index")
        channel_number = data.get("channel_number")
        new_options = data.get("options", {})
        if device_index is not None and channel_number is not None:
            update_options(device_index, channel_number, new_options)
            await websocket.send_json({"status": "updated"})
        else:
            await websocket.send_json({"status": "error", "message": "Invalid data format"})