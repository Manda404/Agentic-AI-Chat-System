"""Publication du brouillon validé ou abstention explicite, sans régénération."""
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
                state.final_answer = 'Je ne trouve pas de passage exploitable dans les documents indexés. Précisez la question ou ajoutez un document pertinent.'
            elif reason == 'retrieval_unavailable':
                state.final_answer = 'La recherche documentaire est indisponible. Veuillez réessayer plus tard.'
            elif reason == 'agent_timeout':
                state.final_answer = 'La recherche a dépassé le temps autorisé. Précisez la question ou réessayez plus tard.'
            elif reason == 'passage_unavailable':
                state.final_answer = 'Un passage consulté n’est plus accessible. Je ne peux pas m’appuyer sur son contenu.'
            elif reason == 'agent_budget_exhausted':
                state.final_answer = 'Je n’ai pas pu établir une réponse vérifiable dans la limite de recherches autorisée. Pouvez-vous préciser la question ?'
            elif reason == 'invalid_agent_action':
                state.final_answer = 'Le modèle n’a pas produit une action exploitable. Veuillez réessayer.'
            elif reason == 'llm_unavailable':
                state.final_answer = 'Le service de génération est indisponible. Veuillez réessayer plus tard.'
            elif state.route in {'calculation', 'document_list'}:
                state.final_answer = state.draft_answer or 'Cet outil est momentanément indisponible.'
            else:
                state.final_answer = 'Je ne peux pas fournir une réponse vérifiable à partir de ces éléments. Précisez la question ou ajoutez un document pertinent.'
            status = 'abstained'
        state.evaluation['answer'] = {'status': status, 'reason': state.metadata.get('answer_failure') or ('validation_failed' if status == 'abstained' else None)}
        return AgentResult(agent='final_answer', output=state.final_answer, metadata=state.evaluation['answer'])
