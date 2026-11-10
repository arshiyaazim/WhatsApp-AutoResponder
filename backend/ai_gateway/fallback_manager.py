from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from .storage import GatewayStore
from .types import Task


class FallbackManager:
    def __init__(self, store: GatewayStore) -> None:
        self.store = store

    def order_for(self, task: Task) -> list[str]:
        order = list(self.store.fallback_orders().get(task, []))
        if task == "text_generation":
            # Local retrieval is a final text-only fallback, never an image provider.
            order = [provider for provider in order if provider != "local-tfidf"] + ["local-tfidf"]
        return order

    def enabled(self) -> bool:
        return bool(self.store.get_settings().get("automatic_failover", True))

    @staticmethod
    def local_tfidf_answer(message: str, knowledge: list[dict[str, Any]], threshold: float = 0.12) -> str | None:
        tokenize = lambda value: re.findall(r"[\w]+", value.lower(), flags=re.UNICODE)
        query = Counter(tokenize(message))
        if not query:
            return None
        documents = [Counter(tokenize(str(entry.get("question", "")) + " " + str(entry.get("keywords", ""))))
                     for entry in knowledge]
        if not documents:
            return None
        document_frequency = Counter(token for doc in documents for token in doc.keys())
        vocabulary = set(query).union(document_frequency)
        def vector(counts: Counter[str]) -> dict[str, float]:
            return {token: count * math.log(1 + (len(documents) + 1) / (1 + document_frequency[token]))
                    for token, count in counts.items() if token in vocabulary}
        query_vector = vector(query)
        query_norm = math.sqrt(sum(value * value for value in query_vector.values()))
        if not query_norm:
            return None
        best: tuple[float, str] | None = None
        for entry, terms in zip(knowledge, documents):
            doc_vector = vector(terms)
            doc_norm = math.sqrt(sum(value * value for value in doc_vector.values()))
            dot = sum(value * doc_vector.get(token, 0.0) for token, value in query_vector.items())
            score = dot / (query_norm * doc_norm) if doc_norm else 0.0
            if best is None or score > best[0]:
                best = (score, str(entry.get("answer", "")))
        return best[1] if best and best[0] >= threshold and best[1] else None
