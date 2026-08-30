import unittest

from app.models.chat_models import SearchResult
from app.tools import CalculatorTool, CitationValidatorTool, DocumentListTool


class _FakeSearchService:
    async def list_indexed_documents(self, limit: int = 200, owner_id: str | None = None):
        return [
            {"title": "Guide - Page 1", "file_name": "guide.pdf", "page_number": 1, "source": "pdf"},
            {"title": "Guide - Page 2", "file_name": "guide.pdf", "page_number": 2, "source": "pdf"},
            {"title": "Catalog entry", "source": "catalog"},
        ]


class ToolTests(unittest.IsolatedAsyncioTestCase):
    def test_calculator_evaluates_arithmetic_without_eval(self):
        result = CalculatorTool().run("Calcule (2 + 3) * 4")
        self.assertTrue(result.success)
        self.assertEqual(result.metadata["value"], 20.0)

    def test_calculator_rejects_code_execution(self):
        result = CalculatorTool().run("calculate __import__('os').system('whoami')")
        self.assertFalse(result.success)
        self.assertNotIn("whoami", result.output)

    async def test_document_list_groups_pdf_pages(self):
        result = await DocumentListTool(_FakeSearchService()).run()  # type: ignore[arg-type]
        self.assertTrue(result.success)
        self.assertIn("guide.pdf", result.output)
        self.assertEqual(result.metadata["unique_sources"], 2)

    def test_citation_validator_accepts_known_labels(self):
        documents = [
            SearchResult(title="Guide", snippet="Evidence", score=1.0, source="test")
        ]
        result = CitationValidatorTool().run("Grounded claim [1].", documents)
        self.assertTrue(result.success)

    def test_citation_validator_can_enforce_lexical_support(self):
        documents = [
            SearchResult(
                title="LangGraph Guide",
                snippet="LangGraph orchestrates stateful multi-agent workflows.",
                score=1.0,
                source="test",
            )
        ]
        accepted = CitationValidatorTool(require_support=True).run(
            "LangGraph orchestrates workflows [1].",
            documents,
        )
        rejected = CitationValidatorTool(require_support=True).run(
            "PostgreSQL stores payments [1].",
            documents,
        )

        self.assertTrue(accepted.success)
        self.assertFalse(rejected.success)
        self.assertEqual(rejected.metadata["unsupported_labels"], [1])

    def test_citation_validator_rejects_missing_or_unknown_labels(self):
        documents = [
            SearchResult(title="Guide", snippet="Evidence", score=1.0, source="test")
        ]
        missing = CitationValidatorTool().run("Grounded claim.", documents)
        unknown = CitationValidatorTool().run("Grounded claim [2].", documents)
        self.assertFalse(missing.success)
        self.assertFalse(unknown.success)

    def test_citation_validator_skips_cleanly_without_documents(self):
        result = CitationValidatorTool().run(
            "No indexed document answers this question.",
            [],
        )
        self.assertTrue(result.success)
        self.assertTrue(result.metadata["skipped"])


if __name__ == "__main__":
    unittest.main()
