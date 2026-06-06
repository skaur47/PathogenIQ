"""
Tests for data collectors.

STRATEGY:
  Collectors make HTTP calls to external APIs. In tests we NEVER hit real
  network endpoints — that would make tests:
    - Slow (network latency)
    - Flaky (external service availability)
    - Rate-limited (NCBI blocks excessive API calls from CI IPs)

  Instead we test the parsing logic (XML, RSS) with real-world sample data.
  The parsing code is the hard part; the HTTP call is just `client.get()`.

WHAT WE TEST:
  1. PubMedCollector._parse_xml() — parses a sample PubMed XML response
  2. PubMedCollector._parse_article() — handles missing/edge case fields
  3. CDCCollector._entry_to_document() — converts RSS entry to CollectedDocument
  4. WHOCollector._entry_to_document() — same for WHO
  5. BaseCollector contract — collect() never raises

WHY NOT MOCK httpx.AsyncClient?
  Mocking at the httpx level (patching AsyncClient.get) tests that we call
  the right URL with the right params — useful but brittle. We focus on parsing
  instead, which is where bugs actually hide. End-to-end HTTP tests belong in
  integration tests (tests/integration/).
"""

import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.collectors.cdc import CDCCollector
from app.collectors.pubmed import PubMedCollector
from app.collectors.who import WHOCollector
from app.db.models.document import DocumentSource

# ── PubMed XML sample ─────────────────────────────────────────────────────────
# Minimal but realistic PubMed XML for a single article.
SAMPLE_PUBMED_XML = """<?xml version="1.0" ?>
<!DOCTYPE PubmedArticleSet PUBLIC "-//NLM//DTD PubMedArticle, 1st January 2019//EN"
  "https://dtd.nlm.nih.gov/ncbi/pubmed/out/pubmed_190101.dtd">
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation Status="MEDLINE" Owner="NLM">
      <PMID Version="1">99887766</PMID>
      <Article PubModel="Electronic">
        <Journal>
          <Title>Emerging Infectious Diseases</Title>
          <JournalIssue>
            <PubDate>
              <Year>2025</Year>
              <Month>Mar</Month>
              <Day>15</Day>
            </PubDate>
          </JournalIssue>
        </Journal>
        <ArticleTitle>Novel H5N2 Avian Influenza Outbreak in Poultry Flocks</ArticleTitle>
        <Abstract>
          <AbstractText Label="BACKGROUND">H5N2 caused significant poultry losses.</AbstractText>
          <AbstractText Label="METHODS">Surveillance data from 2024–2025 were analysed.</AbstractText>
          <AbstractText Label="CONCLUSIONS">Enhanced monitoring is recommended.</AbstractText>
        </Abstract>
        <AuthorList CompleteYN="Y">
          <Author ValidYN="Y">
            <LastName>Smith</LastName>
            <ForeName>Alice R</ForeName>
          </Author>
          <Author ValidYN="Y">
            <LastName>Jones</LastName>
            <ForeName>Bob</ForeName>
          </Author>
        </AuthorList>
        <ELocationID EIdType="doi" ValidYN="Y">10.3201/example.2025.test</ELocationID>
      </Article>
      <MeshHeadingList>
        <MeshHeading>
          <DescriptorName MajorTopicYN="Y">Influenza in Birds</DescriptorName>
        </MeshHeading>
        <MeshHeading>
          <DescriptorName MajorTopicYN="N">Disease Outbreaks</DescriptorName>
        </MeshHeading>
      </MeshHeadingList>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="pubmed">99887766</ArticleId>
        <ArticleId IdType="doi">10.3201/example.2025.test</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>
"""

# Minimal article with no abstract, no authors, no DOI — tests graceful fallback.
SAMPLE_MINIMAL_XML = """<?xml version="1.0" ?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation Status="MEDLINE">
      <PMID Version="1">11223344</PMID>
      <Article PubModel="Print">
        <ArticleTitle>Brief Communication on Cholera</ArticleTitle>
      </Article>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="pubmed">11223344</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>
"""


class TestPubMedCollector:
    """Tests for PubMedCollector XML parsing (no HTTP calls)."""

    def setup_method(self):
        self.collector = PubMedCollector()

    def test_parse_xml_returns_documents(self):
        """_parse_xml() returns one CollectedDocument per article in the XML."""
        docs = self.collector._parse_xml(SAMPLE_PUBMED_XML)
        assert len(docs) == 1

    def test_parse_xml_extracts_pmid(self):
        docs = self.collector._parse_xml(SAMPLE_PUBMED_XML)
        assert docs[0].external_id == "99887766"

    def test_parse_xml_extracts_title(self):
        docs = self.collector._parse_xml(SAMPLE_PUBMED_XML)
        assert "H5N2" in docs[0].title

    def test_parse_xml_joins_structured_abstract(self):
        """Structured abstracts (multiple AbstractText with Labels) are joined."""
        docs = self.collector._parse_xml(SAMPLE_PUBMED_XML)
        abstract = docs[0].abstract
        assert "BACKGROUND:" in abstract
        assert "METHODS:" in abstract
        assert "CONCLUSIONS:" in abstract

    def test_parse_xml_extracts_authors(self):
        docs = self.collector._parse_xml(SAMPLE_PUBMED_XML)
        assert "Smith Alice R" in docs[0].authors
        assert "Jones Bob" in docs[0].authors

    def test_parse_xml_extracts_doi(self):
        docs = self.collector._parse_xml(SAMPLE_PUBMED_XML)
        assert docs[0].doi == "10.3201/example.2025.test"

    def test_parse_xml_extracts_pub_date(self):
        docs = self.collector._parse_xml(SAMPLE_PUBMED_XML)
        assert docs[0].published_date == "2025-Mar-15"

    def test_parse_xml_extracts_mesh_terms(self):
        docs = self.collector._parse_xml(SAMPLE_PUBMED_XML)
        assert "Influenza in Birds" in docs[0].metadata["mesh_terms"]
        assert "Disease Outbreaks" in docs[0].metadata["mesh_terms"]

    def test_parse_xml_builds_pubmed_url(self):
        docs = self.collector._parse_xml(SAMPLE_PUBMED_XML)
        assert docs[0].url == "https://pubmed.ncbi.nlm.nih.gov/99887766/"

    def test_parse_xml_correct_source(self):
        docs = self.collector._parse_xml(SAMPLE_PUBMED_XML)
        assert docs[0].source == DocumentSource.PUBMED

    def test_parse_xml_handles_minimal_article(self):
        """An article with only PMID and title should not raise."""
        docs = self.collector._parse_xml(SAMPLE_MINIMAL_XML)
        assert len(docs) == 1
        assert docs[0].external_id == "11223344"
        assert docs[0].abstract is None
        assert docs[0].authors == []
        assert docs[0].doi is None

    def test_parse_xml_handles_malformed_xml(self):
        """Malformed XML returns empty list instead of raising."""
        docs = self.collector._parse_xml("<not valid xml >>>")
        assert docs == []

    def test_parse_xml_handles_empty_string(self):
        docs = self.collector._parse_xml("")
        assert docs == []

    @pytest.mark.asyncio
    async def test_collect_returns_empty_list_on_http_error(self):
        """collect() must not raise — return [] on any failure."""
        with patch("app.collectors.pubmed.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.side_effect = Exception("network error")

            collector = PubMedCollector()
            result = await collector.collect()

        assert result == []


# ── CDC collector tests ───────────────────────────────────────────────────────

class TestCDCCollector:
    """Tests for CDCCollector RSS entry parsing (no HTTP calls)."""

    def setup_method(self):
        self.collector = CDCCollector()

    def _make_entry(self, **kwargs):
        """Build a feedparser-style entry (SimpleNamespace) from kwargs."""
        defaults = {
            "link": "https://emergency.cdc.gov/han/2025/han0123.asp",
            "id": "https://emergency.cdc.gov/han/2025/han0123.asp",
            "title": "Health Alert: Novel Pathogen Detected in Southwest",
            "summary": "Clinicians should be aware of a novel pathogen...",
            "published": "Mon, 15 Jan 2025 14:00:00 +0000",
            "tags": [],
        }
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_entry_to_document_basic(self):
        entry = self._make_entry()
        doc = self.collector._entry_to_document(entry)
        assert doc is not None
        assert doc.source == DocumentSource.CDC
        assert doc.external_id == "https://emergency.cdc.gov/han/2025/han0123.asp"
        assert doc.title == "Health Alert: Novel Pathogen Detected in Southwest"

    def test_entry_uses_link_as_external_id(self):
        entry = self._make_entry(link="https://cdc.gov/han/unique-url")
        doc = self.collector._entry_to_document(entry)
        assert doc.external_id == "https://cdc.gov/han/unique-url"

    def test_entry_falls_back_to_id_when_no_link(self):
        entry = self._make_entry(link=None)
        doc = self.collector._entry_to_document(entry)
        assert doc.external_id == "https://emergency.cdc.gov/han/2025/han0123.asp"

    def test_entry_hashes_title_when_no_link_or_id(self):
        entry = SimpleNamespace(title="Alert: mysterious disease", summary="text")
        doc = self.collector._entry_to_document(entry)
        assert doc is not None
        assert len(doc.external_id) == 40  # SHA-256 hex prefix

    def test_entry_returns_none_when_no_identifiers(self):
        entry = SimpleNamespace()  # no link, id, or title
        doc = self.collector._entry_to_document(entry)
        assert doc is None

    def test_entry_pub_date_from_published(self):
        entry = self._make_entry(published="Mon, 15 Jan 2025 14:00:00 +0000")
        doc = self.collector._entry_to_document(entry)
        assert doc.published_date == "Mon, 15 Jan 2025 14:00:00 +0000"

    def test_entry_pub_date_falls_back_to_updated(self):
        entry = self._make_entry()
        del entry.published  # remove published attribute
        entry.updated = "Tue, 16 Jan 2025 10:00:00 +0000"
        doc = self.collector._entry_to_document(entry)
        assert doc.published_date == "Tue, 16 Jan 2025 10:00:00 +0000"

    @pytest.mark.asyncio
    async def test_collect_returns_empty_on_http_error(self):
        with patch("app.collectors.cdc.httpx.AsyncClient") as mock_class:
            mock_client = AsyncMock()
            mock_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.side_effect = Exception("connection refused")

            result = await self.collector.collect()

        assert result == []


# ── WHO collector tests ───────────────────────────────────────────────────────

class TestWHOCollector:
    """Tests for WHOCollector RSS entry parsing."""

    def setup_method(self):
        self.collector = WHOCollector()

    def _make_entry(self, **kwargs):
        defaults = {
            "link": "https://www.who.int/emergencies/disease-outbreak-news/item/2025-DON123",
            "id": "https://www.who.int/emergencies/disease-outbreak-news/item/2025-DON123",
            "title": "Mpox – Democratic Republic of the Congo",
            "summary": "From 1 to 14 January 2025, 1,234 cases were reported...",
            "published": "Wed, 22 Jan 2025 12:00:00 +0000",
        }
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_entry_to_document_basic(self):
        entry = self._make_entry()
        doc = self.collector._entry_to_document(entry)
        assert doc is not None
        assert doc.source == DocumentSource.WHO
        assert "who.int" in doc.external_id
        assert "Mpox" in doc.title

    def test_entry_returns_none_when_no_link(self):
        entry = SimpleNamespace(title="Some alert")  # no link, no id
        doc = self.collector._entry_to_document(entry)
        assert doc is None

    def test_entry_url_only_set_for_http_links(self):
        entry = self._make_entry(link="not-a-url")
        doc = self.collector._entry_to_document(entry)
        assert doc.url is None  # non-HTTP links not stored as URL

    @pytest.mark.asyncio
    async def test_collect_returns_empty_on_http_error(self):
        with patch("app.collectors.who.httpx.AsyncClient") as mock_class:
            mock_client = AsyncMock()
            mock_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.side_effect = Exception("timeout")

            result = await self.collector.collect()

        assert result == []
