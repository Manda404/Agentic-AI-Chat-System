"""Métriques simples pour valider une réponse ChatResponse."""

from typing import Any

from app.models.chat_models import ChatResponse


def response_has_sources(response: ChatResponse) -> bool:
    return "Sources:" in response.answer or any(
        bool(result.metadata.get("sources_used") or result.metadata.get("documents"))
        for result in response.agent_results
    )


def score_response(response: ChatResponse, expected_route: str, expect_sources: bool = False) -> dict[str, Any]:
    route_ok = response.route == expected_route
    non_empty = bool(response.answer.strip())
    sources_ok = response_has_sources(response) if expect_sources else True
    critic_ok = response.critic_passed or response.critic_passed is False
    passed = route_ok and non_empty and sources_ok and critic_ok
    return {
        "passed": passed,
        "route_ok": route_ok,
        "non_empty": non_empty,
        "sources_ok": sources_ok,
        "critic_observed": critic_ok,
    }
