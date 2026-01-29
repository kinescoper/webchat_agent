#!/usr/bin/env python3
"""
MCP-сервер поиска в Qdrant. Использует общий модуль rag.search.
Возвращает результат только как type=text, чтобы Cursor не падал с ошибкой 'document'.
"""
from __future__ import annotations

import asyncio
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from rag.search import search as rag_search


async def _search_async(query: str, limit: int = 5) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, rag_search, query)


def main() -> int:
    app = Server("qdrant-papers")

    @app.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="qdrant-find",
                description=(
                    "Поиск по базе знаний (Qdrant, коллекция papers). Возвращает релевантные фрагменты с полем content и ссылками source. "
                    "ОБЯЗАТЕЛЬНО после вызова: (1) ознакомься со всеми полученными фрагментами (content); "
                    "(2) на их основе сформулируй чёткий прямой ответ на вопрос пользователя; "
                    "(3) в конце ответа укажи ссылки на источники (source) из результатов поиска."
                ),
                inputSchema={
                    "type": "object",
                    "required": ["query"],
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Текст запроса для семантического поиска",
                        },
                    },
                },
            )
        ]

    @app.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
        if name != "qdrant-find":
            return [types.TextContent(type="text", text=f"Unknown tool: {name}")]
        query = (arguments or {}).get("query") or ""
        if not query.strip():
            return [types.TextContent(type="text", text="Укажите query для поиска.")]
        try:
            text = await _search_async(query)
            return [types.TextContent(type="text", text=text)]
        except Exception as e:
            return [types.TextContent(type="text", text=f"Ошибка поиска: {e}")]

    async def run_server() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await app.run(
                read_stream,
                write_stream,
                app.create_initialization_options(),
            )

    asyncio.run(run_server())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
