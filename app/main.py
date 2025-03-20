from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import sounddevice as sd
import os


sd.default.latency = "low"

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def read_root():
    return {"Hello": "World"}

@app.get("/devices")
def get_devices():
    devices = sd.query_devices()
    return devices

@app.get("/devices_page", response_class=HTMLResponse)
def get_devices_page():
    with open(os.path.join("static", "index.html")) as f:
        return HTMLResponse(content=f.read(), status_code=200)