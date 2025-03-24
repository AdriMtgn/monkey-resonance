from fastapi import FastAPI, WebSocket
from core.audio_stream import start_stream, stop_stream
from core.audio_options import update_options, OPTIONS_DEFAULT_VALUES
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

import sounddevice as sd
import os
from contextlib import asynccontextmanager


# Set default options for sounddevice
sd.default.latency = "low"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    start_stream()
    yield
    # Shutdown logic
    stop_stream()


app = FastAPI(lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def read_index():
    return FileResponse("static/mix_table.html")


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
