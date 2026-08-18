"""Nœud de validation structurelle des citations après génération RAG."""

from app.logger import logger
from app.models.chat_models import AgentResult
from app.state import GraphState
from app.tools import CitationValidatorTool


class CitationValidatorAgent:
    """Exécute CitationValidatorTool et expose son verdict au critic."""

    def __init__(self, tool: CitationValidatorTool):
        self.tool = tool

    async def run(self, state: GraphState) -> AgentResult:
        documents = state.reranked_results or state.search_results
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
