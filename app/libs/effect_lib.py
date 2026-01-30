import pyo

class CustomDelay(pyo.PyoObject):
    """
    A custom delay effect that mixes the original sound with the delayed sound.

    Parameters:
        input (PyoObject): The input sound to process.
        delay_time (float): The delay time in seconds.
        feedback (float): The feedback amount (0 to 1).
        wet_level (float): The amplitude of the delayed signal (0 to 1).
    """
    def __init__(self, input, delay_time=0.5, feedback=0.5, wet_level=0.5):
        pyo.PyoObject.__init__(self)
        self._input = input
        self._delay_time = delay_time
        self._feedback = feedback
        self._wet_level = wet_level

        # Create the delay effect
        self._delay = pyo.Delay(input, delay=delay_time, feedback=feedback)

        # Mix the original signal with the delayed signal
        self._mix = pyo.Mix([input, self._delay * wet_level], voices=2)

        # Define the output
        self._base_objs = self._mix.getBaseObjects()

    def setDelayTime(self, delay_time):
        """Set the delay time."""
        self._delay.setDelay(delay_time)
        self._delay_time = delay_time

    def setFeedback(self, feedback):
        """Set the feedback amount."""
        self._delay.setFeedback(feedback)
        self._feedback = feedback

    def setWetLevel(self, wet_level):
        """Set the amplitude of the delayed signal."""
        self._wet_level = wet_level
        self._mix = pyo.Mix([self._input, self._delay * wet_level], voices=2)
        self._base_objs = self._mix.getBaseObjects()

    def getDelayTime(self):
        """Get the current delay time."""
        return self._delay_time

    def getFeedback(self):
        """Get the current feedback amount."""
        return self._feedback

    def getWetLevel(self):
        """Get the current wet level."""
        return self._wet_level