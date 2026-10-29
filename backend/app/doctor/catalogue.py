"""Type-ahead suggestions for the doctor portal: medicines (with their usual
Indian strengths and forms, and brand names that lead to them), diagnoses
and tests.

The lists here are the common outpatient ones, so suggestions work without
any database. Diagnoses also come from the knowledge index in memory
(`knowledge_base`, 2,400 diseases); medicine names also come from the
guideline database (`kb_drugs`) when it can be reached. A suggestion only
fills in fields: the doctor still sets the dose and how often, and nothing
is signed without them.
"""

import re

from ..ingest.transform import normalize

# (name, form, strength, route): the usual Indian preparations.
MEDICINES: list[tuple[str, str, str, str]] = [
    ("Paracetamol", "tablet", "500 mg", "oral"),
    ("Paracetamol", "tablet", "650 mg", "oral"),
    ("Paracetamol", "syrup", "125 mg/5 ml", "oral"),
    ("Paracetamol", "suspension", "250 mg/5 ml", "oral"),
    ("Paracetamol", "drops", "100 mg/ml", "oral"),
    ("Ibuprofen", "tablet", "400 mg", "oral"),
    ("Ibuprofen", "suspension", "100 mg/5 ml", "oral"),
    ("Ibuprofen + Paracetamol", "tablet", "400 mg + 325 mg", "oral"),
    ("Mefenamic acid", "tablet", "500 mg", "oral"),
    ("Mefenamic acid + Dicyclomine", "tablet", "250 mg + 10 mg", "oral"),
    ("Diclofenac", "tablet", "50 mg", "oral"),
    ("Diclofenac", "gel", "1%", "topical"),
    ("Aceclofenac + Paracetamol", "tablet", "100 mg + 325 mg", "oral"),
    ("Naproxen", "tablet", "250 mg", "oral"),
    ("Tramadol", "capsule", "50 mg", "oral"),
    ("Drotaverine", "tablet", "40 mg", "oral"),
    ("Dicyclomine", "tablet", "10 mg", "oral"),
    ("Cetirizine", "tablet", "10 mg", "oral"),
    ("Cetirizine", "syrup", "5 mg/5 ml", "oral"),
    ("Levocetirizine", "tablet", "5 mg", "oral"),
    ("Fexofenadine", "tablet", "120 mg", "oral"),
    ("Fexofenadine", "tablet", "180 mg", "oral"),
    ("Loratadine", "tablet", "10 mg", "oral"),
    ("Chlorphenamine", "tablet", "4 mg", "oral"),
    ("Montelukast", "tablet", "10 mg", "oral"),
    ("Montelukast + Levocetirizine", "tablet", "10 mg + 5 mg", "oral"),
    ("Dextromethorphan", "syrup", "10 mg/5 ml", "oral"),
    ("Ambroxol", "syrup", "30 mg/5 ml", "oral"),
    ("Guaifenesin", "syrup", "100 mg/5 ml", "oral"),
    ("Salbutamol", "inhaler", "100 mcg/puff", "inhaled"),
    ("Salbutamol", "nebuliser solution", "5 mg/ml", "inhaled"),
    ("Budesonide", "inhaler", "200 mcg/puff", "inhaled"),
    ("Budesonide + Formoterol", "inhaler", "200 mcg + 6 mcg", "inhaled"),
    ("Ipratropium", "inhaler", "20 mcg/puff", "inhaled"),
    ("Fluticasone", "nasal spray", "50 mcg/spray", "nasal"),
    ("Mometasone", "nasal spray", "50 mcg/spray", "nasal"),
    ("Xylometazoline", "nasal drops", "0.1%", "nasal"),
    ("Saline", "nasal drops", "0.65%", "nasal"),
    ("Pantoprazole", "tablet", "40 mg", "oral"),
    ("Pantoprazole + Domperidone", "capsule", "40 mg + 30 mg", "oral"),
    ("Omeprazole", "capsule", "20 mg", "oral"),
    ("Rabeprazole", "tablet", "20 mg", "oral"),
    ("Esomeprazole", "tablet", "40 mg", "oral"),
    ("Famotidine", "tablet", "20 mg", "oral"),
    ("Antacid (aluminium + magnesium hydroxide)", "suspension", "", "oral"),
    ("Sucralfate", "suspension", "1 g/10 ml", "oral"),
    ("Domperidone", "tablet", "10 mg", "oral"),
    ("Ondansetron", "tablet", "4 mg", "oral"),
    ("Ondansetron", "syrup", "2 mg/5 ml", "oral"),
    ("Metoclopramide", "tablet", "10 mg", "oral"),
    ("Oral rehydration salts (ORS)", "sachet", "20.5 g/l", "oral"),
    ("Zinc", "tablet", "20 mg", "oral"),
    ("Zinc", "syrup", "20 mg/5 ml", "oral"),
    ("Racecadotril", "capsule", "100 mg", "oral"),
    ("Loperamide", "capsule", "2 mg", "oral"),
    ("Lactulose", "syrup", "10 g/15 ml", "oral"),
    ("Bisacodyl", "tablet", "5 mg", "oral"),
    ("Isabgol (psyllium husk)", "powder", "", "oral"),
    ("Probiotic (Saccharomyces boulardii)", "sachet", "250 mg", "oral"),
    ("Amoxicillin", "capsule", "500 mg", "oral"),
    ("Amoxicillin", "suspension", "250 mg/5 ml", "oral"),
    ("Amoxicillin + Clavulanic acid", "tablet", "625 mg", "oral"),
    ("Amoxicillin + Clavulanic acid", "suspension", "228.5 mg/5 ml", "oral"),
    ("Azithromycin", "tablet", "500 mg", "oral"),
    ("Azithromycin", "suspension", "200 mg/5 ml", "oral"),
    ("Doxycycline", "capsule", "100 mg", "oral"),
    ("Cefixime", "tablet", "200 mg", "oral"),
    ("Cefuroxime", "tablet", "500 mg", "oral"),
    ("Cefalexin", "capsule", "500 mg", "oral"),
    ("Cefpodoxime", "tablet", "200 mg", "oral"),
    ("Ciprofloxacin", "tablet", "500 mg", "oral"),
    ("Levofloxacin", "tablet", "500 mg", "oral"),
    ("Ofloxacin", "tablet", "200 mg", "oral"),
    ("Nitrofurantoin", "capsule", "100 mg", "oral"),
    ("Fosfomycin", "sachet", "3 g", "oral"),
    ("Co-trimoxazole", "tablet", "800 mg + 160 mg", "oral"),
    ("Metronidazole", "tablet", "400 mg", "oral"),
    ("Tinidazole", "tablet", "500 mg", "oral"),
    ("Clarithromycin", "tablet", "500 mg", "oral"),
    ("Clindamycin", "capsule", "300 mg", "oral"),
    ("Fluconazole", "tablet", "150 mg", "oral"),
    ("Albendazole", "tablet", "400 mg", "oral"),
    ("Ivermectin", "tablet", "12 mg", "oral"),
    ("Permethrin", "cream", "5%", "topical"),
    ("Clotrimazole", "cream", "1%", "topical"),
    ("Clotrimazole", "vaginal tablet", "500 mg", "vaginal"),
    ("Terbinafine", "cream", "1%", "topical"),
    ("Mupirocin", "ointment", "2%", "topical"),
    ("Fusidic acid", "cream", "2%", "topical"),
    ("Hydrocortisone", "cream", "1%", "topical"),
    ("Calamine", "lotion", "", "topical"),
    ("Silver sulfadiazine", "cream", "1%", "topical"),
    ("Aciclovir", "tablet", "400 mg", "oral"),
    ("Aciclovir", "cream", "5%", "topical"),
    ("Oseltamivir", "capsule", "75 mg", "oral"),
    ("Artemether + Lumefantrine", "tablet", "80 mg + 480 mg", "oral"),
    ("Chloroquine", "tablet", "250 mg", "oral"),
    ("Primaquine", "tablet", "7.5 mg", "oral"),
    ("Moxifloxacin", "eye drops", "0.5%", "eye"),
    ("Ciprofloxacin", "eye drops", "0.3%", "eye"),
    ("Carboxymethylcellulose", "eye drops", "0.5%", "eye"),
    ("Ciprofloxacin", "ear drops", "0.3%", "ear"),
    ("Metformin", "tablet", "500 mg", "oral"),
    ("Metformin", "tablet", "1000 mg", "oral"),
    ("Glimepiride", "tablet", "1 mg", "oral"),
    ("Gliclazide", "tablet", "80 mg", "oral"),
    ("Sitagliptin", "tablet", "100 mg", "oral"),
    ("Vildagliptin", "tablet", "50 mg", "oral"),
    ("Amlodipine", "tablet", "5 mg", "oral"),
    ("Telmisartan", "tablet", "40 mg", "oral"),
    ("Losartan", "tablet", "50 mg", "oral"),
    ("Enalapril", "tablet", "5 mg", "oral"),
    ("Atenolol", "tablet", "50 mg", "oral"),
    ("Metoprolol", "tablet", "50 mg", "oral"),
    ("Hydrochlorothiazide", "tablet", "12.5 mg", "oral"),
    ("Furosemide", "tablet", "40 mg", "oral"),
    ("Atorvastatin", "tablet", "10 mg", "oral"),
    ("Rosuvastatin", "tablet", "10 mg", "oral"),
    ("Aspirin", "tablet", "75 mg", "oral"),
    ("Clopidogrel", "tablet", "75 mg", "oral"),
    ("Glyceryl trinitrate", "sublingual tablet", "0.5 mg", "sublingual"),
    ("Levothyroxine", "tablet", "50 mcg", "oral"),
    ("Prednisolone", "tablet", "10 mg", "oral"),
    ("Methylprednisolone", "tablet", "8 mg", "oral"),
    ("Ferrous sulfate + Folic acid", "tablet", "", "oral"),
    ("Folic acid", "tablet", "5 mg", "oral"),
    ("Calcium + Vitamin D3", "tablet", "500 mg + 250 IU", "oral"),
    ("Vitamin B complex", "tablet", "", "oral"),
    ("Methylcobalamin", "tablet", "1500 mcg", "oral"),
    ("Cholecalciferol (Vitamin D3)", "sachet", "60,000 IU", "oral"),
    ("Betahistine", "tablet", "16 mg", "oral"),
    ("Cinnarizine", "tablet", "25 mg", "oral"),
    ("Pregabalin", "capsule", "75 mg", "oral"),
    ("Amitriptyline", "tablet", "10 mg", "oral"),
    ("Sertraline", "tablet", "50 mg", "oral"),
    ("Escitalopram", "tablet", "10 mg", "oral"),
    ("Thiocolchicoside", "capsule", "4 mg", "oral"),
    ("Tamsulosin", "capsule", "0.4 mg", "oral"),
]

# Brand names a doctor may type, and the preparation each one is.
BRANDS: dict[str, tuple[str, str, str, str]] = {
    "Dolo 650": ("Paracetamol", "tablet", "650 mg", "oral"),
    "Crocin": ("Paracetamol", "tablet", "500 mg", "oral"),
    "Calpol": ("Paracetamol", "tablet", "500 mg", "oral"),
    "Combiflam": ("Ibuprofen + Paracetamol", "tablet", "400 mg + 325 mg", "oral"),
    "Brufen": ("Ibuprofen", "tablet", "400 mg", "oral"),
    "Meftal Spas": ("Mefenamic acid + Dicyclomine", "tablet", "250 mg + 10 mg", "oral"),
    "Cyclopam": ("Dicyclomine", "tablet", "10 mg", "oral"),
    "Drotin": ("Drotaverine", "tablet", "40 mg", "oral"),
    "Cetzine": ("Cetirizine", "tablet", "10 mg", "oral"),
    "Okacet": ("Cetirizine", "tablet", "10 mg", "oral"),
    "Allegra": ("Fexofenadine", "tablet", "120 mg", "oral"),
    "Montair LC": ("Montelukast + Levocetirizine", "tablet", "10 mg + 5 mg", "oral"),
    "Asthalin": ("Salbutamol", "inhaler", "100 mcg/puff", "inhaled"),
    "Pan 40": ("Pantoprazole", "tablet", "40 mg", "oral"),
    "Pantocid": ("Pantoprazole", "tablet", "40 mg", "oral"),
    "Pan D": ("Pantoprazole + Domperidone", "capsule", "40 mg + 30 mg", "oral"),
    "Omez": ("Omeprazole", "capsule", "20 mg", "oral"),
    "Razo": ("Rabeprazole", "tablet", "20 mg", "oral"),
    "Emeset": ("Ondansetron", "tablet", "4 mg", "oral"),
    "Electral": ("Oral rehydration salts (ORS)", "sachet", "20.5 g/l", "oral"),
    "Augmentin 625": ("Amoxicillin + Clavulanic acid", "tablet", "625 mg", "oral"),
    "Azithral": ("Azithromycin", "tablet", "500 mg", "oral"),
    "Azee": ("Azithromycin", "tablet", "500 mg", "oral"),
    "Taxim O": ("Cefixime", "tablet", "200 mg", "oral"),
    "Ciplox": ("Ciprofloxacin", "tablet", "500 mg", "oral"),
    "Flagyl": ("Metronidazole", "tablet", "400 mg", "oral"),
    "Zentel": ("Albendazole", "tablet", "400 mg", "oral"),
    "Volini": ("Diclofenac", "gel", "1%", "topical"),
    "Glycomet": ("Metformin", "tablet", "500 mg", "oral"),
    "Amlong": ("Amlodipine", "tablet", "5 mg", "oral"),
    "Telma": ("Telmisartan", "tablet", "40 mg", "oral"),
    "Thyronorm": ("Levothyroxine", "tablet", "50 mcg", "oral"),
    "Shelcal": ("Calcium + Vitamin D3", "tablet", "500 mg + 250 IU", "oral"),
    "Vertin": ("Betahistine", "tablet", "16 mg", "oral"),
}

# Common outpatient diagnoses, as an Indian doctor writes them.
DIAGNOSES = [
    "Viral fever", "Acute upper respiratory tract infection", "Common cold", "Acute pharyngitis",
    "Acute tonsillitis", "Acute sinusitis", "Allergic rhinitis", "Acute bronchitis",
    "Community-acquired pneumonia", "Bronchial asthma", "Acute exacerbation of asthma", "COPD exacerbation",
    "Influenza", "COVID-19", "Dengue fever", "Dengue fever with warning signs", "Malaria (P. vivax)",
    "Malaria (P. falciparum)", "Typhoid (enteric) fever", "Chikungunya", "Leptospirosis", "Scrub typhus",
    "Acute gastroenteritis", "Acute diarrhoea with mild dehydration", "Food poisoning", "Amoebic dysentery",
    "Acid peptic disease", "Gastro-oesophageal reflux disease (GERD)", "Gastritis", "Dyspepsia",
    "Irritable bowel syndrome", "Constipation", "Acute appendicitis (suspected)", "Biliary colic",
    "Acute hepatitis", "Urinary tract infection", "Acute cystitis", "Acute pyelonephritis", "Renal colic",
    "Migraine", "Tension-type headache", "Vertigo (BPPV)", "Peripheral neuropathy",
    "Essential hypertension", "Uncontrolled hypertension", "Type 2 diabetes mellitus",
    "Uncontrolled type 2 diabetes mellitus", "Hypothyroidism", "Iron deficiency anaemia", "Vitamin D deficiency",
    "Vitamin B12 deficiency", "Dyslipidaemia", "Stable angina", "Acute coronary syndrome (suspected)",
    "Sinus tachycardia", "Palpitations", "Musculoskeletal chest pain", "Acute low back pain",
    "Mechanical neck pain", "Osteoarthritis knee", "Ankle sprain", "Soft tissue injury", "Gout",
    "Scabies", "Tinea corporis", "Urticaria", "Contact dermatitis", "Atopic dermatitis", "Impetigo",
    "Cellulitis", "Herpes zoster", "Chickenpox", "Acne vulgaris", "Acute conjunctivitis",
    "Acute otitis media", "Otitis externa", "Wax impaction", "Dental caries", "Primary dysmenorrhoea",
    "Vaginal candidiasis", "Anxiety disorder", "Depression", "Insomnia", "Dehydration",
    "Snake bite", "Dog bite (rabies exposure)", "Heat exhaustion",
]

TESTS = [
    "Complete blood count (CBC)", "Haemoglobin", "ESR", "C-reactive protein (CRP)", "Peripheral smear for malaria",
    "Malaria rapid diagnostic test", "Dengue NS1 antigen", "Dengue IgM", "Typhidot / Widal test", "Blood culture",
    "Urine routine and microscopy", "Urine culture and sensitivity", "Urine pregnancy test (hCG)",
    "Random blood sugar", "Fasting blood sugar", "Post-prandial blood sugar", "HbA1c", "Serum creatinine",
    "Blood urea", "Serum electrolytes", "Liver function tests (LFT)", "Lipid profile", "Thyroid profile (TSH)",
    "Serum vitamin D", "Serum vitamin B12", "Serum uric acid", "Stool routine", "Chest X-ray (PA view)",
    "ECG (12-lead)", "Troponin I", "D-dimer", "Echocardiogram", "Ultrasound abdomen", "Ultrasound pelvis",
    "X-ray of the affected part", "Sputum for AFB (TB)", "CBNAAT / TrueNat for TB", "RT-PCR COVID-19",
    "Leptospira IgM", "Scrub typhus IgM", "Pulse oximetry monitoring", "Blood pressure monitoring",
]

# Short forms doctors type for the common diagnoses.
ALIASES = {
    "Urinary tract infection": "UTI", "Acute upper respiratory tract infection": "URTI",
    "Acute gastroenteritis": "AGE", "Gastro-oesophageal reflux disease (GERD)": "GERD reflux",
    "Type 2 diabetes mellitus": "T2DM DM diabetes", "Uncontrolled type 2 diabetes mellitus": "T2DM DM diabetes",
    "Essential hypertension": "HTN", "Uncontrolled hypertension": "HTN", "Community-acquired pneumonia": "CAP LRTI",
    "Acute bronchitis": "LRTI", "Vertigo (BPPV)": "BPPV", "Osteoarthritis knee": "OA",
    "Acid peptic disease": "APD", "Acute coronary syndrome (suspected)": "ACS", "Iron deficiency anaemia": "IDA anemia",
    "Typhoid (enteric) fever": "enteric", "COPD exacerbation": "AECOPD", "Primary dysmenorrhoea": "dysmenorrhea period pain",
    "Acute exacerbation of asthma": "asthma attack",
}

FOLLOW_UPS = [
    "Review in 3 days", "Review in 1 week", "Review in 2 weeks", "Review with test reports",
    "Come back at once if worse", "No follow-up needed",
]

LIMIT = 8


def _rank(query: str, text: str) -> int | None:
    """0: the text starts with the query; 1: every query word starts a word
    of the text; 2: the query is somewhere in it; None: no match."""
    q = normalize(query)
    t = normalize(text)
    if not q or not t:
        return None
    words = t.split()
    if t.startswith(q) or q in words:  # "cbc" is CBC's own short name
        return 0
    if all(any(w.startswith(part) for w in words) for part in q.split()):
        return 1
    # Inside a word only for longer queries: "azi" must not find sulfadiazine.
    if len(q) >= 4 and q.replace(" ", "") in t.replace(" ", ""):
        return 2
    return None


def _medicine(name: str, form: str, strength: str, route: str, brand: str = "") -> dict:
    label = " ".join(x for x in (name, strength, form) if x)
    return {
        "label": f"{brand} · {label}" if brand else label,
        "name": name, "form": form, "strength": strength, "route": route,
        "source": "brand" if brand else "common",
    }  # fmt: skip


def medicines(query: str, extra_names: list[str] = ()) -> list[dict]:
    """Preparations whose name (or a brand of theirs) matches, best first;
    then other medicine names from the guideline database."""
    hits: list[tuple[int, int, int, dict]] = []
    for i, (name, form, strength, route) in enumerate(MEDICINES):
        rank = _rank(query, f"{name} {strength}")
        if rank is not None:
            hits.append((rank, 0, i, _medicine(name, form, strength, route)))
    for i, (brand, prep) in enumerate(BRANDS.items()):
        rank = _rank(query, brand)
        if rank is not None:
            hits.append((rank, 1, i, _medicine(*prep, brand=brand)))
    hits.sort(key=lambda h: h[:3])
    out = [h[3] for h in hits]
    known = {normalize(m["name"]) for m in out} | {normalize(m[0]) for m in MEDICINES}
    others = sorted(
        ((r, n) for n in extra_names if normalize(n) not in known and (r := _rank(query, n)) is not None),
        key=lambda x: (x[0], len(x[1])),
    )
    out += [{"label": n, "name": n, "form": "", "strength": "", "route": "", "source": "guidelines"} for _, n in others]
    return out[:LIMIT]


def names(query: str, common: list[str], extra: list[str] = ()) -> list[dict]:
    """Diagnoses or tests: the common list first, then the rest."""
    seen: set[str] = set()
    hits: list[tuple[int, int, int, str]] = []
    for tier, pool in ((0, common), (1, extra)):
        for i, n in enumerate(pool):
            key = normalize(n)
            if key in seen:
                continue
            rank = _rank(query, f"{n} {ALIASES.get(n, '')}")
            if rank is not None:
                seen.add(key)
                hits.append((rank, tier, len(n) if tier else i, n))
    hits.sort(key=lambda h: h[:3])
    return [{"label": n, "name": n} for *_, n in hits[:LIMIT]]


_CLEAN = re.compile(r"\s+")


def tidy(name: str) -> str:
    """A database name as a doctor would read it."""
    return _CLEAN.sub(" ", name or "").strip()
