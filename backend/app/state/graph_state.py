"""
État partagé du workflow LangGraph.

`GraphState` reste une dataclass lisible pour les agents existants, tandis
que `GraphStateDict` sert de schéma explicite au `StateGraph`. Le workflow
convertit entre les deux formats aux frontières des nœuds LangGraph afin de
garder les agents faciles à tester et à lire.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, TypedDict

from app.models.chat_models import AgentResult, ChatMessage, PlannerDecision, SearchResult


class GraphStateDict(TypedDict, total=False):
    """Schéma de données utilisé par LangGraph pour chaque étape du chat."""

    conversation_id: str
    transaction_id: Optional[str]
    user_message: str
    history: List[ChatMessage]
    conversation_context: List[Dict[str, str]]
    route: Optional[str]
    intent: Optional[str]
    plan: List[str]
    tools: List[str]
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
    metadata: Dict[str, Any]


@dataclass
class GraphState:
    """Contexte d'exécution d'une requête de chat, du routage à la réponse finale."""

    conversation_id: str
    user_message: str
    transaction_id: Optional[str] = None
    history: List[ChatMessage] = field(default_factory=list)
    conversation_context: List[Dict[str, str]] = field(default_factory=list)
    route: Optional[str] = None
    intent: Optional[str] = None
    plan: List[str] = field(default_factory=list)
    tools: List[str] = field(default_factory=list)
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
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: Dict[str, Any]) -> "GraphState":
        """Reconstruit un état dataclass depuis le dictionnaire transmis par LangGraph."""
        values = dict(payload)
        values.setdefault("history", [])
        values.setdefault("conversation_context", [])
        values.setdefault("plan", [])
        values.setdefault("tools", [])
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
        if values.get("planner_decision") and not isinstance(values["planner_decision"], PlannerDecision):
            values["planner_decision"] = PlannerDecision(**values["planner_decision"])
        return cls(**values)

    def to_dict(self) -> GraphStateDict:
        """Convertit l'état en dictionnaire compatible avec `StateGraph`."""
        return asdict(self)

    def record_result(self, result: AgentResult) -> None:
        """Ajoute une sortie agent et maintient la liste `agents_used` sans doublons consécutifs."""
        self.agent_results.append(result)
        if result.agent not in self.agents_used:
            self.agents_used.append(result.agent)
