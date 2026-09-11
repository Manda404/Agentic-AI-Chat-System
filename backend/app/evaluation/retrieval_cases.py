"""Retrieval ground truth matching the bundled ten-document ai_tooling_catalog.csv dataset. Run after POST /ingest/sample-data. search_methods_comparison and parallel_vs_supervisor include multiple relevant documents or semantically close distractors, so merely finding a related topic is insufficient. Add RetrievalGoldCase entries with annotated relevance to evaluate your own ingested documents."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalGoldCase:
    name: str
    query: str
    relevant_titles: frozenset[str]


GOLD_RETRIEVAL_CASES: list[RetrievalGoldCase] = [
    RetrievalGoldCase(
        name="langgraph_purpose",
        query="What is LangGraph used for?",
        relevant_titles=frozenset({"LangGraph Overview"}),
    ),
    RetrievalGoldCase(
        name="redis_conversation_memory",
        query="How does Redis help store chat conversation history?",
        relevant_titles=frozenset({"Redis Context Memory"}),
    ),
    RetrievalGoldCase(
        name="langfuse_observability",
        query="What is Langfuse used for in LLM applications?",
        relevant_titles=frozenset({"Langfuse Tracing"}),
    ),
    RetrievalGoldCase(
        name="local_model_inference",
        query="How can I run open source language models locally instead of a hosted API?",
        relevant_titles=frozenset({"Ollama Local Models"}),
    ),
    RetrievalGoldCase(
        name="hosted_inference_api",
        query="What hosted API can I call over HTTPS for text generation without running my own server?",
        relevant_titles=frozenset({"Hugging Face Inference API"}),
    ),
    RetrievalGoldCase(
        name="search_methods_comparison",
        query="What's the difference between keyword search and vector similarity search?",
        relevant_titles=frozenset({"Elasticsearch Search Basics", "Vector Search Concepts"}),
    ),
    RetrievalGoldCase(
        name="embeddings_semantic_similarity",
        query="How do embeddings help find semantically similar content?",
        relevant_titles=frozenset({"Vector Search Concepts"}),
    ),
    RetrievalGoldCase(
        name="parallel_agent_execution",
        query="How can multiple agents run search and summarization at the same time?",
        relevant_titles=frozenset({"Parallel Agent Pattern"}),
    ),
    RetrievalGoldCase(
        name="parallel_vs_supervisor",
        query="How does a supervisor agent decide which tool or route to use for a query?",
        relevant_titles=frozenset({"Supervisor Routing"}),
    ),
    RetrievalGoldCase(
        name="frontend_backend_chat_flow",
        query="How does the frontend send a chat message to the backend and render the response?",
        relevant_titles=frozenset({"Chat UI Integration"}),
    ),
]
