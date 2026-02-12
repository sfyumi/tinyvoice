#!/usr/bin/env python3
"""Step-by-step Bing search debugger for tinyvoice.

Usage examples:
  python debug_bing_search.py "现在的美国总统是谁"
  python debug_bing_search.py "2026 美国总统" --lang zh-CN --count 8 --fetch-top 3
  python debug_bing_search.py "current president of the united states" --compare-tool
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from typing import Any

import requests
from bs4 import BeautifulSoup


SEARCH_UA = "curl/7.88.1"
FETCH_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
STRIP_TAGS = {"script", "style", "nav", "header", "footer", "iframe", "noscript", "svg", "form"}


@dataclass
class SearchItem:
    title: str
    snippet: str
    url: str


def decode_bing_url(href: str) -> str:
    """Decode Bing redirect URL to its target URL."""
    import base64
    from urllib.parse import parse_qs, urlparse

    if "/ck/a?" not in href:
        return href
    try:
        parsed = urlparse(href)
        params = parse_qs(parsed.query)
        u_val = params.get("u", [""])[0]
        if u_val.startswith("a1"):
            padded = u_val[2:] + "=="
            return base64.b64decode(padded).decode("utf-8", errors="ignore")
    except Exception:
        pass
    return href


def parse_results(html: str, max_items: int) -> list[SearchItem]:
    soup = BeautifulSoup(html, "html.parser")
    blocks = soup.find_all("li", class_="b_algo")
    items: list[SearchItem] = []
    for block in blocks[:max_items]:
        h2 = block.find("h2")
        a_tag = h2.find("a") if h2 else None
        title = a_tag.get_text(strip=True) if a_tag else (h2.get_text(strip=True) if h2 else "")
        href = decode_bing_url(a_tag.get("href", "")) if a_tag else ""
        caption = block.find("div", class_="b_caption")
        p_tag = caption.find("p") if caption else block.find("p")
        snippet = p_tag.get_text(" ", strip=True) if p_tag else ""
        items.append(SearchItem(title=title, snippet=snippet, url=href))
    return items


def fetch_page_text(url: str, timeout: int = 8, max_chars: int = 3000) -> tuple[str, str]:
    try:
        with requests.Session() as session:
            resp = session.get(
                url,
                headers={"User-Agent": FETCH_UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
                timeout=timeout,
                allow_redirects=True,
            )
            resp.raise_for_status()
            if "text/html" not in resp.headers.get("content-type", "").lower():
                return str(resp.url), ""
            if resp.encoding and resp.encoding.lower() == "iso-8859-1":
                resp.encoding = resp.apparent_encoding

            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(STRIP_TAGS):
                tag.decompose()
            main = (
                soup.find("main")
                or soup.find("article")
                or soup.find("div", id="content")
                or soup.find("div", class_="content")
                or soup.body
                or soup
            )
            text = main.get_text(separator="\n", strip=True)
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            collapsed = "\n".join(lines)
            return str(resp.url), collapsed[:max_chars]
    except Exception:
        return "", ""


def direct_bing_search(query: str, count: int, lang: str) -> tuple[str, list[SearchItem]]:
    with requests.Session() as session:
        resp = session.get(
            "https://www.bing.com/search",
            headers={
                "User-Agent": SEARCH_UA,
                "Accept-Language": f"{lang},zh;q=0.9,en;q=0.8",
            },
            params={"q": query, "count": count},
            timeout=10,
        )
        resp.raise_for_status()
        items = parse_results(resp.text, count)
        return resp.url, items


async def run_tool_web_search(query: str, max_results: int) -> str:
    # Import locally to keep this script standalone unless needed.
    from app.tools import _make_web_search

    tool = _make_web_search()
    result = await tool.execute({"query": query, "max_results": max_results})
    return f"is_error={result.is_error}\nchars={len(result.content)}\n\n{result.content[:4000]}"


def print_results(items: list[SearchItem]) -> None:
    if not items:
        print("No parsed search results (li.b_algo).")
        return
    for i, item in enumerate(items, 1):
        print(f"{i}. {item.title}")
        print(f"   URL: {item.url}")
        print(f"   Snippet: {item.snippet}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Debug Bing results used by tinyvoice web_search.")
    parser.add_argument("query", help="Search query text")
    parser.add_argument("--count", type=int, default=5, help="How many Bing results to parse")
    parser.add_argument("--lang", default="zh-CN", help="Accept-Language primary tag (default: zh-CN)")
    parser.add_argument("--fetch-top", type=int, default=0, help="Fetch body text for top N URLs")
    parser.add_argument("--max-chars", type=int, default=3000, help="Max chars when fetching page text")
    parser.add_argument(
        "--compare-tool",
        action="store_true",
        help="Also run current app.tools web_search and print its output preview",
    )
    args = parser.parse_args()

    count = max(1, min(args.count, 10))
    fetch_top = max(0, min(args.fetch_top, 5))
    max_chars = max(500, args.max_chars)

    print("=== Step 1: Direct Bing request ===")
    print(f"Query: {args.query}")
    print(f"Count: {count}")
    print(f"Accept-Language: {args.lang}")
    final_url, items = direct_bing_search(args.query, count=count, lang=args.lang)
    print(f"Final request URL: {final_url}\n")

    print("=== Step 2: Parsed results ===")
    print_results(items)

    if fetch_top > 0:
        print("=== Step 3: Fetch top page texts ===")
        urls = [it.url for it in items if it.url][:fetch_top]
        for i, url in enumerate(urls, 1):
            final_page_url, text = fetch_page_text(url, max_chars=max_chars)
            print(f"[{i}] {url}")
            print(f"Final URL: {final_page_url or '(failed)'}")
            print(f"Fetched chars: {len(text)}")
            if text:
                preview = text[:500].replace("\n", " ")
                print(f"Preview: {preview}")
            print()

    if args.compare_tool:
        print("=== Step 4: Compare with app.tools web_search ===")
        output = asyncio.run(run_tool_web_search(args.query, max_results=count))
        print(output)


if __name__ == "__main__":
    main()
