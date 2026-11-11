"""Tests du parseur MIDI brut (sans device audio ni MIDI)."""

from libs.midi_control import MidiStreamParser, list_midi_devices, resolve_midi_device
from libs.performance import MidiEvent


def test_program_change():
    events = MidiStreamParser().feed(bytes([0xC0, 5]))
    assert events == [MidiEvent(type="program_change", channel=0, number=5)]


def test_control_change():
    events = MidiStreamParser().feed(bytes([0xB2, 21, 127]))
    assert events == [
        MidiEvent(type="control_change", channel=2, controller=21, value=127)
    ]


def test_note_on_and_note_off():
    parser = MidiStreamParser()
    events = parser.feed(bytes([0x90, 60, 100, 0x80, 60, 0]))
    assert events == [
        MidiEvent(type="note_on", channel=0, number=60, value=100),
        MidiEvent(type="note_off", channel=0, number=60, value=0),
    ]


def test_note_on_velocity_zero_is_note_off():
    events = MidiStreamParser().feed(bytes([0x90, 36, 0]))
    assert events == [MidiEvent(type="note_off", channel=0, number=36, value=0)]


def test_running_status():
    events = MidiStreamParser().feed(bytes([0x90, 60, 100, 62, 80]))
    assert [event.number for event in events] == [60, 62]
    assert all(event.type == "note_on" for event in events)


def test_sysex_and_realtime_are_ignored():
    parser = MidiStreamParser()
    # F0 ... sysex ... F7, puis un CC valide, avec une horloge F8 au milieu.
    events = parser.feed(
        bytes([0xF0, 0x01, 0x02, 0xF8, 0xF7, 0xB0, 20, 64, 0xF8, 0xF7])
    )
    assert events == [
        MidiEvent(type="control_change", channel=0, controller=20, value=64)
    ]


def test_incomplete_messages_are_held_until_complete():
    parser = MidiStreamParser()
    assert parser.feed(bytes([0xB0, 21])) == []
    assert parser.feed(bytes([127])) == [
        MidiEvent(type="control_change", channel=0, controller=21, value=127)
    ]


def test_simulated_event_defaults_and_normalization():
    assert MidiEvent.from_dict(
        {"type": "note_on", "number": 36}
    ) == MidiEvent(type="note_on", channel=0, number=36, value=127)
    assert MidiEvent.from_dict(
        {"type": "control_change", "controller": 21}
    ) == MidiEvent(
        type="control_change", channel=0, controller=21, value=127
    )
    assert MidiEvent.from_dict(
        {"type": "note_on", "number": 36, "value": 0}
    ) == MidiEvent(type="note_off", channel=0, number=36, value=0)


def test_device_helpers_return_stable_shapes():
    assert isinstance(list_midi_devices(), list)
    # Un chemin inexistant ne doit pas lever.
    assert resolve_midi_device("/dev/snd/does-not-exist") is None


def test_resolve_numeric_card_index(monkeypatch):
    import libs.midi_control as midi_control

    class FakeGlob:
        @staticmethod
        def glob(pattern):
            if pattern == "/dev/snd/midiC2D*":
                return ["/dev/snd/midiC2D0"]
            return []

    monkeypatch.setattr(midi_control, "glob", FakeGlob)
    assert resolve_midi_device("2") == "/dev/snd/midiC2D0"


def test_resolve_name_falls_back_when_proc_asound_is_absent(monkeypatch):
    import libs.midi_control as midi_control

    class FakeGlob:
        @staticmethod
        def glob(pattern):
            if pattern == "/dev/snd/midiC*D*":
                return ["/dev/snd/midiC0D0"]
            return []

    monkeypatch.setattr(midi_control, "_read_sound_cards", lambda: [])
    monkeypatch.setattr(midi_control, "glob", FakeGlob)
    assert resolve_midi_device("AudioBox") == "/dev/snd/midiC0D0"
