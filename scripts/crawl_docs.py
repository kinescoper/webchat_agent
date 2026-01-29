#!/usr/bin/env python3
"""
Краул базы знаний https://docs.kinescope.ru/ с сохранением в .md с иерархией.
Сохраняет страницы в docs_crawl/<path>/index.md по URL.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md

BASE_URL = "https://docs.kinescope.ru"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "docs_crawl"
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; KinescopeDocsCrawl/1.0)",
    "Accept": "text/html,application/xhtml+xml",
}
CHUNK_SIZE = 8192


def normalize_path(url_path: str) -> str:
    """Нормализует путь URL в путь файловой системы."""
    path = url_path.strip("/") or "index"
    path = re.sub(r"[^\w\-/.]", "_", path)
    return path.replace("//", "/")


def get_links_from_page(soup: BeautifulSoup, base: str) -> set[str]:
    """Собирает все внутренние ссылки на docs.kinescope.ru."""
    links: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("javascript:"):
            continue
        full = urljoin(base, href)
        parsed = urlparse(full)
        if parsed.netloc != urlparse(BASE_URL).netloc:
            continue
        path = parsed.path.rstrip("/") or "/"
        if path.startswith("/"):
            links.add(BASE_URL + path)
    return links


def html_to_markdown(soup: BeautifulSoup) -> str:
    """Конвертирует основной контент страницы в Markdown."""
    main = soup.find("main") or soup.find("article") or soup.find("div", class_=re.compile("content|main|md-content"))
    if main is None:
        main = soup.find("body")
    if main is None:
        return ""
    for tag in main.find_all(["script", "style", "nav", "header"]):
        tag.decompose()
    return md(str(main), heading_style="ATX", strip=["a"])


def fetch_page(url: str) -> str | None:
    """Загружает HTML страницы."""
    try:
        r = requests.get(url, headers=REQUEST_HEADERS, timeout=30)
        r.raise_for_status()
        return r.text
    except requests.RequestException as e:
        print(f"  skip {url}: {e}", file=sys.stderr)
        return None


def crawl() -> list[tuple[str, str, str]]:
    """Краулит сайт, возвращает список (url, path_key, markdown)."""
    seen: set[str] = set()
    to_visit = {BASE_URL + "/"}
    results: list[tuple[str, str, str]] = []

    while to_visit:
        url = to_visit.pop()
        if url in seen:
            continue
        seen.add(url)
        parsed = urlparse(url)
        path_key = parsed.path.rstrip("/") or "index"

        html = fetch_page(url)
        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")
        new_links = get_links_from_page(soup, url)
        to_visit.update(new_links - seen)

        content_md = html_to_markdown(soup)
        if content_md.strip():
            results.append((url, path_key, content_md))
        print(f"  {path_key}", flush=True)

    return results


def save_md_with_hierarchy(results: list[tuple[str, str, str]]) -> None:
    """Сохраняет результаты в docs_crawl с иерархией."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for url, path_key, content_md in results:
        parts = path_key.strip("/").split("/") if path_key != "index" else ["index"]
        safe_parts = [re.sub(r"[^\w\-.]", "_", p) for p in parts if p]
        if not safe_parts or safe_parts == ["index"]:
            dir_path = OUTPUT_DIR / "index"
        else:
            dir_path = OUTPUT_DIR / Path(*safe_parts)
        dir_path.mkdir(parents=True, exist_ok=True)
        md_file = dir_path / "index.md"
        md_file.write_text(f"# Source: {url}\n\n{content_md}", encoding="utf-8")
    print(f"Saved {len(results)} pages under {OUTPUT_DIR}", flush=True)


def main() -> None:
    print("Crawling", BASE_URL, "...", flush=True)
    results = crawl()
    if not results:
        print("No pages found.", file=sys.stderr)
        sys.exit(1)
    save_md_with_hierarchy(results)


if __name__ == "__main__":
    main()
