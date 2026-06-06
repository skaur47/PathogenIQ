"""
Outbreak relevance filter — two-gate binary classifier for Phase 2 ingestion.

Gate 1 — Exclusion (checked against TITLE):
  Hard-rejects vaccine-policy, lifestyle, mental health, review/opinion,
  and non-outbreak administrative content. If any exclusion term is found
  in the title, the document is dropped regardless of positive signals.

Gate 2 — Active outbreak signal (checked against TITLE + ABSTRACT):
  Must find at least one active-event indicator (outbreak, cases reported,
  spread, novel detection, health alert) OR a high-consequence pathogen name
  that is inherently newsworthy whenever it appears in a health-authority feed.

What this keeps in:
  "H5N1 avian influenza detected in two human cases in Egypt" → ✓ (h5n1 signal)
  "Notes from the Field: Salmonella Outbreak Investigation" → ✓ (outbreak signal)
  "ECDC Communicable disease threats report, Week 20" → ✓ (disease threat signal)
  "First human case of Nipah virus in Bangladesh" → ✓ (nipah signal)

What this filters out:
  "COVID vaccine uptake lower among rural populations" → ✗ (vaccine coverage)
  "UK COVID pandemic inquiry: key findings" → ✗ (inquiry + key findings)
  "Physical activity and mental health in adolescents" → ✗ (lifestyle)
  "Systematic review of influenza vaccine efficacy" → ✗ (systematic review)
  "Remdesivir outcomes in hospitalised COVID patients" → ✗ (no outbreak signal)

NOT applied to PubMed (has its own ESearch query) or directly to ProMED/CIDRAP
posts (called from collect() in each respective collector).
"""

import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from .schemas import CollectedDocument

# ── Gate 1: Exclusion terms ───────────────────────────────────────────────────
# Matched against the document TITLE (case-insensitive, literal strings).
# One match → document dropped immediately.

_EXCLUDE_TERMS: list[str] = [
    # Vaccine policy / coverage (not outbreak-driven vaccination)
    "vaccine coverage", "vaccine uptake", "vaccine hesitancy",
    "vaccine acceptance", "vaccine confidence",
    "vaccination rate", "vaccination coverage",
    "immunization coverage", "immunization rate",
    "immunization programme", "immunization program",
    "vaccine rollout", "vaccine mandate",
    "booster uptake", "booster coverage",
    "vaccine safety", "vaccine efficacy trial",
    "vaccines a huge success", "vaccines extraordinary",
    "vaccine trial results", "vaccination campaign results",
    # Mental / behavioural health
    "suicide", "suicidal", "self-harm",
    "mental health", "depressive disorder", "anxiety disorder",
    "substance use disorder", "alcohol use disorder",
    "smoking cessation", "tobacco control",
    # Lifestyle / chronic non-infectious disease
    "physical activity", "sedentary", "exercise regimen",
    "dietary intake", "dietary pattern", "nutrition",
    "obesity", "overweight", "body mass index",
    "cardiovascular disease", "heart failure", "myocardial",
    "stroke", "hypertension", "blood pressure",
    "type 2 diabetes", "diabetes mellitus", "insulin resistance",
    "cancer treatment", "chemotherapy", "oncology", "tumour", "tumor",
    "dental caries", "oral health",
    "maternal mortality rate", "prenatal care",
    # Review / opinion content
    "systematic review", "scoping review", "narrative review",
    "meta-analysis", "literature review", "rapid review",
    "commentary", "editorial", "opinion article",
    "perspective article", "expert opinion",
    # Policy / administrative / retrospective
    "pandemic inquiry", "covid inquiry", "public inquiry",
    "key findings from", "what is the",
    "retrospective analysis", "looking back",
    # Drug / toxicology (non-pathogen) events
    "drug overdose", "overdose death",
    "withdrawal syndrome", "medetomidine",
    "opioid", "fentanyl", "kratom", "cannabis", "marijuana",
    "stimulant use", "substance overdose",
    # Environmental / non-infectious health events
    "heat-related illness", "heatrisk", "heat stress",
    "air quality", "wildfire smoke",
    # Vaccine recommendations (not outbreak-driven vaccination)
    "meningococcal vaccine",     # ACIP recommendation articles
    "pentavalent vaccine", "recommendations and reports",
    # Screen / technology / policy non-health-emergency content
    "screen time", "social media use",
    "burning questions", "senators had",   # political/governance news
    "inside health",                        # BBC podcast show heading, not article
    # Other irrelevant topics
    "healthcare worker burnout", "medical education",
    "clinical training", "residency training",
    "health economics", "cost-effectiveness",
]

_EXCLUSION_PATTERN = re.compile(
    "|".join(re.escape(t) for t in _EXCLUDE_TERMS),
    re.IGNORECASE,
)

# ── Gate 2: Active outbreak signals ───────────────────────────────────────────
# Matched against TITLE + ABSTRACT (case-insensitive, literal strings).
# At least one match required to pass.

_SIGNAL_TERMS: list[str] = [
    # Core outbreak vocabulary — any of these in isolation is sufficient
    "outbreak", "epidemic", "pandemic",
    "disease cluster", "cluster of cases",
    "cases reported", "cases detected", "cases confirmed", "cases identified",
    "new cases of", "new human case", "human cases of",
    "first human case", "first confirmed case",
    "novel pathogen", "novel strain", "novel variant", "novel virus",
    "emerging disease", "emerging pathogen", "emerging infection",
    "emerging outbreak",
    "public health emergency", "pheic",
    "health alert", "health advisory", "disease alert",
    "rapid risk assessment",
    "imported case", "travel-related case", "travel-associated case",
    "cross-border spread", "international spread",
    "zoonotic spillover",
    "deaths reported", "fatalities reported",
    "disease threat", "communicable disease threat",
    "outbreak investigation", "outbreak response",
    "notes from the field",          # CDC MMWR outbreak reports
    "surveillance update", "disease surveillance report",
    "epidemic intelligence",
    "contact tracing", "quarantine",
    # Removed: "notes from the field" — too broad; MMWR uses this section for
    # drug/heat/environmental events, not just infectious disease outbreaks.
    # High-consequence pathogens — any mention qualifies
    "rabies",                    # every human case is a public health event
    "measles",                   # outbreaks; vaccine articles caught by Gate 1
    "meningococcal",             # invasive bacterial disease
    "haemophilus influenzae",    # invasive Hib disease
    "pertussis", "whooping cough",
    "coccidioidomycosis", "valley fever",
    "congenital syphilis",
    "ebola", "marburg virus",
    "nipah", "nipah virus",
    "hendra", "hendra virus",
    "lassa fever",
    "plague", "yersinia pestis",
    "anthrax", "bacillus anthracis",
    "smallpox", "variola",
    "h5n1", "h5n2", "h5n5", "h5n6", "h5n8", "h5n9",
    "h7n2", "h7n9", "h9n2",
    "avian influenza", "bird flu", "highly pathogenic avian",
    "sars-cov", "sars-cov-2",
    "mers-cov", "mers coronavirus",
    "novel coronavirus",
    "mpox", "monkeypox",
    "viral haemorrhagic fever", "viral hemorrhagic fever",
    "rift valley fever",
    "hantavirus",
    "eastern equine encephalitis",
    "western equine encephalitis",
    "west nile virus",
    "chikungunya outbreak",
    "dengue outbreak", "dengue fever outbreak",
    "yellow fever outbreak",
    "cholera outbreak",
    "typhoid outbreak",
    # Drug-resistance emergencies
    "drug-resistant outbreak",
    "xdr-tb", "mdr-tb", "extensively drug-resistant",
    "carbapenem-resistant",
    "candida auris",
    # Foodborne / waterborne outbreaks
    "foodborne illness outbreak", "food poisoning outbreak",
    "waterborne disease outbreak",
    "e. coli outbreak", "salmonella outbreak",
    "listeria outbreak", "listeria monocytogenes outbreak",
    "legionnaire", "legionella outbreak",
    "botulism outbreak",
    # MMWR-style outbreak report phrasing
    "invasive disease",           # invasive Hib, invasive meningococcal
    "invasive infection",
    "increase in incidence",      # regional rise in disease
    "increases in incidence",
    "fatal case", "fatal cases",
    "high severity season",       # influenza severity tracking
    "influenza-associated deaths", "influenza-associated hospitalizations",
    "associated deaths",          # pathogen-associated mortality
    # Specific high-alert events
    "disease spillover", "pathogen spillover",
    "human-to-human transmission",
    "sustained transmission",
]

_SIGNAL_PATTERN = re.compile(
    "|".join(re.escape(t) for t in _SIGNAL_TERMS),
    re.IGNORECASE,
)


def is_outbreak_relevant(doc: CollectedDocument) -> bool:
    """
    Return True only if the document clears both gates:
      1. Title contains no exclusion keywords
      2. Title + abstract contains at least one active outbreak signal
    """
    title = doc.title or ""
    abstract = doc.abstract or ""

    if _EXCLUSION_PATTERN.search(title):
        return False

    return bool(_SIGNAL_PATTERN.search(title + " " + abstract))


def filter_outbreak_relevant(
    docs: list[CollectedDocument],
) -> list[CollectedDocument]:
    """Return only documents that pass both outbreak-relevance gates."""
    return [doc for doc in docs if is_outbreak_relevant(doc)]


# ── Date filter ───────────────────────────────────────────────────────────────

def _parse_pub_date(date_str: str | None) -> datetime | None:
    """
    Parse an RSS/Atom date string into a timezone-aware datetime.
    Handles RFC 2822 ("Wed, 22 May 2026 12:00:00 +0000") and ISO 8601
    ("2026-05-22T12:00:00Z"). Returns None if the string cannot be parsed.
    """
    if not date_str:
        return None
    # RFC 2822 — used by most RSS 2.0 feeds (CDC, BBC, etc.)
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        pass
    # ISO 8601 — used by Atom feeds and ECDC
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        pass
    # Date-only fallback: "2026-05-22"
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        return dt.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    return None


def is_within_days(doc: CollectedDocument, days: int = 14) -> bool:
    """
    Return True if the document was published within the last `days` days.
    Documents with an unparseable date are kept (assume recent).
    """
    pub_dt = _parse_pub_date(doc.published_date)
    if pub_dt is None:
        return True  # Unknown date — keep rather than silently discard
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return pub_dt >= cutoff


def filter_recent(
    docs: list[CollectedDocument],
    days: int = 14,
) -> list[CollectedDocument]:
    """Return only documents published within the last `days` days."""
    return [doc for doc in docs if is_within_days(doc, days=days)]
