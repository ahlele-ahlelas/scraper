import threading

# This module is imported once and cached by Python.
# Both the Streamlit UI and background threads share this same object.
shared = {
    'logs':       [],
    'running':    False,
    'done':       False,
    'saved':      [],
    'stop_event': None,
}
