"""Find declared, safe many-to-one paths between datasets."""
from collections import deque

from ..catalog import Catalog, SemanticError


def find_join_paths(catalog: Catalog, root: str, targets: set[str]) -> list[dict]:
    graph: dict[str, list[dict]] = {}
    for relation in catalog.relationships:
        graph.setdefault(relation["from"], []).append(relation)
    for edges in graph.values():
        edges.sort(key=lambda r: r["name"])

    # Paths are ordered by BFS discovery, making generated SQL reproducible.
    paths: dict[str, list[dict]] = {root: []}
    shortest_path_counts = {root: 1}
    queue = deque([root])
    while queue:
        node = queue.popleft()
        for relation in graph.get(node, []):
            destination = relation["to"]
            if destination not in paths:
                paths[destination] = [*paths[node], relation]
                shortest_path_counts[destination] = shortest_path_counts[node]
                queue.append(destination)
            elif len(paths[destination]) == len(paths[node]) + 1:
                shortest_path_counts[destination] += shortest_path_counts[node]
    missing = targets - paths.keys()
    if missing:
        raise SemanticError("no safe many-to-one join path to: " + ", ".join(sorted(missing)))

    ambiguous = sorted(name for name in targets if shortest_path_counts[name] > 1)
    if ambiguous:
        raise SemanticError("ambiguous shortest join path to: " + ", ".join(ambiguous))

    required = {edge["name"] for target in targets for edge in paths[target]}
    joined = {root}
    ordered: list[dict] = []
    # Traverse BFS tree by growing from already joined datasets.
    for path in paths.values():
        for edge in path:
            if edge["name"] in required and edge["to"] not in joined:
                if edge["from"] not in joined:
                    raise SemanticError("invalid join order")
                ordered.append(edge)
                joined.add(edge["to"])
    return ordered
