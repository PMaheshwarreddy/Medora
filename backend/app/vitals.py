"""Each measured vital against its normal range, for the report.

Done in code, never by a model: the ranges are fixed and the same reading
must always get the same verdict. They are common adult resting ranges and,
like the urgency thresholds in `triage.vital_flags`, await clinician review.
Heart rate and blood pressure are not judged for children, whose normal
ranges depend on age.
"""


def _row(name: str, value: str, normal: str, status: str, note: str = "") -> dict:
    # status: normal | low | high | not_assessed
    return {"name": name, "value": value, "normal": normal, "status": status, "note": note}


def assess(vitals: dict | None, age: int) -> list[dict]:
    """The measured vitals, each with its normal range and a verdict.
    Vitals the band did not measure are left out."""
    v = vitals or {}
    rows: list[dict] = []
    adult = age >= 18

    hr = v.get("heart_rate")
    if hr is not None:
        if not adult:
            rows.append(_row("Heart rate", f"{hr} bpm", "depends on age", "not_assessed"))
        elif hr < 60:
            rows.append(_row("Heart rate", f"{hr} bpm", "60–100 bpm", "low", "Slower than the usual resting rate."))
        elif hr > 100:
            rows.append(_row("Heart rate", f"{hr} bpm", "60–100 bpm", "high", "Faster than the usual resting rate."))
        else:
            rows.append(_row("Heart rate", f"{hr} bpm", "60–100 bpm", "normal"))

    spo2 = v.get("spo2")
    if spo2 is not None:
        if spo2 >= 95:
            rows.append(_row("Oxygen (SpO2)", f"{spo2}%", "95–100%", "normal"))
        elif spo2 >= 90:
            rows.append(_row("Oxygen (SpO2)", f"{spo2}%", "95–100%", "low", "Below normal."))
        else:
            rows.append(_row("Oxygen (SpO2)", f"{spo2}%", "95–100%", "low", "Very low: needs attention now."))

    temp = v.get("temperature_c")
    if temp is not None:
        shown = f"{temp:.1f} °C"
        if temp >= 38:
            rows.append(_row("Temperature", shown, "36.1–37.2 °C", "high", "Fever."))
        elif temp > 37.2:
            rows.append(_row("Temperature", shown, "36.1–37.2 °C", "high", "Slightly raised."))
        elif temp < 35:
            rows.append(_row("Temperature", shown, "36.1–37.2 °C", "low", "Low body temperature."))
        elif temp < 36.1:
            rows.append(_row("Temperature", shown, "36.1–37.2 °C", "low", "Slightly low."))
        else:
            rows.append(_row("Temperature", shown, "36.1–37.2 °C", "normal"))

    sys, dia = v.get("systolic"), v.get("diastolic")
    if sys is not None and dia is not None:
        shown = f"{sys}/{dia} mmHg"
        if not adult:
            rows.append(_row("Blood pressure", shown, "depends on age", "not_assessed"))
        elif sys < 90 or dia < 60:
            rows.append(_row("Blood pressure", shown, "90–119 / 60–79 mmHg", "low", "Low."))
        elif sys >= 140 or dia >= 90:
            rows.append(_row("Blood pressure", shown, "90–119 / 60–79 mmHg", "high", "High."))
        elif sys >= 120 or dia >= 80:
            rows.append(_row("Blood pressure", shown, "90–119 / 60–79 mmHg", "high", "Elevated."))
        else:
            rows.append(_row("Blood pressure", shown, "90–119 / 60–79 mmHg", "normal"))
    return rows


def describe(rows: list[dict]) -> str:
    """The assessment as one line for a model to read."""
    if not rows:
        return "Vitals: not measured."
    parts = [
        f"{r['name']} {r['value']} ({'normal' if r['status'] == 'normal' else r['note'] or r['status']})"
        for r in rows
    ]
    return "Vitals assessment: " + "; ".join(parts)
