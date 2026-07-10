"""Évaluateur léger branchable sur ChatWorkflow."""

from app.evaluation.cases import DEFAULT_EVALUATION_CASES, EvaluationCase
from app.evaluation.metrics import score_response
from app.models.chat_models import ChatRequest
from app.workflows.chat_workflow import ChatWorkflow


class WorkflowEvaluator:
    """Exécute des cas d'évaluation sans dépendre d'un framework externe."""

    def __init__(self, workflow: ChatWorkflow):
        self.workflow = workflow

    async def run_cases(self, cases: list[EvaluationCase] | None = None) -> list[dict]:
        results = []
        for case in cases or DEFAULT_EVALUATION_CASES:
            response = await self.workflow.run(ChatRequest(message=case.message))
            metrics = score_response(response, case.expected_route, case.expect_sources)
            if case.expect_critic_passed is not None:
                metrics["critic_expected"] = response.critic_passed == case.expect_critic_passed
                metrics["passed"] = metrics["passed"] and metrics["critic_expected"]
            results.append(
                {
                    "case": case.name,
                    "message": case.message,
                    "route": response.route,
                    "expected_route": case.expected_route,
                    "metrics": metrics,
                }
            )
        return results
