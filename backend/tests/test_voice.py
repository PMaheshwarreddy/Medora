

def test_greeting_is_short_and_english_and_asks_the_language_only_after_a_bare_hello():
    from app.voice import system_instruction

    text = system_instruction(True, "auto")
    assert "Hi, I'm Dr. Medora. How can I help you today?" in text
    assert "Which language are you comfortable with, English or Malayalam?" in text
    assert "നമസ്കാരം" not in text.split("LANGUAGE")[0]


def test_age_and_gender_come_first_and_habits_are_for_every_adult():
    from app.voice import clean_intake, system_instruction

    text = system_instruction(True, "en")
    assert "Step 2, age and gender, before anything else" in text
    assert text.index("Step 2, age and gender") < text.index("Step 3, the complaint")
    assert "Always ask gender: never guess it" in text
    assert "ONLY in step 2, straight after the patient has told you their gender" in text
    # Women smoke and drink too (the user's correction of 2026-10-29).
    assert "HABITS, ADULTS ONLY (18 and over, men and women alike)" in text
    assert "MEN ONLY" not in text and "Never ask children these questions" in text
    assert clean_intake({"habits": "smokes 5 a day"}) == {"habits": "smokes 5 a day"}


def test_one_question_per_reply_and_an_answer_fills_only_its_own_question():
    from app.voice import system_instruction

    text = system_instruction(True, "en")
    assert 'Wrong: "How long have you had the fever? Do you have any allergies?"' in text
    assert "Never save one answer into two fields" in text
    assert "how long it has been going on, as a question of its own" in text


def test_vitals_are_always_taken_and_the_band_is_shown_by_the_tool_call():
    from app.voice import system_instruction, tool_declarations

    text = system_instruction(True, "en")
    assert "never skip this step" in text and "call request_vitals in that same reply" in text
    assert "vitals_needed" not in text
    assert "vitals_needed" not in {t["name"] for t in tool_declarations()}
    # The per-complaint decision only when the settings ask for it.
    assert "First call vitals_needed" in system_instruction(True, "en", decide_vitals=True)
    assert "vitals_needed" in {t["name"] for t in tool_declarations(decide_vitals=True)}


def test_malayalam_starts_in_malayalam_with_the_right_greeting():
    from app.voice import GREETING, system_instruction

    text = system_instruction(True, "ml")
    assert f'Say exactly: "{GREETING["ml"]}"' in text
    assert "എനിക്ക് നിങ്ങളെ എങ്ങനെ സഹായിക്കാൻ കഴിയും" in GREETING["ml"]
    assert "Hi, I'm Dr. Medora" not in text


def test_a_restarted_conversation_carries_on_and_resume_says_no_welcome_back():
    from app.voice import RESUMED, system_instruction

    text = system_instruction(True, "en", {"symptoms": "fever", "age": 30, "bogus": "x"}, vitals_taken=True)
    assert "CARRYING ON" in text and "symptoms: fever; age: 30" in text and "bogus" not in text
    assert "do not call request_vitals again" in text
    assert "CARRYING ON" not in system_instruction(True, "en")
    assert "do not say welcome back" in RESUMED


def test_patient_speech_is_transcribed_as_english_or_malayalam():
    from app.voice import TRANSCRIBE_LANGUAGES

    assert TRANSCRIBE_LANGUAGES == ["en-IN", "ml-IN"]
