"""
Service d'accès au LLM, via le "HuggingFace Router" (API compatible OpenAI).

Le router HuggingFace redirige un même client OpenAI vers différents
modèles hébergés sur HuggingFace, selon le nom de modèle demandé. Ce
service choisit automatiquement le modèle le plus adapté à la tâche
(`ModelCapability`) : résumé/raisonnement, génération de code, ou
question-réponse — chacun surchageable via les variables d'environnement
`MODEL_SUMMARIZATION`, `MODEL_CODE_GENERATION`, etc.

Si Langfuse est activé (`LANGFUSE_ENABLED=true`), chaque appel notable
est tracé (`@observe`) pour analyser prompts/réponses/latences a
posteriori dans le dashboard Langfuse. Sinon, `@observe` devient un
décorateur transparent qui ne change rien au comportement.
"""

import json
from typing import Any, Dict, List, Optional, Type, TypeVar
from enum import Enum
from openai import AsyncOpenAI
from app.prompts import LLMPrompts
from app.config.settings import settings
from app.logger import logger
from app.models.chat_models import CriticReview, PlannerDecision, SafetyReview
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
    
    
class ModelConfig:
    """Configuration for top 4 HuggingFace Router models"""
    
    MODELS = {
        "deepseek-ai/DeepSeek-V4-Pro":{
            "capabilities": [ModelCapability.REASONING, ModelCapability.SUMMARIZATION],
            "max_tokens": 4096,
            "temperature": 0.7,
            "best_for": "Complex reasoning, analysis, and summarization",
            "size": "862B"
        },
        
        "Qwen/Qwen2.5-Coder-7B-Instruct": {
            "capabilities": [ModelCapability.CODE_GENERATION],
            "max_tokens": 8192,
            "temperature": 0.2,
            "best_for": "Code generation and programming tasks",
            "size": "8B"
        },
        
         "meta-llama/Llama-3.2-3B-Instruct": {
            "capabilities": [ModelCapability.QUESTION_ANSWERING],
            "max_tokens": 2048,
            "temperature": 0.7,
            "best_for": "Fast Q&A and simple tasks",
            "size": "3B"
        },
         
        "meta-llama/Llama-3.1-8B-Instruct": {
            "capabilities": [ModelCapability.SUMMARIZATION, ModelCapability.QUESTION_ANSWERING],
            "max_tokens": 4096,
            "temperature": 0.7,
            "best_for": "General purpose tasks and Q&A",
            "size": "8B"
        },
    }


TModel = TypeVar("TModel", bound=BaseModel)
    
class LLMService:
    """
    LLM Service using HuggingFace Router with OpenAI-compatible API
    Uses 4 specialized models for different tasks
    """
    
    def __init__(self):
        self.client = None
        self.langfuse_enabled = settings.langfuse_enabled
        self._initialize_client()
        
    def _initialize_client(self):
        """Crée le client OpenAI asynchrone pointé vers le HuggingFace Router (si une clé API est configurée).

        Le client OFFICIEL asynchrone (`AsyncOpenAI`) est utilisé plutôt que
        `OpenAI` : `generate()` est une méthode `async def` appelée depuis des
        agents async eux-mêmes appelés par LangGraph — un client synchrone
        bloquerait l'event loop pendant tout l'appel HTTP (jusqu'à
        `LLM_TIMEOUT_SECONDS`), gelant toutes les autres requêtes en cours
        sur le même worker.
        """

        if not settings.huggingface_api_key:
            logger.warning("HuggingFace API key not configured")
            return

        # Initialize async OpenAI client (ne bloque pas l'event loop)
        self.client = AsyncOpenAI(
            base_url="https://router.huggingface.co/v1",
            api_key=settings.huggingface_api_key,
            timeout=settings.llm_timeout_seconds,
        )
        
        if self.langfuse_enabled:
            logger.info("HuggingFace Router client initialized with Langfuse tracing enabled")
        else:
            logger.info("HuggingFace Router client initialized (Langfuse disabled)")
            
    def get_model_for_capability(self, capability: ModelCapability) -> str:
        """
        Choisit le nom de modèle HuggingFace à utiliser pour une capacité donnée
        (résumé, code, Q&A, raisonnement) : d'abord la variable d'environnement
        dédiée si elle est définie, sinon un modèle par défaut codé en dur.
        """
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
        
        default_models = {
            ModelCapability.SUMMARIZATION: "deepseek-ai/DeepSeek-V4-Pro",
            ModelCapability.CODE_GENERATION: "Qwen/Qwen2.5-Coder-7B-Instruct",
            ModelCapability.QUESTION_ANSWERING: "meta-llama/Llama-3.2-3B-Instruct",
            ModelCapability.REASONING: "deepseek-ai/DeepSeek-V4-Pro",
        }
        
        model = default_models.get(capability, "meta-llama/Llama-3.1-8B-Instruct")
        logger.info(f"Using default model for {capability.value}: {model}")
        return model
    
    
    @observe(name="llm_generate")
    async def generate(
        self,
        prompt:str,
        model: Optional[str] = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        capability: Optional[ModelCapability] = None,
        ) -> str:
        
        """
        Point d'entrée bas niveau : envoie un prompt au LLM et retourne le texte généré.
        Toutes les autres méthodes (summarize, answer_question, grounded_answer,
        reason, generate_code) passent par ici après avoir construit leur prompt.

        Args:
            prompt: Le prompt final déjà formaté (voir `app.prompts.LLMPrompts`)
            model: Nom de modèle explicite (prioritaire sur `capability`)
            max_tokens: Nombre maximum de tokens générés
            temperature: Température d'échantillonnage (0 = déterministe)
            capability: Capacité utilisée pour sélectionner un modèle automatiquement

        Returns:
            Le texte généré par le modèle (chaîne vide si la réponse est vide)
        """

        if not self.client:
            raise RuntimeError("HuggingFace Router client not initialized. Check HF_TOKEN.")

        if not model and capability:
            model = self.get_model_for_capability(capability)
        elif not model:
            model = "meta-llama/Llama-3.1-8B-Instruct"

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
          logger.info(f"Generated {len(response)} characters")
            
          return response
        except Exception as e:
            logger.error(f"Error generating with HuggingFace Router: {e}")
            raise
        
    async def summarize(self,text:str,context:str="") -> str:
        """Summarize text using DeepSeek-V4-Pro (best for reasoning/summarization)"""
        prompt = LLMPrompts.summarization(text=text, context=context)
        
        return await self.generate(
            prompt=prompt,
            capability=ModelCapability.SUMMARIZATION,
            max_tokens=1024,
            temperature=0.5,
        )
        
    async def generate_code(self, description: str, language: str = "python") -> str:
        """Generate code using Qwen2.5-Coder (best for code generation)"""
        prompt = LLMPrompts.code_generation(description=description, language=language)
        
        return await self.generate(
            prompt=prompt,
            capability=ModelCapability.CODE_GENERATION,
            max_tokens=2048,
            temperature=0.2,
        )

    async def answer_question(self, question: str, context: str = "") -> str:
        """Answer a question using Llama-3.2-3B (fast Q&A)"""
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

    async def plan(
        self,
        user_message: str,
        conversation_history: str = "",
    ) -> PlannerDecision:
        """Produit un plan JSON validé pour le workflow agentique."""
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
        """Évalue une réponse provisoire avec un format JSON validé."""
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

    async def safety_review(self, answer: str) -> SafetyReview:
        """Passe une réponse dans un garde-fou sécurité JSON."""
        prompt = LLMPrompts.safety_review(answer=answer)
        raw = await self.generate(
            prompt=prompt,
            capability=ModelCapability.QUESTION_ANSWERING,
            max_tokens=400,
            temperature=0.0,
        )
        return self._parse_json_model(raw, SafetyReview)

    async def compress_context(self, user_message: str, documents: str, max_chars: int = 4000) -> str:
        """Compresse un contexte documentaire avant génération RAG."""
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
        """Point d'extension pour un futur reranking LLM/cross-encoder."""
        prompt = (
            "Rank these documents for the user question. Return the best source labels only.\n\n"
            f"Question:\n{user_message}\n\nDocuments:\n{documents}"
        )
        return await self.generate(
            prompt=prompt,
            capability=ModelCapability.REASONING,
            max_tokens=300,
            temperature=0.0,
        )

    async def reason(self, problem: str) -> str:
        """Solve a complex reasoning problem using DeepSeek-V4-Pro"""
        prompt = LLMPrompts.reasoning(problem=problem)
        
        return await self.generate(
            prompt=prompt,
            capability=ModelCapability.REASONING,
            max_tokens=2048,
            temperature=0.7,
        )

    def _parse_json_model(self, raw: str, model: Type[TModel]) -> TModel:
        """Parse un JSON LLM même si le modèle entoure la réponse de texte."""
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

    def list_available_models(self) -> List[Dict]:
        """List all 4 available models with their capabilities"""
        return [
            {
                "name": name,
                "capabilities": [cap.value for cap in config["capabilities"]],
                "best_for": config["best_for"],
                "size": config["size"],
                "max_tokens": config["max_tokens"],
            }
            for name, config in ModelConfig.MODELS.items()
        ]
