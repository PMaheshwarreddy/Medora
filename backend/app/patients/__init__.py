"""Patient records: one per person per hospital, so a returning patient's
visits are linked and the doctor (and the report AI) can use the history.

The kiosk only ever sees a masked first name and an age when it looks a
phone number up (several people often share one phone in India); the
history itself is shown only in the doctor portal.
"""
