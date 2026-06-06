"""
Programmatic validation and correction layer for PathogenIQ agents.

Applies two layers of correction to LLM-synthesized pathogen data:
  1. Filter: remove values not in the allowed set (routes, hosts)
  2. Override: replace routes/hosts/category for known pathogens with
     biologically verified values from a lookup table.

Also provides name normalization for the Sentinel agent to canonicalize
disease names and common synonyms to scientific pathogen names.

WHY THIS EXISTS:
  The default LLM (qwen2.5:0.5b, 500M params) cannot reliably follow
  complex prohibitions in prompts. This layer intercepts the LLM output
  and enforces correctness programmatically so hallucinations never reach
  the database, regardless of model behavior.
"""

from __future__ import annotations

# ── Allowed value sets ────────────────────────────────────────────────────────

ALLOWED_ROUTES: frozenset[str] = frozenset([
    "airborne", "droplet", "contact", "fecal-oral", "vector-borne",
    "sexual", "bloodborne", "zoonotic", "waterborne", "iatrogenic",
])

ALLOWED_HOSTS: frozenset[str] = frozenset([
    "rodents", "bats", "non-human primates", "poultry", "waterfowl",
    "pigs", "camels", "horses", "cattle", "sheep", "goats",
    "dogs", "foxes", "deer", "soil", "aquatic environments", "humans",
])

# ── Known taxonomy: category ──────────────────────────────────────────────────
# Keys are lowercase. Longer/more-specific keys must come first so prefix
# matching picks the right entry (e.g., "borrelia burgdorferi" before "borrelia").

_KNOWN_CATEGORIES: dict[str, str] = {
    # Bacteria
    "mycobacterium tuberculosis":   "bacterium",
    "clostridioides difficile":     "bacterium",
    "pseudomonas aeruginosa":       "bacterium",
    "acinetobacter baumannii":      "bacterium",
    "streptococcus pneumoniae":     "bacterium",
    "listeria monocytogenes":       "bacterium",
    "neisseria meningitidis":       "bacterium",
    "klebsiella pneumoniae":        "bacterium",
    "staphylococcus aureus":        "bacterium",
    "mycoplasma pneumoniae":        "bacterium",
    "vibrio cholerae":              "bacterium",
    "coxiella burnetii":            "bacterium",
    "yersinia pestis":              "bacterium",
    "borrelia burgdorferi":         "bacterium",
    "borrelia mayonii":             "bacterium",
    "enterobacterales":             "bacterium",
    "salmonella":                   "bacterium",
    "brucella":                     "bacterium",
    "borrelia":                     "bacterium",
    # Viruses
    "influenza a h5n1":             "virus",
    "measles morbillivirus":        "virus",
    "lassa mammarenavirus":         "virus",
    "rift valley fever virus":      "virus",
    "respiratory syncytial virus":  "virus",
    "varicella-zoster virus":       "virus",
    "yellow fever virus":           "virus",
    "herpes simplex virus":         "virus",
    "rabies lyssavirus":            "virus",
    "west nile virus":              "virus",
    "dengue virus":                 "virus",
    "marburg virus":                "virus",
    "ebola virus":                  "virus",
    "nipah virus":                  "virus",
    "sars-cov-2":                   "virus",
    "mers-cov":                     "virus",
    "mpox virus":                   "virus",
    "hantavirus":                   "virus",
    "norovirus":                    "virus",
    "rotavirus":                    "virus",
    "influenza":                    "virus",
    "hepatitis b":                  "virus",
    "hepatitis c":                  "virus",
    "hiv":                          "virus",
    "rsv":                          "virus",
    # Fungi
    "aspergillus fumigatus":        "fungus",
    "cryptococcus neoformans":      "fungus",
    "histoplasma capsulatum":       "fungus",
    "candida auris":                "fungus",
    "coccidioides":                 "fungus",
    # Parasites
    "plasmodium falciparum":        "parasite",
    "toxoplasma gondii":            "parasite",
    "cryptosporidium":              "parasite",
    "trypanosoma":                  "parasite",
    "leishmania":                   "parasite",
    "plasmodium":                   "parasite",
}

# ── Known transmission routes ─────────────────────────────────────────────────

_KNOWN_ROUTES: dict[str, list[str]] = {
    # Bloodborne / sexual
    "hiv":                          ["sexual", "bloodborne"],
    "ebola virus":                  ["contact", "bloodborne"],
    "marburg virus":                ["contact", "bloodborne"],
    "hepatitis b":                  ["bloodborne", "sexual"],
    "hepatitis c":                  ["bloodborne", "sexual"],
    # Contact / zoonotic
    "rabies lyssavirus":            ["contact", "zoonotic"],
    "mpox virus":                   ["contact", "droplet"],
    "mers-cov":                     ["droplet", "zoonotic"],
    "nipah virus":                  ["contact", "zoonotic"],
    "influenza a h5n1":             ["contact", "zoonotic"],
    "lassa mammarenavirus":         ["contact", "zoonotic"],
    "herpes simplex virus":         ["contact", "sexual"],
    # Airborne
    "measles morbillivirus":        ["airborne", "droplet"],
    "sars-cov-2":                   ["airborne", "droplet"],
    "mycobacterium tuberculosis":   ["airborne"],
    "hantavirus":                   ["airborne", "zoonotic"],
    "aspergillus fumigatus":        ["airborne"],
    "varicella-zoster virus":       ["airborne", "contact"],
    "influenza":                    ["airborne", "droplet"],
    # Vector-borne
    "dengue virus":                 ["vector-borne"],
    "yellow fever virus":           ["vector-borne"],
    "west nile virus":              ["vector-borne"],
    "rift valley fever virus":      ["vector-borne", "contact", "zoonotic"],
    "leishmania":                   ["vector-borne"],
    "plasmodium":                   ["vector-borne"],
    "trypanosoma brucei":           ["vector-borne"],
    "trypanosoma cruzi":            ["vector-borne", "contact", "bloodborne"],
    "trypanosoma":                  ["vector-borne"],
    "borrelia burgdorferi":         ["vector-borne", "zoonotic"],
    "borrelia mayonii":             ["vector-borne", "zoonotic"],
    "borrelia":                     ["vector-borne", "zoonotic"],
    "yersinia pestis":              ["vector-borne", "contact", "zoonotic"],
    # Fecal-oral / waterborne
    "vibrio cholerae":              ["fecal-oral", "waterborne"],
    "norovirus":                    ["fecal-oral", "contact", "waterborne"],
    "rotavirus":                    ["fecal-oral", "contact"],
    "cryptosporidium":              ["fecal-oral", "waterborne"],
    "salmonella":                   ["fecal-oral", "zoonotic"],
    "listeria monocytogenes":       ["fecal-oral", "zoonotic"],
    # Healthcare / nosocomial
    "klebsiella pneumoniae":        ["contact", "iatrogenic"],
    "pseudomonas aeruginosa":       ["contact", "iatrogenic"],
    "acinetobacter baumannii":      ["contact", "iatrogenic"],
    "clostridioides difficile":     ["fecal-oral", "contact", "iatrogenic"],
    "candida auris":                ["contact", "iatrogenic"],
}

# ── Known reservoir hosts ─────────────────────────────────────────────────────

_KNOWN_HOSTS: dict[str, list[str]] = {
    "sars-cov-2":                   ["humans"],
    "hiv":                          ["humans"],
    "measles morbillivirus":        ["humans"],
    "influenza":                    ["humans"],
    "herpes simplex virus":         ["humans"],
    "varicella-zoster virus":       ["humans"],
    "ebola virus":                  ["bats"],
    "marburg virus":                ["bats"],
    "nipah virus":                  ["bats"],
    "mers-cov":                     ["camels"],
    "influenza a h5n1":             ["poultry", "waterfowl"],
    "lassa mammarenavirus":         ["rodents"],
    "hantavirus":                   ["rodents"],
    "yersinia pestis":              ["rodents"],
    "borrelia burgdorferi":         ["rodents", "deer"],
    "borrelia mayonii":             ["rodents", "deer"],
    "borrelia":                     ["rodents", "deer"],
    "rabies lyssavirus":            ["bats", "dogs", "foxes"],
    "rift valley fever virus":      ["cattle", "sheep", "goats"],
    "coxiella burnetii":            ["sheep", "goats", "cattle"],
    "brucella":                     ["cattle", "sheep", "goats", "pigs"],
    "listeria monocytogenes":       ["soil", "cattle"],
    # No natural animal reservoir — return empty list
    "klebsiella pneumoniae":        [],
    "clostridioides difficile":     [],
    "candida auris":                [],
    "dengue virus":                 [],
    "yellow fever virus":           [],
    "west nile virus":              [],
    "leishmania":                   [],
    "plasmodium":                   [],
    "trypanosoma":                  [],
}

# ── Sentinel name normalization ───────────────────────────────────────────────
# Maps lowercase aliases and disease names → canonical scientific name.

_NORMALIZATIONS: dict[str, str] = {
    # Measles
    "measles":                      "Measles morbillivirus",
    "measles virus":                "Measles morbillivirus",
    "rubeola":                      "Measles morbillivirus",
    # COVID
    "covid":                        "SARS-CoV-2",
    "covid-19":                     "SARS-CoV-2",
    "covid19":                      "SARS-CoV-2",
    "novel coronavirus":            "SARS-CoV-2",
    "2019-ncov":                    "SARS-CoV-2",
    # Influenza
    "flu":                          "Influenza",
    "seasonal flu":                 "Influenza",
    "seasonal influenza":           "Influenza",
    "bird flu":                     "Influenza A H5N1",
    "avian flu":                    "Influenza A H5N1",
    "avian influenza":              "Influenza A H5N1",
    "h5n1":                         "Influenza A H5N1",
    "swine flu":                    "Influenza A H1N1",
    # Filoviruses
    "ebola":                        "Ebola virus",
    "ebola hemorrhagic fever":      "Ebola virus",
    "marburg":                      "Marburg virus",
    "marburg hemorrhagic fever":    "Marburg virus",
    # TB
    "tb":                           "Mycobacterium tuberculosis",
    "tuberculosis":                 "Mycobacterium tuberculosis",
    # Mpox
    "mpox":                         "Mpox virus",
    "monkeypox":                    "Mpox virus",
    # RSV
    "rsv":                          "Respiratory syncytial virus",
    # Staph
    "mrsa":                         "Staphylococcus aureus",
    "mssa":                         "Staphylococcus aureus",
    "staph":                        "Staphylococcus aureus",
    # C. diff
    "c. diff":                      "Clostridioides difficile",
    "c difficile":                  "Clostridioides difficile",
    "cdiff":                        "Clostridioides difficile",
    "clostridium difficile":        "Clostridioides difficile",
    # Disease names → pathogen names
    "genital herpes":               "Herpes simplex virus 2",
    "herpes":                       "Herpes simplex virus",
    "chickenpox":                   "Varicella-zoster virus",
    "varicella":                    "Varicella-zoster virus",
    "shingles":                     "Varicella-zoster virus",
    "plague":                       "Yersinia pestis",
    "cholera":                      "Vibrio cholerae",
    "rabies":                       "Rabies lyssavirus",
    "mumps":                        "Mumps orthorubulavirus",
    "rubella":                      "Rubella virus",
    "dengue":                       "Dengue virus",
    "dengue fever":                 "Dengue virus",
    "malaria":                      "Plasmodium falciparum",
    "lyme disease":                 "Borrelia burgdorferi",
    "lyme":                         "Borrelia burgdorferi",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _lookup(name_lower: str, table: dict):
    """Exact match, then longest-key prefix match (more specific wins)."""
    if name_lower in table:
        return table[name_lower]
    for key in sorted(table, key=len, reverse=True):
        if name_lower.startswith(key):
            return table[key]
    return None


# ── Public API ────────────────────────────────────────────────────────────────

def normalize_pathogen_name(raw: str) -> str:
    """
    Map a Sentinel-extracted name to its canonical scientific name.

    Handles common aliases, disease names used in place of pathogen names,
    and abbreviations. Returns raw unchanged when no mapping exists.
    """
    key = raw.lower().strip()
    return _NORMALIZATIONS.get(key, raw)


def correct_pathogen_profile(species_name: str, profile: dict) -> dict:
    """
    Apply programmatic corrections to an LLM-synthesized pathogen profile.

    Three passes:
      1. Category  — override to known biological classification.
      2. Routes    — hardcoded for known pathogens; filtered to allowed set otherwise.
      3. Hosts     — same strategy as routes.

    Returns a corrected copy of the profile dict.
    """
    name_lower = species_name.lower().strip()
    profile = dict(profile)

    # 1. Category
    known_cat = _lookup(name_lower, _KNOWN_CATEGORIES)
    if known_cat:
        profile["category"] = known_cat

    # 2. Transmission routes
    known_routes = _lookup(name_lower, _KNOWN_ROUTES)
    if known_routes is not None:
        profile["transmission_routes"] = list(known_routes)
    else:
        raw = profile.get("transmission_routes") or []
        profile["transmission_routes"] = [r for r in raw if r in ALLOWED_ROUTES]

    # 3. Reservoir hosts — deduplicate while preserving order
    known_hosts = _lookup(name_lower, _KNOWN_HOSTS)
    if known_hosts is not None:
        profile["reservoir_hosts"] = list(known_hosts)
    else:
        raw = profile.get("reservoir_hosts") or []
        seen: set[str] = set()
        filtered: list[str] = []
        for h in raw:
            if h in ALLOWED_HOSTS and h not in seen:
                filtered.append(h)
                seen.add(h)
        profile["reservoir_hosts"] = filtered

    return profile
