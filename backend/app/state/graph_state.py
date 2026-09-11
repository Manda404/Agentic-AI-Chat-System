"""Shared LangGraph workflow state. Agents use the GraphState dataclass; GraphStateDict defines the graph schema. Convert between them at node boundaries for readable, testable components."""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, TypedDict

from app.models.chat_models import AgentResult, ChatMessage, PlannerDecision, SearchResult, ToolResult


class GraphStateDict(TypedDict, total=False):
    """Data schema used by LangGraph at each chat stage."""

    conversation_id: str
    transaction_id: Optional[str]
    user_message: str
    history: List[ChatMessage]
    conversation_context: List[Dict[str, str]]
    route: Optional[str]
    intent: Optional[str]
    plan: List[str]
    tools: List[str]
    tool_results: List[ToolResult]
    planner_decision: Optional[PlannerDecision]
    search_results: List[SearchResult]
    reranked_results: List[SearchResult]
    compressed_context: Optional[str]
    search_output: Optional[str]
    summary_output: Optional[str]
    rag_output: Optional[str]
    draft_answer: Optional[str]
    critic_feedback: Optional[str]
    critic_passed: bool
    critic_score: Optional[float]
    safety_feedback: Optional[str]
    safety_passed: bool
    final_answer: Optional[str]
    agents_used: List[str]
    agent_results: List[AgentResult]
    retrieval_metrics: Dict[str, Any]
    evaluation: Dict[str, Any]
    error: Optional[str]
    correction_attempted: bool
    retrieval_correction_attempted: bool
    metadata: Dict[str, Any]


@dataclass
class GraphState:
    """Execution context of one chat request from routing to final output."""

    conversation_id: str
    user_message: str
    transaction_id: Optional[str] = None
    history: List[ChatMessage] = field(default_factory=list)
    conversation_context: List[Dict[str, str]] = field(default_factory=list)
    route: Optional[str] = None
    intent: Optional[str] = None
    plan: List[str] = field(default_factory=list)
    tools: List[str] = field(default_factory=list)
    tool_results: List[ToolResult] = field(default_factory=list)
    planner_decision: Optional[PlannerDecision] = None
    search_results: List[SearchResult] = field(default_factory=list)
    reranked_results: List[SearchResult] = field(default_factory=list)
    compressed_context: Optional[str] = None
    search_output: Optional[str] = None
    summary_output: Optional[str] = None
    rag_output: Optional[str] = None
    draft_answer: Optional[str] = None
    critic_feedback: Optional[str] = None
    critic_passed: bool = False
    critic_score: Optional[float] = None
    safety_feedback: Optional[str] = None
    safety_passed: bool = True
    final_answer: Optional[str] = None
    agents_used: List[str] = field(default_factory=list)
    agent_results: List[AgentResult] = field(default_factory=list)
    retrieval_metrics: Dict[str, Any] = field(default_factory=dict)
    evaluation: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    correction_attempted: bool = False
    retrieval_correction_attempted: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def selected_documents(self) -> List[SearchResult]:
        if self.reranked_results or "reranked_count" in self.retrieval_metrics or "corrective_rag" in self.retrieval_metrics:
            documents = self.reranked_results
        else:
            documents = self.search_results
        count = self.metadata.get("context_document_count")
        return documents if count is None else documents[:count]

    @classmethod
    def from_mapping(cls, payload: Dict[str, Any]) -> "GraphState":
        """Rebuild the state dataclass from the LangGraph channel mapping."""
        values = dict(payload)
        values.setdefault("history", [])
        values.setdefault("conversation_context", [])
        values.setdefault("plan", [])
        values.setdefault("tools", [])
        values.setdefault("tool_results", [])
        values.setdefault("search_results", [])
        values.setdefault("reranked_results", [])
        values.setdefault("agents_used", [])
        values.setdefault("agent_results", [])
        values.setdefault("retrieval_metrics", {})
        values.setdefault("evaluation", {})
        values.setdefault("metadata", {})
        values["history"] = [
            item if isinstance(item, ChatMessage) else ChatMessage(**item)
            for item in values["history"]
        ]
        values["search_results"] = [
            item if isinstance(item, SearchResult) else SearchResult(**item)
            for item in values["search_results"]
        ]
        values["reranked_results"] = [
            item if isinstance(item, SearchResult) else SearchResult(**item)
            for item in values["reranked_results"]
        ]
        values["agent_results"] = [
            item if isinstance(item, AgentResult) else AgentResult(**item)
            for item in values["agent_results"]
        ]
        values["tool_results"] = [
            item if isinstance(item, ToolResult) else ToolResult(**item)
            for item in values["tool_results"]
        ]
        if values.get("planner_decision") and not isinstance(values["planner_decision"], PlannerDecision):
            values["planner_decision"] = PlannerDecision(**values["planner_decision"])
        return cls(**values)

    def to_dict(self) -> GraphStateDict:
        """Convert state into a StateGraph-compatible mapping."""
        return asdict(self)

    def record_result(self, result: AgentResult) -> None:
        """Append an agent result and maintain the deduplicated agents_used list."""
        self.agent_results.append(result)
        if result.agent not in self.agents_used:
            self.agents_used.append(result.agent)
