# Step-by-step operation

The current architecture uses four collaborating Hugging Face agents and three read-only search/passage tools. The team is limited to one correction, thirteen LLM calls and a default 90-second overall timeout.

1. On startup, `ApplicationServices` builds memory, search, embedding, generation and authentication services, then compiles the outer graph and team subgraph.
2. An authenticated user imports PDF/CSV files. The backend extracts text, chunks it, adds ownership/visibility, prepares embeddings and writes MongoDB fragments. Vector failures are reported; textless PDFs are rejected.
3. For a question, the backend loads existing owner-scoped history before storing the current message. There is no answer cache or parallel conversation checkpoint.
4. The local router honors `documents`, `general` and `auto`. Automatic mode prioritizes documentary research except for greetings, standalone calculations, explicit inventory requests and supplied-text transformations. `general` bypasses retrieval; `documents` blocks web search.
5. The planner defines an objective and subquestions. The researcher chooses its tools. Document search runs text and vector retrieval in parallel, with the same query and access scope, then applies RRF, reranking and compression. Tavily provides optional public web evidence. Passage reads recheck current permissions.
6. The researcher sends evidence and a draft to the synthesizer. The synthesizer writes a cited answer, requests specific missing evidence or abstains. The verifier approves, rejects, requests additional research or requests a writing correction. Only one return is allowed for the whole team; a second request causes abstention.
7. Local checks validate the draft, required tools and citations. An existing citation does not prove that its associated claim is true. The verdict explicitly retains this limitation.
8. The finalizer publishes the validated answer, clarification or abstention; the secret filter checks the final text. The API returns the answer and diagnostics, and conversation history stores the completed turn.

Greetings, calculations and inventory requests require no LLM generation. `SummaryAgent` handles direct answers and transformations; `RAGAgent` is retained for the simple `baseline` evaluation strategy.

The research loop runs inside the team's `researcher` node. The `documentary` outer node contains the team subgraph. Local citation failure does not trigger another generation loop.

Diagnostics include `evaluation.collaboration`, `evaluation.documentary_team`, `evaluation.documentary_agent`, `evaluation.latency_ms`, `evaluation.component_latency_ms`, `retrieval_metrics` and `evaluation.answer`. The frontend displays agent exchanges after the response, not as a live stream.

See [ARCHITECTURE_AGENT.md](ARCHITECTURE_AGENT.md) for contracts, [RAG_SYSTEM.md](RAG_SYSTEM.md) for parallel retrieval, and [EVALUATION.md](EVALUATION.md) for verification limits.
