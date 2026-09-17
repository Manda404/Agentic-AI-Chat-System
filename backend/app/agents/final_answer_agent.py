"""Publish a validated draft or explicit abstention without regeneration."""
from app.models.chat_models import AgentResult
from app.state import GraphState


class FinalAnswerAgent:
    async def run(self, state: GraphState) -> AgentResult:
        if state.critic_passed:
            state.final_answer = state.draft_answer or ''
            status = 'clarification_requested' if state.metadata.get('clarification_requested') else 'answered'
        else:
            reason = state.metadata.get('answer_failure')
            if reason == 'no_documents':
                state.final_answer = 'I could not find a usable passage in the indexed documents. Clarify your question or add a relevant document.'
            elif reason == 'retrieval_unavailable':
                state.final_answer = 'Document search is unavailable. Please try again later.'
            elif reason == 'agent_timeout':
                state.final_answer = 'Research exceeded the time limit. Clarify your question or try again later.'
            elif reason == 'passage_unavailable':
                state.final_answer = 'A retrieved passage is no longer accessible. I cannot use its content as evidence.'
            elif reason == 'agent_budget_exhausted':
                state.final_answer = 'I could not establish a verifiable answer within the search budget. Could you clarify your question?'
            elif reason == 'invalid_agent_action':
                state.final_answer = 'The model did not produce a valid action. Please try again.'
            elif reason == 'llm_unavailable':
                state.final_answer = 'The generation service is unavailable. Please try again later.'
            elif reason == 'llm_payment_required':
                state.final_answer = 'The model provider requires credits or a billing update before it can answer. Update the provider account or configure another model provider.'
            elif reason == 'llm_credits_exhausted':
                state.final_answer = 'The model provider reports that your monthly credits are exhausted. Add credits to the provider account or configure another provider to resume answers. Your indexed documents are still available.'
            elif reason == 'agent_stage_failed':
                state.final_answer = 'An internal error interrupted the research. Please try again.'
            elif state.route in {'calculation', 'document_list'}:
                state.final_answer = state.draft_answer or 'This tool is temporarily unavailable.'
            else:
                state.final_answer = 'I cannot provide a verifiable answer from this evidence. Clarify your question or add a relevant document.'
            status = 'abstained'
        state.evaluation['answer'] = {'status': status, 'reason': state.metadata.get('answer_failure') or ('validation_failed' if status == 'abstained' else None)}
        return AgentResult(agent='final_answer', output=state.final_answer, metadata=state.evaluation['answer'])
