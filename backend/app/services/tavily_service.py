"""Tavily web search without answer generation or arbitrary URL fetching."""
import hashlib
from urllib.parse import urlsplit

import httpx

from app.config.settings import settings
from app.models.chat_models import SearchResult


class TavilyService:
    @property
    def available(self):
        return bool(settings.tavily_api_key.strip())

    async def search(self, query):
        if not self.available:
            raise RuntimeError('web_search_unconfigured')
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            response = await client.post('https://api.tavily.com/search',
                headers={'Authorization': f'Bearer {settings.tavily_api_key}'},
                json={'query': query, 'search_depth': 'basic', 'max_results': 5,
                      'include_answer': False, 'include_raw_content': False, 'auto_parameters': False})
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get('results'), list):
            raise ValueError('invalid_web_response')
        documents, seen = [], set()
        for item in data['results'][:5]:
            if not isinstance(item, dict):
                continue
            url, content = item.get('url'), item.get('content')
            if not isinstance(url, str) or not isinstance(content, str) or not content.strip():
                continue
            parsed = urlsplit(url)
            if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password or len(url) > 2000 or url in seen:
                continue
            seen.add(url)
            documents.append(SearchResult(document_id='web:' + hashlib.sha256(url.encode()).hexdigest(),
                title=str(item.get('title') or parsed.hostname)[:200], source=url,
                snippet=content[:1500], score=0))
        return documents, {'provider': 'tavily', 'result_count': len(documents)}
