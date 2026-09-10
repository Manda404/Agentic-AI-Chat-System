"""Bounded read-only inventory of MongoDB documents."""

from app.models.chat_models import ToolResult
from app.services.search_service import SearchService


class DocumentListTool:
    """List unique sources without running semantic search."""

    name = "document_list"

    def __init__(self, search_service: SearchService, limit: int = 200):
        self.search_service = search_service
        self.limit = limit

    async def run(self, owner_id: str | None = None) -> ToolResult:
        try:
            records = await self.search_service.list_indexed_documents(limit=self.limit, owner_id=owner_id)
        except Exception as exc:
            return ToolResult(
                tool=self.name,
                output=f"Document inventory unavailable: {exc}",
                success=False,
                metadata={"reason": type(exc).__name__},
            )

        sources: dict[tuple[str, str], dict[str, object]] = {}
        for record in records:
            file_name = str(record.get("file_name") or "").strip()
            title = str(record.get("title") or "Untitled").strip()
            source = str(record.get("source") or "mongodb").strip()
            key = ("file", file_name) if file_name else ("entry", f"{source}:{title}")
            item = sources.setdefault(
                key,
                {"label": file_name or title, "source": source, "chunks": 0, "pages": set()},
            )
            item["chunks"] = int(item["chunks"]) + 1
            page = record.get("page_number")
            if page is not None:
                item["pages"].add(str(page))  # type: ignore[union-attr]

        lines: list[str] = []
        for item in sorted(sources.values(), key=lambda value: str(value["label"]).lower()):
            details = f"{item['chunks']} chunk(s)"
            pages = item["pages"]
            if pages:
                details += f", {len(pages)} page(s)"
            lines.append(f"- {item['label']} — {details}")

        if not lines:
            output = "No documents are currently indexed."
        else:
            output = f"Indexed documents ({len(lines)} unique source(s)):\n" + "\n".join(lines)
        return ToolResult(
            tool=self.name,
            output=output,
            metadata={
                "unique_sources": len(lines),
                "indexed_records_scanned": len(records),
                "scan_limit": self.limit,
                "truncated": len(records) >= self.limit,
                "owner_scoped": bool(owner_id),
            },
        )
