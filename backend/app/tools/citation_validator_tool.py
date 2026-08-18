"""Validation structurelle des labels de citation produits par le RAG."""

import re

from app.models.chat_models import SearchResult, ToolResult


class CitationValidatorTool:
    """Vérifie présence et plage des citations ``[n]`` sans prétendre valider le sens."""

    name = "citation_validator"
    _CITATION_PATTERN = re.compile(r"\[(\d+)\]")

    def run(self, answer: str, documents: list[SearchResult]) -> ToolResult:
        answer_body = answer.split("\n\nSources:", 1)[0]
        cited_labels = sorted({int(value) for value in self._CITATION_PATTERN.findall(answer_body)})
        valid_labels = set(range(1, len(documents) + 1))
        invalid_labels = sorted(set(cited_labels) - valid_labels)
        missing = bool(documents) and not cited_labels
        # Une réponse « aucun document trouvé » n'a rien à citer : ce cas est
        # valide mais explicitement marqué comme ignoré dans les métadonnées.
        success = not documents or (not missing and not invalid_labels)

        if not documents:
            output = "Validation ignorée : aucun document RAG disponible."
        elif missing:
            output = "La réponse RAG ne contient aucune citation [n]."
        elif invalid_labels:
            output = f"Citations hors plage détectées : {invalid_labels}."
        else:
            output = f"Citations structurellement valides : {cited_labels}."

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
                "scope": "structural_only",
            },
        )
