import unittest
from unittest.mock import patch

from app.config.settings import settings
from app.services.llm_service import LLMService, ModelCapability


class ModelConfigurationTests(unittest.TestCase):
    def test_ollama_uses_local_client_and_model_without_huggingface_key(self):
        with patch.object(settings, 'llm_provider', 'ollama'), patch.object(settings, 'huggingface_api_key', ''), patch.object(settings, 'ollama_base_url', 'http://localhost:11434/'), patch.object(settings, 'ollama_model', 'installed-local-model'), patch('app.services.llm_service.AsyncOpenAI') as client:
            service = LLMService()
            self.assertEqual(client.call_args.kwargs['base_url'], 'http://localhost:11434/v1')
            self.assertEqual(client.call_args.kwargs['max_retries'], 0)
            self.assertEqual(service.get_model_for_capability(ModelCapability.SUMMARIZATION), 'installed-local-model')

    def test_huggingface_defaults_to_one_configured_model(self):
        with patch.object(settings, 'llm_provider', 'huggingface'), patch.object(settings, 'huggingface_api_key', 'test'), patch.object(settings, 'huggingface_model', 'configured-model'), patch.object(settings, 'model_summarization', ''), patch.object(settings, 'model_question_answering', ''), patch('app.services.llm_service.AsyncOpenAI') as client:
            service = LLMService()
            self.assertEqual(client.call_args.kwargs['base_url'], 'https://router.huggingface.co/v1')
            for capability in (ModelCapability.SUMMARIZATION, ModelCapability.QUESTION_ANSWERING):
                self.assertEqual(service.get_model_for_capability(capability), 'configured-model')

    def test_explicit_capability_override_is_preserved(self):
        with patch.object(settings, 'llm_provider', 'huggingface'), patch.object(settings, 'huggingface_api_key', ''), patch.object(settings, 'model_question_answering', 'explicit-qa'):
            service = LLMService()
            self.assertEqual(service.get_model_for_capability(ModelCapability.QUESTION_ANSWERING), 'explicit-qa')
