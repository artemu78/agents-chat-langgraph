from __future__ import annotations

from langchain_core.tools import tool
from langchain_community.tools import DuckDuckGoSearchRun


class _DuckDuckGoToolAdapter:
    def __init__(self, wrapped):
        self._wrapped = wrapped

    def run(self, query: str):
        return self._wrapped.run(query)

    def invoke(self, query: str):
        return self._wrapped.run(query)


_ddg = _DuckDuckGoToolAdapter(DuckDuckGoSearchRun())


def web_search(query: str) -> str:
    """Search the public web for current or externally verifiable information."""
    cleaned = (query or "").strip()
    if not cleaned:
        return "Search query is empty. Ask the user for a specific search term."

    try:
        raw_results = _ddg.invoke(cleaned)
    except Exception:
        return "Web search is currently unavailable."

    if not raw_results:
        return "No web search results were returned."

    if isinstance(raw_results, str):
        return raw_results

    formatted: list[str] = []
    for index, item in enumerate(raw_results[:5], start=1):
        if isinstance(item, str):
            formatted.append(f"{index}. {item}")
            continue
        title = item.get("title", "Untitled") if isinstance(item, dict) else str(item)
        snippet = item.get("snippet", "") if isinstance(item, dict) else ""
        link = item.get("link", "") if isinstance(item, dict) else ""
        formatted.append(f"{index}. {title} — {snippet} ({link})")
    return "\n".join(formatted)


web_search_tool = tool(web_search)
