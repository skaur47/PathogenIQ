"""
Shared filter utilities for PathogenIQ agents.

Non-pathogen filter: blocks toxicological events, poisoning syndromes, and
envenomations from flowing through Scholar → Research → Hypothesis. These
terms can appear in surveillance documents alongside real pathogens but do
not represent infectious microorganisms.

Article category classifier: scores keyword hits in title + abstract to
assign the most accurate ArticleCategory rather than inheriting the sub-agent
that happened to collect the article from PubMed.
"""

from app.db.models.research import ArticleCategory

# ── Non-pathogen term filter ──────────────────────────────────────────────────

_NON_PATHOGEN_TERMS: frozenset[str] = frozenset({
    "poisoning",
    "poisonings",
    "envenomation",
    "envenomations",
    "toxicity",
    "intoxication",
    "venom",
    "overdose",
    "toxin",
    "toxic",
})

# Words that appear in geographic / institutional descriptions but never in a
# scientific pathogen name — used as a secondary article-title detector.
_LOCATION_TERMS: frozenset[str] = frozenset({
    "facility", "hospital", "clinic", "center", "centre", "region", "province",
    "county", "canton", "district", "territory", "ontario", "canada", "united",
    "kingdom", "states", "republic", "africa", "europe", "asia", "americas",
    "colonization", "colonisation", "long-term", "nursing", "care",
})

# Maximum number of whitespace-separated tokens a valid pathogen name can have.
# Pathogen names with strains/variants (e.g., "Influenza A H5N1 clade Ib") rarely
# exceed this. Anything longer is almost certainly an article title or description.
_MAX_NAME_WORDS = 6


def is_non_pathogen(name: str) -> bool:
    """
    Return True when name is not a valid infectious pathogen identifier.

    Catches:
      - Toxicological events (poisonings, envenomation, venom …)
      - Geographic / institutional phrases (article titles with facility names)
      - Names that are simply too long to be a scientific name (> 6 tokens)

    Examples:
      "Amanita Species Mushroom Poisonings"                             → True
      "Klebsiella pneumoniae … Long-Term Care Facility — Ontario …"    → True
      "Clostridioides difficile"                                        → False
      "Influenza A H5N1 clade Ib"                                      → False
    """
    words = name.lower().split()
    if len(words) > _MAX_NAME_WORDS:
        return True
    if any(w in _NON_PATHOGEN_TERMS for w in words):
        return True
    if any(w in _LOCATION_TERMS for w in words):
        return True
    return False


# ── Article category keyword classifier ───────────────────────────────────────

_CATEGORY_KEYWORDS: dict[ArticleCategory, frozenset[str]] = {
    ArticleCategory.MOLECULAR_BIOLOGY: frozenset({
        "genome", "genomic", "proteomics", "receptor binding", "spike protein",
        "capsid", "replication", "immune evasion", "virulence", "gene expression",
        "transcriptome", "phylogenetic", "sequence", "mutation", "variant",
        "structural protein", "host cell entry", "rna structure", "plasmid",
        "protein structure", "virulence factor", "pathogenesis mechanism",
    }),
    ArticleCategory.EXPERIMENTS: frozenset({
        "in vitro", "in vivo", "cell line", "cell culture", "cell-based",
        "vero", "hek293", "a549", "organoid", "mouse model", "animal model",
        "neutralization assay", "plaque assay", "elisa", "rna-seq", "western blot",
        "flow cytometry", "syrian hamster", "ferret model", "challenge model",
        "cytopathic effect", "titre", "titer", "inoculation", "infection model",
    }),
    ArticleCategory.THERAPEUTICS: frozenset({
        "vaccine", "vaccination", "antiviral", "monoclonal antibody",
        "antibody therapy", "clinical trial", "phase i", "phase ii", "phase iii",
        "mrna vaccine", "treatment", "therapeutic", "prophylaxis", "drug candidate",
        "efficacy", "neutralizing antibody", "immunization", "approved",
        "fda approval", "ema approval", "repurposed", "inhibitor", "antifungal",
        "antibiotic", "antimicrobial",
    }),
    ArticleCategory.CLINICAL_EPIDEMIOLOGY: frozenset({
        "epidemiology", "outbreak", "surveillance", "incidence", "prevalence",
        "case fatality", "transmission dynamics", "r0", "reproduction number",
        "risk factor", "mortality", "public health", "infection control",
        "contact tracing", "quarantine", "phylogeograph", "spread", "cluster",
        "seroprevalence", "cohort", "hospitalization", "icu", "death rate",
    }),
}


def classify_article_category(
    title: str,
    abstract: str,
    fallback: ArticleCategory,
) -> ArticleCategory:
    """
    Assign an ArticleCategory based on keyword hits in title + abstract.

    Scores each category independently; returns the one with the most matches.
    When all scores are zero or tied, returns the fallback (the sub-agent that
    collected the article).

    Using both title and the first 400 chars of the abstract covers the
    primary subject matter without overweighting method sections that
    routinely mention e.g. "cell culture" in therapeutics papers.
    """
    text = (title + " " + abstract[:400]).lower()
    best_cat = fallback
    best_score = 0
    for cat, keywords in _CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text)
        if score > best_score:
            best_score = score
            best_cat = cat
    return best_cat
