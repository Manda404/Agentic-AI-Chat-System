"""LLM access through Hugging Face Router or the optional Ollama-compatible interface. Choose the configured model with optional MODEL_* capability overrides. AsyncOpenAI avoids blocking the event loop during provider requests. Optional Langfuse decorators trace calls when enabled and otherwise leave execution unchanged."""

import json
import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Type, TypeVar
from enum import Enum
from openai import AsyncOpenAI
from app.prompts import LLMPrompts
from app.config.settings import settings
from app.logger import logger
from app.models.chat_models import CorrectiveRAGReview, CriticReview, PlannerDecision, SafetyReview
from pydantic import BaseModel, ValidationError

if settings.langfuse_enabled:
    try:
        from langfuse import observe
    except ImportError:
        def observe(*args,**kwargs):
            def decorator(func):
                return func
            return decorator if args and callable(args[0]) else decorator
else:
     def observe(*args, **kwargs):
        def decorator(func):
            return func
        return decorator if args and callable(args[0]) else decorator

class ModelCapability(Enum):
    """Define unique capabilities for different models"""
    SUMMARIZATION = "summarization"
    CODE_GENERATION = "code_generation"
    REASONING = "reasoning"
    QUESTION_ANSWERING = "question_answering"
    
    
TModel = TypeVar("TModel", bound=BaseModel)

def generation_failure_reason(exc: Exception) -> str:
    """Classify billing failures without exposing provider response bodies."""
    from openai import APIStatusError
    if isinstance(exc, APIStatusError) and exc.status_code == 402:
        if 'depleted your monthly included credits' in str(exc.body).lower():
            return 'llm_credits_exhausted'
        return 'llm_payment_required'
    return 'llm_unavailable'
    
class LLMService:
    """
    LLM Service using HuggingFace Router with OpenAI-compatible API
    Uses one configured model, with optional capability overrides
    """
    
    def __init__(self):
        self.client = None
        self.last_call_status = 'unverified'
        self.last_call_at = None
        self.last_call_reason = None
        self.langfuse_enabled = settings.langfuse_enabled
        self._initialize_client()
        
    def _initialize_client(self):
        """Create the asynchronous provider client. Hugging Face requires a configured API key; Ollama uses its configured local endpoint. Avoid synchronous HTTP calls in async graph nodes."""

        if settings.llm_provider == "ollama":
            self.client = AsyncOpenAI(
                base_url=settings.ollama_base_url.rstrip("/") + "/v1",
                api_key="ollama",
                timeout=settings.llm_timeout_seconds,
                max_retries=0,
            )
        elif settings.huggingface_api_key:
            self.client = AsyncOpenAI(
                base_url="https://router.huggingface.co/v1",
                api_key=settings.huggingface_api_key,
                timeout=settings.llm_timeout_seconds,
                max_retries=0,
            )
        else:
            logger.warning("HUGGINGFACE_API_KEY is not configured.")

    async def check_availability(self):
        """One bounded startup probe, without user data or document content."""
        self.last_call_status = 'checking'
        try:
            async with asyncio.timeout(10):
                await self.generate(prompt='Reply OK.', max_tokens=1, temperature=0.0,
                                    capability=ModelCapability.QUESTION_ANSWERING)
        except Exception as exc:
            self.last_call_status = 'offline'
            self.last_call_reason = generation_failure_reason(exc)
            self.last_call_at = datetime.now(timezone.utc).isoformat()

    def get_model_for_capability(self, capability: ModelCapability) -> str:
        """Use the explicit Hugging Face capability override or HUGGINGFACE_MODEL. The optional Ollama backend uses OLLAMA_MODEL."""
        if settings.llm_provider == "ollama":
            return settings.ollama_model
        capability_models = {
            ModelCapability.SUMMARIZATION: settings.model_summarization,
            ModelCapability.CODE_GENERATION: settings.model_code_generation,
            ModelCapability.QUESTION_ANSWERING: settings.model_question_answering,
            ModelCapability.REASONING: settings.model_reasoning,
        }
        
        custom_model = capability_models.get(capability)
        if custom_model:
            logger.info(f"Using custom model for {capability.value}: {custom_model}")
            return custom_model
        
        # One configured general model with capability overrides only when needed.
        return settings.huggingface_model

    @observe(name="llm_generate")
    async def generate(
        self,
        prompt:str,
        model: Optional[str] = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        capability: Optional[ModelCapability] = None,
        ) -> str:
        
        """Send a formatted prompt and return generated text, or an empty string for empty content. An explicit model overrides capability-based selection; max_tokens and temperature control generation. Higher-level operations build prompts then delegate here."""

        if not self.client:
            self.last_call_status = 'offline'
            self.last_call_reason = 'llm_unavailable'
            self.last_call_at = datetime.now(timezone.utc).isoformat()
            raise RuntimeError("LLM client unavailable. Check LLM_PROVIDER and its configuration.")

        if not model and capability:
            model = self.get_model_for_capability(capability)
        elif not model:
            model = self.get_model_for_capability(ModelCapability.QUESTION_ANSWERING)

        logger.bind(model=model, temperature=temperature, max_tokens=max_tokens).info(
            "Generating with HuggingFace Router"
        )
        
        try:
          completion = await self.client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_tokens=max_tokens,
                temperature=temperature,
          )
          
          response = completion.choices[0].message.content or ""
          self.last_call_status = 'online'
          self.last_call_reason = None
          self.last_call_at = datetime.now(timezone.utc).isoformat()
          logger.info(f"Generated {len(response)} characters")
            
          return response
        except Exception as e:
            self.last_call_status = 'offline'
            self.last_call_reason = generation_failure_reason(e)
            self.last_call_at = datetime.now(timezone.utc).isoformat()
            logger.error(f"Error generating with HuggingFace Router: {e}")
            raise
        
    async def summarize(self,text:str,context:str="") -> str:
        """Summarize text using the configured model"""
        prompt = LLMPrompts.summarization(text=text, context=context)
        
        return await self.generate(
            prompt=prompt,
            capability=ModelCapability.SUMMARIZATION,
            max_tokens=1024,
            temperature=0.5,
        )
        
    async def generate_code(self, description: str, language: str = "python") -> str:
        """Generate code using the configured model"""
        prompt = LLMPrompts.code_generation(description=description, language=language)
        
        return await self.generate(
            prompt=prompt,
            capability=ModelCapability.CODE_GENERATION,
            max_tokens=2048,
            temperature=0.2,
        )

    async def answer_question(self, question: str, context: str = "") -> str:
        """Answer using the configured model"""
        prompt = LLMPrompts.question_answering(question=question, context=context)
        
        return await self.generate(
            prompt=prompt,
            capability=ModelCapability.QUESTION_ANSWERING,
            max_tokens=1024,
            temperature=0.7,
        )

    async def grounded_answer(
        self,
        question: str,
        retrieved_documents: str,
        conversation_history: str = "",
    ) -> str:
        """Answer a question from retrieved documents with conversation context."""
        prompt = LLMPrompts.grounded_answer(
            user_message=question,
            retrieved_documents=retrieved_documents,
            conversation_history=conversation_history,
        )

        return await self.generate(
            prompt=prompt,
            capability=ModelCapability.QUESTION_ANSWERING,
            max_tokens=1024,
            temperature=0.2,
        )

    async def documentary_step(self, question, history, passages, observations, budget):
        """Generate one action or answer per call and validate it before execution."""
        from app.models.documentary_models import DocumentaryAction
        from app.prompts.documentary_prompt import documentary_prompt

        raw = await self.generate(
            prompt=documentary_prompt(question, history, passages, observations, budget),
            capability=ModelCapability.QUESTION_ANSWERING,
            max_tokens=1800,
            temperature=0.0,
        )
        return DocumentaryAction.model_validate_json(raw)

    async def plan(
        self,
        user_message: str,
        conversation_history: str = "",
    ) -> PlannerDecision:
        """Generate a validated JSON plan for the experimental workflow."""
        prompt = LLMPrompts.planner(
            user_message=user_message,
            conversation_history=conversation_history,
        )
        raw = await self.generate(
            prompt=prompt,
            capability=ModelCapability.REASONING,
            max_tokens=700,
            temperature=0.0,
        )
        return self._parse_json_model(raw, PlannerDecision)

    async def critic_review(
        self,
        user_message: str,
        draft_answer: str,
        sources: str = "",
    ) -> CriticReview:
        """Assess a candidate answer using a validated JSON schema."""
        prompt = LLMPrompts.critic_review(
            user_message=user_message,
            draft_answer=draft_answer,
            sources=sources,
        )
        raw = await self.generate(
            prompt=prompt,
            capability=ModelCapability.REASONING,
            max_tokens=700,
            temperature=0.0,
        )
        return self._parse_json_model(raw, CriticReview)

    async def corrective_rag_review(
        self,
        user_message: str,
        documents: str,
    ) -> CorrectiveRAGReview:
        """Assess retrieved documents and propose a query correction when needed."""
        prompt = LLMPrompts.corrective_rag_review(
            user_message=user_message,
            documents=documents,
        )
        raw = await self.generate(
            prompt=prompt,
            capability=ModelCapability.REASONING,
            max_tokens=900,
            temperature=0.0,
        )
        return self._parse_json_model(raw, CorrectiveRAGReview)

    async def safety_review(self, answer: str) -> SafetyReview:
        """Review an answer using the JSON safety contract."""
        prompt = LLMPrompts.safety_review(answer=answer)
        raw = await self.generate(
            prompt=prompt,
            capability=ModelCapability.QUESTION_ANSWERING,
            max_tokens=400,
            temperature=0.0,
        )
        return self._parse_json_model(raw, SafetyReview)

    async def compress_context(self, user_message: str, documents: str, max_chars: int = 4000) -> str:
        """Compress documentary context before grounded generation."""
        prompt = LLMPrompts.compress_context(
            user_message=user_message,
            documents=documents,
            max_chars=max_chars,
        )
        return await self.generate(
            prompt=prompt,
            capability=ModelCapability.SUMMARIZATION,
            max_tokens=900,
            temperature=0.0,
        )

    async def rerank_with_llm(self, user_message: str, documents: str) -> str:
        """Extension point for future LLM or cross-encoder reranking."""
        prompt = LLMPrompts.rerank(user_message=user_message, documents=documents)
        return await self.generate(
            prompt=prompt,
            capability=ModelCapability.REASONING,
            max_tokens=300,
            temperature=0.0,
        )

    async def reason(self, problem: str) -> str:
        """Reason using the configured model"""
        prompt = LLMPrompts.reasoning(problem=problem)
        
        return await self.generate(
            prompt=prompt,
            capability=ModelCapability.REASONING,
            max_tokens=2048,
            temperature=0.7,
        )

    def _parse_json_model(self, raw: str, model: Type[TModel]) -> TModel:
        """Parse legacy LLM JSON even when surrounded by other text."""
        text = raw.strip()
        try:
            return model.model_validate_json(text)
        except ValidationError:
            pass

        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                payload: Dict[str, Any] = json.loads(text[start : end + 1])
                return model.model_validate(payload)
            except (json.JSONDecodeError, ValidationError) as exc:
                logger.bind(model=model.__name__, reason=str(exc)).warning(
                    "Structured LLM JSON parsing failed."
                )
        raise ValueError(f"LLM did not return valid {model.__name__} JSON.")
