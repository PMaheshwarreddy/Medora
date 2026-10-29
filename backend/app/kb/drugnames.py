"""One key per medicine across sources: Indian (BAN/INN), WHO (INN) and US
(USAN) spellings meet here, so 'Amoxycillin', 'amoxicillin', 'Adrenaline
(Epinephrine)' and 'acetaminophen' land on the same row as their siblings.

The key is the INN-style spelling, lower case; the name shown stays as the
first source printed it. Every spelling seen is kept as a drug term.
"""

import re

from .text import normalize

# word -> INN word (applied word by word after normalising)
_WORDS = {
    "amoxycillin": "amoxicillin", "cephalexin": "cefalexin", "cephazolin": "cefazolin", "cephradine": "cefradine",
    "frusemide": "furosemide", "lignocaine": "lidocaine", "adrenaline": "epinephrine", "noradrenaline": "norepinephrine",
    "acetaminophen": "paracetamol", "albuterol": "salbutamol", "glyburide": "glibenclamide", "phenobarbitone": "phenobarbital",
    "acyclovir": "aciclovir", "valacyclovir": "valaciclovir", "rifampin": "rifampicin", "cyclosporine": "ciclosporin",
    "cyclosporin": "ciclosporin", "chlorpheniramine": "chlorphenamine", "dicyclomine": "dicycloverine",
    "meperidine": "pethidine", "isoproterenol": "isoprenaline", "oestradiol": "estradiol", "ethinyloestradiol": "ethinylestradiol",
    "sulphate": "sulfate", "sulphamethoxazole": "sulfamethoxazole", "sulfamethoxazol": "sulfamethoxazole",
    "sulphasalazine": "sulfasalazine", "sulphadiazine": "sulfadiazine", "cotrimoxazole": "co trimoxazole",
    "thiopentone": "thiopental", "methylene": "methylene", "levothyroxin": "levothyroxine", "salbutamol": "salbutamol",
    "beclomethasone": "beclometasone", "dexamethazone": "dexamethasone", "ondansatron": "ondansetron",
    "metformine": "metformin", "busulphan": "busulfan", "aluminum": "aluminium", "oxytocine": "oxytocin",
    "clavulanate": "clavulanic", "pyridoxin": "pyridoxine", "riboflavine": "riboflavin", "retinol": "retinol",
    "ciprofloxacine": "ciprofloxacin", "mesalazine": "mesalazine", "mesalamine": "mesalazine",
    "nitroglycerin": "glyceryl trinitrate", "aspirin": "acetylsalicylic acid", "acetylsalicylic": "acetylsalicylic",
    "salicyclic": "salicylic", "acetylsalicyclic": "acetylsalicylic",
}
# salt and form words a US label adds to the substance
_SALTS = {
    "hydrochloride", "hcl", "sodium", "potassium", "sulfate", "maleate", "tartrate", "citrate", "phosphate", "acetate",
    "besylate", "besilate", "mesylate", "mesilate", "succinate", "fumarate", "bromide", "calcium", "magnesium",
    "dihydrate", "trihydrate", "monohydrate", "anhydrous", "hyclate", "disodium", "dipropionate", "propionate",
    "hydrobromide", "lactate", "gluconate", "nitrate", "valerate", "furoate", "xinafoate", "tromethamine",
}
_PAREN = re.compile(r"\(([^)]*)\)")
_JOINERS = {"and", "with", "plus"}


def _words(text: str) -> list[str]:
    out = []
    for w in normalize(text).split():
        if w in _JOINERS:
            continue
        out.extend(_WORDS.get(w, w).split())
    return out


def canonical(name: str) -> str:
    """The shared key: INN spelling, bracketed alternatives and joiners removed."""
    return " ".join(_words(_PAREN.sub(" ", name or "")))


def stripped(name: str) -> str:
    """The key without salt words ('metformin hydrochloride' -> 'metformin')."""
    ws = [w for w in canonical(name).split() if w not in _SALTS]
    return " ".join(ws)


def spellings(name: str) -> list[str]:
    """Names to keep as terms: as printed, without the brackets, and each bracketed alternative."""
    out = [name.strip()]
    base = _PAREN.sub(" ", name).strip()
    out.append(re.sub(r"\s+", " ", base))
    for alt in _PAREN.findall(name):
        if alt.strip() and not re.search(r"\d", alt):
            out.append(alt.strip())
    seen, result = set(), []
    for n in out:
        if n and normalize(n) not in seen:
            seen.add(normalize(n))
            result.append(n)
    return result


# US names a model may write -> the name an Indian prescription uses.
_INDIAN = {
    "acetaminophen": "paracetamol", "albuterol": "salbutamol", "levalbuterol": "levosalbutamol",
    "glyburide": "glibenclamide", "meperidine": "pethidine", "rifampin": "rifampicin",
    "isoproterenol": "isoprenaline", "nitroglycerin": "glyceryl trinitrate",
}


def indian(name: str) -> str:
    """'Acetaminophen 500 mg' -> 'Paracetamol 500 mg' (case kept); other names unchanged."""
    def swap(m):
        word = m.group(0)
        new = _INDIAN.get(word.lower(), word.lower())
        if new == word.lower():
            return word
        return new.title() if word[:1].isupper() else new

    return re.sub(r"[A-Za-z]+", swap, name or "")
