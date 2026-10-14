"""SemanticQuery and optional transient provider settings; neither contains SQL."""
from datetime import date
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


class SortKey(BaseModel):
    model_config = ConfigDict(extra='forbid')
    field: str
    direction: Literal['asc', 'desc'] = 'desc'


class SemanticQuery(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    metrics: list[str] = Field(min_length=1, max_length=8)
    dimensions: list[str] = Field(default_factory=list, max_length=3)
    filters: dict[str, str | list[str]] = Field(default_factory=dict)
    time_grain: Literal["day", "week", "month"] | None = None
    date_from: date | None = None
    date_to: date | None = None
    order_by: list[SortKey] = Field(default_factory=list, max_length=4)
    limit: int = Field(default=100, ge=1, le=100)

    @model_validator(mode='after')
    def check_request(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError('date_from must be <= date_to')
        if len(set(self.metrics)) != len(self.metrics):
            raise ValueError('duplicate metrics are not allowed')
        if len(set(self.dimensions)) != len(self.dimensions):
            raise ValueError('duplicate dimensions are not allowed')
        if len(self.filters) > 4:
            raise ValueError('too many filters')
        for value in self.filters.values():
            values = value if isinstance(value, list) else [value]
            if not 1 <= len(values) <= 50 or any(not v or len(v) > 80 for v in values):
                raise ValueError('filter values must contain 1 to 50 nonempty strings')
        allowed = set(self.metrics + self.dimensions + (['time_period'] if self.time_grain else []))
        if any(key.field not in allowed for key in self.order_by):
            raise ValueError('sort keys must be selected metrics or dimensions')
        if len({key.field for key in self.order_by}) != len(self.order_by):
            raise ValueError('duplicate sort keys')
        return self


class LLMOptions(BaseModel):
    """Per-request OpenAI-compatible provider config; no persistence or response echo."""
    model_config = ConfigDict(extra='forbid')
    base_url: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=100)
    api_key: SecretStr | None = None
    json_mode: bool = True

    @field_validator('base_url')
    @classmethod
    def valid_endpoint(cls, value):
        if not value:
            return None
        p = urlparse(value)
        if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
            raise ValueError('provider URL must be a valid http(s) endpoint without embedded credentials')
        return value.rstrip('/')


class AskRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    question: str = Field(min_length=3, max_length=500)
    mode: str = Field(default='rules', pattern='^(rules|llm)$')
    llm: LLMOptions | None = None


class Period(BaseModel):
    model_config = ConfigDict(extra='forbid')
    start: date
    end: date

    @model_validator(mode='after')
    def check_dates(self):
        if self.start > self.end:
            raise ValueError('period start must precede end')
        return self


class PeriodComparison(BaseModel):
    model_config = ConfigDict(extra='forbid')
    metric: str = 'total_stake'
    dimension: str = 'country'
    filters: dict[str, str | list[str]] = Field(default_factory=dict)
    previous: Period | None = None
    current: Period | None = None
    top_n: int = Field(default=10, ge=1, le=100)

    @model_validator(mode='after')
    def check_periods(self):
        if (self.previous is None) != (self.current is None):
            raise ValueError('provide both periods or neither')
        if self.previous and self.previous.end >= self.current.start:
            raise ValueError('comparison periods must not overlap')
        return self


class ModelComparison(BaseModel):
    model_config = ConfigDict(extra='forbid')
    query: SemanticQuery
    metric: str
    expression: str = Field(min_length=1, max_length=2000)


class DrillRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    query: SemanticQuery
    selection: dict[str, str] = Field(default_factory=dict)
    target: str


class MetricExplanation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    query: SemanticQuery
    metric: str
