"""Métriques simples pour valider une réponse ChatResponse."""

from typing import Any

from app.models.chat_models import ChatResponse


def response_has_sources(response: ChatResponse) -> bool:
    validation = response.evaluation.get("citation_validation", {})
    return bool(
        validation.get("passed")
        and validation.get("cited_labels")
        and not validation.get("skipped")
    )


def score_response(response: ChatResponse, expected_route: str, expect_sources: bool = False) -> dict[str, Any]:
    route_ok = response.route == expected_route
    non_empty = bool(response.answer.strip())
    sources_ok = response_has_sources(response) if expect_sources else True
    critic_ok = any(result.agent in {"critic", "critic_skipped"} for result in response.agent_results)
    quality_ok = response.critic_passed and response.safety_passed
    generation_ok = not any(
        result.agent == "rag" and result.metadata.get("grounded") is False
        for result in response.agent_results
    ) if expect_sources else True
    passed = route_ok and non_empty and sources_ok and critic_ok and quality_ok and generation_ok
    return {
        "passed": passed,
        "route_ok": route_ok,
        "non_empty": non_empty,
        "sources_ok": sources_ok,
        "critic_observed": critic_ok,
        "quality_ok": quality_ok,
        "generation_ok": generation_ok,
    }
