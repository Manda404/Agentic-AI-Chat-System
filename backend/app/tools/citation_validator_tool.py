"""Validation des labels de citation produits par le RAG."""

import re

from app.config.settings import settings
from app.models.chat_models import SearchResult, ToolResult


class CitationValidatorTool:
    """Vérifie présence/plage des citations et ajoute un signal lexical de support."""

    name = "citation_validator"
    _CITATION_PATTERN = re.compile(r"\[(\d+)\]")
    _TERM_PATTERN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9_]{3,}")

    def __init__(
        self,
        require_support: bool | None = None,
        min_overlap: int | None = None,
    ) -> None:
        self.require_support = (
            settings.citation_support_required if require_support is None else require_support
        )
        self.min_overlap = (
            settings.citation_support_min_overlap if min_overlap is None else min_overlap
        )

    def run(self, answer: str, documents: list[SearchResult]) -> ToolResult:
        answer_body = answer.split("\n\nSources:", 1)[0]
        cited_labels = sorted({int(value) for value in self._CITATION_PATTERN.findall(answer_body)})
        valid_labels = set(range(1, len(documents) + 1))
        invalid_labels = sorted(set(cited_labels) - valid_labels)
        missing = bool(documents) and not cited_labels
        support = self._support_by_label(answer_body, documents, cited_labels)
        unsupported_labels = [
            label
            for label, details in support.items()
            if details["overlap_count"] < self.min_overlap
        ]
        # Une réponse « aucun document trouvé » n'a rien à citer : ce cas est
        # valide mais explicitement marqué comme ignoré dans les métadonnées.
        support_failed = bool(unsupported_labels) and self.require_support
        success = not documents or (not missing and not invalid_labels and not support_failed)

        if not documents:
            output = "Validation ignorée : aucun document RAG disponible."
        elif missing:
            output = "La réponse RAG ne contient aucune citation [n]."
        elif invalid_labels:
            output = f"Citations hors plage détectées : {invalid_labels}."
        elif unsupported_labels:
            output = (
                f"Citations structurellement valides : {cited_labels}. "
                f"Support lexical faible : {unsupported_labels}."
            )
        else:
            output = f"Citations valides avec support lexical : {cited_labels}."

        return ToolResult(
            tool=self.name,
            output=output,
            success=success,
            metadata={
                "cited_labels": cited_labels,
                "valid_label_count": len(valid_labels),
                "invalid_labels": invalid_labels,
                "missing_citations": missing,
                "skipped": not documents,
                "unsupported_labels": unsupported_labels,
                "support_by_label": support,
                "support_required": self.require_support,
                "scope": "structural_plus_lexical_support",
            },
        )

    def _support_by_label(
        self,
        answer_body: str,
        documents: list[SearchResult],
        cited_labels: list[int],
    ) -> dict[int, dict[str, object]]:
        """Compare les termes de la phrase citante avec ceux du document cité."""
        sentences = [
            segment.strip()
            for segment in re.split(r"(?<=[.!?])\s+|\n+", answer_body)
            if segment.strip()
        ]
        support: dict[int, dict[str, object]] = {}
        for label in cited_labels:
            if label < 1 or label > len(documents):
                continue
            citation_pattern = re.compile(rf"\[{label}\]")
            claim_text = " ".join(sentence for sentence in sentences if citation_pattern.search(sentence))
            claim_terms = self._terms(self._CITATION_PATTERN.sub(" ", claim_text))
            document = documents[label - 1]
            source_terms = self._terms(f"{document.title} {document.snippet}")
            overlap = sorted(claim_terms & source_terms)
            support[label] = {
                "overlap_count": len(overlap),
                "overlap_terms": overlap[:12],
            }
        return support

    def _terms(self, text: str) -> set[str]:
        """Tokenisation légère, suffisante pour produire un signal de citation auditable."""
        return {match.group(0).lower() for match in self._TERM_PATTERN.finditer(text or "")}
