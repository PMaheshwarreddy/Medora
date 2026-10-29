"""The report pipeline: retrieval, the specialist panel, and the safety rules."""

import asyncio
from datetime import datetime, timezone

import numpy as np
import pytest
from sqlalchemy.orm import Session

from app.db import make_engine
from app.ingest.pipeline import init_db
from app.knowledge_base import KnowledgeIndex
from app.knowledge_models import Disease, DiseaseLink, Drug, Precaution, Symptom
from app.models import IntakeSession
from app.panel import SPECIALISTS, PanelError, PanelResult, parse_json
from app.triage import build_report, choose_panel

KNOWLEDGE = {
    "Urinary tract infection": (["Dysuria", "Burning sensation during urination", "Frequent urination", "Lower abdominal pain"], ["Nitrofurantoin", "Ciprofloxacin"], ["Drink plenty of water."]),
    "Diverticulitis": (["Lower abdominal pain", "Fever", "Constipation"], ["Metronidazole"], []),
    "Influenza": (["Fever", "Cough", "Body aches", "Sore throat"], ["Oseltamivir"], ["Rest at home."]),
    "Myocardial infarction": (["Chest pain", "Sweating", "Shortness of breath"], ["Aspirin"], ["Stop smoking."]),
}  # fmt: skip


class WordEmbedder:
    """Bag-of-words vectors: enough to stand in for meaning in a test."""

    model = "words"
    vocabulary: dict[str, int] = {}

    def embed(self, texts):
        rows = []
        for text in texts:
            row = np.zeros(64, dtype=np.float32)
            for word in text.lower().replace(",", " ").split():
                row[self.vocabulary.setdefault(word, len(self.vocabulary) % 64)] += 1
            rows.append(row / (np.linalg.norm(row) or 1))
        return np.asarray(rows)


@pytest.fixture
def kb(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'kb.db'}")
    init_db(engine)
    with Session(engine) as db:
        symptoms: dict[str, Symptom] = {}
        for name, (symptom_names, drugs, precautions) in KNOWLEDGE.items():
            disease = Disease(name=name, normalized_name=name.lower(), aliases=[], description=f"{name} described.")
            db.add(disease)
            db.flush()
            for s in symptom_names:
                if s not in symptoms:
                    symptoms[s] = Symptom(name=s, normalized_name=s.lower(), aliases=[])
                    db.add(symptoms[s])
                    db.flush()
                db.add(DiseaseLink(disease_id=disease.id, symptom_id=symptoms[s].id))
            for d in drugs:
                drug = Drug(name=d, normalized_name=d.lower(), aliases=[], uses=f"Used for {name}.")
                db.add(drug)
                db.flush()
                db.add(DiseaseLink(disease_id=disease.id, drug_id=drug.id))
            for p in precautions:
                db.add(Precaution(disease_id=disease.id, precaution=p))
        # A reversed row: a symptom posing as a disease with a huge symptom list.
        junk = Disease(name="Pain", normalized_name="pain", aliases=[])
        db.add(junk)
        db.flush()
        for i in range(95):
            filler = Symptom(name=f"Condition {i}", normalized_name=f"condition {i}", aliases=[])
            db.add(filler)
            db.flush()
            db.add(DiseaseLink(disease_id=junk.id, symptom_id=filler.id))
        db.add(DiseaseLink(disease_id=junk.id, symptom_id=symptoms["Fever"].id))
        db.commit()
    return KnowledgeIndex(engine, WordEmbedder(), tmp_path / "cache")


def session_for(symptoms, age=29, vitals=None):
    return IntakeSession(
        id="s" * 32, created_at=datetime.now(timezone.utc), mode="voice", name="Asha Rao",
        age=age, gender="female", phone="9876543210", email="", symptoms=symptoms,
        duration="2 days", medications="", vitals=vitals,
    )  # fmt: skip


class Understander:
    """Stands in for the model: answers each step by its instructions."""

    name = "understander"

    def __init__(self, symptoms, specialists, select=None, review=None, write=None, check=None):
        self.understanding = {"symptoms": symptoms, "specialists": specialists}
        self.select = select if select is not None else {"keep": [], "written": []}
        self.review = review if review is not None else {"unsafe": []}
        # The report writer's draft and the pharmacist's review of it.
        self.write = write if write is not None else {"clinical_summary": "", "medicines": []}
        self.check = check if check is not None else {
            "medicines": [],
            "conditions": [{"number": n, "approve": True} for n in range(1, 11)],
            "summary_ok": False,
        }
        self.calls = []

    async def json(self, system, user, thinking=None, **_):
        if "clinical pharmacist" in system:
            step, reply = "check", self.check
        elif "check the possible conditions" in system:
            # The condition check, answered from the test's verdicts.
            step = "fit"
            reply = self.check if isinstance(self.check, Exception) else {"conditions": [
                {"number": c["number"], "keep": c["approve"], "pointed_to_by": "the case" if c["approve"] else ""}
                for c in self.check.get("conditions", [])
            ]}
        elif "pre-consultation report a hospital doctor reads" in system:
            step, reply = "write", self.write
        elif "safety reviewer" in system:
            step, reply = "review", self.review
        elif "choose the precautions" in system:
            step, reply = "select", self.select
        else:
            step, reply = "understand", self.understanding
        self.calls.append((step, user))
        if isinstance(reply, Exception):
            raise reply
        return reply


class FakePanel:
    name = "fake-panel"

    def __init__(self, conclusion=None, opinions=None, error=None):
        self.conclusion, self.opinions, self.error = conclusion or {}, opinions, error
        self.case = self.members = None

    async def run(self, case, specialists, progress=None):
        self.case, self.members = case, specialists
        if progress is not None:
            for o in self.opinions or []:
                progress.answered(o["specialist"], "took_part" if o.get("relevant", True) else "stepped_aside")
            progress.at("chair")
        if self.error:
            raise self.error
        opinions = self.opinions or [
            {"specialist": s, "relevant": True, "assessment": f"{s} view.", "urgency": "soon", "conditions": []}
            for s in specialists
        ]
        return PanelResult(opinions, self.conclusion, self.name)


def run(coro):
    return asyncio.run(coro)


# --- retrieval ----------------------------------------------------------------


def test_retrieval_ranks_the_disease_that_explains_the_symptoms(kb):
    evidence = kb.retrieve([["dysuria", "burning sensation during urination"], ["frequent urination"], ["lower abdominal pain"]])
    # Diverticulitis shares one of the three symptoms: with that many
    # reported, a single shared symptom is not evidence.
    assert [c.name for c in evidence.candidates] == ["Urinary tract infection"]
    top = evidence.candidates[0]
    assert top.score > 0.9
    two = kb.retrieve([["lower abdominal pain"], ["fever"]])
    assert [c.name for c in two.candidates][0] == "Diverticulitis"
    # Two wordings of one complaint are one piece of evidence, not two.
    assert {m.group for m in evidence.matches} == {0, 1, 2}
    assert [d["name"] for d in top.drugs] == ["Ciprofloxacin", "Nitrofurantoin"]
    assert top.precautions == ["Drink plenty of water."]


def test_retrieval_matches_by_meaning_and_from_free_text(kb):
    evidence = kb.retrieve([["burning urination sensation"]], free_text="also a bit of fever and a sore throat since morning")
    names = {m.name: m.how for m in evidence.matches}
    assert names["Burning sensation during urination"] == "meaning"
    assert names["Sore throat"] == "name"  # found in the text, not in the phrase list
    assert kb.retrieve([["purple elephants"]]).candidates == []


def test_reversed_rows_never_become_candidates(kb):
    evidence = kb.retrieve([["fever"]])
    assert "Pain" not in [c.name for c in evidence.candidates]
    assert {"Influenza", "Diverticulitis"} <= {c.name for c in evidence.candidates}


def test_lookup_finds_a_condition_by_contained_name(kb):
    assert kb.lookup("Acute myocardial infarction (heart attack)").name == "Myocardial infarction"
    assert kb.lookup("Made-up syndrome") is None
    assert kb.mentions_drug("Take some aspirin for the pain") is True
    assert kb.mentions_drug("Drink water and rest") is False
    kb._drug_keys |= {"water"} - __import__("app.knowledge_base", fromlist=["x"])._EVERYDAY_SUBSTANCES
    assert kb.mentions_drug("Drink plenty of water") is False


# --- the panel ----------------------------------------------------------------


def test_panel_membership():
    assert choose_panel(["Cardiology", "Pulmonology"], 58, "male", 5) == ["Cardiology", "Pulmonology"]
    assert choose_panel(["Neurology"], 7, "female", 5) == ["Pediatrics", "Neurology"]
    assert choose_panel(["Pediatrics", "Obstetrics & Gynecology", "Cardiology"], 40, "male", 5) == ["Cardiology"]
    assert len(choose_panel(["Cardiology", "Neurology", "Urology", "Psychiatry", "Dermatology"], 30, "female", 3)) == 3
    # Only specialists: the generalist roles are not agents, and a plain
    # viral fever may concern no specialty at all.
    assert choose_panel(["Family Medicine", "Internal Medicine", "Emergency Medicine"], 30, "male", 5) == []
    assert not {"Family Medicine", "Internal Medicine", "Emergency Medicine"} & set(SPECIALISTS)


def test_department_is_a_real_department():
    from app.triage import _department

    assert _department("cardiology", "soon") == "Cardiology"
    assert _department("Family Medicine", "routine") == "General OPD"
    assert _department("Cardiology", "emergency") == "Emergency Department"


def test_model_replies_are_parsed_leniently():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Here you go: {"a": {"b": 2}} hope it helps') == {"a": {"b": 2}}
    with pytest.raises(PanelError):
        parse_json("I cannot answer in JSON")


def test_report_grounds_conditions_and_medicines_in_the_knowledge_base(kb):
    llm = Understander(
        [{"term": "dysuria", "plain": "burning sensation during urination"}, {"term": "frequent urination", "plain": "peeing often"}],
        ["Urology", "Obstetrics & Gynecology", "Not A Specialty"],
    )
    panel = FakePanel(
        {
            "summary": "Burning and frequent urination for two days.",
            "discussion": "All agreed on a urinary infection.",
            "urgency": "routine",
            "department": "General OPD",
            "possible_conditions": [
                {"name": "Uncomplicated urinary tract infection", "likelihood": "high", "reasoning": "Classic.", "raised_by": "Urology and the Emergency Physician"},
                {"name": "Myocardial infarction", "likelihood": "low", "reasoning": "Unlikely."},
                {"name": "Interstitial cystitis", "likelihood": "low", "reasoning": "Possible."},
            ],
            # One real match, one drug of a condition that was not listed, one invention.
            "medicines": [{"name": "nitrofurantoin", "purpose": "Treats the infection."}, {"name": "Metronidazole"}, {"name": "Wonderdrug"}],
            "lifestyle_advice": ["Wipe front to back."],
            "doctor_notes": ["Check for fever."],
        }
    )  # fmt: skip
    report = run(build_report(session_for("It burns when I pee and I go all the time"), llm, kb, panel, 5))

    assert panel.members == ["Urology", "Obstetrics & Gynecology"]
    assert "Asha" not in panel.case and "9876543210" not in panel.case  # no identity in the case
    assert "Urinary tract infection: score" in panel.case

    uti, heart, other = report["possibleConditions"]
    # The panel's own wording is shown; the knowledge-base disease stays linked.
    assert (uti["name"], uti["kbName"], uti["inKnowledgeBase"], uti["raisedBy"]) == (
        "Uncomplicated urinary tract infection", "Urinary tract infection", True, "Urology")
    assert uti["evidenceScore"] > 0.5
    # Named by the panel, not surfaced by the search, but looked up in the knowledge base.
    assert (heart["name"], heart["inKnowledgeBase"], heart["evidenceScore"]) == ("Myocardial infarction", True, 0.0)
    assert (other["name"], other["inKnowledgeBase"], other["evidenceScore"]) == ("Interstitial cystitis", False, None)

    # The panel's own medicine picks are only hints now: the report writer
    # decides, and here it wrote none.
    assert report["medicines"] == []
    assert report["knowledgeUsed"] is True and report["generator"] == "fake-panel"
    assert [o["specialist"] for o in report["panel"]] == panel.members


def test_urgency_can_only_be_raised(kb):
    llm = Understander([{"term": "chest pain", "plain": "chest pain"}], ["Cardiology"])
    calm = {"urgency": "routine", "department": "Cardiology", "possible_conditions": [{"name": "Myocardial infarction", "likelihood": "high"}]}

    # Vitals set a floor the panel cannot go below.
    low_oxygen = {"heart_rate": 80, "spo2": 88, "temperature_c": 36.8, "systolic": 120, "diastolic": 80}
    report = run(build_report(session_for("chest pain", 58, low_oxygen), llm, kb, FakePanel(calm), 5))
    assert report["urgency"] == "emergency"

    # One relevant specialist calling an emergency is not overruled below urgent.
    opinions = [
        {"specialist": "Pulmonology", "relevant": True, "assessment": "Fine.", "urgency": "routine"},
        {"specialist": "Cardiology", "relevant": True, "assessment": "Heart attack until proven otherwise.", "urgency": "emergency"},
    ]
    report = run(build_report(session_for("chest pain", 58), llm, kb, FakePanel(calm, opinions), 5))
    assert report["urgency"] == "urgent"

    # An irrelevant specialist's alarm does not count.
    opinions[1]["relevant"] = False
    report = run(build_report(session_for("chest pain", 58), llm, kb, FakePanel(calm, opinions), 5))
    assert report["urgency"] == "routine"


def test_without_the_panel_no_conditions_or_medicines_are_offered(kb):
    class Solo:
        name = "local-model"

        async def json(self, system, user, thinking=None, **_):
            return {"summary": "Chest pain.", "urgency": "soon", "department": "Cardiology", "precautions": ["Rest."],
                    "possible_conditions": [{"name": "Something invented"}], "medicines": [{"name": "Aspirin"}]}  # fmt: skip

    offline = run(build_report(session_for("chest pain"), Solo(), kb, None))
    assert offline["possibleConditions"] == [] and offline["medicines"] == [] and offline["panel"] == []
    assert "internet" in offline["panelNote"] and offline["generator"] == "local-model"

    failed = run(build_report(session_for("chest pain"), Solo(), kb, FakePanel(error=PanelError("rate limited")), 5))
    assert failed["possibleConditions"] == [] and "could not be reached" in failed["panelNote"]
    assert failed["summary"] == "Chest pain."


# --- precautions ---------------------------------------------------------------

UTI_PANEL = {
    "urgency": "soon", "department": "General OPD",
    "possible_conditions": [{"name": "Urinary tract infection", "likelihood": "high"}, {"name": "Influenza", "likelihood": "low"}],
}  # fmt: skip
UTI_SYMPTOMS = [{"term": "dysuria", "plain": "burning sensation during urination"}, {"term": "frequent urination", "plain": "peeing often"}]


def precautions_for(kb, llm, panel=UTI_PANEL, symptoms="It burns when I pee", **session):
    report = run(build_report(session_for(symptoms, **session), llm, kb, FakePanel(panel), 5))
    return report["precautions"], report["precautionsSource"]


def test_knowledge_base_precautions_are_offered_first_and_only_selected(kb):
    with Session(kb._engine) as db:
        uti = db.query(Disease).filter_by(normalized_name="urinary tract infection").one()
        db.add_all(Precaution(disease_id=uti.id, precaution=p) for p in ["Urinate after intercourse.", "Wipe from front to back.", "Avoid holding urine."])
        db.commit()
    llm = Understander(UTI_SYMPTOMS, ["Urology"], select={"keep": [1, 3, 4, 99], "written": ["Something extra to do today."]})
    lines, source = precautions_for(kb, llm)

    # The model only picks from the stored lines; with three kept, nothing is written.
    assert lines == ["Drink plenty of water.", "Wipe from front to back.", "Avoid holding urine."]
    assert source == "knowledge_base"

    # The warning-signs line is added even when the knowledge base supplies the rest.
    llm.select = {"keep": [1, 3, 4], "warning_signs": "Tell the staff at once if you get a fever or back pain."}
    lines, source = precautions_for(kb, llm)
    assert lines[-1] == "Tell the staff at once if you get a fever or back pain." and len(lines) == 4
    assert source == "mixed"
    offered = next(user for step, user in llm.calls if step == "select")
    assert "1. Drink plenty of water." in offered and "4. Avoid holding urine." in offered
    assert "Rest at home." not in offered  # influenza was only a low likelihood
    assert "Asha" not in offered
    assert [step for step, _ in llm.calls].count("review") == 1  # only the written line was reviewed


def test_missing_precautions_are_written_then_filtered_and_reviewed(kb):
    llm = Understander(
        UTI_SYMPTOMS, ["Urology"],
        select={"keep": [1], "written": [
            "Take ciprofloxacin twice a day.",            # names a drug
            "Take 500 mg of something for the pain.",      # a dose
            "You have a bladder infection, so rest.",      # a diagnosis
            "Rest.",                                       # too short to be useful
            "Go to the toilet as soon as you feel the need.",
            "Tell the staff at once if you get a fever or back pain.",
            "Sit in a very hot bath for an hour.",
        ]},
        review={"unsafe": [{"number": 3, "why": "risk of burns and fainting"}]},
    )  # fmt: skip
    lines, source = precautions_for(kb, llm)

    assert lines == [
        "Drink plenty of water.",
        "Go to the toilet as soon as you feel the need.",
        "Tell the staff at once if you get a fever or back pain.",
    ]
    assert source == "mixed"
    reviewed = next(user for step, user in llm.calls if step == "review")
    assert "ciprofloxacin" not in reviewed and "3. Sit in a very hot bath" in reviewed


def test_written_precautions_are_not_shown_without_a_review(kb):
    from app.llm import LlmError

    panel = {**UTI_PANEL, "possible_conditions": [{"name": "Interstitial cystitis", "likelihood": "high"}]}
    written = {"keep": [], "written": ["Go to the toilet as soon as you feel the need."]}

    lines, source = precautions_for(kb, Understander(UTI_SYMPTOMS, [], select=written), panel)
    assert (lines, source) == (["Go to the toilet as soon as you feel the need."], "written")

    lines, source = precautions_for(kb, Understander(UTI_SYMPTOMS, [], select=written, review=LlmError("down")), panel)
    assert (lines, source) == ([], "none")


def test_emergency_precautions_start_with_calling_for_help(kb):
    from app.llm import LlmError

    panel = {"urgency": "emergency", "department": "Cardiology", "possible_conditions": [{"name": "Myocardial infarction", "likelihood": "high"}]}
    chest = [{"term": "chest pain", "plain": "chest pain"}]
    llm = Understander(chest, ["Cardiology"], select={"keep": [], "written": ["Sit down and stay as still as you can."]})
    lines, source = precautions_for(kb, llm, panel, "crushing chest pain", age=58)
    assert lines == ["Tell the hospital staff now that you need urgent help.", "Sit down and stay as still as you can."]
    offered = next(user for step, user in llm.calls if step == "select")
    assert "Urgency: emergency" in offered
    # Stored prevention advice ("Stop smoking.") is not even offered in an emergency.
    assert "Stop smoking" not in offered and "(none)" in offered

    # If the model cannot be asked, stored prevention advice is not shown in an emergency.
    llm = Understander(chest, ["Cardiology"], select=LlmError("down"))
    lines, source = precautions_for(kb, llm, panel, "crushing chest pain", age=58)
    assert lines == ["Tell the hospital staff now that you need urgent help."] and source == "none"


def test_a_specialist_who_stepped_aside_is_credited_with_nothing(kb):
    llm = Understander([{"term": "dysuria", "plain": "burning sensation during urination"}], ["Urology", "Cardiology"])
    conclusion = {**UTI_PANEL, "possible_conditions": [{"name": "Urinary tract infection", "likelihood": "high", "raised_by": "Urology and Cardiology"}]}
    opinions = [
        {"specialist": "Urology", "relevant": True, "assessment": "Cystitis.", "urgency": "routine"},
        {"specialist": "Cardiology", "relevant": False, "assessment": "Not a cardiac problem.", "urgency": "emergency"},
    ]
    report = run(build_report(session_for("It burns when I pee"), llm, kb, FakePanel(conclusion, opinions), 5))
    assert report["possibleConditions"][0]["raisedBy"] == "Urology"
    assert [(o["specialist"], o["relevant"]) for o in report["panel"]][-1] == ("Cardiology", False)
    assert report["urgency"] == "soon"  # the alarm of someone who stepped aside does not count


def test_progress_follows_the_real_panel(kb):
    from app.progress import ReportProgress

    llm = Understander([{"term": "dysuria", "plain": "burning sensation during urination"}], ["Urology", "Cardiology"])
    opinions = [
        {"specialist": "Urology", "relevant": True, "assessment": "Cystitis.", "urgency": "routine"},
        {"specialist": "Cardiology", "relevant": False, "assessment": "Not cardiac.", "urgency": "routine"},
    ]
    progress = ReportProgress()
    run(build_report(session_for("It burns when I pee"), llm, kb, FakePanel(UTI_PANEL, opinions), 5, progress))
    shown = progress.to_json()
    # Who was asked is exactly who the pipeline chose, with each one's answer.
    assert [s["name"] for s in shown["specialists"]] == ["Urology", "Cardiology"]
    assert [s["state"] for s in shown["specialists"]] == ["took_part", "stepped_aside"]
    assert shown["stage"] == "precautions" and len(shown["roster"]) == 18

    offline = ReportProgress()
    run(build_report(session_for("It burns when I pee"), llm, kb, None, 5, offline))
    assert offline.stage == "writing" and offline.to_json()["specialists"] == []


UTI_DRAFT = {
    "clinical_summary": "A 29-year-old woman with two days of burning and frequent urination.",
    "medicines": [
        {"name": "nitrofurantoin", "dose": "100 mg", "frequency": "twice daily", "duration": "5 days",
         "route": "oral", "for_condition": "Urinary tract infection", "prescription": True},
        {"name": "Paracetamol", "dose": "500-1000 mg", "frequency": "every 6 hours as needed",
         "duration": "up to 3 days", "max_daily": "4 g", "for_condition": "pain"},
        {"name": "Tramadol", "dose": "50 mg", "frequency": "every 8 hours"},  # controlled
        {"name": "Ibuprofen", "dose": "as needed", "frequency": "when in pain"},  # no real dose
        {"name": "Ciprofloxacin", "dose": "500 mg", "frequency": "twice daily", "prescription": True},
    ],
    "lifestyle_advice": ["Drink plenty of water."],
    "doctor_notes": ["Check temperature: it was not measured."],
}
APPROVE_ALL_BUT_LAST = {
    "medicines": [{"number": n, "approve": n != 5} for n in range(1, 6)],
    "conditions": [{"number": n, "approve": True} for n in range(1, 6)],
    "summary_ok": True,
}


def written_report(kb, check=APPROVE_ALL_BUT_LAST, **session):
    llm = Understander(UTI_SYMPTOMS, ["Urology"], write=UTI_DRAFT, check=check)
    intake = session_for("It burns when I pee", **session)
    intake.medications = "Paracetamol 500 mg this morning"
    report = run(build_report(intake, llm, kb, FakePanel(UTI_PANEL), 5))
    return report, llm


def test_medicines_are_written_reviewed_then_ruled_by_code(kb):
    report, llm = written_report(kb)
    names = [m["name"] for m in report["medicines"]]
    # Tramadol is a controlled drug and "as needed" is no dose: code drops
    # them; ciprofloxacin was rejected by the reviewer.
    assert names == ["Nitrofurantoin", "Paracetamol"]
    nitro, para = report["medicines"]
    assert (nitro["source"], nitro["prescription"], nitro["dose"]) == ("knowledge_base", True, "100 mg")
    assert (para["source"], para["prescription"], para["maxDaily"]) == ("suggested", False, "4 g")
    # Already taken by the patient: said so, whatever the reviewer missed.
    assert "already taken" in para["caution"]
    assert "already taken" not in nitro["caution"]
    # A 29-year-old woman: every medicine carries a pregnancy check.
    cautions = {m["name"]: m["caution"].lower() for m in report["medicines"]}
    assert "hcg" in cautions["Nitrofurantoin"] and "hcg" not in cautions["Paracetamol"]
    assert not any("pregnan" in c for c in cautions.values())
    assert report["medicinesDropped"] == 3
    assert report["clinicalSummary"].startswith("A 29-year-old woman")
    assert report["doctorNotes"] == ["Check temperature: it was not measured."]
    # The reviewer saw exactly what the writer wrote.
    assert "Tramadol" in [u for step, u in llm.calls if step == "check"][0]


def test_no_written_medicines_without_review_for_children_or_in_an_emergency(kb):
    from app.llm import LlmError

    unreviewed, _ = written_report(kb, check=LlmError("down"))
    assert unreviewed["medicines"] == [] and "safety review" in unreviewed["medicinesNote"]
    assert unreviewed["clinicalSummary"] == ""  # an unreviewed summary is not shown either

    child, _ = written_report(kb, age=7)
    assert child["medicines"] == [] and "weight" in child["medicinesNote"]

    low_oxygen = {"heart_rate": 120, "spo2": 85, "temperature_c": 37.0, "systolic": 120, "diastolic": 80}
    emergency, _ = written_report(kb, vitals=low_oxygen)
    assert emergency["urgency"] == "emergency"
    assert emergency["medicines"] == [] and "immediate" in emergency["medicinesNote"]


def test_without_the_panel_online_the_writer_names_reviewed_conditions(kb):
    draft = {**UTI_DRAFT, "possible_conditions": [
        {"name": "Urinary tract infection", "likelihood": "high", "reasoning": "Burning and frequency."},
        {"name": "Kidney stone", "likelihood": "low", "reasoning": "Nothing suggests it."},
    ]}  # fmt: skip
    check = {**APPROVE_ALL_BUT_LAST, "conditions": [{"number": 1, "approve": True}, {"number": 2, "approve": False}]}
    llm = Understander(UTI_SYMPTOMS, ["Urology"], write=draft, check=check)
    llm.understanding.update({"summary": "Burning urination.", "urgency": "soon", "department": "Urology"})
    report = run(build_report(session_for("It burns when I pee"), llm, kb, FakePanel(error=PanelError("429")), 5))
    assert [c["name"] for c in report["possibleConditions"]] == ["Urinary tract infection"]
    assert report["possibleConditions"][0]["inKnowledgeBase"] is True
    assert "could not be reached" in report["panelNote"] and "AI" not in report["panelNote"]
    assert report["panel"] == []
    assert [m["name"] for m in report["medicines"]] == ["Nitrofurantoin", "Paracetamol"]


def test_vitals_are_judged_against_normal_ranges():
    from app.vitals import assess

    rows = {r["name"]: r for r in assess({"heart_rate": 73, "spo2": 92, "temperature_c": 38.4}, 30)}
    assert (rows["Heart rate"]["status"], rows["Heart rate"]["normal"]) == ("normal", "60–100 bpm")
    assert rows["Oxygen (SpO2)"]["status"] == "low"
    assert (rows["Temperature"]["status"], rows["Temperature"]["note"]) == ("high", "Fever.")
    assert "Blood pressure" not in rows  # not measured, not shown
    # Children's heart rate depends on age, so it is not judged.
    assert assess({"heart_rate": 120}, 4)[0]["status"] == "not_assessed"


def test_the_review_drops_panel_conditions_the_patient_s_account_does_not_support(kb):
    panel = {**UTI_PANEL, "possible_conditions": [
        {"name": "Urinary tract infection", "likelihood": "high", "reasoning": "Burning and frequency."},
        {"name": "Hepatitis B", "likelihood": "low", "reasoning": "Shares fatigue."},
    ]}  # fmt: skip
    check = {**APPROVE_ALL_BUT_LAST, "conditions": [{"number": 1, "approve": True}, {"number": 2, "approve": False}]}
    llm = Understander(UTI_SYMPTOMS, ["Urology"], write=UTI_DRAFT, check=check)
    report = run(build_report(session_for("It burns when I pee"), llm, kb, FakePanel(panel), 5))
    assert [c["name"] for c in report["possibleConditions"]] == ["Urinary tract infection"]
    assert report["conditionsRuledOut"] == ["Hepatitis B"]
    # The reviewer was shown the panel's conditions to judge.
    assert "2. Hepatitis B" in [u for step, u in llm.calls if step == "fit"][0]

    # Without a review the panel's conditions stand.
    from app.llm import LlmError

    llm = Understander(UTI_SYMPTOMS, ["Urology"], write=UTI_DRAFT, check=LlmError("down"))
    report = run(build_report(session_for("It burns when I pee"), llm, kb, FakePanel(panel), 5))
    assert len(report["possibleConditions"]) == 2 and report["conditionsRuledOut"] == []


def test_the_report_never_names_pregnancy_or_sexual_health_unless_the_patient_did():
    from app import sensitive

    report = {
        "possibleConditions": [{"name": "Ectopic pregnancy"}, {"name": "Appendicitis"}],
        "conditionsRuledOut": ["Pelvic inflammatory disease", "Sexually transmitted infection"],
        "precautions": ["Use a condom.", "Rest."], "lifestyleAdvice": [], "doctorNotes": ["Check for pregnancy."],
        "summary": "Lower abdominal pain since last night. Ectopic pregnancy must be excluded.",
        "clinicalSummary": "", "panel": [], "discussion": "",
        "medicines": [{"name": "Paracetamol", "caution": "Safe in pregnancy. Do not exceed 4 g.", "purpose": "", "forCondition": ""}],
    }  # fmt: skip
    out = sensitive.clean(report, "lower stomach pain", "", could_conceive=True)
    assert [c["name"] for c in out["possibleConditions"]] == ["Appendicitis"]
    assert out["precautions"] == ["Rest."]
    assert out["summary"] == "Lower abdominal pain since last night."
    assert out["medicines"][0]["caution"] == "Do not exceed 4 g."
    assert out["doctorNotes"] == [sensitive.DOCTOR_CHECK]
    assert "Sexually transmitted infection" not in out["conditionsRuledOut"]

    # The patient raised it: nothing is hidden.
    kept = sensitive.clean({"possibleConditions": [{"name": "Ectopic pregnancy"}]}, "I am pregnant and have pain", "", True)
    assert kept["possibleConditions"] == [{"name": "Ectopic pregnancy"}]


def test_guideline_passages_reach_the_panel_and_writer_and_stay_with_the_doctor(kb):
    from tests.test_kb import FakeRetriever

    llm = Understander([{"term": "dysuria", "plain": "burning when passing urine"}], ["Urology"])
    panel = FakePanel({
        "summary": "Burning urination.", "urgency": "routine", "department": "General OPD",
        "possible_conditions": [{"name": "Urinary tract infection", "likelihood": "high", "reasoning": "Classic."}],
    })  # fmt: skip
    retriever = FakeRetriever()
    report = run(build_report(session_for("It burns when I pee"), llm, kb, panel, 5, retriever=retriever))

    # pass 1 went to the panel, labelled for citation
    assert "Guideline passages on assessing this presentation" in panel.case and "[S1]" in panel.case
    # pass 2 asked about what the panel concluded
    assert any(q.startswith("Urinary tract infection treatment") for q, *_ in retriever.asked)
    evidence = report["doctorView"]["guidelineEvidence"]
    assert [e["label"] for e in evidence] == ["S1", "S2", "S3"]
    assert evidence[0]["sourceTitle"] == "ICMR STW" and evidence[0]["pass"] == "diagnosis" and evidence[0]["page"] == 46

    from app.routers.reports import for_patient

    shown = for_patient(report)
    assert "doctorView" not in shown and "guidelineEvidence" not in shown



def test_the_report_model_writes_the_final_report_and_the_panel_model_does_not(kb):
    """writer_llm takes the draft, the condition check and the review; the
    main model keeps symptom understanding and precautions."""
    main = Understander([{"term": "dysuria", "plain": "burning when passing urine"}], ["Urology"])
    writer = Understander([], [])
    writer.name = "gemini:report-model"
    panel = FakePanel({"summary": "Burning urination.", "urgency": "routine", "department": "General OPD",
                       "possible_conditions": [{"name": "Urinary tract infection", "likelihood": "high", "reasoning": "x"}]})
    report = run(build_report(session_for("It burns when I pee"), main, kb, panel, 5, writer_llm=writer))
    assert {"write", "fit"} <= {step for step, _ in writer.calls}
    assert not {"write", "fit", "check"} & {step for step, _ in main.calls}
    assert "understand" in {step for step, _ in main.calls}
    assert report["reportWriter"] == "gemini:report-model"


def test_a_child_sent_to_general_opd_goes_to_pediatrics():
    from app.triage import _department

    assert _department("General OPD", "soon", 6) == "Pediatrics"
    assert _department("Ophthalmology", "soon", 6) == "Ophthalmology"
    assert _department("General OPD", "soon", 30) == "General OPD"
    assert _department("Pediatrics", "emergency", 6) == "Emergency Department"


def test_a_condition_finds_its_knowledge_base_disease_by_another_name():
    from app.knowledge_base import Candidate, Evidence
    from app.triage import _candidate_for

    scabies = Candidate(disease_id=1, name="Acariasis", score=0.8, matched=["itching"], symptom_count=4,
                        aliases=["scabies", "sarcoptic itch"])
    found = _candidate_for("scabies", Evidence(candidates=[scabies]))
    assert found is scabies


def test_offline_the_chair_concludes_alone_and_precautions_need_no_model():
    from app import precautions
    from app.knowledge_base import Evidence
    from app.triage import choose_panel

    assert choose_panel(["Urology"], 6, "male", 0) == []
    assert choose_panel(["Urology"], 6, "male", 1) == ["Pediatrics"]

    class NoCalls:
        async def json(self, *a, **k):
            raise AssertionError("no model call offline")

    lines, source = run(precautions.choose(NoCalls(), "case", [], "soon", Evidence(), None, select=False))
    assert isinstance(lines, list)


def test_local_model_calls_take_turns():
    import asyncio

    import httpx

    from app.llm import OllamaLlm

    running, most = 0, 0

    async def answer(request):
        nonlocal running, most
        running += 1
        most = max(most, running)
        await asyncio.sleep(0.01)
        running -= 1
        return httpx.Response(200, json={"message": {"content": "{\"ok\": true}"}})

    real = httpx.AsyncClient

    class Client(real):
        def __init__(self, *a, **k):
            super().__init__(transport=httpx.MockTransport(answer))

    llm = OllamaLlm("http://ollama", "turns-test", clinical=True, threads=10)

    async def three():
        httpx.AsyncClient = Client
        try:
            return await asyncio.gather(*(llm.json("s", "u") for _ in range(3)))
        finally:
            httpx.AsyncClient = real

    assert run(three()) == [{"ok": True}] * 3
    assert most == 1


def test_a_stuck_model_call_is_stopped_and_tried_once_more():
    import asyncio

    import pytest

    from app.llm import with_retries

    calls = 0

    async def stuck():
        nonlocal calls
        calls += 1
        await asyncio.sleep(5)

    with pytest.raises(TimeoutError):
        run(with_retries(stuck, "test", timeout=0.05))
    assert calls == 2

    async def slow_then_fine():
        nonlocal calls
        calls += 1
        if calls == 3:
            await asyncio.sleep(5)
        return "ok"

    assert run(with_retries(slow_then_fine, "test", timeout=0.05)) == "ok"
