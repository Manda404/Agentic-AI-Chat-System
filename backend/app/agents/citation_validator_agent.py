"""Citation validation following grounded generation."""

from app.logger import logger
from app.models.chat_models import AgentResult
from app.state import GraphState
from app.tools import CitationValidatorTool


class CitationValidatorAgent:
    """Run CitationValidatorTool and expose its verdict to the local critic."""

    def __init__(self, tool: CitationValidatorTool):
        self.tool = tool

    async def run(self, state: GraphState) -> AgentResult:
        documents = state.selected_documents
        result = self.tool.run(state.draft_answer or state.rag_output or "", documents)
        state.tool_results.append(result)
        state.evaluation["citation_validation"] = {
            "passed": result.success,
            **result.metadata,
        }
        logger.bind(
            conversation_id=state.conversation_id,
            citation_validation_passed=result.success,
        ).info("Citation validation completed.")
        return AgentResult(
            agent="citation_validator",
            output=result.output,
            metadata={"tool": result.tool, "success": result.success, **result.metadata},
        )
