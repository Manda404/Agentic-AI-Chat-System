# Evaluating the project

The current Hugging Face workflow uses planning, research, synthesis and verification, followed by local checks. One correction is allowed, with a global budget of thirteen LLM calls and 90 seconds by default. See [ARCHITECTURE_AGENT.md](ARCHITECTURE_AGENT.md).

Keep three questions separate: does the code behave correctly, does retrieval find the right evidence, and are the answers factually correct?

## 1. Provider-free contract tests

```sh
make test
```

The suite checks ingestion, isolation, indexing, arithmetic, source selection, citations and LangGraph behavior. MongoDB, Redis and LLM doubles verify the one-generation baseline, collaborative budgets, permissions, timeout, structured JSON, clarification, no-LLM routes, history, failures, provider selection and abstention. These tests do not measure real model quality.

For a local run without remote observability:

```sh
cd backend
APP_ENV=test LANGFUSE_ENABLED=false LANGFUSE_TRACING_ENABLED=false LOG_TO_FILE=false \
HUGGINGFACE_API_KEY='' TAVILY_API_KEY='' MONGODB_URI='' .venv/bin/python -m unittest discover -s tests
```

## 2. Real diagnostics and retrieval

```sh
cd backend
.venv/bin/python -m app.evaluation.index_health
.venv/bin/python -m app.evaluation.retrieval_benchmark --verbose --k 5
```

Read-only diagnostics check index existence/readiness, declared dimensions, prefilter fields, vectorized document counts and embedding-model provenance.

The full benchmark uses Atlas and Hugging Face. Ingest the reference CSV and wait for ready indexes first. In owner mode, specify `--owner-id <corpus-owner>`. It reports Precision@k, Recall@k, MRR and NDCG@k for text retrieval, hybrid fusion and reranking, using the same parallel retrieval path as chat. Required provider failures abort the benchmark rather than producing misleading scores.

Duplicate results keep their rank positions but earn no repeated relevance credit. Precision@k always divides by k. The ten catalog cases use titles as labels; a real fragment corpus needs annotated document/page/passage identities. These retrieval metrics do not evaluate compression or generation.

## 3. Answers and abstention

`WorkflowEvaluator` receives a `ChatWorkflow`. Each `EvaluationCase` specifies route, mode (`auto/documents/general`), source expectations and `expected_status` (`answered`, `clarification_requested`, `abstained`). A no-answer case should reward correct abstention rather than artificially requiring `critic_passed=true`.

Results retain the answer for independent reading. Automated checks cover route, nonempty output, expected status, citations, local checks and successful generation. Nonempty text is not proof of correctness.

The current path reports `critic_score=null` and `factuality_evaluated=false`. The online verifier's judgment is not an independent factuality measurement. Historical planning, CRAG and LLM-critic components in `evaluation/experimental/` likewise do not establish validated quality scores by themselves.

## Comparison protocol

Build a versioned set of representative questions, answers, expected pages/citations, missing-evidence cases and access-control cases. Keep a held-out set separate from tuning. Include multilingual cases when the corpus requires them, even though the project interface and default response instructions are English.

Measure independently annotated answer correctness, citation support, correct and excessive abstention, Recall@k, ranking quality, p50/p95 latency, provider calls and cost. Break down results for PDFs, tables, paraphrases and conversational questions.

```sh
cd backend
.venv/bin/python -m app.evaluation.compare_workflows --cases cases.json --owner-id <corpus-owner>
```

The JSON file contains `EvaluationCase` objects. Without `--cases`, functional catalog cases are used. The comparator alternates strategy order and retains answers, statuses, latency and counters. History stays in memory without writing Redis conversations. Real runs use Atlas and configured providers and may send questions/passages to generation or embedding services.

`contracts_passed` measures software contracts, not factual accuracy. LLM/tool counters are not monetary cost. Independently annotate results before claiming business gains. Introduce one change at a time: reranking, retrieval parameters or budgets. Earlier audit numbers do not validate the current architecture's semantic quality.

## Collaboration and web tests

The four-node team subgraph has conditional returns to research or synthesis. Tests cover plan handoffs, missing-evidence requests, writing corrections, the single-correction limit, the thirteen-call ceiling and concurrent isolation. The frontend reads exchanges from `evaluation.collaboration`.

Tavily uses `rechercher_web` in automatic mode with `TAVILY_API_KEY`, sharing the search budget with documents. Tests cover missing credentials, provider failures, shared budgets, source propagation and blocking in documents-only mode.

Parallel retrieval tests verify that both branches start before either completes, preserve equivalent RRF rankings, retain the available branch on failure, cancel both asynchronous waits and isolate users. Measure real Atlas latency separately; simulated timings are not production performance results.
