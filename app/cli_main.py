import pyo
import sys

from IPython.terminal.embed import InteractiveShellEmbed

from traitlets.config import Config


audio_devices = pyo.pa_get_devices_infos()


input_audio_device = 0
output_audio_device = 0


def main():

    print(
        f"Selected input device : {audio_devices[0].get(input_audio_device).get("name")}"
    )
    print(
        f"Selected output device : {audio_devices[1].get(output_audio_device).get("name")}"
    )

    s = pyo.Server()
    s.setInputDevice(input_audio_device)
    s.setOutputDevice(output_audio_device)
    s.setIchnls(2)
    s.setNchnls(2)
    s.boot()
    s.start()

    print("Pyo server started. You can now interact with Pyo objects.")
    print("Type 'exit' or press Ctrl+D to quit.")

    # Configure IPython for autocompletion
    cfg = Config()
    cfg.TerminalInteractiveShell.display_completions = "readlinelike"

    # Start IPython shell with the configuration
    shell = InteractiveShellEmbed(config=cfg)
    shell()

    s.stop()
    s.shutdown()


if __name__ == "__main__":
    main()
