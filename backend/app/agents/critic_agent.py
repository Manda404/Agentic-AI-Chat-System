"""Validation locale de contrat ; aucun score de factualité n'est inventé."""
from app.models.chat_models import AgentResult
from app.state import GraphState


class CriticAgent:
    async def run(self, state: GraphState) -> AgentResult:
        issues = []
        if not (state.draft_answer or '').strip():
            issues.append('No answer was generated.')
        failure = state.metadata.get('answer_failure')
        if failure:
            issues.append(f'Answer unavailable: {failure}.')
        if state.route == 'rag' and not state.metadata.get('clarification_requested'):
            if not state.selected_documents:
                issues.append('No documentary evidence available.')
            if not state.evaluation.get('citation_validation', {}).get('passed', False):
                issues.append('Citations are missing or invalid.')
        if any(not result.success for result in state.tool_results if result.tool not in {"rechercher", "rechercher_web", "lire_passage"}):
            issues.append('A required tool failed.')
        state.critic_passed = not issues
        state.critic_score = None
        state.critic_feedback = 'Local checks passed; factual accuracy is not measured.' if not issues else ' '.join(issues)
        state.evaluation['critic'] = {'source': 'local', 'passed': state.critic_passed, 'issues': issues, 'factuality_evaluated': False}
        return AgentResult(agent='critic', output=state.critic_feedback, metadata=state.evaluation['critic'])
