"""Smoke tests : les modules de base s'importent sans device audio.

Ils ne bootent pas le serveur pyo (aucun /dev/snd requis pour l'import) et
servent de garde-fou contre les régressions du type « import cassé qui casse
toute la collection pytest » (cf. l'ancien app/core/test_audio_stream_pyo.py).
"""


def test_import_utils():
    from libs import utils

    assert utils.APP_BASE_FOLDER == "/monkey-resonance"
    assert set(utils.APP_FOLDERS.values()) == {
        "records",
        "saved_effects",
        "saved_midi_maps",
    }


def test_import_audio_stream():
    from libs.audio_stream import AudioStream

    for method in ("add_effect", "remove_effect", "update_effect", "start", "stop",
                   "close", "start_recording", "stop_recording", "save_effects",
                   "load_effects", "play_recording", "stop_playback",
                   "playback_status", "add_listener", "remove_listener",
                   "process_segment", "extract", "attach_engine",
                   "set_input_channels", "set_effect_enabled", "toggle_effect",
                   "effect_positions"):
        assert hasattr(AudioStream, method), f"AudioStream.{method} manquant"


def test_import_mixer():
    from libs.mixer import MixerEngine, parse_input_layout, parse_output_layout

    for method in ("start", "stop", "close", "add_input", "remove_input",
                   "set_input_channels", "set_input_mix", "set_route",
                   "add_output", "remove_output", "set_output_channels",
                   "set_output_volume", "mute_output", "unmute_output",
                   "set_master_volume", "get_mixer_state"):
        assert hasattr(MixerEngine, method), f"MixerEngine.{method} manquant"

    assert [spec.name for spec in parse_input_layout(None, 2)] == [
        "input_0",
        "input_1",
    ]
    assert parse_output_layout(None, 2)[0].name == "main"


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
    # mixer : routes REST
    assert "/mixer" in paths
    assert "/mixer/inputs" in paths
    assert "/mixer/routes" in paths
    assert "/mixer/outputs" in paths
    assert "/mixer/master" in paths
    # performance : presets, bypass, looper et MIDI
    assert "/presets" in paths
    assert "/presets/next" in paths
    assert "/performance" in paths
    assert "/effects/{input_index}/toggle" in paths
    assert "/midi/map" in paths
    assert "/midi/bindings" in paths
    assert "/midi/simulate" in paths


def test_mcp_module_defines_server():
    from server import server as mcp_mod

    assert mcp_mod.mcp.name == "Monkey Resonance MCP"
    # les tools historiques doivent survivre à un refactor
    tools = {tool.name for tool in mcp_mod.mcp._tool_manager.list_tools()}
    assert {
        "list_inputs",
        "mute_input",
        "add_effect_to_input",
        "save_input_effects",
        "load_input_effects",
        "set_output_volume",
        "get_rms_level",
        "get_pitch_info",
        "get_frequency_analysis",
        "get_audio_profile",
        "list_recordings",
        "play_recording",
        "stop_playback",
        "playback_status",
        # mixer : inputs indépendants + bus
        "get_mixer",
        "add_input",
        "remove_input",
        "set_input_channels",
        "set_input_mix",
        "set_route",
        "add_output",
        "remove_output",
        "set_output_channels",
        "mute_output",
        "unmute_output",
        "set_master_volume",
        "mute_master",
        "unmute_master",
        # performance : presets, bypass, looper et mappings MIDI
        "list_presets",
        "load_preset",
        "next_preset",
        "previous_preset",
        "performance_status",
        "toggle_effect",
        "set_effect_enabled",
        "loop_toggle",
        "loop_record",
        "loop_play",
        "loop_stop",
        "list_midi_devices",
        "get_midi_status",
        "list_midi_maps",
        "get_midi_map",
        "configure_midi_map",
        "save_midi_map",
        "load_midi_map",
        "add_midi_binding",
        "update_midi_binding",
        "remove_midi_binding",
        "simulate_midi_event",
        "start_midi_learn",
        "stop_midi_learn",
        "get_midi_learn",
    } <= tools
