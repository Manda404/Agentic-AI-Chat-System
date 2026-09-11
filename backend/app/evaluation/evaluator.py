"""Lightweight evaluator for ChatWorkflow."""

import time

from app.evaluation.cases import DEFAULT_EVALUATION_CASES, EvaluationCase
from app.evaluation.metrics import score_response
from app.models.chat_models import ChatRequest
from app.workflows.chat_workflow import ChatWorkflow


class WorkflowEvaluator:
    """Run evaluation cases without an additional evaluation framework."""

    def __init__(self, workflow: ChatWorkflow):
        self.workflow = workflow

    async def run_cases(self, cases: list[EvaluationCase] | None = None, owner_id: str | None = None) -> list[dict]:
        results = []
        for case in DEFAULT_EVALUATION_CASES if cases is None else cases:
            started = time.perf_counter()
            response = await self.workflow.run(ChatRequest(message=case.message, mode=case.mode), user_id=owner_id)
            metrics = score_response(response, case.expected_route, case.expect_sources, case.expected_status)
            if case.expect_critic_passed is not None:
                metrics["critic_expected"] = response.critic_passed == case.expect_critic_passed
                metrics["passed"] = metrics["passed"] and metrics["critic_expected"]
            results.append(
                {
                    "case": case.name,
                    "answer": response.answer,
                    "message": case.message,
                    "route": response.route,
                    "expected_route": case.expected_route,
                    "metrics": metrics,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    "llm_calls": response.evaluation.get("llm_calls", 0),
                    "documentary_tool_calls": sum(item.tool in {"rechercher", "lire_passage"} for item in response.tool_results),
                    "source_count": response.evaluation.get("citation_validation", {}).get("valid_label_count", 0),
                    "answer_status": response.evaluation.get("answer", {}).get("status"),
                    "failure_reason": response.evaluation.get("answer", {}).get("reason"),
                }
            )
        return results
