"""Knowledge-base pipeline (app/kb): the checks and parsers that stand in for
a person reviewing each page. No database or network needed."""

from app.kb import checks
from app.kb.drugnames import canonical, spellings, stripped
from app.kb.load import Bundle
from app.kb.readers.fda import match_key
from app.kb.readers.nfi import _label, _name, _split_label
from app.kb.readers.stw import _boilerplate, _transcript
from app.kb.sources import BY_KEY, SOURCES
from app.kb.text import chunk, numbers


PAGE = """DENGUE FEVER ICD-10-A90 Compensated shock Ringer's Lactate/ NS 10 ml/kg/hr
No Improvement RL 10-15ml/kg/hr Paracetamol for fever: avoid NSAIDs PLT <10.000/cumm"""


def test_numbers_are_written_one_way():
    assert numbers("10.0 mg, 0.50 g and 1,5 ml; 007") == {"10", "0.5", "1.5", "7"}


def test_a_number_the_page_lacks_is_caught():
    assert checks.unknown_numbers("RL 10-15 ml/kg/hr", PAGE) == set()
    assert checks.unknown_numbers("RL 20 ml/kg/hr", PAGE) == {"20"}


def test_coverage_counts_the_pages_words():
    assert checks.coverage(PAGE, PAGE) == 1.0
    assert checks.coverage("dengue fever", PAGE) < 0.3


def test_dose_rows_need_a_medicine_an_amount_and_the_pages_numbers():
    ok = {"drug": "Ringer's Lactate/ NS", "dose": "10 ml/kg/hr"}
    assert checks.dose_problem(ok, PAGE) == ""
    assert "not a medicine" in checks.dose_problem({"drug": "infusion rate", "dose": "10 ml/kg/hr"}, PAGE)
    assert "does not look like a dose" in checks.dose_problem({"drug": "Platelets", "dose": "PLT <10.000/cumm"}, PAGE)
    assert "numbers not on the page" in checks.dose_problem({"drug": "RL", "dose": "25 ml/kg/hr"}, PAGE)
    assert "drug name not on the page" in checks.dose_problem({"drug": "Amoxicillin", "dose": "10 ml/kg/hr"}, PAGE)


def test_a_source_with_too_many_refusals_fails_whole():
    assert not checks.too_many_rejects(kept=90, refused=10)
    assert checks.too_many_rejects(kept=60, refused=40)
    assert not checks.too_many_rejects(kept=3, refused=5)  # too few items to judge


def test_chunks_fit_and_tables_keep_their_header():
    table = "| Drug | Dose |\n|---|---|\n" + "\n".join(f"| drug{i} | {i} mg twice daily for five days |" for i in range(120))
    pieces = chunk(table, "NFI 2011 › Test", max_tokens=200)
    assert len(pieces) > 2
    assert all(p.startswith("| Drug | Dose |\n|---|---|") for p in pieces)
    assert chunk("short text", "crumb") == ["short text"]


def test_spellings_from_different_sources_share_one_key():
    assert canonical("Amoxycillin") == canonical("amoxicillin")
    assert canonical("Adrenaline (Epinephrine)") == canonical("epinephrine (adrenaline)") == "epinephrine"
    assert canonical("Acetaminophen") == "paracetamol"
    assert stripped("Metformin Hydrochloride") == "metformin"
    assert match_key("Amoxicillin and Clavulanate Potassium") == match_key("Amoxicillin + Clavulanic acid")
    assert spellings("Valproic acid (sodium valproate)") == ["Valproic acid (sodium valproate)", "Valproic acid", "sodium valproate"]


def test_bundle_records_every_spelling_as_a_drug_term():
    b = Bundle()
    key = b.drug("Adrenaline (Epinephrine)", schedule="H")
    assert key == "epinephrine" and b.drugs[key]["schedule"] == "H"
    assert {t["term"] for t in b.rows["kb_terms"]} == {"Adrenaline (Epinephrine)", "Adrenaline", "Epinephrine"}
    assert all(t["concept"] == "DRUG:epinephrine" for t in b.rows["kb_terms"])


def test_nfi_labels_tolerate_the_books_spelling_slips():
    assert _label("Avaialbility:") == "availability"
    assert _label("Dosage:") == "dose"
    assert _label("Adverse reactions") == "adverse_effects"
    assert _label("Doxycycline") is None
    segs = _split_label([(40.0, "Contraindications Porphyria.")])
    assert [s for _, s in segs] == ["Contraindications", "Porphyria."]


def test_nfi_drug_names_drop_headings_and_cross_references():
    assert _name(["24.5.1 Oxytocics", "Ergometrine"]) == "Ergometrine"
    assert _name(["Carbamazepine* (Refer Page No. 585)"]) == "Carbamazepine"
    assert _name(["Sulfamethoxazole +", "Trimethoprim"]) == "Sulfamethoxazole + Trimethoprim"


def test_stw_boilerplate_and_transcript():
    pages = ["disclaimer stw icmr dengue"] * 4 + ["disclaimer stw icmr malaria"] * 4
    assert {"disclaimer", "stw", "icmr"} <= _boilerplate(pages)
    assert "malaria" not in _boilerplate(pages)
    text = _transcript({"title": "Dengue", "sections": [{"heading": "Warning signs", "markdown": "- Persistent vomiting"}],
                        "doses": [{"drug": "RL", "dose": "10 ml/kg/hr"}], "red_flags": [{"sign": "Shock", "action": ""}]})
    assert "Persistent vomiting" in text and "10 ml/kg/hr" in text and "Shock" in text


def test_every_source_states_its_licence_and_reader():
    for s in SOURCES:
        assert s.licence and s.reader and s.files
        for dep in s.after:
            assert dep in BY_KEY
    # sources that need permission are loaded for testing only
    assert not BY_KEY["icmr-stw-vol1"].production_allowed
    assert not BY_KEY["nfi-2011"].production_allowed
    assert not BY_KEY["who-eml-2025"].production_allowed
    assert BY_KEY["nlem-2022"].production_allowed


def test_salt_only_medicines_keep_their_whole_name_for_us_labels():
    assert match_key("Magnesium sulphate") == match_key("MAGNESIUM SULFATE") == "magnesium sulfate"
    assert match_key("Potassium Nitrate") != match_key("Magnesium sulfate")
    assert match_key("Metformin Hydrochloride") == "metformin"


def test_brand_compositions_are_parsed_into_medicine_and_strength():
    from app.kb.readers.hf import composition, composition_key

    parts = composition("Amoxycillin  (500mg) +  Clavulanic Acid (125mg)")
    assert parts == [{"drug": "Amoxycillin", "strength": "500mg"}, {"drug": "Clavulanic Acid", "strength": "125mg"}]
    assert composition_key(parts) == "amoxicillin clavulanic acid"
    assert composition("Progesterone (Natural Micronized) (300mg)") == [
        {"drug": "Progesterone (Natural Micronized)", "strength": "300mg"}]
    assert composition_key(composition("Paracetamol (650mg)")) == "paracetamol"
    assert composition("-") == []


def test_reversed_symptom_rows_are_refused():
    from app.kb.readers import hf

    class FakeConn:
        def execute(self, sql):
            return [("muscle weakness",), ("fever",)] if "symptom" in sql else [("angiolipoma",), ("malaria",)]

    import json, tempfile, pathlib

    rows = [{"disease": "Muscle Weakness", "symptoms": "Angiolipoma"}, {"disease": "Malaria", "symptoms": "fever, chills"}]
    path = pathlib.Path(tempfile.mkdtemp()) / "data.json"
    path.write_text(json.dumps(rows))
    b = Bundle()
    hf._json_symptom([path], b, conn=FakeConn())
    assert [(r["disease"], r["symptom"]) for r in b.rows["kb_disease_symptoms"]] == [("Malaria", "fever"), ("Malaria", "chills")]
    assert b.rows["kb_quarantine"][0]["reason"].startswith("the 'disease' is a symptom")


def test_appendix_cell_starts_come_from_repeated_cell_positions():
    from app.kb.readers.nfi import _cell_starts

    def w(x, text):
        return {"x0": x, "x1": x + 5 * len(text), "text": text}

    lines = [[w(38, "Drug"), w(107, "GFR")]] + [[w(38, f"Drug{i}"), w(82, "D"), w(107, "75%"), w(132, "50%")] for i in range(6)]
    assert _cell_starts(lines, 38) == [39, 81, 108, 132]  # rounded to 3 points


# --- RAG: the two passes, labels and the dose check (no database: a fake retriever) ---

from app.kb import rag  # noqa: E402
from app.kb.retrieve import DIAGNOSIS, TREATMENT, Evidence, Passage, dose_found, label  # noqa: E402


def _passage(i, body, title="NFI 2011", tier=1, page=45):
    return Passage(i, "nfi-2011", title, tier, page, f"{title} › topic {i}", body, "drug:monograph", False)


class FakeRetriever:
    def __init__(self):
        self.asked = []
        self.topics = []

    def search(self, question, kind, k=8, topic_hint="", rerank_n=16, topics=()):
        self.asked.append((question, kind, topic_hint))
        self.topics.append(list(topics))
        if kind == DIAGNOSIS:
            return Evidence([_passage(1, "Warning signs: persistent vomiting, mucosal bleed", "ICMR STW", page=46)], question)
        return Evidence([_passage(2, "Paracetamol for fever: avoid NSAIDs"),
                         _passage(3, "Paracetamol Dose: Oral Adult- 0.5 to 1g every 4 to 6 h (max. 4g)")], question)

    def condition_doses(self, condition, limit=8):
        if "urinary" in condition.lower():
            return [{"drug": "Nitrofurantoin", "indication": "Uncomplicated UTI", "population": "adult", "dose": "100 mg",
                     "route": "oral", "frequency": "twice daily", "duration": "5 days", "page": 28,
                     "source": "ICMR STW 2019 Vol. 1", "tier": 1},
                    {"drug": "Syrup X", "indication": "UTI in children", "population": "child", "dose": "5 ml",
                     "route": "oral", "frequency": "", "duration": "", "page": 28, "source": "ICMR STW", "tier": 1}]
        return []

    def doses(self, drug):
        return [{"drug": "Ibuprofen", "dose": "400 mg three times daily", "frequency": "", "duration": "",
                 "source": "NFI 2011", "page": 50}] if "ibuprofen" in drug.lower() else []


class _Session:
    age, gender, symptoms, duration = 34, "female", "fever and body ache", "3 days"


def test_pass_one_asks_about_the_presentation_and_pass_two_about_the_conditions():
    r = FakeRetriever()
    first = rag.pass1(r, _Session(), [["fever", "high temperature"], ["myalgia", "body ache"]])
    second = rag.pass2(r, _Session(), [{"name": "Viral fever"}, {"name": "Dengue fever"}])
    assert r.asked[0] == ("woman with fever, myalgia for 3 days", DIAGNOSIS, "")
    assert r.asked[1] == ("Viral fever treatment and dose for woman", TREATMENT, "Viral fever")
    assert r.asked[2][0].startswith("Dengue fever treatment")
    # the same passage found for both conditions is listed once
    assert [p.id for p in second.passages] == [2, 3]
    sources = rag.number(first, second)
    assert [p.label for p in sources] == ["S1", "S2", "S3"]
    assert "[S1]" in first.prompt("Guideline passages") and "page 46" in first.prompt("Guideline passages")


def test_without_a_database_the_passes_say_so_instead_of_failing():
    ev = rag.pass1(None, _Session(), [["fever"]])
    assert ev.passages == [] and "not configured" in ev.note
    assert "none found" in ev.prompt("Guideline passages")


def test_a_written_dose_is_checked_against_guidelines_and_printed_doses():
    r = FakeRetriever()
    ev = Evidence([_passage(3, "Paracetamol Dose: Oral Adult- 0.5 to 1g every 4 to 6 h (max. 4g)")])
    label(ev)
    meds = rag.check_doses(r, [
        {"name": "Paracetamol", "dose": "1 g every 6 h"},          # numbers 1, 6: on the cited page
        {"name": "Paracetamol", "dose": "650 mg every 8 h"},       # 650, 8: not there
        {"name": "Ibuprofen", "dose": "400 mg three times daily"},  # from the printed dose rows
    ], ev)
    assert meds[0]["doseEvidence"] == {"found": True, "source": "[S1] NFI 2011, page 45"}
    assert meds[1]["doseEvidence"]["found"] is False
    assert meds[2]["doseEvidence"] == {"found": True, "source": "NFI 2011, page 50"}


def test_dose_found_needs_the_medicine_named_and_every_number():
    assert dose_found("500 mg", "Amoxicillin", ["Amoxicillin capsule 500 mg"])
    assert not dose_found("500 mg", "Amoxicillin", ["Metformin 500 mg"])
    assert not dose_found("500 mg twice for 5 days", "Amoxicillin", ["Amoxicillin 500 mg"])
    assert not dose_found("", "Amoxicillin", ["Amoxicillin 500 mg"])


def test_brands_the_patient_took_are_spelled_out_for_the_models():
    class Brands:
        def brand(self, name):
            return {"dolo 650": {"brand": "Dolo 650 Tablet", "composition": [{"drug": "Paracetamol", "strength": "650mg"}],
                                 "generic": "paracetamol"}}.get(name.lower())

    line = rag.brands_taken(Brands(), "Dolo 650, home remedy")
    assert line == "Medication already taken, from the brand list (check with the patient): Dolo 650 = Paracetamol 650mg."
    assert rag.brands_taken(Brands(), "") == "" and rag.brands_taken(None, "Dolo 650") == ""



def test_printed_doses_for_the_concluded_conditions_suit_the_patients_age():
    class Adult:
        age, gender = 30, "female"

    text, rows = rag.printed_doses(FakeRetriever(), Adult(), [{"name": "Urinary tract infection"}, {"name": "Viral fever"}])
    assert [r["drug"] for r in rows] == ["Nitrofurantoin"]  # the children's row is not offered for an adult
    assert "Urinary tract infection: Nitrofurantoin: 100 mg oral twice daily 5 days (adult; ICMR STW 2019 Vol. 1, page 28)" in text
    meds = rag.check_doses(None, [{"name": "Nitrofurantoin", "dose": "100 mg twice daily for 5 days"}], Evidence(), rows)
    assert meds[0]["doseEvidence"] == {"found": True, "source": "ICMR STW 2019 Vol. 1, page 28"}
    assert rag.printed_doses(None, Adult(), [{"name": "x"}]) == ("", [])


def test_stw_titles_lose_the_series_prefix():
    from app.kb.readers.stw import _title

    assert _title("Standard Treatment Workflow (STW) for the Management of DENGUE FEVER") == "Dengue Fever"
    assert _title("Management of DEPRESSION") == "Depression"
    assert _title("Acute Urinary Retention in Men (AUR)") == "Acute Urinary Retention in Men (AUR)"


def test_guideline_reader_headings_kinds_and_charts():
    from app.kb.readers.guideline import _NUMBERED, _REFERENCES, _diagram, _kind

    assert _NUMBERED.match("2.1 Clinical features")
    assert not _NUMBERED.match("2. Primaquine: 0.75 mg/kg body weight")  # a list item, not a heading
    assert _REFERENCES.match("References:") and _REFERENCES.match("7. Bibliography")
    assert (_kind("Chemoprophylaxis"), _kind("Treatment of severe malaria"), _kind("Danger signs")) == (
        "prevention", "treatment", "red_flags")
    chart = [{"text": "Treat with", "table": False}] * 30
    prose = [{"text": "Malaria is one of the major public health problems of the country", "table": False}] * 30
    assert _diagram(chart) and not _diagram(prose)


def test_dose_found_needs_the_dose_on_the_medicines_own_line():
    box = ("ICMR STW › UTI › Male Uti\n- Nitrofurantoin* 100 mg PO BD x 7d\n- TMP/SMX 1 DS tab PO BD x 7d\n"
           "- Ciprofloxacin 500 mg BD x 7 days")
    assert dose_found("500 mg", "Ciprofloxacin", [box])
    assert not dose_found("100 mg", "Ciprofloxacin", [box])
    # a text whose heading is about the medicine: any line counts
    assert dose_found("500 mg", "Amoxicillin", ["NFI › Amoxicillin › Dose\nOral: Adult- 500 mg every 8 h"])


def test_pass_two_adds_the_patients_box_from_the_same_page_and_drops_other_groups():
    from app.kb import rag

    male = _passage(10, "- Nitrofurantoin* 100 mg PO BD x 7d\n- Ciprofloxacin 500 mg BD x 7 days", "ICMR STW", page=28)
    male.breadcrumb = "ICMR STW › UTI (N39.0) › Male Uti [secondary care]"
    female = _passage(11, "- Nitrofurantoin* 100 mg PO BD x 5d\n- TMP/SMX 1 DS tab PO BD x 3d", "ICMR STW", page=28)
    female.breadcrumb = "ICMR STW › UTI (N39.0) › Cystitis/Uti In Females [secondary care]"
    child = _passage(12, "- Cefixime 8 mg/kg/day", "ICMR STW", page=28)
    child.breadcrumb = "ICMR STW › UTI (N39.0) › Uti In Children"

    class R(FakeRetriever):
        def search(self, question, kind, k=8, topic_hint="", rerank_n=16, topics=()):
            return Evidence([male], question)

        def page_boxes(self, p, limit=12):
            return [female, child]

    ev = rag.pass2(R(), _Session(), [{"name": "Cystitis"}])
    assert [p.id for p in ev.passages] == [11]

    class Man(_Session):
        gender = "male"

    assert [p.id for p in rag.pass2(R(), Man(), [{"name": "Cystitis"}]).passages] == [10]


def test_dose_conflicts_quote_the_guideline_line_for_the_reviewer():
    from app.kb import rag

    p = _passage(5, "- Nitrofurantoin* 100 mg PO BD x 7d\n- Ciprofloxacin 500 mg BD x 7 days", "ICMR STW", page=28)
    p.label = "S5"
    note = rag.dose_conflicts([{"name": "Ciprofloxacin", "dose": "100 mg"}, {"name": "Nitrofurantoin", "dose": "100 mg"}],
                              Evidence([p], "q"))
    assert "Medicine 1 (Ciprofloxacin 100 mg)" in note and "[S5] Ciprofloxacin 500 mg BD x 7 days" in note
    assert "Medicine 2" not in note



def test_dose_found_ignores_the_tablet_count():
    box = "ICMR STW › UTI › Cystitis/Uti In Females\n- Nitrofurantoin* 100 mg PO BD x 5d"
    assert dose_found("100 mg (1 tablet)", "Nitrofurantoin", [box])
    assert not dose_found("200 mg (2 tablets)", "Nitrofurantoin", [box])


def test_an_unreachable_knowledge_database_is_not_retried_for_every_look_up(monkeypatch):
    import psycopg

    from app.kb.retrieve import Retriever

    tries = []

    def refuse(*a, **k):
        tries.append(1)
        raise psycopg.OperationalError("connection timeout expired")

    monkeypatch.setattr(psycopg, "connect", refuse)
    r = Retriever("postgresql://x@nowhere/db")
    for _ in range(5):
        try:
            r.brand("Dolo 650")
        except Exception:
            pass
    assert len(tries) == 1  # one 5 s wait, not five


def test_pass_one_also_reads_the_pages_of_the_conditions_to_look_up():
    r = FakeRetriever()
    rag.pass1(r, _Session(), [["fever"], ["chills"]], ["Malaria", "Dengue fever", "Typhoid", "Extra"])
    assert r.topics[0] == ["Malaria", "Dengue fever", "Typhoid"]


def test_a_condition_name_becomes_the_words_a_guideline_heading_uses():
    from app.kb.retrieve import _topic_core

    assert _topic_core("Uncomplicated urinary tract infections") == "urinary tract infection"
    assert _topic_core("Dengue fever") == "dengue fever"
    assert _topic_core("Severe") == ""


def test_the_offline_case_carries_fewer_shorter_passages():
    from app.kb.retrieve import Evidence, Passage

    ps = [Passage(i, "stw", "ICMR STW", 1, 3, f"Fever › box {i}", "x" * 2000, "treatment", True, label=f"S{i}")
          for i in range(1, 7)]
    full, short = Evidence(passages=ps).prompt("Passages"), Evidence(passages=ps).prompt("Passages", 3, 500)
    assert full.count("\n[S") == 6 and short.count("\n[S") == 3
    assert len(short) < len(full) / 3
