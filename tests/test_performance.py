"""Tests du contrôleur presets / bypass / looper / dispatch MIDI."""

import json

import pytest
from libs import audio_stream as audio_stream_module
from libs import performance as performance_module
from libs.audio_stream import AudioStream
from libs.performance import (
    MidiEvent,
    MidiMap,
    PerformanceController,
    list_presets,
)


CHAIN_A = {
    "engine": "pedalboard",
    "effect_chain": [
        {"effect": "pedalboard.Gain", "params": {"gain_db": -3}},
    ],
    "global_volume": 1.0,
}
CHAIN_B = {
    "engine": "pedalboard",
    "effect_chain": [
        {"effect": "pedalboard.Delay", "params": {"delay_seconds": 0.2}},
    ],
    "global_volume": 1.0,
}


@pytest.fixture
def engine():
    instance = AudioStream(open_device=False)
    yield instance
    instance.close()


@pytest.fixture
def controller(engine, tmp_path, monkeypatch):
    effects = tmp_path / "saved_effects"
    effects.mkdir()
    (effects / "clean.json").write_text(json.dumps(CHAIN_A), encoding="utf-8")
    (effects / "space.json").write_text(json.dumps(CHAIN_B), encoding="utf-8")
    (effects / "broken.json").write_text("{not json", encoding="utf-8")
    (effects / "notes.wav").write_bytes(b"not audio")
    (effects / "scalar.json").write_text("42", encoding="utf-8")
    monkeypatch.setattr(audio_stream_module, "effects_folder", str(effects))
    monkeypatch.setattr(performance_module, "midi_maps_folder", str(tmp_path / "maps"))
    mapping = MidiMap(
        name="test",
        debounce_ms=0,
        preset_order=["clean", "space"],
    )
    return PerformanceController([engine], mapping=mapping)


def test_list_presets_ignores_invalid_and_non_json(controller):
    assert list_presets() == ["clean", "space"]
    assert controller.list_presets() == ["clean", "space"]


def test_apply_preset_preserves_volume(controller, engine):
    engine.global_volume = 0.4
    result = controller.apply_preset("clean")
    assert result["preset"] == "clean"
    assert controller.current_preset == "clean"
    assert engine.global_volume == pytest.approx(0.4)
    assert engine.effects_chain[0]["effect"] == "pedalboard.Gain"


def test_apply_preset_can_restore_saved_volume(controller, engine):
    engine.global_volume = 0.4
    controller.apply_preset("clean", keep_volume=False)
    assert engine.global_volume == pytest.approx(1.0)


def test_unknown_preset_is_rejected(controller):
    with pytest.raises(ValueError):
        controller.apply_preset("../secret")
    with pytest.raises(FileNotFoundError):
        controller.apply_preset("missing")


def test_next_and_previous_follow_configured_order(controller):
    controller.apply_preset("clean")
    assert controller.next_preset()["preset"] == "space"
    assert controller.next_preset()["preset"] == "clean"
    assert controller.previous_preset()["preset"] == "space"


def test_toggle_and_set_effect_enabled(controller, engine):
    engine.add_effect(None, "pedalboard.Gain", gain_db=-3)
    result = controller.toggle_effect("pedalboard.Gain")
    assert result["enabled"] is False
    assert engine.effects_chain[0]["enabled"] is False
    assert len(engine._board) == 1  # seulement le gain de sortie

    result = controller.toggle_effect(0)
    assert result["enabled"] is True
    assert len(engine._board) == 2

    result = controller.set_effect_enabled("pedalboard.Gain", False)
    assert result["enabled"] is False

    with pytest.raises(ValueError):
        controller.toggle_effect("pedalboard.DoesNotExist")


def test_mapping_input_index_selects_target_track(controller, engine):
    from libs.audio_stream import AudioStream
    from libs.performance import MidiMap

    second = AudioStream(open_device=False)
    try:
        controller._inputs.append(second)
        controller.set_mapping(
            MidiMap(
                input_index=1,
                preset_order=["clean", "space"],
            )
        )
        controller.apply_preset("clean")
        assert second.effects_chain[0]["effect"] == "pedalboard.Gain"
        assert engine.effects_chain == []
    finally:
        second.close()


def test_continuous_cc_controls_input_volume(controller, engine):
    controller.add_binding(
        {"type": "control_change", "controller": 7, "mode": "value"},
        {"type": "set_input_volume"},
        binding_id="cc7",
    )
    engine.global_volume = 1.0
    controller.dispatch_event(
        MidiEvent(type="control_change", channel=0, controller=7, value=64)
    )
    assert engine.global_volume == pytest.approx(64 / 127, abs=1e-3)
    controller.dispatch_event(
        MidiEvent(type="control_change", channel=0, controller=7, value=127)
    )
    assert engine.global_volume == pytest.approx(1.0)


def test_mapping_crud_and_persistence(controller, tmp_path):
    added = controller.add_binding(
        {"type": "program_change", "number": 0},
        {"type": "preset", "target": "clean"},
        binding_id="pc0",
    )
    assert added["binding"]["id"] == "pc0"

    controller.add_binding(
        {"type": "control_change", "controller": 21, "mode": "press"},
        {"type": "next_preset"},
        binding_id="cc21",
    )
    assert [binding["id"] for binding in controller.get_mapping_dict()["bindings"]] == [
        "pc0",
        "cc21",
    ]

    updated = controller.update_binding(
        "cc21",
        action={"type": "previous_preset"},
    )
    assert updated["binding"]["action"]["type"] == "previous_preset"

    configured = controller.configure_mapping(
        {
            "preset_order": ["space", "clean"],
            "channel": 2,
            "debounce_ms": 0,
        }
    )
    assert configured["mapping"]["preset_order"] == ["space", "clean"]
    assert configured["mapping"]["channel"] == 2
    with pytest.raises(ValueError):
        controller.configure_mapping({"channel": 99})
    assert controller.get_mapping_dict()["channel"] == 2

    path = controller.save_mapping("live")
    assert path["file"].endswith("live.json")
    assert "live" in controller.list_mappings()

    controller.remove_binding("pc0")
    assert [binding["id"] for binding in controller.get_mapping_dict()["bindings"]] == [
        "cc21"
    ]

    other = PerformanceController([controller._inputs[0]])
    loaded = other.load_mapping("live")
    assert loaded["mapping"]["bindings"][0]["id"] == "pc0"
    assert loaded["mapping"]["preset_order"] == ["space", "clean"]


def test_dispatch_program_change_and_cc(controller, engine):
    controller.add_binding(
        {"type": "program_change", "number": 0},
        {"type": "preset", "target": "clean"},
        binding_id="pc0",
    )
    controller.add_binding(
        {"type": "control_change", "controller": 21, "mode": "press"},
        {"type": "next_preset"},
        binding_id="cc21",
    )
    controller.add_binding(
        {"type": "control_change", "controller": 22, "mode": "press"},
        {"type": "toggle_effect", "target": "pedalboard.Delay"},
        binding_id="cc22",
    )
    engine.add_effect(None, "pedalboard.Delay", delay_seconds=0.2)

    controller.dispatch_event(
        MidiEvent(type="program_change", channel=0, number=0)
    )
    assert controller.current_preset == "clean"

    controller.dispatch_event(
        MidiEvent(type="control_change", channel=0, controller=21, value=127)
    )
    assert controller.current_preset == "space"

    # Un relâchement ne déclenche pas un second « next ».
    controller.dispatch_event(
        MidiEvent(type="control_change", channel=0, controller=21, value=0)
    )
    assert controller.current_preset == "space"

    controller.dispatch_event(
        MidiEvent(type="control_change", channel=0, controller=22, value=127)
    )
    assert engine.effects_chain[0]["enabled"] is False


def test_dispatch_note_on_triggers_loop(controller, monkeypatch):
    from libs.performance import TriggerAction, MidiBinding, MidiSource

    class FakeInput:
        def __init__(self):
            self.recording = False
            self.playback = None
            self.global_volume = 1.0
            self.effects_chain = []

        def start_recording(self, filename=None):
            self.recording = True
            return "/tmp/loop.wav"

        def stop_recording(self):
            self.recording = False
            return "/tmp/loop.wav"

        def play_recording(self, filename, *, loop=True, volume=1.0):
            self.playback = {"file": filename, "loop": loop}
            return self.playback

        def stop_playback(self):
            playback = self.playback
            self.playback = None
            return playback

    fake = FakeInput()
    controller = PerformanceController([fake], mapping=MidiMap(debounce_ms=0))
    controller.add_binding(
        {"type": "note_on", "number": 36},
        {"type": "loop_toggle"},
        binding_id="pad36",
    )
    def press():
        controller.dispatch_event(
            MidiEvent(type="note_on", channel=0, number=36, value=100)
        )
        controller.dispatch_event(
            MidiEvent(type="note_off", channel=0, number=36, value=0)
        )

    press()
    assert fake.recording is True
    press()
    assert fake.recording is False
    assert fake.playback == {"file": "/tmp/loop.wav", "loop": True}
    press()
    assert fake.playback is None


def test_learn_captures_without_executing(controller, engine):
    controller.add_binding(
        {"type": "program_change", "number": 0},
        {"type": "preset", "target": "clean"},
        binding_id="pc0",
    )
    controller.start_learn()
    result = controller.dispatch_event(
        MidiEvent(type="program_change", channel=0, number=0)
    )
    assert result["result"] == "learned"
    assert controller.current_preset is None
    stopped = controller.stop_learn()
    assert stopped["event"]["number"] == 0
    # Le mode learn s'arrête après le premier message : le suivant s'exécute.
    controller.dispatch_event(
        MidiEvent(type="program_change", channel=0, number=0)
    )
    assert controller.current_preset == "clean"


def test_mapping_from_nested_config():
    mapping = MidiMap.from_dict(
        {
            "name": "nested",
            "order": ["clean"],
            "startup": "clean",
            "midi": {
                "device": "AudioBox",
                "channel": 0,
                "bindings": [
                    {
                        "id": "pc0",
                        "source": {"type": "program_change", "number": 0},
                        "action": {"type": "preset", "target": "clean"},
                    }
                ],
            },
        }
    )
    assert mapping.device == "AudioBox"
    assert mapping.startup_preset == "clean"
    assert mapping.preset_order == ["clean"]
    assert mapping.bindings[0].id == "pc0"


def test_bad_binding_is_rejected(controller):
    with pytest.raises(ValueError):
        controller.add_binding(
            {"type": "control_change", "controller": 21, "mode": "value"},
            {"type": "next_preset"},
        )
    with pytest.raises(ValueError):
        controller.add_binding(
            {"type": "program_change", "number": 200},
            {"type": "preset", "target": "clean"},
        )


def test_trigger_action_helpers():
    from libs.performance import MidiBinding, MidiSource, TriggerAction

    binding = MidiBinding(
        source=MidiSource(type="control_change", controller=20, mode="toggle"),
        action=TriggerAction(type="toggle_effect", target="pedalboard.Delay"),
    )
    assert binding.to_dict()["source"]["controller"] == 20


def test_rest_endpoints_use_main_controller(controller, engine, monkeypatch):
    import sys

    from monkey_api import api

    main = sys.modules["__main__"]
    monkeypatch.setattr(main, "performance", controller, raising=False)

    assert "clean" in api.list_presets()["presets"]
    assert api.load_preset("clean")["preset"] == "clean"
    assert api.next_preset()["preset"] == "space"
    assert api.performance_status()["current_preset"] == "space"
    configured = api.update_midi_map({"order": ["space", "clean"]})
    assert configured["mapping"]["preset_order"] == ["space", "clean"]

    engine.add_effect(None, "pedalboard.Gain", gain_db=-3)
    assert api.toggle_effect(
        0, api.EffectTargetParams(target="pedalboard.Gain")
    )["enabled"] is False

    controller.add_binding(
        {"type": "program_change", "number": 0},
        {"type": "preset", "target": "clean"},
        binding_id="pc0",
    )
    simulated = api.simulate_midi_event(
        {"type": "program_change", "channel": 0, "number": 0}
    )
    assert simulated["triggered"][0]["binding"] == "pc0"
    assert controller.current_preset == "clean"


def test_mcp_tools_use_main_controller(controller, monkeypatch):
    import asyncio
    import sys

    from server import server as mcp_mod

    main = sys.modules["__main__"]
    monkeypatch.setattr(main, "performance", controller, raising=False)

    presets = asyncio.run(mcp_mod.list_presets())
    assert "clean" in presets["presets"]
    assert asyncio.run(mcp_mod.load_preset("clean"))["preset"] == "clean"
    configured = asyncio.run(
        mcp_mod.configure_midi_map({"order": ["clean", "space"]})
    )
    assert configured["mapping"]["preset_order"] == ["clean", "space"]

    controller.add_binding(
        {"type": "program_change", "number": 1},
        {"type": "preset", "target": "space"},
        binding_id="pc1",
    )
    result = asyncio.run(
        mcp_mod.simulate_midi_event(
            {"type": "program_change", "channel": 0, "number": 1}
        )
    )
    assert result["triggered"][0]["binding"] == "pc1"
    assert controller.current_preset == "space"
