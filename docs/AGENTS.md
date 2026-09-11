# Agents and LangGraph components

The current Hugging Face workflow uses four agents: planning → research → synthesis → verification, followed by local checks. The researcher supplies evidence and a draft; the synthesizer can abstain or request evidence; the verifier can reject or request a correction. One correction is allowed, with an overall ceiling of 13 LLM calls and 90 seconds by default. See [ARCHITECTURE_AGENT.md](ARCHITECTURE_AGENT.md).

## Outer graph and collaborative subgraph

| Outer node | Responsibility |
|---|---|
| `route` | Local routing according to the question and explicit mode |
| `documentary` | Run the four-node team subgraph: `planner`, `researcher`, `synthesizer`, `verifier` |
| `answer` | Direct greeting, calculation, inventory, general-answer or text-transformation paths |
| `validate` | Independent draft and citation checks |
| `finalize` | Publication or abstention, followed by secret filtering |

The documentary path is `route → documentary → validate → finalize`. Five outer graph nodes do not mean five sequential LLM calls. Each research pass is limited to two searches, three tools and four LLM calls; one team-wide correction is allowed. The global timeout does not reset for correction.

`PlanningAgent`, `SynthesisAgent` and `VerificationAgent` are defined in `agents/documentary_team.py`. `DocumentaryAgent` is defined in `agents/documentary_agent.py`. The team has conditional returns to research or synthesis, and exposes work messages through `evaluation.collaboration` in the frontend.

## Tools and technical components

`DocumentaryTools` exposes `rechercher(query)`, `lire_passage(passage_id)` and optional `rechercher_web(query)`. The server supplies access scope and rejects undiscovered passage IDs. The original tool names are compatibility identifiers.

`RetrievalPipeline` assembles `SearchAgent`, `HybridRetrieverAgent`, `RerankerAgent` and `ContextCompressionAgent`. These are technical components, not additional autonomous agents. Text and vector retrieval run in parallel, then fuse through RRF. A shared query and owner scope apply to both branches; errors and branch/parallel durations are observable. See [RAG_SYSTEM.md](RAG_SYSTEM.md).

`SummaryAgent` handles supplied-text transformations and general answers. `ToolExecutorAgent` handles arithmetic and document inventory. `CitationValidatorAgent`, `CriticAgent`, `FinalAnswerAgent` and `SafetyGuardAgent` provide local validation, publication and filtering.

For a grounded answer, `GraphState.selected_documents` contains exactly the excerpts from the last research context. Labels belong to that context. Citation checks do not prove factual accuracy: `critic_score=null` and `factuality_evaluated=false` remain explicit. Answer status is `answered`, `clarification_requested` or `abstained`.

Tavily is available in automatic mode when `TAVILY_API_KEY` is set. It shares the two-search-per-pass budget, with four searches overall when correction is used. Web URLs enter synthesis and verification evidence. Documents-only mode blocks web access in code.

## Reference strategies and experiments

`ChatWorkflow(strategy="baseline")` retains `route → retrieve → answer → validate → finalize`, with at most one generation call through `RAGAgent`. `strategy="agent"` retains the researcher-only variant for comparison.

`evaluation/experimental/` contains the historical `LLMPlannerAgent`, `CorrectiveRAGAgent` and `LLMCriticAgent`. They are neither imported nor instantiated by the HTTP workflow. The current planner is `PlanningAgent`.

## Changing the workflow

Prefer changing the responsible component to adding another node. Preserve `ChatResponse` compatibility, shared evidence selection and code-enforced budgets. Test behavior, failures, access scope, abstention and correction limits. Update this document, [FONCTIONNEMENT.md](FONCTIONNEMENT.md), [RAG_SYSTEM.md](RAG_SYSTEM.md) and [ARCHITECTURE_AGENT.md](ARCHITECTURE_AGENT.md) when the contract changes.
