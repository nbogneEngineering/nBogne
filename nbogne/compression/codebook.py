"""
Medical Code Dictionaries

Maps common medical codes (ICD-10, LOINC, CVX, medications, etc.) to compact
uint16 indices for binary encoding. Both sender and receiver share this codebook.

Index 0: empty/missing code
Index 1-65534: codebook entries
Index 65535 (0xFFFF): inline string follows (code not in codebook)
"""

NOT_IN_CODEBOOK = 0xFFFF

CODEBOOKS = {
    "icd10": {
        # Most common in Sub-Saharan Africa primary care
        "I10": 1,       # Essential hypertension
        "E11.9": 2,     # Type 2 diabetes mellitus
        "J06.9": 3,     # Acute upper respiratory infection
        "B50.9": 4,     # Plasmodium falciparum malaria
        "D50.9": 5,     # Iron deficiency anaemia
        "O80": 6,       # Single spontaneous delivery
        "A09": 7,       # Diarrhoea and gastroenteritis
        "J18.9": 8,     # Pneumonia, unspecified
        "N39.0": 9,     # Urinary tract infection
        "B24": 10,      # HIV disease
        "K29.7": 11,    # Gastritis, unspecified
        "J45.9": 12,    # Asthma, unspecified
        "E55.9": 13,    # Vitamin D deficiency
        "L30.9": 14,    # Dermatitis, unspecified
        "M54.5": 15,    # Low back pain
        "R50.9": 16,    # Fever, unspecified
        "K21.0": 17,    # GERD
        "E78.5": 18,    # Hyperlipidaemia
        "G43.9": 19,    # Migraine, unspecified
        "J02.9": 20,    # Acute pharyngitis
        "E10.9": 21,    # Type 1 diabetes
        "I11.9": 22,    # Hypertensive heart disease
        "I25.9": 23,    # Chronic ischaemic heart disease
        "E11.65": 24,   # Type 2 DM with hyperglycaemia
        "Z23": 25,      # Encounter for immunization
        "J20.9": 26,    # Acute bronchitis
        "B37.0": 27,    # Candida stomatitis
        "E86.0": 28,    # Dehydration
        "R51": 29,      # Headache
        "K59.0": 30,    # Constipation
    },
    "loinc": {
        "8480-6": 1,    # Systolic BP
        "8462-4": 2,    # Diastolic BP
        "8867-4": 3,    # Heart rate
        "8310-5": 4,    # Body temperature
        "2708-6": 5,    # SpO2
        "29463-7": 6,   # Body weight
        "8302-2": 7,    # Body height
        "2339-0": 8,    # Glucose [mass/vol] in blood
        "59408-5": 9,   # SpO2 (pulse ox)
        "718-7": 10,    # Hemoglobin
        "2160-0": 11,   # Creatinine
        "2345-7": 12,   # Glucose [mass/vol] in serum
        "6299-2": 13,   # Urea nitrogen
        "17861-6": 14,  # Calcium
        "2947-0": 15,   # Sodium
        "6298-4": 16,   # Potassium
        "32623-1": 17,  # Platelet count
        "26464-8": 18,  # Leukocytes
        "789-8": 19,    # Erythrocytes
        "4548-4": 20,   # HbA1c
    },
    "medication": {
        "amlodipine-5mg": 1,
        "metformin-500mg": 2,
        "amoxicillin-500mg": 3,
        "paracetamol-500mg": 4,
        "artemether-lumefantrine": 5,
        "lisinopril-10mg": 6,
        "atorvastatin-20mg": 7,
        "omeprazole-20mg": 8,
        "ibuprofen-400mg": 9,
        "ciprofloxacin-500mg": 10,
        "metronidazole-400mg": 11,
        "doxycycline-100mg": 12,
        "azithromycin-500mg": 13,
        "hydrochlorothiazide-25mg": 14,
        "atenolol-50mg": 15,
        "glibenclamide-5mg": 16,
        "ferrous-sulfate-200mg": 17,
        "folic-acid-5mg": 18,
        "cotrimoxazole-960mg": 19,
        "oral-rehydration-salts": 20,
        "metformin-1000mg": 21,
        "amlodipine-10mg": 22,
        "losartan-50mg": 23,
        "nifedipine-20mg": 24,
        "insulin-glargine": 25,
    },
    "cvx": {
        "03": 1,    # MMR
        "21": 2,    # Varicella
        "08": 3,    # Hep B
        "10": 4,    # IPV
        "20": 5,    # DTaP
        "114": 6,   # MCV4
        "133": 7,   # PCV13
        "141": 8,   # Influenza intranasal
        "115": 9,   # Tdap
        "94": 10,   # MMRV
        "62": 11,   # HPV quadrivalent
        "187": 12,  # RZV (shingles)
        "207": 13,  # COVID-19 mRNA
        "83": 14,   # Hep A
        "89": 15,   # Polio (unspecified)
        "02": 16,   # OPV trivalent
        "01": 17,   # DTP
        "28": 18,   # DT
        "09": 19,   # Td
        "52": 20,   # Hep A (adult)
    },
    "encounter_type": {
        "AMB": 1,       # Ambulatory
        "EMER": 2,      # Emergency
        "IMP": 3,       # Inpatient
        "PRENC": 4,     # Pre-admission
        "SS": 5,        # Short stay
        "VR": 6,        # Virtual
        "HH": 7,        # Home health
        "OBSENC": 8,    # Observation encounter
    },
    "ucum": {
        "mmHg": 1,
        "/min": 2,
        "Cel": 3,
        "kg": 4,
        "cm": 5,
        "mg/dL": 6,
        "mmol/L": 7,
        "g/dL": 8,
        "%": 9,
        "mL": 10,
        "g/L": 11,
        "10*9/L": 12,
        "10*12/L": 13,
        "fL": 14,
        "U/L": 15,
    },
    "interpretation": {
        "N": 1,     # Normal
        "H": 2,     # High
        "L": 3,     # Low
        "HH": 4,    # Critical high
        "LL": 5,    # Critical low
        "A": 6,     # Abnormal
    },
    "body_site": {
        "LA": 1,    # Left arm
        "RA": 2,    # Right arm
        "LT": 3,    # Left thigh
        "RT": 4,    # Right thigh
        "LD": 5,    # Left deltoid
        "RD": 6,    # Right deltoid
    },
    "facility": {
        # Populated per-deployment with facility codes
    },
}

# Precompute reverse lookups (index → code string)
_REVERSE = {}
for _book_name, _mapping in CODEBOOKS.items():
    _REVERSE[_book_name] = {v: k for k, v in _mapping.items()}


def encode_code(value: str, codebook_name: str) -> tuple[int, bool]:
    """Look up a code in the codebook. Returns (index, found).
    Empty string maps to index 0 (reserved for missing)."""
    if not value:
        return 0, True
    book = CODEBOOKS.get(codebook_name, {})
    idx = book.get(value)
    if idx is not None:
        return idx, True
    return NOT_IN_CODEBOOK, False


def decode_code(index: int, codebook_name: str) -> str:
    """Reverse lookup from codebook index to code string.
    Index 0 returns empty string. NOT_IN_CODEBOOK means inline string follows."""
    if index == 0:
        return ""
    if index == NOT_IN_CODEBOOK:
        return ""  # caller reads inline string
    reverse = _REVERSE.get(codebook_name, {})
    return reverse.get(index, f"UNKNOWN:{index}")
