import json
from unittest.mock import AsyncMock, patch
import test_documentary_agent as helpers
from test_documentary_agent import action
from app.models.chat_models import ChatRequest
from app.config.settings import Settings
import unittest


class TeamTests(unittest.IsolatedAsyncioTestCase):
    def workflow(self, outputs):
        workflow = helpers.DocumentaryAgentTests().workflow([
            action('rechercher', query='télétravail'), action('answer', text='Deux jours [1].')])
        from app.workflows.chat_workflow import ChatWorkflow
        source = workflow
        workflow = ChatWorkflow(memory_service=source.memory_service, search_service=source.search_service,
                                llm_service=source.llm_service, embedding_service=source.embedding_service)
        workflow.documentary_agent.tools = source.documentary_agent.tools
        workflow.llm_service.generate = AsyncMock(side_effect=[json.dumps(item) if isinstance(item, dict) else item for item in [{'objective': 'Vérifier la règle', 'questions': ['Combien de jours ?']}, *outputs]])
        return workflow

    async def test_independent_synthesis_and_review(self):
        w = self.workflow([{'answerable': True, 'text': 'Deux jours de télétravail [1].'},
                           {'approved': True, 'feedback': 'Étaye par le passage.'}])
        response = await w.run(ChatRequest(message='Combien de jours ?', mode='documents'))
        self.assertEqual(response.evaluation['architecture'], 'multi_agent')
        self.assertEqual(response.evaluation['llm_calls'], 5)
        self.assertEqual(response.evaluation['llm_call_budget'], 13)
        self.assertTrue(response.critic_passed)
        self.assertIn('synthesis_agent', response.agents_used)
        self.assertIn('verification_agent', response.agents_used)
        self.assertIn('Deux jours de télétravail', w.llm_service.generate.call_args.kwargs['prompt'])

    async def test_full_first_pass_is_seven_calls(self):
        w = self.workflow([{'answerable': True, 'text': 'Deux jours [1].'}, {'approved': True, 'feedback': 'OK'}])
        w.llm_service.documentary_step.side_effect = [action('rechercher', query='q1'), action('rechercher', query='q2'),
                                                     action('lire_passage', passage_id='p1'), action('answer', text='Deux jours [1].')]
        r = await w.run(ChatRequest(message='Combien ?', mode='documents'))
        self.assertEqual(r.evaluation['llm_calls'], 7)
        self.assertEqual(w.llm_service.generate.await_count, 3)
        self.assertTrue(r.critic_passed)

    async def test_reviewer_can_veto(self):
        w = self.workflow([{'answerable': True, 'text': 'Cinq jours [1].'}, {'approved': False, 'feedback': 'Nombre erroné.'}])
        r = await w.run(ChatRequest(message='Combien ?', mode='documents'))
        self.assertEqual(r.evaluation['answer']['status'], 'abstained')
        self.assertEqual(r.evaluation['answer']['reason'], 'agent_review_rejected')
        self.assertNotIn('Cinq jours', r.answer)

    async def test_local_citations_override_llm_approval(self):
        w = self.workflow([{'answerable': True, 'text': 'Deux jours [99].'}, {'approved': True, 'feedback': 'OK'}])
        r = await w.run(ChatRequest(message='Combien ?', mode='documents'))
        self.assertFalse(r.critic_passed)

    async def test_invalid_review_fails_closed(self):
        w = self.workflow([{'answerable': True, 'text': 'Deux jours [1].'}, {'approved': 'false', 'feedback': 'invalid boolean'}])
        r = await w.run(ChatRequest(message='Combien ?', mode='documents'))
        self.assertEqual(r.evaluation['answer']['reason'], 'agent_stage_failed')

    async def test_synthesis_abstention_skips_review(self):
        w = self.workflow([{'answerable': False, 'text': 'Preuves insuffisantes.'}])
        r = await w.run(ChatRequest(message='Combien ?', mode='documents'))
        self.assertEqual(r.evaluation['answer']['status'], 'abstained')
        self.assertEqual(w.llm_service.generate.await_count, 2)

    async def test_team_timeout(self):
        import asyncio
        w = self.workflow([])
        async def slow(**kwargs):
            await asyncio.sleep(1)
        w.llm_service.generate.side_effect = slow
        with patch('app.agents.documentary_team.settings.documentary_agent_timeout_seconds', 0.02):
            r = await w.run(ChatRequest(message='Combien ?', mode='documents'))
        self.assertEqual(r.evaluation['answer']['reason'], 'agent_timeout')

    def test_huggingface_default(self):
        self.assertEqual(Settings.model_fields['llm_provider'].default, 'huggingface')

    async def test_verifier_requests_research_and_receives_new_evidence(self):
        w = self.workflow([
            {'answerable': True, 'text': 'Deux jours [1].'},
            {'approved': False, 'feedback': 'Vérifier les conditions d’accord.', 'next_step': 'research'},
            {'answerable': True, 'text': 'Deux jours avec accord écrit [1].'},
            {'approved': True, 'feedback': 'Conditions couvertes.'}])
        w.llm_service.documentary_step.side_effect = [action('rechercher', query='jours'), action('answer', text='Deux jours [1].'),
            action('lire_passage', passage_id='p1'), action('answer', text='Deux jours avec accord écrit [1].')]
        r = await w.run(ChatRequest(message='Quelles conditions ?', mode='documents'), user_id='alice')
        self.assertTrue(r.critic_passed)
        self.assertEqual(r.evaluation['documentary_team']['corrections'], 1)
        self.assertEqual(r.evaluation['llm_calls'], 9)
        correction_input = w.llm_service.documentary_step.call_args_list[2].kwargs
        self.assertIn('conditions', str(correction_input['observations']))
        w.documentary_agent.tools.lire_passage.assert_awaited_once_with('p1', owner_id='alice', allowed_ids={'p1'})
        self.assertTrue(any(e['from'] == 'Verifier' and e['to'] == 'Researcher' for e in r.evaluation['collaboration']))

    async def test_revision_reuses_evidence_without_new_research(self):
        w = self.workflow([{'answerable': True, 'text': 'Cinq jours [1].'},
            {'approved': False, 'feedback': 'Corriger cinq en deux.', 'next_step': 'revise'},
            {'answerable': True, 'text': 'Deux jours [1].'}, {'approved': True, 'feedback': 'Corrigé.'}])
        r = await w.run(ChatRequest(message='Combien ?', mode='documents'))
        self.assertTrue(r.critic_passed)
        self.assertEqual(w.documentary_agent.tools.rechercher.await_count, 1)
        self.assertIn('Corriger cinq en deux', w.llm_service.generate.call_args_list[3].kwargs['prompt'])
        self.assertNotIn('Cinq jours', r.answer)

    async def test_synthesis_can_request_missing_evidence(self):
        w = self.workflow([{'answerable': False, 'text': 'Condition manquante.', 'next_step': 'research', 'request': 'Chercher l’accord requis.'},
            {'answerable': True, 'text': 'Accord écrit [1].'}, {'approved': True, 'feedback': 'OK'}])
        w.llm_service.documentary_step.side_effect = [action('rechercher', query='jours'), action('answer', text='Deux jours [1].'),
            action('lire_passage', passage_id='p1'), action('answer', text='Accord écrit [1].')]
        r = await w.run(ChatRequest(message='Quelles conditions ?', mode='documents'))
        self.assertTrue(r.critic_passed)
        self.assertTrue(any(e['from'] == 'Synthesizer' and e['to'] == 'Researcher' for e in r.evaluation['collaboration']))

    async def test_second_correction_is_blocked_at_thirteen_calls(self):
        w = self.workflow([{'answerable': True, 'text': 'Deux jours [1].'},
            {'approved': False, 'feedback': 'Chercher une date.', 'next_step': 'research'},
            {'answerable': True, 'text': 'Deux jours [1].'},
            {'approved': False, 'feedback': 'Chercher encore.', 'next_step': 'research'}])
        one_pass = [action('rechercher', query='q1'), action('rechercher', query='q2'),
                    action('lire_passage', passage_id='p1'), action('answer', text='Deux jours [1].')]
        w.llm_service.documentary_step.side_effect = one_pass + one_pass
        r = await w.run(ChatRequest(message='Combien ?', mode='documents'))
        self.assertEqual(r.evaluation['llm_calls'], 13)
        self.assertEqual(r.evaluation['documentary_team']['searches'], 4)
        self.assertEqual(r.evaluation['documentary_team']['tool_calls'], 6)
        self.assertEqual(r.evaluation['answer']['reason'], 'collaboration_budget_exhausted')
        self.assertEqual(w.llm_service.documentary_step.await_count, 8)

    async def test_invalid_planner_stops_before_research(self):
        w = self.workflow([])
        w.llm_service.generate.side_effect = ['{"objective":"Do it","questions":[],"owner_id":"another-user"}']
        r = await w.run(ChatRequest(message='Recherche', mode='documents'))
        self.assertEqual(r.evaluation['answer']['reason'], 'agent_stage_failed')
        w.documentary_agent.tools.rechercher.assert_not_awaited()
        self.assertEqual(r.evaluation['llm_calls'], 1)
        self.assertEqual(r.evaluation['agent_error']['stage'], 'planner')
        self.assertIn('internal error', r.answer)
        self.assertNotIn('add a relevant document', r.answer)

    async def test_unavailable_model_is_not_reported_as_missing_evidence(self):
        import httpx
        from openai import BadRequestError
        w = self.workflow([])
        w.llm_service.generate.side_effect = BadRequestError(
            'private provider details',
            response=httpx.Response(400, request=httpx.Request('POST', 'https://provider.invalid')),
            body={'code': 'model_not_available'})
        r = await w.run(ChatRequest(message='do you have any argument about Baruch Spinoza'))
        self.assertEqual(r.evaluation['answer']['reason'], 'llm_unavailable')
        self.assertEqual(r.evaluation['agent_error'], {'stage': 'planner', 'error_type': 'BadRequestError'})
        self.assertIn('generation service is unavailable', r.answer)
        self.assertNotIn('private provider details', str(r))
        self.assertEqual(r.evaluation['llm_calls'], 1)
        w.documentary_agent.tools.rechercher.assert_not_awaited()

    async def test_plan_is_transmitted_and_graph_has_explicit_agents(self):
        w = self.workflow([{'answerable': True, 'text': 'Deux jours [1].'}, {'approved': True, 'feedback': 'OK'}])
        r = await w.run(ChatRequest(message='Combien ?', mode='documents'))
        self.assertIn('planning_agent', r.agents_used)
        self.assertIn('Vérifier la règle', str(w.llm_service.documentary_step.call_args_list[0].kwargs['observations']))
        self.assertTrue({'planner', 'researcher', 'synthesizer', 'verifier'} <= set(w.documentary_team.graph.get_graph().nodes))

    async def test_concurrent_collaboration_requests_are_isolated(self):
        import asyncio
        w = self.workflow([])
        async def generate(**kwargs):
            data = json.loads(kwargs['prompt'].split('\nDATA:\n')[1])
            question = data['question']
            if 'planning agent' in kwargs['prompt']:
                return json.dumps({'objective': question, 'questions': [question]})
            if 'synthesis agent' in kwargs['prompt']:
                return json.dumps({'answerable': True, 'text': 'Deux jours [1].'})
            return json.dumps({'approved': True, 'feedback': question})
        async def research(**kwargs):
            await asyncio.sleep(0)
            return action('answer', text='Deux jours [1].') if kwargs['passages'] else action('rechercher', query=kwargs['question'])
        w.llm_service.generate.side_effect = generate
        w.llm_service.documentary_step.side_effect = research
        results = await asyncio.gather(*[w.run(ChatRequest(message=name, mode='documents'), user_id=name) for name in ('alice', 'bob')])
        for name, response in zip(('alice', 'bob'), results):
            self.assertTrue(response.critic_passed)
            self.assertEqual(response.evaluation['collaboration'][0]['message'], name)
            self.assertEqual(response.evaluation['llm_calls'], 5)
