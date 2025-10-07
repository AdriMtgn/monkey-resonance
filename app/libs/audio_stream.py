import os
import json
import pyo
import importlib

class AudioStream(pyo.PyoObject):
    def __init__(self, input_channel):
        """
        Initialize the PyoStream object with a pyo.Input object and an empty effects chain.
        """
        self.input_channel = input_channel
        self.input_stream = pyo.Input(input_channel)
        self.effects_chain = []
        self.pyo_effects_chain = []
        self.global_volume = 1.0
        self.output = self.input_stream * self.global_volume
    # Recording state
    self.recording = False
    self.recorder = None

    # Private Methods
    def _get_effect_class_from_name(self, effect_name):
        module_name, class_name = effect_name.rsplit('.', 1)
        module = importlib.import_module(module_name)
        return getattr(module, class_name)
    
    def _get_stream_for_position(self, position):
        """
        Get the stream to connect the new effect to, based on the position.
        :param position: The position in the chain where the effect will be added.
        :return: The stream to connect the new effect to.
        """
        if position == 0:
            return self.input_stream
        elif 0 < position <= len(self.effects_chain):
            return self.effects_chain[position - 1]["instance"]
        else:
            raise IndexError("Invalid position for adding an effect.")
        
    def _stop_all_chain(self):
        self.stop()
        for effect in self.pyo_effects_chain:
            effect.stop()
        self.input_stream.stop()

    def _start_all_chain(self):
        for effect in self.pyo_effects_chain:
            effect.play()
        self.input_stream.play()

    def _rebuild_chain(self):
        """
        Rebuild the internal stream chain to ensure all effects are connected correctly.
        """
        stream = self.input_stream
        for effect in self.pyo_effects_chain:
            effect.setInput(stream)
            stream = effect

    # Public Methods
    def add_effect(self, position, effect, **kwargs):
        """
        Add an effect to the effects chain at a specific position.
        :param position: The position in the chain where the effect will be added.
        :param effect: A pyo effect class (e.g., pyo.Chorus, pyo.Delay).
        :param kwargs: Parameters to initialize the effect.
        """
        if position is None:
            position = len(self.effects_chain)
        if position < 0 or position > len(self.effects_chain):
            raise IndexError("Invalid position for adding an effect.")

        if not hasattr(effect, "setInput"):
            raise AttributeError("L'effet choisi n'at pas de méthode setInput, impossible de l'ajouté!")
        
        self._stop_all_chain()
        new_effect = effect(self.input_stream, **kwargs)

        self.effects_chain.insert(position, {"effect": effect.__module__ + "." + effect.__name__, "params": kwargs})
        self.pyo_effects_chain.insert(position, new_effect)

        self._rebuild_chain()
        self._set_output()
        self._start_all_chain()

    def remove_effect(self, index):
        """
        Remove an effect from the effects chain by its index.
        :param index: The index of the effect to remove.
        """
        if 0 <= index < len(self.pyo_effects_chain):
            self._stop_all_chain()
            # Stop and remove the effect
            self.effects_chain.pop(index)
            effect_to_remove = self.pyo_effects_chain.pop(index)
            effect_to_remove.stop()

            # Rebuild the chain to ensure proper connections
            self._rebuild_chain()
            self._set_output()
            self._start_all_chain()
        else:
            raise IndexError("Invalid index for removing an effect.")

    def _set_output(self):
        """
        Get the final output of the effects chain.
        :return: The last effect in the chain or the input stream if no effects are applied.
        """
        # TODO : ajouter une logique pour relancer l'out si il joue déjà
        self.output.stop()
        if self.pyo_effects_chain:
            self.output = self.pyo_effects_chain[-1] * self.global_volume
        else:
            self.output = self.input_stream * self.global_volume

    def start(self):
        """
        Start the stream by playing the final output.
        """
        self.output.out()

    def stop(self):
        """
        Stop the stream by stopping the final output.
        """
        self.output.stop()

    def save_effects(self, effect_name):
        """
        Save the effects chain to a JSON file in the /saved_effects/ directory.
        :param effect_name: The base name of the effect file (without .json).
        """

        # Construct the full file path
        filepath = os.path.join("/monkey-resonance/saved_effects", f"{effect_name}.json")

        # Write to the JSON file
        saved_data = {
            "effect_chain": self.effects_chain,
            "global_volume": self.global_volume,
        }
        with open(filepath, "w") as f:
            json.dump(saved_data, f, indent=4)
        print(f"Effects chain saved to {filepath}")


    # Recording API
    def start_recording(self, filename: str = None):
        """
        Start recording the current output to a WAV file under /monkey-resonance/records.
        If filename is None, generate a timestamped filename.
        """
        try:
            os.makedirs("/monkey-resonance/records", exist_ok=True)
        except Exception:
            # Best-effort: ignore errors creating folder
            pass

        if filename is None:
            import datetime
            filename = f"record_{self.input_channel}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"

        filepath = os.path.join("/monkey-resonance/records", filename)

        if self.recording:
            raise RuntimeError("Recording already in progress")

        RecordClass = getattr(pyo, 'Record', None)
        if RecordClass is None:
            # Fall back to raising an error when Record is not available
            raise RuntimeError("pyo.Record is not available in this environment")

        # Ensure output is up-to-date
        self._set_output()

        # Create and start recorder
        try:
            # Record expects a PyoObject input; use the final output
            self.recorder = RecordClass(self.output, filename=filepath)
            # play/start naming differs, but play() is commonly present on pyo objects
            if hasattr(self.recorder, 'play'):
                self.recorder.play()
            elif hasattr(self.recorder, 'out'):
                self.recorder.out()
            self.recording = True
            return filepath
        except Exception as e:
            self.recorder = None
            raise

    def stop_recording(self):
        """
        Stop a running recording and return the recorded filepath (if available).
        """
        if not self.recording or self.recorder is None:
            raise RuntimeError("No recording in progress")

        try:
            if hasattr(self.recorder, 'stop'):
                self.recorder.stop()
            # try to get filename attribute if provided by the recorder
            filepath = getattr(self.recorder, 'filename', None)
            # clear recorder
            self.recorder = None
            self.recording = False
            return filepath
        except Exception:
            self.recorder = None
            self.recording = False
            raise


    def load_effects(self, effect_name):
        """
        Load the effects chain from a JSON file in the /saved_effects/ directory.
        :param effect_name: The base name of the effect file (without .json).
        """
        # Construct the full file path
        filepath = os.path.join("/monkey-resonance/saved_effects", f"{effect_name}.json")

        # Check if the file exists
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Effect file '{filepath}' not found.")

        # Read the JSON file
        with open(filepath, "r") as f:
            saved_data = json.load(f)
            self.effects_chain = saved_data.get("effect_chain",[])
            self.global_volume = saved_data.get("global_volume",1.0)


        # Recreate the effects chain
        self._stop_all_chain()
        self.pyo_effects_chain = [
            self._get_effect_class_from_name(effect_infos["effect"])(self.input_stream,**effect_infos["params"])
            for effect_infos in self.effects_chain
        ]
        self._rebuild_chain()
        self._start_all_chain()
        print(f"Effects chain loaded from {filepath}")

    def __del__(self):
        """
        Ensure the input stream and all effects are properly stopped and cleaned up.
        """
        self._stop_all_chain()
        # Stop recorder if active
        try:
            if getattr(self, 'recording', False) and getattr(self, 'recorder', None) is not None:
                if hasattr(self.recorder, 'stop'):
                    self.recorder.stop()
        except Exception:
            pass
