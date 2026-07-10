"""Cas d'évaluation simples pour le chat agentique."""

from dataclasses import dataclass


@dataclass(frozen=True)
class EvaluationCase:
    name: str
    message: str
    expected_route: str
    expect_sources: bool = False
    expect_critic_passed: bool | None = None


DEFAULT_EVALUATION_CASES = [
    EvaluationCase(name="greeting", message="hello", expected_route="greeting"),
    EvaluationCase(
        name="document_question",
        message="How does LangGraph work?",
        expected_route="rag",
        expect_sources=True,
        expect_critic_passed=True,
    ),
    EvaluationCase(name="out_of_scope", message="What is in a document that was never ingested?", expected_route="rag"),
    EvaluationCase(name="summary", message="Summarize Redis caching", expected_route="direct_answer"),
    EvaluationCase(name="correction", message="Please review and correct this answer", expected_route="direct_answer"),
    EvaluationCase(name="ambiguous", message="Can you help?", expected_route="direct_answer"),
]
