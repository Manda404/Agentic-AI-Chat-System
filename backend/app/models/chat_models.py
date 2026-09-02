"""
Schémas Pydantic pour le chat multi-agent (`chat_router.py`, `ChatWorkflow`).
"""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """Un message d'historique envoyé par le frontend avec la requête de chat."""
    role: Literal["user", "assistant", "system"]
    content: str

class ChatRequest(BaseModel):
    """Corps attendu par `POST /api/v1/chat`."""
    message: str = Field(min_length=1)
    conversation_id: Optional[str] = None
    history: List[ChatMessage] = Field(default_factory=list)

class SearchResult(BaseModel):
    """Un résultat de recherche MongoDB Atlas (full-text ou vectoriel), avec sa localisation source si connue."""
    document_id: Optional[str] = None
    title: str
    snippet: str
    score: float
    source: str
    page_number: Optional[int] = None
    file_name: Optional[str] = None
    embedding: Optional[List[float]] = None

class AgentResult(BaseModel):
    """Sortie brute d'un agent (search/summary/answer/...), affichée telle quelle côté frontend."""
    agent: str
    output: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """Résultat typé d'un outil déterministe autorisé par le workflow."""

    tool: Literal["calculator", "document_list", "citation_validator"]
    output: str
    success: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PlannerDecision(BaseModel):
    """Plan structuré produit par le planner LLM ou son fallback déterministe."""

    intent: Literal[
        "greeting",
        "direct_answer",
        "document_qa",
        "summarization",
        "analysis",
        "correction",
        "planning",
        "calculation",
        "document_list",
        "unknown",
    ] = "unknown"
    requires_retrieval: bool = False
    requires_rag: bool = False
    requires_critic: bool = True
    requires_safety: bool = True
    steps: List[str] = Field(default_factory=list)
    tools: List[str] = Field(default_factory=list)
    reason: str = "Fallback deterministic plan."


class CriticReview(BaseModel):
    """Évaluation structurée d'une réponse provisoire."""

    passed: bool = False
    score: float = 0.0
    groundedness_score: float = 0.0
    relevance_score: float = 0.0
    clarity_score: float = 0.0
    issues: List[str] = Field(default_factory=list)
    recommendation: Literal["accept", "revise", "retrieve_more", "fallback"] = "fallback"
    feedback: str = "No critic review available."


class CorrectiveRAGDocumentGrade(BaseModel):
    """Évaluation CRAG d'un document candidat avant génération."""

    label: str
    verdict: Literal["relevant", "ambiguous", "irrelevant"] = "irrelevant"
    relevance_score: float = 0.0
    reason: str = "No relevance evidence found."


class CorrectiveRAGReview(BaseModel):
    """Décision CRAG structurée sur le contexte récupéré."""

    decision: Literal["accept", "rewrite", "fallback"] = "fallback"
    confidence: float = 0.0
    rewritten_query: Optional[str] = None
    grades: List[CorrectiveRAGDocumentGrade] = Field(default_factory=list)
    feedback: str = "No corrective retrieval review available."


class SafetyReview(BaseModel):
    """Résultat du garde-fou de sécurité appliqué à la réponse finale candidate."""

    passed: bool = True
    issues: List[str] = Field(default_factory=list)
    redacted: bool = False
    feedback: str = "No safety issue detected."

class ChatResponse(BaseModel):
    """Réponse complète de `POST /api/v1/chat`, incluant la route choisie et les sorties des agents."""
    conversation_id: str
    route: str
    answer: str
    agents_used: List[str]
    agent_results: List[AgentResult]
    tool_results: List[ToolResult] = Field(default_factory=list)
    cached: bool = False
    context_messages: int = 0
    plan: List[str] = Field(default_factory=list)
    critic_feedback: Optional[str] = None
    critic_passed: bool = False
    critic_score: Optional[float] = None
    retrieval_metrics: Dict[str, Any] = Field(default_factory=dict)
    safety_feedback: Optional[str] = None
    safety_passed: bool = True
    evaluation: Dict[str, Any] = Field(default_factory=dict)
    trace_id: Optional[str] = None

class ConversationContextResponse(BaseModel):
    """Historique brut d'une conversation, retourné/vidé via `/conversations/{id}/context`."""
    conversation_id: str
    message_count: int
    messages: List[Dict[str, str]]
