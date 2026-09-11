"""Compare the baseline and collaborative team on identical cases with real providers. Usage: python -m app.evaluation.compare_workflows --cases cases.json --owner-id user@example.com. Without --cases, run functional catalog cases; this is not a factuality score."""
import argparse
import asyncio
import json
from pathlib import Path

from app.evaluation.cases import DEFAULT_EVALUATION_CASES, EvaluationCase
from app.evaluation.evaluator import WorkflowEvaluator
from app.services.embedding_service import HuggingFaceEmbeddingService
from app.services.llm_service import LLMService
from app.services.search_service import SearchService
from app.workflows.chat_workflow import ChatWorkflow


class EvaluationMemory:
    """Ephemeral history: the benchmark does not write Redis conversations."""
    def __init__(self):
        self.messages = {}

    async def get_messages(self, conversation_id, owner_id=None):
        return self.messages.get((owner_id, conversation_id), [])

    async def append_message(self, conversation_id, role, content, owner_id=None):
        self.messages.setdefault((owner_id, conversation_id), []).append({'role': role, 'content': content})


async def compare_workflows(baseline, agent, cases, owner_id=None):
    """Retain answers and execution counters for independent annotation."""
    runs = []
    for index, case in enumerate(cases):
        # Alternate execution order to reduce service warm-up bias.
        strategies = [('baseline', baseline), ('agent', agent)]
        if index % 2:
            strategies.reverse()
        for name, workflow in strategies:
            result = (await WorkflowEvaluator(workflow).run_cases([case], owner_id=owner_id))[0]
            runs.append({'strategy': name, **result})
    summary = {}
    for name in ('baseline', 'agent'):
        group = [run for run in runs if run['strategy'] == name]
        summary[name] = {
            'cases': len(group),
            'contracts_passed': sum(run['metrics']['passed'] for run in group),
            'mean_latency_ms': sum(run['latency_ms'] for run in group) / len(group) if group else 0,
            'total_llm_calls': sum(run['llm_calls'] for run in group),
            'total_documentary_tool_calls': sum(run['documentary_tool_calls'] for run in group),
        }
    return {'factuality_evaluated': False, 'summary': summary, 'runs': runs}


async def main(cases, owner_id):
    search, embedding, llm = SearchService(), HuggingFaceEmbeddingService(), LLMService()
    try:
        if not search.available:
            raise RuntimeError('Atlas unavailable: cannot compare workflows.')
        def build(strategy):
            return ChatWorkflow(memory_service=EvaluationMemory(), search_service=search,
                                embedding_service=embedding, llm_service=llm, strategy=strategy)
        return await compare_workflows(build('baseline'), build('multi_agent'), cases, owner_id)
    finally:
        search.close()
        if llm.client is not None:
            await llm.client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=Path, help='JSON array of EvaluationCase objects.')
    parser.add_argument('--owner-id', help='Owner of the evaluation corpus.')
    args = parser.parse_args()
    cases = [EvaluationCase(**item) for item in json.loads(args.cases.read_text())] if args.cases else DEFAULT_EVALUATION_CASES
    print(json.dumps(asyncio.run(main(cases, args.owner_id)), indent=2, ensure_ascii=False))
