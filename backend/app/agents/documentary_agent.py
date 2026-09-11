"""Research agent with read-only tools and server-enforced budgets."""
import asyncio
import json
import time

from pydantic import ValidationError

from app.config.settings import settings
from app.models.chat_models import AgentResult, SearchResult, ToolResult
from app.models.documentary_models import DocumentaryAction
from app.services.llm_service import generation_failure_reason
from app.state import GraphState


class DocumentaryAgent:
    MAX_SEARCHES = 2
    MAX_TOOLS = 3
    MAX_LLM_CALLS = 4

    def __init__(self, llm_service, tools, timeout_seconds=None):
        self.llm_service = llm_service
        self.tools = tools
        self.timeout_seconds = settings.documentary_agent_timeout_seconds if timeout_seconds is None else timeout_seconds

    async def run(self, state: GraphState) -> AgentResult:
        # All mutable state belongs to this request, never shared across users.
        counts = {'llm_calls': 0, 'tool_calls': 0, 'searches': 0, 'web_searches': 0}
        ledger: dict[str, SearchResult] = {}
        if state.metadata.get('collaboration_request'):
            ledger = {item.document_id: item for item in state.selected_documents if item.document_id}
        observations = []
        if state.metadata.get('research_plan'):
            observations.append({'action': 'plan', 'success': True, 'plan': state.metadata['research_plan']})
        if state.metadata.get('collaboration_request'):
            observations.append({'action': 'correction_request', 'success': True, 'request': state.metadata['collaboration_request']})
        started = time.perf_counter()
        state.evaluation['documentary_agent'] = counts
        state.plan = ['route', 'documentary_agent (bounded tools)', 'validate', 'finalize']
        try:
            async with asyncio.timeout(self.timeout_seconds):
                await self._loop(state, ledger, observations, counts)
        except TimeoutError:
            self._fail(state, 'agent_timeout')
        finally:
            state.evaluation['llm_calls'] = counts['llm_calls']
            counts['elapsed_ms'] = round((time.perf_counter() - started) * 1000, 2)
            counts['limits'] = {'llm_calls': self.MAX_LLM_CALLS, 'tool_calls': self.MAX_TOOLS,
                                'searches': self.MAX_SEARCHES, 'timeout_seconds': self.timeout_seconds}
        return AgentResult(agent='documentary_agent', output=state.draft_answer or 'Documentary agent abstained.',
                           metadata={'grounded': not state.metadata.get('answer_failure') and not state.metadata.get('clarification_requested'),
                                     'reason': state.metadata.get('answer_failure'), **counts})

    async def _loop(self, state, ledger, observations, counts):
        for _ in range(self.MAX_LLM_CALLS):
            passages, visible = self._visible_passages(ledger)
            allowed = ['clarify', 'abstain']
            if visible:
                allowed.append('answer')
            # Reserve the last decision for an answer, clarification or abstention.
            if counts['llm_calls'] < self.MAX_LLM_CALLS - 1 and counts['tool_calls'] < self.MAX_TOOLS:
                if counts['searches'] < self.MAX_SEARCHES:
                    allowed.append('rechercher')
                    if state.metadata.get('request_mode', 'auto') == 'auto' and getattr(self.tools, 'web_available', False) is True:
                        allowed.append('rechercher_web')
                if any(not key.startswith('web:') for key in ledger):
                    allowed.append('lire_passage')
            budget = {'allowed_actions': allowed,
                      'searches_remaining': self.MAX_SEARCHES - counts['searches'],
                      'tools_remaining': self.MAX_TOOLS - counts['tool_calls'],
                      'llm_calls_including_this_one': self.MAX_LLM_CALLS - counts['llm_calls']}
            counts['llm_calls'] += 1
            if '_team_llm_calls' in state.metadata:
                state.metadata['_team_llm_calls'] += 1
            try:
                action = await self.llm_service.documentary_step(
                    question=state.user_message,
                    history=self._history(state), passages=passages,
                    observations=list(observations), budget=budget,
                )
                if not isinstance(action, DocumentaryAction):
                    action = DocumentaryAction.model_validate(action)
            except (ValidationError, ValueError, TypeError):
                self._fail(state, 'invalid_agent_action')
                return
            except Exception as exc:
                self._fail(state, generation_failure_reason(exc))
                return
            state.record_result(AgentResult(agent='documentary_decision', output=action.action,
                                            metadata=action.model_dump(exclude_none=True, exclude={'text'})))
            if action.action not in allowed:
                self._fail(state, 'no_documents' if action.action == 'answer' and not visible else 'agent_budget_exhausted')
                return
            if action.action == 'answer':
                # External validation sees the exact excerpts used for the final decision.
                state.search_results = visible
                state.reranked_results = visible
                state.metadata['context_document_count'] = len(visible)
                state.compressed_context = json.dumps(passages, ensure_ascii=False)
                body = action.text.split('\n\nSources:', 1)[0].strip()
                source_lines = []
                for index, item in enumerate(visible, 1):
                    location = item.source if (item.document_id or '').startswith('web:') else item.file_name or item.source
                    if item.page_number is not None:
                        location += f", page {item.page_number}"
                    source_lines.append(f"- [{index}] {item.title} ({location})")
                sources = '\n'.join(source_lines)
                state.draft_answer = state.rag_output = f'{body}\n\nSources:\n{sources}'
                return
            if action.action == 'clarify':
                state.metadata['clarification_requested'] = True
                state.draft_answer = action.text
                return
            if action.action == 'abstain':
                failures = [item for item in observations if item['action'] in {'rechercher', 'rechercher_web'}]
                reason = 'insufficient_evidence' if ledger else 'no_documents'
                if failures and all(not item['success'] for item in failures):
                    reason = 'retrieval_unavailable'
                self._fail(state, reason)
                return
            await self._execute(state, action, ledger, observations, counts)
            if state.metadata.get('answer_failure'):
                return
        self._fail(state, 'agent_budget_exhausted')

    async def _execute(self, state, action, ledger, observations, counts):
        counts['tool_calls'] += 1
        observation = {'action': action.action, 'success': False}
        try:
            if action.action in {'rechercher', 'rechercher_web'}:
                counts['searches'] += 1
                if action.action == 'rechercher_web':
                    counts['web_searches'] += 1
                    documents, metrics = await self.tools.rechercher_web(action.query)
                else:
                    documents, metrics = await self.tools.rechercher(
                        action.query, owner_id=state.metadata.get('user_id'), conversation_id=state.conversation_id,
                    )
                # Merge search results by identity; labels belong to the current context.
                for document in documents:
                    key = document.document_id
                    if not key:
                        continue
                    if key not in ledger and len(ledger) < settings.max_rag_documents * 2:
                        ledger[key] = document
                    elif key in ledger and len(ledger[key].snippet) <= 500:
                        # A reformulated query may select a different sentence from the same passage.
                        ledger[key] = document
                observation.update(query=action.query, passage_ids=[item.document_id for item in documents if item.document_id])
                state.retrieval_metrics.setdefault('search_attempts', []).append(metrics)
            else:
                document = await self.tools.lire_passage(action.passage_id, owner_id=state.metadata.get('user_id'),
                                                          allowed_ids={key for key in ledger if not key.startswith('web:')})
                if document.document_id != action.passage_id:
                    raise PermissionError('passage_unavailable')
                ledger[action.passage_id] = document.model_copy(update={'embedding': None})
                observation.update(passage_id=action.passage_id)
            observation['success'] = True
        except PermissionError:
            # Revoked access forbids answering from the earlier in-memory copy.
            self._fail(state, 'passage_unavailable')
            observation['error'] = 'passage_unavailable'
        except ValueError:
            observation['error'] = 'invalid_tool_argument'
        except Exception:
            observation['error'] = 'tool_unavailable'
        observations.append(observation)
        state.tool_results.append(ToolResult(tool=action.action, success=observation['success'],
                                             output=json.dumps(observation, ensure_ascii=False), metadata=observation))

    def _visible_passages(self, ledger):
        """Bound evidence JSON and preserve a verifiable mapping of numeric citation labels."""
        limit = max(1, settings.max_rag_context_chars)
        pairs = list(ledger.items())
        passages = [{'label': i, 'passage_id': key, 'title': item.title[:100],
                     'file_name': (item.file_name or item.source)[:100], 'page': item.page_number,
                     'kind': 'web' if key.startswith('web:') else 'document',
                     'text': item.snippet[:settings.max_ingested_snippet_chars]}
                    for i, (key, item) in enumerate(pairs, 1)]
        while passages and len(json.dumps(passages, ensure_ascii=False)) > limit:
            largest = max(passages, key=lambda item: len(item['text']))
            if largest['text']:
                excess = len(json.dumps(passages, ensure_ascii=False)) - limit
                largest['text'] = largest['text'][:max(0, len(largest['text']) - max(64, excess))]
            else:
                passages.pop()
        # A label without text is not evidence. Rebuild contiguous labels for validation.
        passages = [item for item in passages if item['text'].strip()]
        for index, item in enumerate(passages, 1):
            item['label'] = index
        visible = [ledger[item['passage_id']].model_copy(update={'title': item['title'], 'file_name': item['file_name'], 'snippet': item['text'], 'embedding': None}) for item in passages]
        return passages, visible

    @staticmethod
    def _history(state):
        text = '\n'.join(f"{item.get('role', 'unknown')}: {item.get('content', '')}" for item in state.conversation_context[-10:])
        return text[-4000:]

    @staticmethod
    def _fail(state, reason):
        state.metadata['answer_failure'] = reason
        state.draft_answer = ''
