"""
PubMedCollector — fetches scientific literature from NCBI via E-utilities.

PHASE 2 STATUS: NOT ACTIVE
  PubMed collection is deferred to Phase 3. Reasons:
    1. PubMed abstracts are most valuable when paired with vector embeddings
       and semantic search (Qdrant), both of which are Phase 3 concerns.
    2. The Scholar (LiteratureAgent) will drive PubMed queries dynamically
       based on signals from the Sentinel agent, rather than a static cron.
    3. RSS-based sources (CDC, WHO, ECDC, CIDRAP, news) cover the same
       real-time outbreak signals without requiring NCBI API access.
  This file is preserved as the Phase 3 starting point. Do not register
  it in workers/settings.py until the Scholar agent is ready.



HOW NCBI E-UTILITIES WORK (two-step process):
  Step 1 — ESearch: text search → returns a list of PubMed IDs (PMIDs).
    URL: https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi
    We query for outbreak-relevant terms and filter to recent publications.

  Step 2 — EFetch: PMIDs → full records in XML format.
    URL: https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi
    We parse the XML to extract title, abstract, authors, DOI, MeSH terms.

RATE LIMITS (NCBI policy):
  Without API key: 3 requests/second max.
  With API key:   10 requests/second max.
  We pass api_key when available and sleep between batch fetches.
  ALWAYS include tool= and email= — NCBI uses these to contact you if
  your code misbehaves and to grant extra quota to named tools.

WHY NOT biopython's Entrez module?
  Biopython is a 500 MB dependency for genome analysis tools we don't need.
  httpx + ElementTree gives us the same functionality with zero extra deps.

FALLIBILITY DESIGN:
  Each parsing step is wrapped in try/except. A malformed record from NCBI
  (it does happen) skips that article rather than crashing the whole batch.
"""

import asyncio
import xml.etree.ElementTree as ET

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import get_settings
from app.db.models.document import DocumentSource

from .base import BaseCollector
from .schemas import CollectedDocument

logger = structlog.get_logger(__name__)

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

# Default query: outbreak-relevant terms filtered to last 2 years.
# [tiab]  = search Title and Abstract fields
# [dp]    = Date Published filter
# [mh]    = MeSH (Medical Subject Headings) — controlled vocabulary terms
DEFAULT_QUERY = (
    "(outbreak[tiab] OR epidemic[tiab] OR pandemic[tiab] "
    'OR "emerging infectious disease"[tiab] OR "novel pathogen"[tiab] '
    'OR "antimicrobial resistance"[tiab]) '
    'AND ("2024"[dp] OR "2025"[dp] OR "2026"[dp])'
)

# How many PMIDs to fetch in one EFetch call.
# NCBI allows up to 500, but large batches → large XML responses → more parse time.
BATCH_SIZE = 50


class PubMedCollector(BaseCollector):
    """
    Collects recent infectious disease papers from PubMed.

    Usage:
        collector = PubMedCollector()
        docs = await collector.collect(max_results=100)
        # returns list[CollectedDocument], empty list on any failure
    """

    @property
    def source_name(self) -> str:
        return "pubmed"

    async def collect(
        self,
        query: str | None = None,
        max_results: int = 100,
    ) -> list[CollectedDocument]:
        search_query = query or DEFAULT_QUERY
        log = logger.bind(source="pubmed", query=search_query[:60])
        log.info("collector_start", max_results=max_results)

        try:
            pmids = await self._search(search_query, max_results)
        except Exception as e:
            log.error("collector_search_failed", error=str(e))
            return []

        if not pmids:
            log.info("collector_no_results")
            return []

        documents = await self._fetch_records(pmids)
        log.info("collector_done", fetched=len(documents))
        return documents

    # ── Private helpers ───────────────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def _search(self, query: str, max_results: int) -> list[str]:
        """
        ESearch: convert a text query into a list of PMIDs.

        retmax capped at 200: collecting thousands of papers per run would
        create a huge processing backlog before Phase 3 agents can handle it.
        Increase this once the pipeline is proven end-to-end.

        usehistory=n: we don't use the NCBI History Server since we fetch
        immediately in the next step rather than storing on NCBI's side.
        """
        settings = get_settings()
        params: dict[str, str] = {
            "db": "pubmed",
            "term": query,
            "retmode": "json",
            "retmax": str(min(max_results, 200)),
            "sort": "relevance",
            "tool": "PathogenIQ",
            "email": "admin@pathogeniq.io",
        }
        if settings.pubmed_api_key:
            params["api_key"] = settings.pubmed_api_key

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(ESEARCH_URL, params=params)
            response.raise_for_status()

        data = response.json()
        pmids: list[str] = data.get("esearchresult", {}).get("idlist", [])
        logger.debug("pubmed_search_complete", count=len(pmids))
        return pmids

    async def _fetch_records(self, pmids: list[str]) -> list[CollectedDocument]:
        """
        Batch-fetch full XML records for all PMIDs.

        We sleep between batches to stay within NCBI rate limits.
        Without an API key: 3 req/s → sleep ~0.4s between requests.
        With an API key:   10 req/s → sleep ~0.15s between requests.
        """
        settings = get_settings()
        delay = 0.15 if settings.pubmed_api_key else 0.4
        documents: list[CollectedDocument] = []

        for i in range(0, len(pmids), BATCH_SIZE):
            batch = pmids[i : i + BATCH_SIZE]
            try:
                batch_docs = await self._fetch_batch(batch)
                documents.extend(batch_docs)
            except Exception as e:
                logger.warning(
                    "pubmed_batch_failed",
                    batch_start=i,
                    batch_size=len(batch),
                    error=str(e),
                )

            # Respect rate limits between batches (not after the last one)
            if i + BATCH_SIZE < len(pmids):
                await asyncio.sleep(delay)

        return documents

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def _fetch_batch(self, pmids: list[str]) -> list[CollectedDocument]:
        """EFetch: download full XML records for a batch of PMIDs."""
        settings = get_settings()
        params: dict[str, str] = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
            "rettype": "abstract",
            "tool": "PathogenIQ",
            "email": "admin@pathogeniq.io",
        }
        if settings.pubmed_api_key:
            params["api_key"] = settings.pubmed_api_key

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(EFETCH_URL, params=params)
            response.raise_for_status()

        return self._parse_xml(response.text)

    # ── XML parsing ───────────────────────────────────────────────────────────

    def _parse_xml(self, xml_text: str) -> list[CollectedDocument]:
        """
        Parse a PubmedArticleSet XML string into CollectedDocuments.

        We use stdlib ElementTree (no extra dependency) because NCBI always
        returns well-formed XML. If a single article element is malformed,
        we skip it and continue — we never crash the entire batch.
        """
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            logger.error("pubmed_xml_parse_error", error=str(e))
            return []

        documents: list[CollectedDocument] = []
        for article_elem in root.findall(".//PubmedArticle"):
            try:
                doc = self._parse_article(article_elem)
                if doc:
                    documents.append(doc)
            except Exception as e:
                pmid = article_elem.findtext(".//PMID") or "unknown"
                logger.warning("pubmed_article_parse_error", pmid=pmid, error=str(e))

        return documents

    def _parse_article(self, elem: ET.Element) -> CollectedDocument | None:
        """
        Extract structured fields from a single <PubmedArticle> XML element.

        PubMed XML structure (simplified):
          <PubmedArticle>
            <MedlineCitation>
              <PMID>12345678</PMID>
              <Article>
                <ArticleTitle>...</ArticleTitle>
                <Abstract>
                  <AbstractText Label="BACKGROUND">...</AbstractText>
                  <AbstractText Label="METHODS">...</AbstractText>  ← structured abstract
                </Abstract>
                <AuthorList>
                  <Author><LastName>Smith</LastName><ForeName>John</ForeName></Author>
                </AuthorList>
                <ELocationID EIdType="doi">10.1234/example</ELocationID>
              </Article>
            </MedlineCitation>
            <PubmedData>
              <ArticleIdList>
                <ArticleId IdType="doi">10.1234/example</ArticleId>
              </ArticleIdList>
            </PubmedData>
          </PubmedArticle>
        """
        pmid = elem.findtext(".//PMID")
        if not pmid:
            return None

        title = elem.findtext(".//ArticleTitle") or None

        # Structured abstracts have multiple AbstractText elements with Labels.
        # We join them as "LABEL: text" to preserve the structure.
        abstract_parts = []
        for at in elem.findall(".//AbstractText"):
            label = at.get("Label")
            text = at.text or ""
            if text:
                abstract_parts.append(f"{label}: {text}" if label else text)
        abstract = " ".join(abstract_parts) or None

        # Authors — prefer "LastName ForeName", fall back to CollectiveName.
        authors: list[str] = []
        for author in elem.findall(".//Author"):
            collective = author.findtext("CollectiveName")
            if collective:
                authors.append(collective)
            else:
                last = author.findtext("LastName") or ""
                first = author.findtext("ForeName") or ""
                name = f"{last} {first}".strip()
                if name:
                    authors.append(name)

        # DOI — check ELocationID first, then ArticleIdList.
        doi: str | None = None
        for loc in elem.findall(".//ELocationID"):
            if loc.get("EIdType") == "doi" and loc.text:
                doi = loc.text.strip()
                break
        if not doi:
            for art_id in elem.findall(".//ArticleId"):
                if art_id.get("IdType") == "doi" and art_id.text:
                    doi = art_id.text.strip()
                    break

        # Publication date — build a partial date string from whatever fields exist.
        pub_date: str | None = None
        pub_date_elem = elem.find(".//PubDate")
        if pub_date_elem is not None:
            year = pub_date_elem.findtext("Year") or ""
            month = pub_date_elem.findtext("Month") or ""
            day = pub_date_elem.findtext("Day") or ""
            parts = [p for p in [year, month, day] if p]
            pub_date = "-".join(parts) if parts else None

        # MeSH terms — Medical Subject Headings, the controlled vocabulary NCBI
        # uses to tag articles. Invaluable for Phase 3 entity extraction.
        mesh_terms: list[str] = [
            descriptor
            for mh in elem.findall(".//MeshHeading")
            if (descriptor := mh.findtext("DescriptorName"))
        ]

        url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"

        return CollectedDocument(
            source=DocumentSource.PUBMED,
            external_id=pmid,
            title=title,
            abstract=abstract,
            raw_content=abstract,
            url=url,
            doi=doi,
            authors=authors,
            published_date=pub_date,
            metadata={"pmid": pmid, "mesh_terms": mesh_terms},
        )
