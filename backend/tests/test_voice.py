

def test_greeting_is_short_and_english_and_asks_the_language_only_after_a_bare_hello():
    from app.voice import system_instruction

    text = system_instruction(True, "auto")
    assert "Hi, I'm Dr. Medora. How can I help you today?" in text
    assert "Which language are you comfortable with, English or Malayalam?" in text
    assert "നമസ്കാരം" not in text.split("LANGUAGE")[0]


def test_pregnancy_waits_for_gender_and_habits_are_for_adult_men():
    from app.voice import clean_intake, system_instruction

    text = system_instruction(True, "en")
    assert "Always ask gender: never guess it" in text
    assert "ONLY in step 4, straight after the patient has told you their gender" in text
    assert "HABITS, MEN ONLY" in text and "Never ask women or children" in text
    assert clean_intake({"habits": "smokes 5 a day"}) == {"habits": "smokes 5 a day"}


def test_patient_speech_is_transcribed_as_english_or_malayalam():
    from app.voice import TRANSCRIBE_LANGUAGES

    assert TRANSCRIBE_LANGUAGES == ["en-IN", "ml-IN"]
