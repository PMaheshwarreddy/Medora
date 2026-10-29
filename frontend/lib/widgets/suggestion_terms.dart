/// What counts as a mention of each tap-to-select answer, so a chip lights
/// up when the patient's own words (typed, or heard by the voice agent)
/// already say it: "fever, worse at night" selects Fever, "Dolo 650"
/// selects Paracetamol. Each list lines up, entry for entry, with the
/// matching list in `l10n/strings.dart`, and holds words in both languages:
/// the patient may speak one and read the other.
library;

const symptomTerms = <List<String>>[
  ['fever', 'feverish', 'temperature', 'പനി'],
  ['cough', 'ചുമ'],
  [
    'cold',
    'runny nose',
    'sneez',
    'blocked nose',
    'stuffy nose',
    'ജലദോഷം',
    'മൂക്കൊലിപ്പ്',
    'തുമ്മൽ',
  ],
  ['sore throat', 'throat pain', 'throat ache', 'തൊണ്ടവേദന', 'തൊണ്ട വേദന'],
  ['headache', 'head ache', 'head pain', 'തലവേദന', 'തല വേദന'],
  [
    'body pain',
    'body ache',
    'bodyache',
    'body-ache',
    'ശരീരവേദന',
    'ശരീര വേദന',
    'മേലുവേദന',
    'ദേഹം വേദന',
  ],
  [
    'stomach pain',
    'stomach ache',
    'abdominal pain',
    'tummy',
    'belly pain',
    'വയറുവേദന',
    'വയറ് വേദന',
  ],
  ['vomit', 'throwing up', 'ഛർദ്ദി', 'ശർദ്ദി'],
  ['loose motion', 'diarrh', 'loose stool', 'വയറിളക്കം'],
  ['chest pain', 'chest tight', 'നെഞ്ചുവേദന', 'നെഞ്ച് വേദന'],
  ['breath', 'ശ്വാസം', 'ശ്വാസംമുട്ട'],
  ['dizz', 'giddi', 'vertigo', 'light-headed', 'തലകറക്ക', 'തല കറക്ക'],
  ['tired', 'fatigue', 'weakness', 'exhaust', 'ക്ഷീണം', 'തളർച്ച'],
  ['rash', 'itch', 'hives', 'ചൊറിച്ചിൽ', 'തടിപ്പ്', 'ചൊറി'],
  [
    'back pain',
    'backache',
    'joint pain',
    'knee pain',
    'നടുവേദന',
    'സന്ധിവേദന',
    'മുട്ടുവേദന',
  ],
  [
    'burning urin',
    'burning when passing urine',
    'burning while passing urine',
    'pain while passing urine',
    'painful urination',
    'മൂത്രമൊഴിക്കുമ്പോൾ',
    'മൂത്രത്തിൽ നീറ്റൽ',
  ],
];

const medicationTerms = <List<String>>[
  [
    'none',
    'nothing',
    'no medicine',
    'not taken',
    'ഒന്നുമില്ല',
    'ഒന്നും കഴിച്ചില്ല',
  ],
  [
    'paracetamol',
    'acetaminophen',
    'dolo',
    'crocin',
    'calpol',
    'pacimol',
    'പാരസെറ്റമോൾ',
    'ഡോളോ',
    'ക്രോസിൻ',
    'കാൽപോൾ',
  ],
  ['ibuprofen', 'brufen', 'combiflam', 'ഐബുപ്രോഫെൻ', 'കോമ്പിഫ്ലാം'],
  ['syrup', 'സിറപ്പ്'],
  ['antacid', 'digene', 'gelusil', 'eno', 'pantop', 'pan 40', 'ഗ്യാസ്'],
  ['antibiotic', 'amoxi', 'azithro', 'ആന്റിബയോട്ടിക്'],
  [
    'allergy tablet',
    'cetirizine',
    'cetzine',
    'okacet',
    'allegra',
    'avil',
    'അലർജി ഗുളിക',
  ],
  ['inhaler', 'asthalin', 'ഇൻഹേലർ'],
];

const allergyTerms = <List<String>>[
  ['no allerg', 'none', 'nothing', 'not allergic', 'അലർജിയില്ല', 'അലർജി ഇല്ല'],
  ['penicillin', 'amoxi', 'പെൻസിലിൻ'],
  ['sulfa', 'sulpha', 'സൾഫ'],
  [
    'painkiller',
    'pain killer',
    'aspirin',
    'ibuprofen',
    'diclofenac',
    'nsaid',
    'വേദനസംഹാരി',
  ],
  ['injection', 'ഇഞ്ചക്ഷൻ', 'കുത്തിവ'],
  [
    'food',
    'peanut',
    'egg',
    'milk',
    'seafood',
    'prawn',
    'fish',
    'ഭക്ഷണ',
    'മീൻ',
    'ചെമ്മീൻ',
  ],
];

/// Whether [text] mentions any of [terms]. Short English words must stand
/// alone ("eno" is not inside "phenomenon"); longer ones and Malayalam may
/// sit inside a word ("feverish", "പനിയും").
/// Lines up with `S.conditionSuggestions`: the first means "none".
const conditionTerms = <List<String>>[
  ['none', 'no', 'nothing', 'ഒന്നുമില്ല', 'ഇല്ല'],
  ['diabetes', 'diabetic', 'sugar', 'പ്രമേഹം', 'ഷുഗർ'],
  ['high blood pressure', 'hypertension', 'bp', 'രക്തസമ്മർദ്ദം', 'പ്രഷർ'],
  ['asthma', 'wheez', 'ആസ്ത്മ', 'ശ്വാസംമുട്ട്'],
  ['heart', 'cardiac', 'ഹൃദ്രോഗം', 'ഹൃദയ'],
  ['thyroid', 'തൈറോയ്ഡ്'],
  ['kidney', 'renal', 'വൃക്ക'],
];

bool mentions(String text, Iterable<String> terms) {
  final lower = text.toLowerCase();
  for (final term in terms) {
    final t = term.toLowerCase();
    if (t.length <= 4 && RegExp(r'^[a-z ]+$').hasMatch(t)) {
      if (RegExp('\\b${RegExp.escape(t)}\\b').hasMatch(lower)) return true;
    } else if (lower.contains(t)) {
      return true;
    }
  }
  return false;
}
