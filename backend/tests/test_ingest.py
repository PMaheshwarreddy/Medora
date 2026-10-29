import asyncio
import json

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db import make_engine
from app.ingest import records
from app.ingest.articles import extract_article
from app.ingest.pipeline import IngestError, Pipeline, init_db, legacy_tables
from app.ingest.plan import Plan
from app.ingest.planner import make_plan
from app.ingest.sniff import sniff
from app.ingest.transform import apply_plan, check_name, clean_name, clean_text, fuzzy_key, normalize
from app.knowledge_models import Disease, DiseaseLink, Drug, Precaution, Symptom
from app.llm import LlmError

LINK_PLAN = {
    "content": "records",
    "verdict": "usable",
    "summary": "Diseases with their symptoms",
    "confidence": 0.95,
    "outputs": [
        {"kind": "link", "disease": {"sources": ["disease"]}, "symptom": {"sources": ["symptoms"], "split": ","}}
    ],
}


class ScriptedLlm:
    """Answers from a list, in order, and records what it was asked."""

    name = "scripted"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    async def json(self, system, user):
        self.prompts.append(user)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture
def engine(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'kb.db'}")
    init_db(engine)
    return engine


def count(engine, model):
    with Session(engine) as db:
        return db.scalar(select(func.count()).select_from(model))


def run(coro):
    return asyncio.run(coro)


# --- reading files ----------------------------------------------------------


def test_csv_rows_are_repaired(tmp_path):
    path = tmp_path / "messy.csv"
    path.write_text(
        "disease,symptoms\n"
        '"Flu,""fever, cough"""\n'  # whole row quoted as one field
        "Cold,sneezing,runny nose\n"  # unquoted list spilled into extra fields
        'Acne,"pimples, blackheads"\n'
        "\n"
    )
    assert list(records.iter_csv(path)) == [
        {"disease": "Flu", "symptoms": "fever, cough"},
        {"disease": "Cold", "symptoms": "sneezing, runny nose"},
        {"disease": "Acne", "symptoms": "pimples, blackheads"},
    ]


def test_json_records_are_found_and_streamed(tmp_path):
    path = tmp_path / "labels.json"
    path.write_text(
        json.dumps(
            {
                "meta": {"total": 2},
                "results": [
                    {"openfda": {"generic_name": ["IBUPROFEN"], "brand_name": ["Advil", "Motrin"]}, "purpose": ["Pain reliever"]},
                    {"openfda": {}, "purpose": ["Antacid"]},
                ],
            }
        )
    )
    sniffed = sniff(path)
    assert (sniffed.format, sniffed.record_path) == ("json", "results")
    assert "openfda.generic_name[]" in sniffed.columns
    first, second = records.iter_json(path, "results")
    assert records.get_values(first, "openfda.brand_name[]") == ["Advil", "Motrin"]
    assert records.get_values(first, "openfda.generic_name[0]") == ["IBUPROFEN"]
    assert records.get_values(second, "openfda.generic_name[]") == []
    assert records.json_prefix("graphs[].nodes") == "graphs.item.nodes.item"


def test_obo_terms(tmp_path):
    path = tmp_path / "hp.obo"
    path.write_text(
        "format-version: 1.2\n\n[Term]\nid: HP:1\nname: Headache\n"
        'def: "Pain in the head." [ref]\nsynonym: "Cephalgia" EXACT []\n\n'
        "[Term]\nid: HP:2\nname: Old term\nis_obsolete: true\n\n[Typedef]\nid: part_of\nname: part of\n"
    )
    assert sniff(path).format == "obo"
    assert list(records.iter_obo(path)) == [
        {"id": "HP:1", "name": "Headache", "definition": "Pain in the head.", "synonyms": ["Cephalgia"]}
    ]


def test_format_comes_from_content_not_name(tmp_path):
    code = tmp_path / "diseases_final.csv"
    code.write_text("import json\nfrom pathlib import Path\n\nprint('x')\n")
    article = tmp_path / "data.bin"
    article.write_text("Disease : Asthma\n\nAsthma is a long-term disease.\n\n== Causes ==\nUnknown.\n")
    assert sniff(code).format == "code"
    assert sniff(article).format == "text"
    assert sniff(article).headings == ["Causes"]


# --- cleaning and validation ------------------------------------------------


def test_names_are_cleaned_and_matched():
    assert clean_name("  skin_rash ") == "Skin rash"
    assert clean_name("dischromic _patches") == "Dischromic patches"
    assert clean_name("FLUTICASONE PROPIONATE") == "Fluticasone propionate"
    assert clean_name("HIV") == "HIV"
    assert clean_name("Crohn's disease.") == "Crohn's disease"
    assert normalize("Skin_Rash") == normalize("skin rash") == "skin rash"
    assert normalize("Sjögren syndrome") == "sjogren syndrome"
    assert clean_name("HIV/AIDS") == "HIV/AIDS"
    assert clean_name("COVID-19") == "COVID-19"
    assert clean_name("TUBERCULOSIS") == "Tuberculosis"
    assert normalize("Alzheimer\u0092s Disease") == normalize("Alzheimer's disease") == "alzheimers disease"
    assert normalize("Obsessive–compulsive disorder") == normalize("Obsessive-compulsive disorder")
    assert fuzzy_key("chicken pox") == fuzzy_key("chickenpox")
    assert fuzzy_key("headaches") == fuzzy_key("headache")
    assert fuzzy_key("diabetes mellitus") != fuzzy_key("diabetes insipidus")


def test_name_validation():
    assert check_name("symptoms", "Fever") is None
    assert check_name("symptoms", "x") == "name_too_short"
    assert check_name("symptoms", "12345") == "name_has_no_letters"
    assert check_name("diseases", "Unknown") == "name_is_placeholder"
    assert check_name("drugs", "Inhaled corticosteroids") == "name_is_a_drug_class"
    assert check_name("drugs", "Long-acting beta agonists") == "name_is_a_drug_class"
    assert check_name("drugs", "Hydrocortisone") is None
    assert check_name("drugs", "Oral rehydration salts") is None
    sentence = "There is a popular misconception that tuberculosis is purely a disease of the lungs"
    assert check_name("symptoms", sentence) == "name_is_a_sentence"


def test_text_is_capped_at_a_sentence_and_headings_dropped():
    long = "First sentence. " * 200
    assert clean_text(long).endswith(".") and len(clean_text(long)) <= 2000
    assert clean_text("1 INDICATIONS AND USAGE Drug X is indicated for asthma.") == "Drug X is indicated for asthma."
    assert clean_text("ADVERSE REACTIONS The most frequent reactions are mild.") == "The most frequent reactions are mild."
    assert clean_text("DOSAGE AND ADMINISTRATION (See also WARNINGS) Take one.") == "(See also WARNINGS) Take one."
    assert clean_text("ISONIAZID tablets are white.") == "ISONIAZID tablets are white."


def test_apply_plan_stages_and_rejects():
    plan = Plan.model_validate(LINK_PLAN)
    staged = apply_plan(
        plan,
        [
            {"disease": "Flu", "symptoms": "fever, cough_dry, "},
            {"disease": "flu", "symptoms": "Fever, 123"},
            {"disease": "", "symptoms": "fever"},
        ],
    )
    assert set(staged.entities["diseases"]) == {"flu"}
    assert set(staged.entities["symptoms"]) == {"fever", "cough dry"}
    assert staged.links == {("flu", "symptoms", "fever"), ("flu", "symptoms", "cough dry")}
    assert staged.rejected == {"symptoms:name_has_no_letters": 1}


# --- planning ---------------------------------------------------------------


def test_plan_validation():
    with pytest.raises(ValueError, match="exactly one"):
        Plan.model_validate({**LINK_PLAN, "outputs": [{"kind": "link", "disease": {"sources": ["d"]}}]})
    with pytest.raises(ValueError, match="no column"):
        Plan.model_validate(
            {**LINK_PLAN, "outputs": [{"kind": "entity", "table": "symptoms", "name": {"sources": ["n"]}, "fields": {"dosage": {"sources": ["d"]}}}]}
        )
    junk = Plan.model_validate({**LINK_PLAN, "verdict": "junk"})
    assert junk.outputs == []


def test_planner_retries_an_unexecutable_plan(tmp_path):
    path = tmp_path / "a.csv"
    path.write_text("disease,symptoms\nFlu,fever\nCold,sneezing\n")
    wrong = json.loads(json.dumps(LINK_PLAN))
    wrong["outputs"][0]["disease"]["sources"] = ["Disease Name"]
    llm = ScriptedLlm(wrong, LINK_PLAN)
    plan = run(make_plan(llm, path.name, sniff(path)))
    assert plan.outputs[0].disease.sources == ["disease"]
    assert "'Disease Name' is not one of the available fields" in llm.prompts[1]

    llm = ScriptedLlm(wrong, wrong, wrong)
    with pytest.raises(LlmError, match="valid plan"):
        run(make_plan(llm, path.name, sniff(path)))


def test_article_extraction_drops_names_not_in_the_text():
    text = "Asthma is a long-term disease of the airways. Symptoms include wheezing and coughing. Salbutamol relieves attacks."
    llm = ScriptedLlm(
        {
            "disease": "Asthma",
            "aliases": ["Bronchial hyperreactivity syndrome"],
            "description": "A long-term airway disease.",
            "causes": "",
            "symptoms": ["wheezing", "coughing", "blue lips"],
            "drugs": ["salbutamol", "montelukast"],
            "precautions": ["Avoid smoke."],
        }
    )
    record, dropped = run(extract_article(llm, text))
    assert record["symptoms"] == ["wheezing", "coughing"]
    assert record["drugs"] == ["salbutamol"]
    assert set(dropped) == {"alias: Bronchial hyperreactivity syndrome", "symptom: blue lips", "drug: montelukast"}

    with pytest.raises(LlmError, match="not an article"):
        run(extract_article(ScriptedLlm({"disease": ""}), text))
    with pytest.raises(LlmError, match="does not occur"):
        run(extract_article(ScriptedLlm({"disease": "Malaria"}), text))


# --- the whole pipeline -----------------------------------------------------


def make_pipeline(engine, tmp_path, *replies):
    return Pipeline(engine, ScriptedLlm(*replies), tmp_path / "cache")


def test_plan_approve_load_is_idempotent_and_undoable(engine, tmp_path):
    path = tmp_path / "x.csv"
    path.write_text("disease,symptoms\nFlu,\"fever, cough\"\nCold,\"cough, sneezing\"\nflu,Fever\n")
    pipeline = make_pipeline(engine, tmp_path, LINK_PLAN)

    planned, created = run(pipeline.plan_file(path))
    assert created and planned.status == "planned"
    assert planned.stats["preview"]["links"] == 4
    assert planned.stats["needs_review"] == []
    assert count(engine, Disease) == 0  # planning writes no knowledge

    with pytest.raises(IngestError, match="approve it"):
        pipeline.load(planned.id)
    pipeline.approve(planned.id)
    loaded = pipeline.load(planned.id)
    assert loaded.status == "loaded"
    assert (count(engine, Disease), count(engine, Symptom), count(engine, DiseaseLink)) == (2, 3, 4)
    assert loaded.stats["loaded"]["links"] == {"created": 4, "already_present": 0}

    # The same content under another name is recognised, not planned again.
    copy = tmp_path / "x_final_v2.csv"
    copy.write_bytes(path.read_bytes())
    again, created = run(pipeline.plan_file(copy))
    assert not created and again.id == planned.id

    # Re-loading the same facts from a differently shaped file adds nothing.
    other = tmp_path / "y.csv"
    other.write_text("disease,symptoms\nFLU,cough\nFlu,chills\n")
    second, _ = run(Pipeline(engine, ScriptedLlm(LINK_PLAN), tmp_path / "cache").plan_file(other))
    pipeline.approve(second.id)
    stats = pipeline.load(second.id).stats["loaded"]
    assert stats["diseases"]["created"] == 0
    assert stats["symptoms"]["created"] == 1
    assert stats["links"] == {"created": 1, "already_present": 1}

    # Undoing the second run removes only what it added.
    assert pipeline.undo(second.id) == {"links": 1, "precautions": 0, "symptoms": 1, "drugs": 0, "diseases": 0}
    assert (count(engine, Disease), count(engine, Symptom), count(engine, DiseaseLink)) == (2, 3, 4)

    # Undo out of order: the first run's rows stay while the second run's
    # links still use them, and go when that run is undone too.
    pipeline.approve(second.id)
    pipeline.load(second.id)
    pipeline.undo(planned.id)
    assert (count(engine, Disease), count(engine, Symptom), count(engine, DiseaseLink)) == (1, 1, 1)
    pipeline.undo(second.id)
    assert (count(engine, Disease), count(engine, Symptom), count(engine, DiseaseLink)) == (0, 0, 0)


def test_plans_are_cached_by_content(engine, tmp_path):
    path = tmp_path / "x.csv"
    path.write_text("disease,symptoms\nFlu,fever\nCold,cough\n")
    run(make_pipeline(engine, tmp_path, LINK_PLAN).plan_file(path))

    # A fresh database and a model that would fail: the cached plan is used.
    other = make_engine(f"sqlite:///{tmp_path / 'other.db'}")
    init_db(other)
    planned, created = run(make_pipeline(other, tmp_path).plan_file(path))
    assert created and planned.status == "planned"


def test_non_data_and_junk_are_skipped(engine, tmp_path):
    code = tmp_path / "symptoms.csv"
    code.write_text("import csv\n\ndef main():\n    pass\n")
    junk = tmp_path / "diseases.csv"
    junk.write_text("name,type\nEbola,Genetic\nEbola,Parasitic\n")
    pipeline = make_pipeline(
        engine, tmp_path,
        {"content": "records", "verdict": "junk", "confidence": 0.9, "reason": "Contradictory types for the same disease."},
    )  # fmt: skip
    skipped_code, _ = run(pipeline.plan_file(code))
    skipped_junk, _ = run(pipeline.plan_file(junk))
    assert (skipped_code.status, skipped_code.plan["verdict"]) == ("skipped", "not_data")
    assert pipeline.llm.prompts and len(pipeline.llm.prompts) == 1  # code never reaches the model
    assert skipped_junk.status == "skipped" and "Contradictory" in skipped_junk.note
    with pytest.raises(IngestError, match="only planned runs"):
        pipeline.approve(skipped_junk.id)

    data = tmp_path / "ok.csv"
    data.write_text("disease,symptoms\nFlu,fever\nCold,cough\n")
    pipeline.llm.replies.append(LINK_PLAN)
    planned, _ = run(pipeline.plan_file(data))
    rejected = pipeline.reject(planned.id, "symptom lists are unreliable")
    assert rejected.status == "skipped" and "unreliable" in rejected.note
    with pytest.raises(IngestError, match="only planned runs"):
        pipeline.approve(planned.id)


def test_wrong_mapping_is_stopped_by_the_reject_gate(engine, tmp_path):
    path = tmp_path / "symptoms.csv"
    sentence = "There is a popular misconception that tuberculosis is purely a disease of the lungs that manifests as coughing"
    path.write_text("disease_name,symptom\n" + f"Tuberculosis,{sentence}\n" * 3)
    plan = {**LINK_PLAN, "outputs": [{"kind": "link", "disease": {"sources": ["disease_name"]}, "symptom": {"sources": ["symptom"]}}]}
    pipeline = make_pipeline(engine, tmp_path, plan)

    planned, _ = run(pipeline.plan_file(path))
    assert any("fail validation" in r for r in planned.stats["needs_review"])
    pipeline.approve(planned.id)
    failed = pipeline.load(planned.id)
    assert failed.status == "failed" and "failed validation" in failed.note
    assert count(engine, Disease) == 0 and count(engine, Symptom) == 0


def test_articles_enrichment_and_alias_matching(engine, tmp_path):
    article = tmp_path / "tb.txt"
    article.write_text(
        "Disease : Tuberculosis\n\nTuberculosis (TB) is an infectious disease caused by bacteria. "
        "Symptoms include night sweats and a chronic cough. Isoniazid is used for treatment. "
        "Covering the mouth when coughing limits spread.\n"
    )
    links = tmp_path / "pairs.csv"
    links.write_text("disease,symptoms\nTB,weight loss\nTB,Night sweats\n")
    ontology = tmp_path / "terms.obo"
    ontology.write_text(
        "format-version: 1.2\n\n[Term]\nid: HP:1\nname: Hyperhidrosis at night\n"
        'def: "Excessive sweating during sleep." []\nsynonym: "Night sweats" EXACT []\n\n'
        "[Term]\nid: HP:2\nname: Renal cyst\n"
    )
    pipeline = make_pipeline(
        engine, tmp_path,
        {"disease": "Tuberculosis", "aliases": ["TB"], "description": "An infectious disease.", "causes": "Bacteria.",
         "symptoms": ["night sweats", "chronic cough"], "drugs": ["isoniazid"],
         "precautions": ["Cover your mouth when coughing."]},
        LINK_PLAN,
        {"content": "records", "verdict": "usable", "confidence": 0.9, "outputs": [
            {"kind": "entity", "table": "symptoms", "mode": "enrich_only", "name": {"sources": ["name"]},
             "aliases": {"sources": ["synonyms"]}, "fields": {"description": {"sources": ["definition"]}}}]},
    )  # fmt: skip
    for path in (article, links, ontology):
        planned, _ = run(pipeline.plan_file(path))
        assert planned.status == "planned", planned.note
        pipeline.approve(planned.id)
        assert pipeline.load(planned.id).status == "loaded"

    with Session(engine) as db:
        disease = db.scalars(select(Disease)).one()  # "TB" resolved to Tuberculosis by alias
        assert (disease.name, disease.aliases, disease.causes) == ("Tuberculosis", ["TB"], "Bacteria.")
        symptoms = {s.name: s for s in db.scalars(select(Symptom))}
        assert set(symptoms) == {"Night sweats", "Chronic cough", "Weight loss"}  # no "Renal cyst"
        assert symptoms["Night sweats"].aliases == ["Hyperhidrosis at night"]
        assert symptoms["Night sweats"].description == "Excessive sweating during sleep."
        assert db.scalars(select(Drug.name)).all() == ["Isoniazid"]
        assert db.scalars(select(Precaution.precaution)).all() == ["Cover your mouth when coughing."]
        assert db.scalar(select(func.count()).select_from(DiseaseLink)) == 4


def test_failed_load_rolls_everything_back(engine, tmp_path, monkeypatch):
    path = tmp_path / "x.csv"
    path.write_text("disease,symptoms\nFlu,fever\nCold,cough\n")
    pipeline = make_pipeline(engine, tmp_path, LINK_PLAN)
    planned, _ = run(pipeline.plan_file(path))
    pipeline.approve(planned.id)

    def explode(*args, **kwargs):
        raise RuntimeError("connection lost")

    monkeypatch.setattr("app.ingest.load._links", explode)
    failed = pipeline.load(planned.id)
    assert failed.status == "failed" and "rolled back" in failed.note
    assert count(engine, Disease) == 0 and count(engine, Symptom) == 0


def test_changed_file_must_be_planned_again(engine, tmp_path):
    path = tmp_path / "x.csv"
    path.write_text("disease,symptoms\nFlu,fever\nCold,cough\n")
    pipeline = make_pipeline(engine, tmp_path, LINK_PLAN)
    planned, _ = run(pipeline.plan_file(path))
    pipeline.approve(planned.id)
    path.write_text("disease,symptoms\nFlu,fever\nCold,cough\nGout,pain\n")
    with pytest.raises(IngestError, match="changed since"):
        pipeline.load(planned.id)


def test_legacy_tables_are_only_replaced_when_empty(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE diseases (id TEXT PRIMARY KEY, disease_name TEXT)"))
        c.execute(text("CREATE TABLE medicines (id TEXT PRIMARY KEY, brand_name TEXT)"))
        c.execute(text("CREATE TABLE intake_sessions (id TEXT PRIMARY KEY)"))
    assert legacy_tables(engine) == ["diseases", "medicines"]
    with pytest.raises(IngestError, match="older layout"):
        init_db(engine)

    with engine.begin() as c:
        c.execute(text("INSERT INTO medicines VALUES ('1', 'Advil')"))
    with pytest.raises(IngestError, match="holds 1 rows"):
        init_db(engine, replace_legacy=True)

    with engine.begin() as c:
        c.execute(text("DELETE FROM medicines"))
    assert init_db(engine, replace_legacy=True) == ["diseases", "medicines"]
    assert legacy_tables(engine) == []
    with engine.connect() as c:  # unrelated tables are untouched
        c.execute(text("SELECT count(*) FROM intake_sessions"))
        c.execute(text("SELECT normalized_name FROM diseases"))


def test_nested_json_records_are_located(tmp_path):
    path = tmp_path / "onto.json"
    path.write_text(
        json.dumps({"graphs": [{"id": "x", "nodes": [{"lbl": "Headache", "tags": [{"a": 1}, {"a": 2}, {"a": 3}]}, {"lbl": "Fever"}], "edges": [{"s": 1}, {"s": 2}]}]})
    )
    assert records.find_json_records(path) == "graphs[].nodes"
    assert [r["lbl"] for r in records.iter_json(path, "graphs[].nodes")] == ["Headache", "Fever"]
    flat = tmp_path / "flat.json"
    flat.write_text(json.dumps([{"a": 1, "parts": [{"p": 1}, {"p": 2}]}, {"a": 2}]))
    assert records.find_json_records(flat) == ""
    assert len(list(records.iter_json(flat, ""))) == 2


def test_standalone_term_flood_is_flagged_and_can_be_revised(engine, tmp_path, monkeypatch):
    monkeypatch.setattr("app.ingest.pipeline.FLOOD_THRESHOLD", 3)
    path = tmp_path / "terms.csv"
    path.write_text("name,definition\n" + "".join(f"Term number {chr(97 + i)},About it\n" for i in range(5)))
    upsert = {"content": "records", "verdict": "usable", "confidence": 0.95, "outputs": [
        {"kind": "entity", "table": "symptoms", "name": {"sources": ["name"]}, "fields": {"description": {"sources": ["definition"]}}}]}  # fmt: skip
    enrich = json.loads(json.dumps(upsert))
    enrich["outputs"][0]["mode"] = "enrich_only"
    pipeline = make_pipeline(engine, tmp_path, upsert, enrich)

    planned, _ = run(pipeline.plan_file(path))
    assert any("standalone symptoms" in r for r in planned.stats["needs_review"])

    revised = run(pipeline.revise(planned.id, "This is a dictionary: only enrich existing symptoms."))
    assert revised.plan["outputs"][0]["mode"] == "enrich_only"
    assert revised.stats["needs_review"] == []
    assert "only enrich existing symptoms" in pipeline.llm.prompts[1]

    pipeline.approve(revised.id)
    assert pipeline.load(revised.id).status == "loaded"
    assert count(engine, Symptom) == 0  # nothing existed to enrich, nothing created

    with pytest.raises(IngestError, match="undo it first"):
        pipeline.forget(revised.id)
    pipeline.undo(revised.id)
    pipeline.forget(revised.id)
    assert pipeline.runs() == []


def test_enrich_only_never_merges_through_ambiguous_synonyms(engine, tmp_path):
    seed = tmp_path / "pairs.csv"
    seed.write_text("disease,drug\nPain,ibuprofen\nUlcer,famotidine\n")
    catalogue = tmp_path / "products.csv"
    catalogue.write_text(
        "generic,other_names\n"
        "ibuprofen and famotidine,Duexis|ibuprofen|famotidine\n"  # points at two drugs
        "ibuprofen,Advil|Motrin\n"
    )
    pipeline = make_pipeline(
        engine, tmp_path,
        {"content": "records", "verdict": "usable", "confidence": 1, "outputs": [
            {"kind": "link", "disease": {"sources": ["disease"]}, "drug": {"sources": ["drug"]}}]},
        {"content": "records", "verdict": "usable", "confidence": 1, "outputs": [
            {"kind": "entity", "table": "drugs", "mode": "enrich_only", "name": {"sources": ["generic"]},
             "aliases": {"sources": ["other_names"], "split": "|"}}]},
    )  # fmt: skip
    for path in (seed, catalogue):
        planned, _ = run(pipeline.plan_file(path))
        pipeline.approve(planned.id)
        assert pipeline.load(planned.id).status == "loaded"
    with Session(engine) as db:
        drugs = {d.name: d.aliases for d in db.scalars(select(Drug))}
    assert drugs == {"Ibuprofen": ["Advil", "Motrin"], "Famotidine": []}


def test_obo_keeps_exact_synonyms_only(tmp_path):
    path = tmp_path / "t.obo"
    path.write_text(
        "format-version: 1.2\n\n[Term]\nid: X:1\nname: Night sweats\n"
        'synonym: "Nocturnal hyperhidrosis" EXACT layperson []\n'
        'synonym: "Sweating" BROAD []\nsynonym: "Hot flush" RELATED []\n'
    )
    assert next(records.iter_obo(path))["synonyms"] == ["Nocturnal hyperhidrosis"]


def test_a_file_whose_planning_failed_is_planned_again(engine, tmp_path):
    path = tmp_path / "x.csv"
    path.write_text("disease,symptoms\nFlu,fever\nCold,cough\n")
    pipeline = make_pipeline(engine, tmp_path, LlmError("Temporary failure in name resolution"), LINK_PLAN)
    failed, _ = run(pipeline.plan_file(path))
    assert failed.status == "failed" and failed.note.startswith("Planning failed")
    retried, created = run(pipeline.plan_file(path))
    assert created and retried.status == "planned"
    assert len(pipeline.runs()) == 1


def test_spelling_variants_merge_and_subtypes_are_not_aliases(engine, tmp_path):
    first = tmp_path / "a.csv"
    first.write_text("disease,symptoms\nChickenpox,\"Headache, night sweats\"\nChicken pox,Headaches\n")
    second = tmp_path / "b.csv"
    second.write_text("disease,symptoms\nChicken Pox,Night sweat\nFlat feet,Foot pain\nFlatfeet,Foot pain\n")
    pipeline = make_pipeline(engine, tmp_path, LINK_PLAN, LINK_PLAN)
    for path in (first, second):
        planned, _ = run(pipeline.plan_file(path))
        pipeline.approve(planned.id)
        assert pipeline.load(planned.id).status == "loaded"
    with Session(engine) as db:
        diseases = {d.name: d.aliases for d in db.scalars(select(Disease))}
        symptoms = {s.name: s.aliases for s in db.scalars(select(Symptom))}
        links = db.scalar(select(func.count()).select_from(DiseaseLink))
    assert diseases == {"Chickenpox": ["Chicken pox"], "Flat feet": ["Flatfeet"]}
    assert symptoms == {"Headache": ["Headaches"], "Night sweats": ["Night sweat"], "Foot pain": []}
    assert links == 3

    staged = apply_plan(
        Plan.model_validate({"content": "records", "verdict": "usable", "confidence": 1, "outputs": [
            {"kind": "entity", "table": "diseases", "name": {"sources": ["n"]}, "aliases": {"sources": ["a"], "split": "|"}}]}),
        [{"n": "Migraine", "a": "Hemiplegic migraine|Sick headache|Retinal migraine"}],
    )  # fmt: skip
    assert list(staged.entities["diseases"]["migraine"].aliases.values()) == ["Sick headache"]


def test_an_alias_claimed_by_several_rows_is_dropped(engine, tmp_path):
    plan = {"content": "records", "verdict": "usable", "confidence": 1, "outputs": [
        {"kind": "entity", "table": "drugs", "name": {"sources": ["generic"]}, "aliases": {"sources": ["brands"], "split": "|"}}]}  # fmt: skip
    first = tmp_path / "a.csv"
    first.write_text(
        "generic,brands\nibuprofen,Advil|Pain relief\nnaproxen,Aleve|Pain relief\nparacetamol,Tylenol|Naproxen\n"
    )
    second = tmp_path / "b.csv"
    second.write_text("generic,brands\naspirin,Bayer|Advil\ncetirizine,Zyrtec\n")
    pipeline = make_pipeline(engine, tmp_path, plan, plan)
    for path in (first, second):
        planned, _ = run(pipeline.plan_file(path))
        pipeline.approve(planned.id)
        loaded = pipeline.load(planned.id)
        assert loaded.status == "loaded", loaded.note
    with Session(engine) as db:
        drugs = {d.name: d.aliases for d in db.scalars(select(Drug))}
    assert drugs == {
        "Ibuprofen": ["Advil"],       # "Pain relief" is claimed by two drugs
        "Naproxen": ["Aleve"],
        "Paracetamol": ["Tylenol"],   # "Naproxen" is another drug's name
        "Aspirin": ["Bayer"],         # "Advil" already belongs to ibuprofen
        "Cetirizine": ["Zyrtec"],
    }


def test_bracketed_names_and_reversed_rows(monkeypatch):
    monkeypatch.setattr("app.ingest.transform.MAX_SYMPTOMS_PER_DISEASE", 3)
    plan = Plan.model_validate(LINK_PLAN)
    staged = apply_plan(
        plan,
        [
            {"disease": "Urinary tract infection (UTI)", "symptoms": "dysuria, fever"},
            {"disease": "urinary tract infection", "symptoms": "Fever"},
            # A symptom in the disease column, with conditions listed against it.
            {"disease": "Pain", "symptoms": "gout, sciatica, migraine, appendicitis"},
        ],
    )
    diseases = staged.entities["diseases"]
    assert set(diseases) == {"urinary tract infection"}
    assert list(diseases["urinary tract infection"].aliases.values()) == ["UTI"]
    assert set(staged.entities["symptoms"]) == {"dysuria", "fever"}
    assert staged.links == {
        ("urinary tract infection", "symptoms", "dysuria"),
        ("urinary tract infection", "symptoms", "fever"),
    }
    assert staged.rejected == {"diseases:too_many_symptoms_to_be_a_disease": 1}


OWL = """<?xml version="1.0"?>
<rdf:RDF xmlns="http://purl.obolibrary.org/obo/symp.owl#"
     xmlns:owl="http://www.w3.org/2002/07/owl#"
     xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
     xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
     xmlns:obo="http://purl.obolibrary.org/obo/"
     xmlns:oboInOwl="http://www.geneontology.org/formats/oboInOwl#">
    <owl:Ontology rdf:about="http://purl.obolibrary.org/obo/symp.owl"/>
    <owl:Class rdf:about="http://purl.obolibrary.org/obo/SYMP_0000001">
        <oboInOwl:hasExactSynonym>stomach cramp</oboInOwl:hasExactSynonym>
        <oboInOwl:hasRelatedSynonym>bellyache</oboInOwl:hasRelatedSynonym>
        <oboInOwl:id>SYMP:0000001</oboInOwl:id>
        <obo:IAO_0000115>A cramp felt in the abdomen.</obo:IAO_0000115>
        <rdfs:label>abdominal cramp</rdfs:label>
    </owl:Class>
    <owl:Class rdf:about="http://purl.obolibrary.org/obo/SYMP_0000002">
        <owl:deprecated rdf:datatype="http://www.w3.org/2001/XMLSchema#boolean">true</owl:deprecated>
        <rdfs:label>obsolete thing</rdfs:label>
    </owl:Class>
</rdf:RDF>
"""

MESH = """<?xml version="1.0"?>
<DescriptorRecordSet LanguageCode="eng">
<DescriptorRecord DescriptorClass="1">
  <DescriptorUI>D007251</DescriptorUI>
  <DescriptorName><String>Influenza, Human</String></DescriptorName>
  <ConceptList>
    <Concept PreferredConceptYN="Y">
      <ConceptName><String>Influenza, Human</String></ConceptName>
      <ScopeNote>An acute viral infection in humans involving the respiratory tract.</ScopeNote>
      <TermList>
        <Term><String>Influenza, Human</String></Term>
        <Term><String>Influenza</String></Term>
        <Term><String>Grippe</String></Term>
      </TermList>
    </Concept>
  </ConceptList>
  <TreeNumberList><TreeNumber>C01.925.256.466.382</TreeNumber></TreeNumberList>
</DescriptorRecord>
<DescriptorRecord DescriptorClass="1">
  <DescriptorUI>D005334</DescriptorUI>
  <DescriptorName><String>Fever</String></DescriptorName>
  <ConceptList>
    <Concept PreferredConceptYN="Y">
      <ConceptName><String>Fever</String></ConceptName>
      <ScopeNote>An abnormal elevation of body temperature.</ScopeNote>
      <TermList><Term><String>Pyrexia</String></Term></TermList>
    </Concept>
    <Concept PreferredConceptYN="N">
      <ConceptName><String>Fever of Unknown Origin</String></ConceptName>
    </Concept>
  </ConceptList>
  <TreeNumberList><TreeNumber>C23.888.119.344</TreeNumber><TreeNumber>G07.345</TreeNumber></TreeNumberList>
</DescriptorRecord>
</DescriptorRecordSet>
"""


def test_owl_classes_are_read_like_obo_terms(tmp_path):
    path = tmp_path / "symptoms_ontology"  # no extension: format comes from content
    path.write_text(OWL)
    sniffed = sniff(path)
    assert sniffed.format == "owl" and sniffed.columns == list(records.OBO_KEYS)
    terms = list(records.iter_owl(path))
    # Deprecated classes are skipped; only EXACT synonyms count.
    assert terms == [
        {"id": "SYMP:0000001", "name": "abdominal cramp", "definition": "A cramp felt in the abdomen.", "synonyms": ["stomach cramp"]}
    ]


def test_xml_records_are_streamed_as_json_like_data(tmp_path):
    path = tmp_path / "descriptors.dat"
    path.write_text(MESH)
    sniffed = sniff(path)
    assert (sniffed.format, sniffed.record_path) == ("xml", "DescriptorRecord")
    assert "ConceptList.Concept.TermList.Term[].String" in sniffed.columns
    flu, fever = records.iter_xml(path, "DescriptorRecord")
    assert records.get_values(flu, "ConceptList.Concept[].TermList.Term[].String") == ["Influenza, Human", "Influenza", "Grippe"]
    # One child or several: an indexed path reads both the same way.
    assert records.get_values(flu, "ConceptList.Concept[0].ScopeNote") == ["An acute viral infection in humans involving the respiratory tract."]
    assert records.get_values(fever, "ConceptList.Concept[0].ScopeNote") == ["An abnormal elevation of body temperature."]
    assert records.get_values(fever, "TreeNumberList.TreeNumber[]") == ["C23.888.119.344", "G07.345"]
    assert records.get_values(fever, "@DescriptorClass") == ["1"]


def test_a_plan_may_pick_the_first_of_a_listed_field(tmp_path):
    path = tmp_path / "descriptors.dat"
    path.write_text(MESH)
    sniffed = sniff(path)
    plan = Plan.model_validate({
        "content": "records", "verdict": "usable", "confidence": 1,
        "outputs": [{"kind": "entity", "table": "symptoms", "mode": "enrich_only",
                     "name": {"sources": ["DescriptorName.String"]},
                     "aliases": {"sources": ["ConceptList.Concept[0].TermList.Term[].String"]},
                     "fields": {"description": {"sources": ["ConceptList.Concept[0].ScopeNote"]}}}],
    })  # fmt: skip
    assert plan.check_against(sniffed) == []
    bad = plan.model_copy(deep=True)
    bad.outputs[0].fields["description"].sources = ["ConceptList.Concept[0].NoSuchThing"]
    assert bad.check_against(sniffed)
    # Only the preferred concept's terms: "Fever of Unknown Origin" is not fever.
    fever = list(records.iter_xml(path, "DescriptorRecord"))[1]
    assert records.get_values(fever, "ConceptList.Concept[0].TermList.Term[].String") == ["Pyrexia"]
