"""English-only semantic parsing: deterministic offline examples or OpenAI LLM.

The language model may choose only catalog identifiers. It never writes SQL.
"""
import json
import os
import re
from datetime import date, timedelta

from pydantic import ValidationError

from .catalog import Catalog, SemanticError
from .schemas import LLMOptions, SemanticQuery

CATEGORIES = {"casino": "Casino", "sports": "Sports"}


def _found(text: str, alias: str) -> bool:
    # Word boundaries prevent matching "bet" inside "betting" or other metric names.
    return bool(re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", text, re.IGNORECASE))


def _matching(question: str, options: list[dict]) -> list[str]:
    matched: list[tuple[int, str]] = []
    for item in options:
        positions = [
            match.start()
            for alias in [item["name"], *item.get("synonyms", [])]
            if alias
            for match in [re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", question, re.IGNORECASE)]
            if match
        ]
        if positions:
            matched.append((min(positions), item["name"]))
    return [name for _, name in sorted(matched)]


def rule_parse(question: str, catalog: Catalog, today: date | None = None) -> SemanticQuery:
    """Offline demo parser: catalog names/synonyms and a few explicit filters."""
    replacements = {
        '人均投注额': 'stake_per_bettor', '总投注额': 'total_stake', '总充值额': 'total_deposit',
        '投注次数': 'bet_count', '净收入': 'ngr', '投注人数': 'unique_bettors',
        '按月份': 'by month', '按月': 'by month', '按周': 'by week', '按天': 'by day',
        '国家': 'country', '游戏类别': 'game_category', '最近7天': 'last 7 days',
        '美国': 'United States', '日本': 'Japan', '英国': 'United Kingdom', '芬兰': 'Finland',
        '德国': 'Germany', '新加坡': 'Singapore', '加拿大': 'Canada', '印度': 'India',
        '澳大利亚': 'Australia', '巴西': 'Brazil', '法国': 'France', '西班牙': 'Spain',
    }
    for original, translated in replacements.items():
        question = question.replace(original, ' ' + translated + ' ')
    question = re.sub(r'最近\s*(\d+)\s*天', r' last \1 days ', question)
    question = re.sub(r'前\s*(\d+)', r' top \1 ', question)
    question = re.sub(r'\bcountries\b', 'country', question, flags=re.IGNORECASE)
    model = catalog.public_model()
    metrics = _matching(question, model["metrics"])
    dimensions = _matching(question, model["dimensions"])
    if not metrics:
        raise SemanticError("rule mode needs a recognizable metric; choose an example or use LLM mode")

    filters: dict[str, str | list[str]] = {}
    for dimension, entries in catalog.filter_values.items():
        matched = set()
        for entry in entries:
            # Short codes are case-sensitive: English "in"/"us" are not IN/US.
            code_match = re.search(r"(?<!\w)" + re.escape(entry['value']) + r"(?!\w)", question)
            aliases = [entry['label'], *entry.get('aliases', [])]
            if code_match or any(_found(question, alias) for alias in aliases if alias):
                matched.add(entry['value'])
        if matched:
            filters[dimension] = sorted(matched) if len(matched) > 1 else matched.pop()
    for word, category in CATEGORIES.items():
        if _found(question, word) and not _found(question, "by " + word):
            filters["game_category"] = category

    grains = [grain for grain, adverb in [('day', 'daily'), ('week', 'weekly'), ('month', 'monthly')]
              if re.search(r"\b(?:by|per|each)\s+" + grain + r"\b|\b" + adverb + r"\b",
                           question, re.IGNORECASE)]
    if len(grains) > 1:
        raise SemanticError("choose one time grain")
    if grains:
        dimensions = [name for name in dimensions
                      if not catalog.dimensions[name][1].get('dimension', {}).get('is_time')]
    start, end = None, None
    days = re.search(r"\b(?:last|past|previous)\s+(\d+)\s+days\b", question, re.IGNORECASE)
    if days:
        count = int(days.group(1))
        if not 1 <= count <= 3660:
            raise SemanticError('day range must be between 1 and 3660')
        end = today or date.today()
        start = end - timedelta(days=count - 1)
    top = re.search(r'\btop\s+(\d+)\b', question, re.IGNORECASE)
    return SemanticQuery(
        metrics=metrics, dimensions=dimensions, filters=filters,
        limit=int(top.group(1)) if top else 100,
        order_by=[{'field': metrics[0], 'direction': 'desc'}] if top else [],
        date_from=start, date_to=end, time_grain=grains[0] if grains else None,
    )


def llm_parse(
    question: str,
    catalog: Catalog,
    today: date | None = None,
    options: LLMOptions | None = None,
) -> SemanticQuery:
    """OpenAI-compatible chat completion, provider chosen per request.

    Works with OpenAI, proxy endpoints, or local servers exposing chat completions.
    No keys are persisted or included in returned plans.
    """
    options = options or LLMOptions()
    endpoint = options.base_url or os.getenv('OSSIE_LLM_BASE_URL')
    explicit_key = options.api_key.get_secret_value() if options.api_key else None
    key = explicit_key or os.getenv('OSSIE_LLM_API_KEY') or os.getenv('OPENAI_API_KEY')
    if not key and not endpoint:
        raise SemanticError('set OPENAI_API_KEY or configure an OpenAI-compatible endpoint')
    # Local OpenAI-compatible servers often accept a dummy value instead of a key.
    from openai import OpenAI
    kwargs = {'api_key': key or 'no-key-required', 'timeout': 30.0, 'max_retries': 1}
    if endpoint:
        kwargs['base_url'] = endpoint
    client = OpenAI(**kwargs)
    current = today or date.today()
    prompt = (
        "Translate the user's analytics question into one JSON object. "
        "Return keys: metrics (nonempty array of approved names), dimensions (approved names), "
        "filters (object dimension name to string or array of strings), date_from (YYYY-MM-DD or null), "
        "date_to (YYYY-MM-DD or null), time_grain (day, week, month, or null). "
        "Use time_grain for temporal grouping, not raw date dimensions. Weeks start Monday. "
        "Optional order_by: array of {field: selected metric/dimension, direction: asc/desc}, limit: 1..100. No SQL or invented names. "
        "Metrics may come from different fact datasets and are aligned at requested dimensions. "
        "Filter keys must be available dimensions. Do not fabricate filter values. "
        "Dates are inclusive; last 7 days means today and six previous days. "
        "If impossible, return {\"error\": \"unresolvable request\"}. "
        f"Today: {current.isoformat()}. Available catalog: "
        + json.dumps(catalog.public_model(), ensure_ascii=True)
    )
    req = {
        'model': options.model or os.getenv('OSSIE_LLM_MODEL', 'gpt-4o-mini'),
        'messages': [{'role': 'system', 'content': prompt},
                     {'role': 'user', 'content': question}],
    }
    if options.json_mode:
        req['response_format'] = {'type': 'json_object'}
    response = client.chat.completions.create(**req)
    try:
        raw = (response.choices[0].message.content or '').strip()
        if raw.startswith('```'):
            raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw, flags=re.IGNORECASE)
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            raise SemanticError('LLM must return a JSON object')
        if 'error' in obj:
            raise SemanticError(str(obj['error']))
        return SemanticQuery.model_validate(obj)
    except (ValueError, TypeError, ValidationError) as exc:
        if isinstance(exc, SemanticError):
            raise
        raise SemanticError(f'invalid LLM semantic query: {exc}') from exc
