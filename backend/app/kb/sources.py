"""Every source the knowledge base takes, with its licence and tier.

A source is registered here once, by a person, with what its licence allows:
nothing is loaded from a file that is not listed (unknown licence = not
loaded). `production_allowed` is what report generation will check: a source
that needs permission is loaded and tested now and switched on later.

Paths are relative to the repository root. `reader` names a module in
`app/kb/readers/`; `after` lists sources that must be loaded first (the FDA
labels are filtered to the drugs the Indian lists hold, for example).
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Source:
    key: str
    title: str
    publisher: str
    edition: str
    kind: str
    tier: int
    licence: str
    production_allowed: bool
    files: tuple[str, ...]
    reader: str
    licence_note: str = ""
    after: tuple[str, ...] = field(default=())


_STW_LICENCE = "© ICMR, all rights reserved"
_STW_NOTE = "Reproduction needs written permission from ICMR. Loaded for testing; not for reports until permission is granted."

SOURCES: tuple[Source, ...] = (
    # --- Vocabularies and codes (names, synonyms, codes; no clinical advice) ---
    Source("doid", "Human Disease Ontology", "Disease Ontology consortium", "2026", "vocabulary", 4,
           "CC0 1.0", True, ("medora_2/doid.obo",), "ontology"),
    Source("symp", "Symptom Ontology", "Disease Ontology consortium", "2026-07-30", "vocabulary", 4,
           "CC0 1.0", True, ("medora_2/symp.owl",), "ontology"),
    Source("hpo", "Human Phenotype Ontology", "Monarch Initiative", "2026", "vocabulary", 4,
           "HPO licence (free use with attribution; the ontology itself may not be altered)", True,
           ("medora_2/hp.obo",), "ontology"),
    Source("mesh", "Medical Subject Headings (diseases, mental disorders, signs and symptoms)", "US National Library of Medicine", "2026",
           "vocabulary", 4, "NLM terms and conditions (free use)", True, ("medora_2/desc2026.xml",), "mesh",
           after=("doid",)),
    Source("icd10cm", "ICD-10-CM", "US CDC / NCHS", "FY2027", "codes", 4, "Public domain (US government work)", True,
           ("medora_2/icd10cm-order-2027.txt",), "codes"),
    Source("icd11", "ICD-11 MMS simple tabulation", "World Health Organization", "2026", "codes", 4,
           "CC BY-ND 3.0 IGO", True, ("medora_2/SimpleTabulation-ICD-11-MMS-en.xlsx",), "codes",
           licence_note="Codes and titles used unchanged, for look-up only."),
    Source("medgen", "MedGen concept names", "US NCBI", "2026", "vocabulary", 4,
           "NCBI MedGen (free; includes names from SNOMED CT, NCI, MeSH, HPO, MONDO)", True,
           ("medora_2/MGCONSO.RRF",), "medgen", licence_note="Only synonyms of concepts already linked to Disease Ontology or HPO.",
           after=("doid", "hpo")),
    # --- Indian government clinical sources ---
    Source("icmr-stw-vol1", "Standard Treatment Workflows of India, Vol. 1", "ICMR, Department of Health Research", "2019",
           "guideline", 1, _STW_LICENCE, False, ("medora_4/Vol1.pdf",), "stw", _STW_NOTE),
    Source("icmr-stw-vol2", "Standard Treatment Workflows of India, Special Edition: Paediatric and Extrapulmonary TB",
           "ICMR, Department of Health Research", "2022", "guideline", 1, _STW_LICENCE, False, ("medora_4/Vol2.pdf",), "stw", _STW_NOTE),
    Source("icmr-stw-vol3", "Standard Treatment Workflows of India, Vol. 3", "ICMR, Department of Health Research", "2022",
           "guideline", 1, _STW_LICENCE, False, ("medora_4/Vol3.pdf",), "stw", _STW_NOTE),
    Source("icmr-stw-vol4", "Standard Treatment Workflows of India, Vol. 4", "ICMR, Department of Health Research", "2022",
           "guideline", 1, _STW_LICENCE, False, ("medora_4/Vol4.pdf",), "stw", _STW_NOTE),
    Source("nfi-2011", "National Formulary of India", "Indian Pharmacopoeia Commission", "4th edition, 2011", "formulary", 1,
           "© Indian Pharmacopoeia Commission", False, ("medora_4/National Formulary of India (NFI), 2011.pdf",), "nfi",
           "Reproduction needs permission from the IPC. Loaded for testing; not for reports until permission is granted."),
    Source("nlem-2022", "National List of Essential Medicines", "Ministry of Health and Family Welfare, India", "2022",
           "essential_list", 1, "Government of India publication (no copyright notice)", True,
           ("medora_4/medicinesnlem2022.pdf",), "nlem"),
    Source("nvbdcp-malaria-2013", "National Drug Policy on Malaria", "National Vector Borne Disease Control Programme, MoHFW",
           "2013", "guideline", 1, "Government of India programme document (no copyright notice)", True,
           ("medora_5/nvbdcp_national_drug_policy_malaria_2013.pdf",), "guideline",
           "Downloaded from ncvbdc.mohfw.gov.in on 2026-10-27."),
    # --- International ---
    Source("who-eml-2025", "WHO Model List of Essential Medicines, 24th list", "World Health Organization", "2025",
           "essential_list", 2, "CC BY-NC-SA 3.0 IGO", False, ("medora_4/B09474-eng.pdf",), "who_eml",
           "Non-commercial licence: commercial use needs WHO permission.", after=("nlem-2022",)),
    Source("medlineplus", "MedlinePlus health topics (English)", "US National Library of Medicine", "2026-10-13",
           "patient_info", 2, "NLM public domain summaries (credit MedlinePlus)", True,
           ("medora_2/mplus_topics_2026-10-13.xml",), "medlineplus", after=("doid",)),
    Source("msf-clinical-2024", "MSF Clinical guidelines: diagnosis and treatment manual", "Médecins Sans Frontières",
           "December 2024", "guideline", 2, "© Médecins Sans Frontières, all rights reserved", False,
           ("medora6/guideline-170-en.pdf",), "guideline",
           "Reproduction needs MSF's permission. Loaded for testing; not for reports until permission is granted. "
           "Covers typhoid, snake bites and other topics no Indian source here has."),
    Source("msf-essential-drugs-2026", "MSF Essential drugs: practical guidelines", "Médecins Sans Frontières",
           "January 2026", "formulary", 2, "© Médecins Sans Frontières, all rights reserved", False,
           ("medora6/guideline-339-en.pdf",), "guideline",
           "Reproduction needs MSF's permission. Loaded for testing; not for reports until permission is granted."),
    Source("openfda-labels", "FDA drug labels (one label per medicine)", "US FDA via openFDA", "2026-10-13", "drug_label", 3,
           "CC0 1.0 (openFDA)", True, tuple(f"medora_2/drug-label-{i:04d}-of-0014.json" for i in range(1, 15)), "fda",
           "US labels: doses are a fallback when no Indian source has one.", after=("nfi-2011", "nlem-2022", "who-eml-2025")),
)

_HF_NOTE = ("Community dataset from Hugging Face (tier 5): loaded for testing; not for reports until it has been "
            "checked against the tier 1-2 sources.")


def _hf(key: str, repo: str, files: tuple[str, ...], title: str, licence: str, note: str = "",
        after: tuple[str, ...] = ()) -> Source:
    return Source(key, title, repo.split("/")[0], "Hugging Face, 2026-10-27", "community", 5, licence, False,
                  tuple(f"hf:{repo}/{f}" for f in files), "hf", f"{note} {_HF_NOTE}".strip(), after)


SOURCES += (
    _hf("hf-disease-database", "FreedomIntelligence/Disease_Database", ("disease_database_en.json",),
        "Disease Database (English): symptoms and treatment text", "Apache-2.0",
        "zhaoruimeng/Disease_Database is a byte-identical copy and is not loaded twice."),
    _hf("hf-mayo-diseases", "Shaheer14326/Disease_Symptoms_Dataset", ("disease_data.csv",),
        "Disease overviews, symptoms, causes and prevention", "MIT (as stated by the uploader)",
        "The text appears to be scraped from Mayo Clinic pages, which are copyrighted."),
    _hf("hf-medlineplus-symptoms", "Mohamed-Ahmed161/Disease-Symptoms", ("data/train-00000-of-00001.parquet",),
        "Disease symptom lists (from the MedlinePlus encyclopedia)", "None stated",
        "Scraped from the A.D.A.M. encyclopedia on MedlinePlus, which is copyrighted."),
    _hf("hf-kaggle-41", "MagazinePuma/Disease_and_symptoms", ("DiseaseAndSymptoms.csv",),
        "41 diseases with symptoms (Kaggle disease prediction set)", "None stated"),
    _hf("hf-json-symptom", "akhileshav8/json_symptom", ("data.json",),
        "41 diseases with symptoms (the same Kaggle set, repeated rows)", "None stated", after=("doid", "hpo", "symp", "mesh")),
    _hf("hf-columbia-134", "arpitchakraborty/disease-symptoms", ("data/train-00000-of-00001.parquet",),
        "134 diseases with symptoms", "None stated"),
    _hf("hf-symptoms-doctors", "ashnaz/symptoms_diagnose_doctors_data", ("dataset.csv",),
        "99 diseases: symptoms, treatment, which doctor", "MIT"),
    _hf("hf-all-diseases", "nisten/all-human-diseases", ("draft_list_of_all_human_diseases_and_conditions_august_2024.csv",),
        "List of human disease names (draft, August 2024)", "AGPL-3.0"),
    _hf("hf-indian-brands", "Ansh99/medicine-dataset", ("Med_Ultimate_Master(1).csv",),
        "Indian and US medicine brands: composition, uses, side effects, price, substitutes", "None stated",
        "Indian rows appear to be scraped from 1mg."),
    _hf("hf-1mg-medicines", "dmedhi/indian-medicines", ("data/train-00000-of-00001.parquet",),
        "Indian medicine brands (1mg): composition, uses, side effects", "None stated", after=("hf-indian-brands",)),
    _hf("hf-1mg-medicines-qa", "zenitsu09/medicine-dataset",
        ("data/train-00000-of-00001.parquet", "data/test-00000-of-00001.parquet"),
        "Indian medicine brands (the same 1mg set as question/answer)", "None stated", after=("hf-indian-brands",)),
    _hf("hf-1mg-medicines-instruct", "hanzohazashi1/med_llama", ("preprocess.parquet",),
        "Indian medicine brands (the same 1mg set as instructions)", "Other (LICENSE file)", after=("hf-indian-brands",)),
)
BY_KEY = {s.key: s for s in SOURCES}

# Files reviewed and deliberately not loaded, with the reason (shown by `status`).
REJECTED = {
    "medora6/D-DoMiner_miner-diseaseDOID.tsv/D-DoMiner_miner-diseaseDOID.tsv": (
        "An old Disease Ontology snapshot (DoMiner): 2,448 of its 9,247 diseases are obsolete or merged in the "
        "current Disease Ontology (loaded as doid), and its extra synonyms are old mappings, some wrong "
        "('appendicitis' = 'acute appendicitis with peritoneal abscess', 'multifocal motor neuropathy' = "
        "'peripheral motor neuropathy'), which would make the search match the wrong disease."),
    "medora_2/diseases.csv": "Wrong facts (Ebola labelled 'Genetic', meningitis 'Parasitic', random bacteria and virus columns).",
    "medora_2/ddxplus_disease_symptoms.csv": "Synthetic data; its 'symptoms' are question texts.",
    "medora_2/human_disease_knowledge_full.tsv": "Gene-disease links: no use for triage.",
    "medora_2/drug-ndc-0001-of-0001.json": "US package catalogue: no clinical content.",
    "medora_2/hp.json-phenotype ( antibodies)": "The same ontology as hp.obo.",
    "medora_2/medora_hpo_phenotypes.csv": "Derived from hp.obo.",
    "medora_2/icd102019en.xml": "WHO ICD-10 under a stricter licence; ICD-10-CM covers it.",
    "medora_4/WHOlist of essential medB09474-eng.pdf": "Byte-identical copy of B09474-eng.pdf.",
    "medora_2/icd102019syst_*.txt": "WHO ICD-10 lists under a stricter licence; ICD-10-CM covers it.",
    "hf:zhaoruimeng/Disease_Database": "Byte-identical copy of FreedomIntelligence/Disease_Database.",
    "hf:mruthyunjaya05/medicine": ("Wrong facts: 958 of its 1,418 medicines are given the composition 'Ranibizumab 10mg/ml' "
                                    "(Atorlip = atorvastatin, Azysafe = azithromycin, a fever injection ...), and its "
                                    "'efficacy scores' and homeopathic/ayurvedic alternatives are invented."),
}
