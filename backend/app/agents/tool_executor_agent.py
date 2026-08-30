"""Exécuteur borné des outils explicitement autorisés par le workflow."""

from app.logger import logger
from app.models.chat_models import AgentResult
from app.state import GraphState
from app.tools import CalculatorTool, DocumentListTool


class ToolExecutorAgent:
    """Exécute un outil déterministe selon la route validée par ToolRouterAgent."""

    def __init__(self, calculator: CalculatorTool, document_list: DocumentListTool):
        self._tools = {
            "calculation": calculator,
            "document_list": document_list,
        }

    async def run(self, state: GraphState) -> AgentResult:
        tool = self._tools.get(state.route or "")
        if tool is None:
            output = "Aucun outil autorisé ne correspond à cette route."
            state.draft_answer = output
            return AgentResult(
                agent="tool_executor",
                output=output,
                metadata={"success": False, "route": state.route},
            )
        if isinstance(tool, CalculatorTool):
            result = tool.run(state.user_message)
        else:
            result = await tool.run(owner_id=state.metadata.get("user_id"))

        state.tool_results.append(result)
        state.draft_answer = result.output
        state.metadata["executed_tool"] = result.tool
        logger.bind(
            conversation_id=state.conversation_id,
            tool=result.tool,
            success=result.success,
        ).info("Deterministic tool execution completed.")
        return AgentResult(
            agent="tool_executor",
            output=result.output,
            metadata={"tool": result.tool, "success": result.success, **result.metadata},
        )
