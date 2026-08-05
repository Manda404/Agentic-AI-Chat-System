"""
Templates de prompts centralisés pour tous les appels au LLM.

Tous les prompts envoyés au LLM (routage, résumé, réponse groundée,
génération de code...) sont définis ICI, dans une seule classe statique.
C'est volontaire : si tu veux changer le ton, les instructions ou le
format attendu des réponses du LLM, c'est le seul fichier à modifier,
sans avoir à toucher aux agents ou au workflow qui les appellent.
"""
from typing import Dict


class LLMPrompts:
    """
    Collection of prompt templates for different LLM capabilities.
    """
    
    @staticmethod
    
    
    def summarization(text: str, context: str = "") -> str:
        return f"""You are answering a user's question using retrieved business documents.

Question:
{text}

Conversation context:
{context}

Instructions:
- Give the direct answer first, not a meta-summary of the question.
- If the answer contains a numeric value, include the exact value.
- Keep the answer concise and factual.
- Do not say phrases like "The user is asking..." or "This question is about...".
- If the answer is not fully certain, say what is supported by the available data only.

Answer:"""
                
    @staticmethod
    def code_generation(description: str, language: str = "python") -> str:
        """
        Prompt template for code generation
        """
        return f"""Generate {language} code for the following task:

                     {description}

                      Code:"""
                      
    @staticmethod
    def question_answering(question: str, context: str = "") -> str:
        """
        Prompt template for question answering
        """
        return f"""Answer the following question based on the context provided:

                  Context: {context}
                  Question: {question}

                  Answer:"""
                  
    @staticmethod
    def reasoning(problem: str) -> str:
        """
        Prompt template for complex reasoning tasks
        """
        return f"""Solve the following problem step by step:

                      {problem}

                  Solution:"""
                  
    @staticmethod
    def chat_summary(user_message: str, conversation_history: str = "") -> str:
        """
        Prompt template for chat-based summarization with conversation context
        """
        history_section = f"\nConversation History:\n{conversation_history}\n" if conversation_history else ""

        return f"""You are a helpful AI assistant. Provide a clear and informative response to the user's question.
                {history_section}
            User Question: {user_message}

            Your Response:"""

    @staticmethod
    def grounded_answer(
        user_message: str,
        retrieved_documents: str,
        conversation_history: str = "",
    ) -> str:
        history_section = (
            f"\nConversation History:\n{conversation_history}\n"
            if conversation_history
            else ""
        )

        return f"""You are a helpful AI assistant answering strictly from retrieved documents and prior conversation context.

User Question:
{user_message}

Retrieved Documents:
{retrieved_documents}
{history_section}
Instructions:
- First understand the retrieved documents.
- Then use the conversation history only as supporting context.
- Answer the user's question directly and clearly.
- Do not say meta phrases like "the user is asking" or "based on the query".
- If the documents contain the exact value, return it explicitly.
- Keep the final answer concise but complete.
- If the documents do not contain enough information, say that clearly.

Final Answer:"""

    @staticmethod
    def planner(user_message: str, conversation_history: str = "") -> str:
        return f"""You are a production-grade planner for a LangGraph multi-agent chat system.

Return ONLY valid JSON matching this schema:
{{
  "intent": "greeting | direct_answer | document_qa | summarization | analysis | correction | planning | unknown",
  "requires_retrieval": true,
  "requires_rag": true,
  "requires_critic": true,
  "requires_safety": true,
  "steps": ["load_memory", "search_documents", "rerank_results", "generate_grounded_answer", "critic_review", "safety_review", "final_answer"],
  "tools": ["memory", "search", "reranker", "rag", "critic", "safety"],
  "reason": "short explanation"
}}

User message:
{user_message}

Conversation history:
{conversation_history}

Planning rules:
- Use "greeting" for simple greetings.
- Use "document_qa" when indexed documents are likely needed.
- Use "direct_answer" when a general LLM answer is enough.
- Use "summarization" for summarize requests.
- Use "correction" for review/fix/validate requests.
- Use "planning" for roadmap/steps/plan requests.
- Keep tools minimal.

JSON:"""

    @staticmethod
    def critic_review(
        user_message: str,
        draft_answer: str,
        sources: str = "",
    ) -> str:
        return f"""You are a strict but practical quality critic for a RAG/chat answer.

Return ONLY valid JSON matching this schema:
{{
  "passed": true,
  "score": 0.0,
  "groundedness_score": 0.0,
  "relevance_score": 0.0,
  "clarity_score": 0.0,
  "issues": [],
  "recommendation": "accept | revise | retrieve_more | fallback",
  "feedback": "short explanation"
}}

User question:
{user_message}

Draft answer:
{draft_answer}

Available sources:
{sources}

Review rules:
- If sources are provided, penalize unsupported claims.
- Prefer accept only when the answer is relevant, clear, and grounded.
- Use retrieve_more when the answer needs documents but sources are weak.

JSON:"""

    @staticmethod
    def safety_review(answer: str) -> str:
        return f"""You are a lightweight production safety guard.

Return ONLY valid JSON matching this schema:
{{
  "passed": true,
  "issues": [],
  "redacted": false,
  "feedback": "No safety issue detected."
}}

Answer to review:
{answer}

Safety rules:
- Flag exposed API keys, bearer tokens, passwords, private keys, or .env secrets.
- Flag stack traces or internal infrastructure details if they leak sensitive data.
- Do not be overly restrictive for normal technical explanations.

JSON:"""

    @staticmethod
    def compress_context(user_message: str, documents: str, max_chars: int = 4000) -> str:
        return f"""Compress retrieved document snippets for a RAG answer.

User question:
{user_message}

Documents:
{documents}

Instructions:
- Keep only passages useful for answering the user question.
- Preserve source labels and page/file hints.
- Do not invent facts.
- Stay under {max_chars} characters.

Compressed context:"""
            
    @staticmethod
    def get_all_templates() -> Dict[str, str]:
      
        return {
            "summarization": "Summarize text concisely with optional context",
            "code_generation": "Generate code in specified programming language",
            "question_answering": "Answer questions based on provided context",
            "reasoning": "Solve complex problems with step-by-step reasoning",
            "chat_summary": "Generate conversational responses with history awareness",
        }
        
    @staticmethod
    def custom_prompt(template: str, **kwargs) -> str:
        """
        Create a custom prompt from a template string with variable substitution
        
        Args:
            template: Template string with {variable} placeholders
            **kwargs: Variables to substitute in the template
            
        Returns:
            Formatted prompt string
            
        Example:
            >>> template = "Translate {text} to {language}"
            >>> LLMPrompts.custom_prompt(template, text="Hello", language="French")
            'Translate Hello to French'
        """
        return template.format(**kwargs)
