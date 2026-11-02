"""Smoke tests : les modules de base s'importent sans device audio.

Ils ne bootent pas le serveur pyo (aucun /dev/snd requis pour l'import) et
servent de garde-fou contre les régressions du type « import cassé qui casse
toute la collection pytest » (cf. l'ancien app/core/test_audio_stream_pyo.py).
"""


def test_import_utils():
    from libs import utils

    assert utils.APP_BASE_FOLDER == "/monkey-resonance"
    assert set(utils.APP_FOLDERS.values()) == {"records", "saved_effects"}


def test_import_audio_stream():
    from libs.audio_stream import AudioStream

    for method in ("add_effect", "remove_effect", "update_effect", "start", "stop",
                   "close", "start_recording", "stop_recording", "save_effects",
                   "load_effects"):
        assert hasattr(AudioStream, method), f"AudioStream.{method} manquant"


def test_import_effect_lib():
    from libs.effect_lib import CustomDelay

    for method in ("setDelayTime", "setFeedback", "setWetLevel"):
        assert hasattr(CustomDelay, method), f"CustomDelay.{method} manquant"


def test_api_module_defines_fastapi_app():
    from monkey_api import api

    assert api.app.title == "Monkey Resonance API"
    # les routes historiques doivent survivre à un refactor
    paths = {route.path for route in api.app.routes}
    assert "/list_inputs" in paths
    assert "/mute_input/{index}" in paths


def test_mcp_module_defines_server():
    from server import server as mcp_mod

    assert mcp_mod.mcp.name == "Monkey Resonance MCP"
    # les tools historiques doivent survivre à un refactor
    tools = {tool.name for tool in mcp_mod.mcp._tool_manager.list_tools()}
    assert {
        "list_inputs",
        "mute_input",
        "add_effect_to_input",
        "set_output_volume",
        "get_rms_level",
        "get_pitch_info",
        "get_frequency_analysis",
        "get_audio_profile",
    } <= tools
