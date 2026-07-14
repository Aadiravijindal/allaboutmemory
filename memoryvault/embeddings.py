"""Pluggable embeddings — semantic similarity for dedupe, search, contradiction.

The interface is what matters: in production you swap the local provider for
OpenAI / Bedrock / a local sentence-transformer, all behind `embed()`. The
default `HashingEmbedder` needs no network and no model download, so the demo
always runs — it's a character-n-gram hashing vectorizer (a real, if simple,
semantic-ish signal) good enough to show embedding-based dedupe working.

Production note: set MV_EMBEDDINGS=openai|bedrock and the matching adapter
runs INSIDE the customer's tenant on their keys (privacy preserved).
"""
from __future__ import annotations

import math
import os
import re
from typing import List

_TOKEN = re.compile(r"[a-z0-9]+")


class Embedder:
    dim = 256

    def embed(self, text: str) -> List[float]:
        raise NotImplementedError

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return [self.embed(t) for t in texts]

    @staticmethod
    def cosine(a: List[float], b: List[float]) -> float:
        if not a or not b:
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na and nb else 0.0


class HashingEmbedder(Embedder):
    """Zero-dependency char-ngram hashing embedder. Deterministic, offline."""

    def __init__(self, dim: int = 256):
        self.dim = dim

    def embed(self, text: str) -> List[float]:
        vec = [0.0] * self.dim
        text = text.lower().strip()
        tokens = _TOKEN.findall(text)
        # word unigrams + char trigrams => rough semantic fingerprint
        grams = list(tokens)
        for tok in tokens:
            padded = f"#{tok}#"
            grams += [padded[i:i + 3] for i in range(len(padded) - 2)]
        for g in grams:
            h = hash(g) % self.dim
            vec[h] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class OpenAIEmbedder(Embedder):  # pragma: no cover - needs network/key
    """Production adapter. Runs in-tenant on the customer's key."""

    dim = 1536

    def __init__(self, model: str = "text-embedding-3-small"):
        self.model = model
        try:
            from openai import OpenAI
            self.client = OpenAI()
        except Exception as e:
            raise RuntimeError(f"OpenAI embedder unavailable: {e}")

    def embed(self, text: str) -> List[float]:
        r = self.client.embeddings.create(model=self.model, input=text)
        return r.data[0].embedding


def get_embedder() -> Embedder:
    kind = os.environ.get("MV_EMBEDDINGS", "local").lower()
    if kind == "openai":
        return OpenAIEmbedder()
    return HashingEmbedder()
