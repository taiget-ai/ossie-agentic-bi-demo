"""Read Ossie draft 0.2.0.dev0 metadata and enforce demo's supported subset.

Ossie defines a metadata interchange format, not a query engine. This is our
purposefully narrow semantic consumer. Use the upstream validator for full
specification compliance (see README).
"""
import re
from collections import defaultdict
from pathlib import Path

import yaml

from .catalog_errors import SemanticError
from .expression_ast import Aggregate, parse_metric, refs

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def identifier(name: str) -> str:
    if not isinstance(name, str) or not IDENT.fullmatch(name):
        raise SemanticError(f"unsafe identifier: {name!r}")
    return f'"{name}"'


def expression(item: dict) -> str:
    variants = item.get("expression", {}).get("dialects", [])
    for variant in variants:
        if variant.get("dialect") == "ANSI_SQL":
            return variant["expression"]
    raise SemanticError(f"missing ANSI_SQL expression in {item.get('name')}")


class Catalog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        with self.path.open(encoding="utf-8") as f:
            self.raw = yaml.safe_load(f)
        if not isinstance(self.raw, dict) or self.raw.get("version") != "0.2.0.dev0":
            raise SemanticError("expected Ossie flat document with version 0.2.0.dev0")
        if "semantic_model" in self.raw:
            raise SemanticError("legacy semantic_model wrapper is unsupported")
        self.datasets = {d["name"]: d for d in self.raw["datasets"]}
        self.metrics = {m["name"]: m for m in self.raw["metrics"]}
        self.relationships = self.raw.get("relationships", [])
        self.metric_ast = {}
        self.metric_datasets = {}
        self.dimensions = {}
        self.fields = defaultdict(dict)
        self._validate()
        # Consumer-specific value vocabulary stays outside the Ossie document.
        values_path = self.path.with_suffix('.values.yaml')
        self.filter_values = yaml.safe_load(values_path.read_text()) if values_path.exists() else {}
        if not isinstance(self.filter_values, dict):
            raise SemanticError("filter value vocabulary must be a mapping")
        for dimension, entries in self.filter_values.items():
            if dimension not in self.dimensions or not isinstance(entries, list):
                raise SemanticError("invalid filter value dimension")
            seen = set()
            for entry in entries:
                if (not isinstance(entry, dict) or not isinstance(entry.get('value'), str)
                        or not isinstance(entry.get('label'), str)
                        or not isinstance(entry.get('aliases', []), list)
                        or not all(isinstance(a, str) for a in entry.get('aliases', []))):
                    raise SemanticError("invalid filter value entry")
                if entry['value'] in seen:
                    raise SemanticError("duplicate filter value")
                seen.add(entry['value'])

    @classmethod
    def from_raw(cls, raw, filter_values=None):
        import copy
        obj = cls.__new__(cls)
        obj.raw = copy.deepcopy(raw)
        obj.datasets = {d['name']: d for d in obj.raw['datasets']}
        obj.metrics = {m['name']: m for m in obj.raw['metrics']}
        obj.relationships = obj.raw.get('relationships', [])
        obj.metric_ast = {}
        obj.metric_datasets = {}
        obj.dimensions = {}
        obj.fields = defaultdict(dict)
        obj.filter_values = copy.deepcopy(filter_values or {})
        obj._validate()
        return obj

    def _validate(self):
        if not self.datasets or not self.metrics:
            raise SemanticError("expected nonempty datasets and metrics")
        if len(self.datasets) != len(self.raw["datasets"]):
            raise SemanticError("duplicate dataset")
        if len(self.metrics) != len(self.raw["metrics"]):
            raise SemanticError("duplicate metric")
        for ds, spec in self.datasets.items():
            identifier(ds)
            identifier(spec["source"])  # demo: simple table names, no SQL queries
            for field in spec.get("fields", []):
                name = field["name"]
                identifier(name)
                if name in self.fields[ds]:
                    raise SemanticError(f"duplicate field {ds}.{name}")
                # Demo deliberately accepts column references only, not arbitrary expressions.
                if expression(field) != name:
                    raise SemanticError(f"only direct field references supported: {ds}.{name}")
                self.fields[ds][name] = field
                if "dimension" in field:
                    if name in self.dimensions:
                        raise SemanticError(f"dimension name must be globally unique: {name}")
                    self.dimensions[name] = (ds, field)
            for k in spec.get("primary_key", []):
                if k not in self.fields[ds]:
                    raise SemanticError(f"unknown primary key {ds}.{k}")
        for rel in self.relationships:
            src, dst = rel["from"], rel["to"]
            if src not in self.datasets or dst not in self.datasets:
                raise SemanticError(f"invalid relationship: {rel['name']}")
            left, right = rel["from_columns"], rel["to_columns"]
            if not left or len(left) != len(right):
                raise SemanticError(f"relationship key arity: {rel['name']}")
            if any(c not in self.fields[src] for c in left):
                raise SemanticError(f"invalid relationship from_columns: {rel['name']}")
            if any(c not in self.fields[dst] for c in right):
                raise SemanticError(f"invalid relationship to_columns: {rel['name']}")
            keys = [self.datasets[dst].get("primary_key", [])]
            keys += self.datasets[dst].get("unique_keys", [])
            if not any(set(key).issubset(set(right)) for key in keys if key):
                raise SemanticError(f"join target not declared unique: {rel['name']}")
        for metric in self.metrics.values():
            sql = expression(metric)
            try:
                tree = parse_metric(sql)
            except SemanticError as exc:
                raise SemanticError(f"unsupported aggregation in {metric['name']}: {exc}") from exc
            columns = refs(tree)
            for ds, field in columns:
                if ds not in self.datasets or field not in self.fields[ds]:
                    raise SemanticError(f"unknown metric reference {ds}.{field}")
            roots = {ds for ds, _ in columns}
            if len(roots) != 1:
                raise SemanticError("each demo metric must reference exactly one base dataset")
            self.metric_ast[metric['name']] = tree
            self.metric_datasets[metric['name']] = next(iter(roots))

    def metric_base(self, name: str) -> str:
        if name not in self.metrics:
            raise SemanticError(f"unknown metric: {name}")
        return self.metric_datasets[name]

    def public_model(self):
        return {
            "name": self.raw["name"],
            "version": self.raw["version"],
            "metrics": [
                {"name": m["name"], "additive": isinstance(self.metric_ast[m['name']], Aggregate)
                 and self.metric_ast[m['name']].function in ('SUM', 'COUNT')
                 and not self.metric_ast[m['name']].distinct, "description": m.get("description", ""),
                 "synonyms": m.get("ai_context", {}).get("synonyms", [])}
                for m in self.metrics.values()
            ],
            "dimensions": [
                {"name": name, "dataset": ds, "is_time": field.get("dimension", {}).get("is_time", False), "description": field.get("description", ""),
                 "synonyms": field.get("ai_context", {}).get("synonyms", [])}
                for name, (ds, field) in self.dimensions.items()
            ],
            "filter_values": self.filter_values,
            "available_filter_dimensions": list(self.dimensions),
        }
