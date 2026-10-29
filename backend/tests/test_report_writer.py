

def test_a_skin_cream_needs_its_strength_and_how_to_apply_it():
    from app.report_writer import _usable_dose

    cream = {"name": "Permethrin", "form": "cream", "route": "topical", "strength": "5% cream",
             "dose": "Apply a thin layer from the neck down"}
    assert _usable_dose(cream)
    assert not _usable_dose({**cream, "strength": ""})
    assert not _usable_dose({**cream, "route": "oral", "form": "tablet"})
    # the amount for one whole-body application, as the writer gives it
    assert _usable_dose({**cream, "dose": "About 30 grams"})


def test_the_condition_check_never_drops_the_most_likely_condition_for_a_less_likely_one():
    import asyncio

    from app.report_writer import check_conditions

    class Checker:
        name, clinical = "gemini:test", True

        async def json(self, system, user, thinking=None, **_):
            return {"conditions": [{"number": 1, "keep": False, "reason": "type not stated"},
                                   {"number": 2, "keep": True, "pointed_to_by": "thirst"}]}

    conditions = [{"name": "Uncontrolled type 2 diabetes", "likelihood": "high"},
                  {"name": "Diabetic ketoacidosis", "likelihood": "low"}]
    kept = asyncio.run(check_conditions(Checker(), "case", "", conditions))
    assert kept == {"Uncontrolled type 2 diabetes", "Diabetic ketoacidosis"}
