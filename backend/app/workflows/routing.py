"""Local routing: only explicit non-documentary requests bypass the RAG path."""
import re
import unicodedata

from app.models.chat_models import AgentResult
from app.state import GraphState


def _normalize(text: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKD', text.lower()) if not unicodedata.combining(c)).strip()


def select_route(message: str, mode: str = 'auto') -> str:
    if mode == 'documents':
        return 'rag'
    if mode == 'general':
        return 'direct_answer'
    text = _normalize(message).strip('!?., ')
    if text in {'hello', 'hi', 'hey', 'bonjour', 'salut', 'coucou', 'bonsoir', 'can you help', 'peux-tu m’aider'}:
        return 'greeting'
    if re.fullmatch(r'(?:list (?:the )?(?:indexed )?documents|which documents are indexed|(?:liste|lister) (?:les |des )?(?:documents|fichiers)(?: indexes)?|quels (?:documents|fichiers) sont indexes)', text):
        return 'document_list'
    # A date or expression inside a business question is not a calculation request.
    expression = re.sub(r'^(?:calculate|compute|calcule|calculer|combien font)\s*:?\s*', '', text)
    expression = re.sub(r'(\d+(?:[.,]\d+)?)\s*%\s+(?:of|de)\s+(\d+(?:[.,]\d+)?)', r'(\1 / 100) * \2', expression)
    if re.fullmatch(r'[\d\s.,()+*/%^\-]+', expression) and re.search(r'\d', expression) and re.search(r'[+*/%^\-]', expression):
        return 'calculation'
    # Transforming explicitly supplied text does not require document retrieval.
    document_prefix = re.search(r'\b(?:documents?|pdf|fichiers?)\b', text.split(':', 1)[0])
    if not document_prefix and re.match(r'^(?:summarize|summarise|resume|corrige|correct|rewrite|reformule|traduis|translate)\b[^:\n]{0,60}:\s*\S', text):
        return 'direct_answer'
    return 'rag'


def route_request(state: GraphState) -> AgentResult:
    state.route = select_route(state.user_message, state.metadata.get('request_mode', 'auto'))
    state.intent = state.route
    state.plan = ['route', *(['retrieve'] if state.route == 'rag' else []), 'answer', 'validate', 'finalize']
    return AgentResult(agent='router', output=f'Route: {state.route}', metadata={'source': 'local', 'mode': state.metadata.get('request_mode', 'auto')})
