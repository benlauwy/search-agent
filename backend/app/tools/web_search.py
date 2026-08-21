import httpx

from ..settings_store import get_setting
from .base import ToolContext, ToolResult

EXA_URL = "https://api.exa.ai/search"


class WebSearchTool:
    name = "web_search"
    description = (
        "Search the web. Returns result titles, URLs, and text snippets. "
        "Use focused, simple queries."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query"},
            "num_results": {
                "type": "integer",
                "description": "Number of results (default 5, max 10)",
            },
        },
        "required": ["query"],
    }

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        api_key = await get_setting(ctx.db, "exa_api_key")
        if not api_key:
            return ToolResult("Exa API key not configured. Set it in Settings.", is_error=True)
        num = min(int(args.get("num_results") or 5), 10)
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                EXA_URL,
                headers={"x-api-key": api_key},
                json={
                    "query": args["query"],
                    "numResults": num,
                    "contents": {"text": {"maxCharacters": 1500}},
                },
            )
        if resp.status_code != 200:
            return ToolResult(
                f"Exa search failed ({resp.status_code}): {resp.text[:500]}", is_error=True
            )
        results = resp.json().get("results", [])
        if not results:
            return ToolResult("No results found.")
        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"[{i}] {r.get('title') or '(untitled)'}\n{r.get('url')}")
            if r.get("publishedDate"):
                lines.append(f"Published: {r['publishedDate']}")
            if r.get("text"):
                lines.append(r["text"].strip())
            lines.append("")
        return ToolResult("\n".join(lines).strip())
