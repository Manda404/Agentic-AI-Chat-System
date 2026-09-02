import unittest

from app.agents.llm_planner_agent import LLMPlannerAgent
from app.prompts import LLMPrompts
from app.state import GraphState


class PromptContractTests(unittest.TestCase):
    def test_every_declared_prompt_has_a_description(self):
        expected = {
            "summarization", "code_generation", "question_answering", "reasoning",
            "chat_summary", "grounded_answer", "planner", "critic_review",
            "corrective_rag_review", "safety_review", "compress_context", "rerank",
        }
        self.assertEqual(set(LLMPrompts.get_all_templates()), expected)

    def test_structured_prompts_require_json_only(self):
        planner = LLMPrompts.planner("question", "history")
        critic = LLMPrompts.critic_review("question", "answer", "sources")
        corrective_rag = LLMPrompts.corrective_rag_review("question", "[1] evidence")
        safety = LLMPrompts.safety_review("answer")

        for prompt in (planner, critic, corrective_rag, safety):
            self.assertIn("valid JSON", prompt)
            self.assertIn("text outside", prompt.lower())

    def test_document_summary_uses_rag_in_planner_fallback(self):
        state = GraphState(
            conversation_id="test",
            user_message="Summarize the indexed documents",
        )
        decision = LLMPlannerAgent(None)._fallback_decision(state)  # type: ignore[arg-type]

        self.assertEqual(decision.intent, "document_qa")
        self.assertTrue(decision.requires_retrieval)
        self.assertTrue(decision.requires_rag)

    def test_compressor_and_reranker_cannot_answer_the_question(self):
        compressor = LLMPrompts.compress_context("question", "[1] evidence", 1000)
        reranker = LLMPrompts.rerank("question", "[1] evidence")

        self.assertIn("do not answer the question", compressor.lower())
        self.assertIn("answer the question", reranker.lower())
        self.assertIn("one label per line", reranker)


if __name__ == "__main__":
    unittest.main()
