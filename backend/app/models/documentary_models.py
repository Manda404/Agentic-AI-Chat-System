"""Closed action schema: no arbitrary commands or function dispatch."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class DocumentaryAction(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    action: Literal['rechercher_web', 'rechercher', 'lire_passage', 'answer', 'clarify', 'abstain']
    query: str | None = Field(default=None, min_length=1, max_length=1000)
    passage_id: str | None = Field(default=None, min_length=1, max_length=200)
    text: str | None = Field(default=None, min_length=1, max_length=8000)

    @model_validator(mode='after')
    def validate_arguments(self):
        required = {'rechercher_web': 'query', 'rechercher': 'query', 'lire_passage': 'passage_id', 'answer': 'text', 'clarify': 'text'}
        field = required.get(self.action)
        if field and getattr(self, field) is None:
            raise ValueError(f'{self.action} requires {field}.')
        for key in ('query', 'passage_id', 'text'):
            if key != field and getattr(self, key) is not None:
                raise ValueError(f'Unexpected argument {key} for {self.action}.')
        if self.action == 'clarify' and (len(self.text) > 400 or not self.text.endswith('?')):
            raise ValueError('Clarification must be one short question ending in ?. ')
        return self
