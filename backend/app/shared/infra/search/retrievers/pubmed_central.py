"""PubMed Central / PubMed full-text retriever."""

from __future__ import annotations

from xml.etree import ElementTree

import httpx
import structlog

from app.shared.infra.env_support import get_env
from app.shared.infra.search.defaults import DEFAULT_SEARCH_PROVIDER_TIMEOUT_S
from app.shared.infra.search.retrievers.base import BaseRetriever
from app.shared.infra.search.retrievers.common import clamp_max_results, clean_text, make_search_result, normalize_query
from app.shared.infra.search.types import SearchResult

logger = structlog.get_logger(__name__)

_ESEARCH_ENDPOINT = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_EFETCH_ENDPOINT = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


class PubMedCentralRetriever(BaseRetriever):
    canonical_name = "pubmed_central"
    aliases = ("pubmed", "pmc")

    @classmethod
    def availability_reason(cls) -> str | None:
        return None

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        normalized_query = normalize_query(query)
        if not normalized_query:
            return []
        count = clamp_max_results(max_results, upper=20)
        db_type = (get_env("PUBMED_DB", "pmc") or "pmc").strip().lower()
        if db_type not in {"pmc", "pubmed"}:
            db_type = "pmc"
        search_term = f"{normalized_query} AND (ffrft[filter] OR pmc[filter])" if db_type == "pubmed" else normalized_query
        params = {
            "db": db_type,
            "term": search_term,
            "retmax": count,
            "retmode": "json",
            "sort": get_env("PUBMED_SORT", "relevance") or "relevance",
        }
        api_key = (get_env("NCBI_API_KEY") or "").strip()
        if api_key:
            params["api_key"] = api_key

        try:
            async with httpx.AsyncClient(timeout=max(DEFAULT_SEARCH_PROVIDER_TIMEOUT_S, 20.0), follow_redirects=True) as client:
                search_response = await client.get(_ESEARCH_ENDPOINT, params=params)
                search_response.raise_for_status()
                article_ids = (((search_response.json() or {}).get("esearchresult") or {}).get("idlist") or [])[:count]
                if not article_ids:
                    return []
                return await self._fetch_articles(client, article_ids=article_ids, db_type=db_type, api_key=api_key, count=count)
        except Exception as exc:  # pragma: no cover - provider behavior
            logger.warning("pubmed_central_search_failed", error=str(exc), query=normalized_query)
            return []

    async def _fetch_articles(
        self,
        client: httpx.AsyncClient,
        *,
        article_ids: list[str],
        db_type: str,
        api_key: str,
        count: int,
    ) -> list[SearchResult]:
        results: list[SearchResult] = []
        for article_id in article_ids:
            params = {
                "db": "pmc",
                "id": article_id,
                "rettype": "full",
                "retmode": "xml",
            }
            if api_key:
                params["api_key"] = api_key
            try:
                response = await client.get(_EFETCH_ENDPOINT, params=params)
                response.raise_for_status()
                result = self._parse_article_xml(response.text, article_id=article_id, db_type=db_type)
            except Exception as exc:  # pragma: no cover - provider behavior
                logger.warning("pubmed_article_fetch_failed", article_id=article_id, error=str(exc))
                continue
            if result is not None:
                results.append(result)
            if len(results) >= count:
                break
        return results

    def _parse_article_xml(self, text: str, *, article_id: str, db_type: str) -> SearchResult | None:
        try:
            root = ElementTree.fromstring(text)
        except ElementTree.ParseError:
            return None
        title = clean_text(" ".join(root.find(".//article-title").itertext())) if root.find(".//article-title") is not None else ""
        abstract = root.find(".//abstract")
        body = root.find(".//body")
        abstract_text = clean_text(" ".join(abstract.itertext()), limit=1200) if abstract is not None else ""
        body_text = clean_text(" ".join(body.itertext()), limit=1200) if body is not None else ""
        snippet = abstract_text or body_text
        url_id = article_id if db_type == "pmc" or str(article_id).startswith("PMC") else f"PMC{article_id}"
        return make_search_result(
            url=f"https://www.ncbi.nlm.nih.gov/pmc/articles/{url_id}/",
            title=title or f"PubMed Central article {article_id}",
            snippet=snippet,
            source=self.name,
            snippet_limit=1600,
        )


__all__ = ["PubMedCentralRetriever"]
