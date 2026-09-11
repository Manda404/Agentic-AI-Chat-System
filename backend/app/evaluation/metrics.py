"""Simple metrics for checking ChatResponse contracts."""

from typing import Any

from app.models.chat_models import ChatResponse


def response_has_sources(response: ChatResponse) -> bool:
    validation = response.evaluation.get("citation_validation", {})
    return bool(
        validation.get("passed")
        and validation.get("cited_labels")
        and not validation.get("skipped")
    )


def score_response(response: ChatResponse, expected_route: str, expect_sources: bool = False, expected_status: str = "answered") -> dict[str, Any]:
    route_ok = response.route == expected_route
    non_empty = bool(response.answer.strip())
    sources_ok = response_has_sources(response) if expect_sources else True
    critic_ok = any(result.agent in {"critic", "critic_skipped"} for result in response.agent_results)
    answer_status = response.evaluation.get("answer", {}).get("status", "answered")
    status_ok = answer_status == expected_status
    quality_ok = response.safety_passed and (response.critic_passed if expected_status in {"answered", "clarification_requested"} else answer_status == "abstained")
    generation_ok = not any(
        result.agent in {"rag", "documentary_agent"} and result.metadata.get("grounded") is False
        for result in response.agent_results
    ) if expect_sources else True
    passed = route_ok and non_empty and sources_ok and critic_ok and quality_ok and generation_ok and status_ok
    return {
        "passed": passed,
        "status_ok": status_ok,
        "answer_status": answer_status,
        "route_ok": route_ok,
        "non_empty": non_empty,
        "sources_ok": sources_ok,
        "critic_observed": critic_ok,
        "quality_ok": quality_ok,
        "generation_ok": generation_ok,
    }
