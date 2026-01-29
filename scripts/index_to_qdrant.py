#!/usr/bin/env python3
"""
Читает .md из docs_crawl, разбивает на чанки, эмбеддит (fastembed, 384 dim)
и загружает в Qdrant коллекцию papers с именованным вектором fast-all-minilm-l6-v2.
Payload: section, source, content, heading. Чанкинг по заголовкам Markdown (##, ###), длинные блоки — по размеру с перекрытием.
"""
from __future__ import annotations

import re
import sys
import uuid
from pathlib import Path

from fastembed import TextEmbedding
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs_crawl"
QDRANT_URL = "http://localhost:6333"
COLLECTION_NAME = "papers"
VECTOR_NAME = "fast-all-minilm-l6-v2"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
CHUNK_SIZE = 600
CHUNK_OVERLAP = 100


def iter_md_files(root: Path):
    """Рекурсивно обходит все .md файлы."""
    for f in root.rglob("*.md"):
        yield f


def extract_section_and_source(file_path: Path, root: Path) -> tuple[str, str]:
    """section — иерархия (путь), source — URL или путь файла."""
    rel = file_path.relative_to(root)
    section = str(rel.parent).replace("\\", "/") if rel.parent != Path(".") else rel.stem
    source = f"https://docs.kinescope.ru/{section}/{rel.name}" if rel.name != "index.md" else f"https://docs.kinescope.ru/{section}"
    return section, source


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Разбивает текст на чанки по размеру с перекрытием (по границам строк)."""
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + size
        if end < len(text):
            next_break = text.rfind("\n", start, end + 1)
            if next_break > start:
                end = next_break + 1
        chunks.append(text[start:end].strip())
        start = end - overlap
        if start >= len(text):
            break
    return [c for c in chunks if c]


def split_by_headers(text: str) -> list[tuple[str, str]]:
    """Разбивает текст по заголовкам Markdown (##, ###). Возвращает список (заголовок, блок)."""
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    if not text:
        return []
    header_pattern = re.compile(r"^(#{2,3})\s+(.+)$", re.MULTILINE)
    parts: list[tuple[str, str]] = []
    last_end = 0
    current_heading = ""
    for m in header_pattern.finditer(text):
        block = text[last_end : m.start()].strip()
        if block:
            parts.append((current_heading, block))
        current_heading = m.group(2).strip()
        last_end = m.start()
    block = text[last_end:].strip()
    if block:
        parts.append((current_heading, block))
    return parts


def chunk_by_headers(
    text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP
) -> list[tuple[str, str]]:
    """Сначала разбивает по заголовкам, затем длинные блоки — по размеру. Возвращает (heading, chunk)."""
    result: list[tuple[str, str]] = []
    for heading, block in split_by_headers(text):
        if len(block) <= size:
            if len(block) >= 50:
                result.append((heading, block))
        else:
            for chunk in chunk_text(block, size=size, overlap=overlap):
                if len(chunk) >= 50:
                    result.append((heading, chunk))
    return result


def main() -> None:
    if not DOCS_DIR.exists():
        print(f"Run crawl first: python scripts/crawl_docs.py\nDocs dir missing: {DOCS_DIR}", file=sys.stderr)
        sys.exit(1)

    print("Loading embedding model", EMBEDDING_MODEL, "...", flush=True)
    embedder = TextEmbedding(model_name=EMBEDDING_MODEL)
    print("Connecting to Qdrant", QDRANT_URL, "...", flush=True)
    client = QdrantClient(url=QDRANT_URL)

    collections = client.get_collections().collections
    if not any(c.name == COLLECTION_NAME for c in collections):
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config={
                VECTOR_NAME: VectorParams(size=384, distance=Distance.COSINE),
            },
        )
        print("Created collection", COLLECTION_NAME, flush=True)

    items: list[tuple[str, str, str, str]] = []
    for md_file in iter_md_files(DOCS_DIR):
        raw = md_file.read_text(encoding="utf-8")
        title_match = re.match(r"^#\s+Source:\s*\S+\s*\n\n", raw)
        body = raw[title_match.end() :] if title_match else raw
        section, source = extract_section_and_source(md_file, DOCS_DIR)
        for heading, chunk in chunk_by_headers(body):
            items.append((section, source, chunk, heading))

    if not items:
        print("No chunks to index.", file=sys.stderr)
        sys.exit(1)

    texts = [item[2] for item in items]
    print("Embedding", len(texts), "chunks ...", flush=True)
    vectors = list(embedder.embed(texts))
    points = [
        PointStruct(
            id=str(uuid.uuid4()),
            vector={VECTOR_NAME: vectors[i]},
            payload={
                "section": section,
                "source": source,
                "content": chunk,
                "heading": heading,
            },
        )
        for i, (section, source, chunk, heading) in enumerate(items)
    ]

    batch_size = 64
    for j in range(0, len(points), batch_size):
        batch = points[j : j + batch_size]
        client.upsert(collection_name=COLLECTION_NAME, points=batch)
        print(f"  upserted {j + len(batch)} / {len(points)}", flush=True)

    print("Indexed", len(points), "points into", COLLECTION_NAME, flush=True)


if __name__ == "__main__":
    main()
