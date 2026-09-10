"""Pydantic schemas for multi-agent chat requests, responses and intermediate decisions."""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """A history message supplied by the frontend with a chat request."""
    role: Literal["user", "assistant", "system"]
    content: str

class ChatRequest(BaseModel):
    """Request body for POST /api/v1/chat."""
    message: str = Field(min_length=1)
    mode: Literal["auto", "documents", "general"] = "auto"
    conversation_id: Optional[str] = None
    history: List[ChatMessage] = Field(default_factory=list)

class SearchResult(BaseModel):
    """A text, vector or web retrieval hit with source location when available."""
    document_id: Optional[str] = None
    title: str
    snippet: str
    score: float
    source: str
    page_number: Optional[int] = None
    file_name: Optional[str] = None
    embedding: Optional[List[float]] = None

class AgentResult(BaseModel):
    """Raw agent output and metadata exposed in frontend diagnostics."""
    agent: str
    output: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """Typed result of a tool authorized by the workflow."""

    tool: Literal["calculator", "document_list", "citation_validator", "rechercher", "rechercher_web", "lire_passage"]
    output: str
    success: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PlannerDecision(BaseModel):
    """Structured plan from the experimental planner or its deterministic fallback."""

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
    """Structured assessment of a candidate answer."""

    passed: bool = False
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    groundedness_score: float = Field(default=0.0, ge=0.0, le=1.0)
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    clarity_score: float = Field(default=0.0, ge=0.0, le=1.0)
    issues: List[str] = Field(default_factory=list)
    recommendation: Literal["accept", "revise", "retrieve_more", "fallback"] = "fallback"
    feedback: str = "No critic review available."


class CorrectiveRAGDocumentGrade(BaseModel):
    """CRAG assessment of one candidate document before generation."""

    label: str
    verdict: Literal["relevant", "ambiguous", "irrelevant"] = "irrelevant"
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = "No relevance evidence found."


class CorrectiveRAGReview(BaseModel):
    """Structured CRAG decision about retrieved context."""

    decision: Literal["accept", "rewrite", "fallback"] = "fallback"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rewritten_query: Optional[str] = None
    grades: List[CorrectiveRAGDocumentGrade] = Field(default_factory=list)
    feedback: str = "No corrective retrieval review available."


class SafetyReview(BaseModel):
    """Safety assessment of the final candidate answer."""

    passed: bool = True
    issues: List[str] = Field(default_factory=list)
    redacted: bool = False
    feedback: str = "No safety issue detected."

class ChatResponse(BaseModel):
    """Complete POST /api/v1/chat response including the chosen route and agent outputs."""
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
    """Conversation history returned or cleared through /conversations/{id}/context."""
    conversation_id: str
    message_count: int
    messages: List[Dict[str, str]]
