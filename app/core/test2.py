from pipewire_python import link

inputs = link.list_inputs()
outputs = link.list_outputs()

# Connect the last output to the last input -- during testing it was found that
# Midi channel is normally listed first, so this avoids that.
source = outputs[-1]
sink = inputs[-1]
source.connect(sink)

# Fun Fact! You can connect/disconnect in either order!
sink.disconnect(source) # Tada!

# Default Input/Output links will be made with left-left and right-right
# connections; in other words, a straight stereo connection.
# It's possible to manually cross the lines, however!
source.right.connect(sink.left)
source.left.connect(sink.right)