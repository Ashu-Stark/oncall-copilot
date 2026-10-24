"""Hybrid runbook retrieval: BM25 (exact words such as error names) + dense vectors (meaning), fused by rank.

- BM25 is written out here (no library) so every step is visible: term frequency saturation (k1) and length
  normalisation (b).
- Dense: LSA (TF-IDF -> truncated SVD) by default, which needs no model download. Any embedding function with the
  same signature can be swapped in (see `Embedder`).
- Fusion: Reciprocal Rank Fusion (RRF), which only uses ranks, so the two score scales never need calibrating.
Retrieval works on section chunks; a runbook's score is its best chunk's.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer

from .runbooks import Chunk, Runbook

_TOKEN = re.compile(r"[a-z0-9_]+")
STOP = set("a an the and or of to in on for is are be it at by with as from this that not no its if so all any one".split())


def tokens(text: str) -> list[str]:
    # split CamelCase error names (ServerSelectionTimeoutError -> server selection timeout error) and keep the whole too
    parts = []
    for w in re.findall(r"[A-Za-z0-9_]+", text):
        parts.append(w.lower())
        sub = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", w)
        if len(sub) > 1:
            parts.extend(s.lower() for s in sub)
    return [t for t in parts if t not in STOP and len(t) > 1]


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.docs, self.k1, self.b = docs, k1, b
        self.n = len(docs)
        self.avgdl = sum(map(len, docs)) / max(self.n, 1)
        self.tf = [Counter(d) for d in docs]
        df = Counter(t for d in docs for t in set(d))
        # BM25 idf with +1 inside the log so very common terms never get a negative weight
        self.idf = {t: math.log(1 + (self.n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: list[str]) -> np.ndarray:
        out = np.zeros(self.n)
        for i, (tf, d) in enumerate(zip(self.tf, self.docs, strict=True)):
            norm = self.k1 * (1 - self.b + self.b * len(d) / self.avgdl)
            for t in query:
                f = tf.get(t)
                if f:
                    out[i] += self.idf[t] * f * (self.k1 + 1) / (f + norm)
        return out


Embedder = Callable[[list[str]], np.ndarray]  # texts -> (n, dim) L2-normalised


class LsaEmbedder:
    """TF-IDF + truncated SVD fitted on the runbook corpus. Small and offline; captures co-occurring vocabulary
    (e.g. 'slow' near 'latency' and 'p95'), not deep semantics."""

    def __init__(self, corpus: list[str], dim: int = 48, seed: int = 0):
        self.vec = TfidfVectorizer(tokenizer=tokens, lowercase=False, token_pattern=None, sublinear_tf=True)
        x = self.vec.fit_transform(corpus)
        self.svd = TruncatedSVD(n_components=min(dim, x.shape[1] - 1, x.shape[0] - 1), random_state=seed)
        self.svd.fit(x)

    def __call__(self, texts: list[str]) -> np.ndarray:
        z = self.svd.transform(self.vec.transform(texts))
        return z / np.maximum(np.linalg.norm(z, axis=1, keepdims=True), 1e-12)


@dataclass
class Hit:
    runbook_id: str
    score: float
    best_chunk: str
    bm25_rank: int
    dense_rank: int


class HybridRetriever:
    def __init__(self, runbooks: dict[str, Runbook], embedder: Embedder | None = None, rrf_k: int = 60):
        self.runbooks = runbooks
        self.chunks: list[Chunk] = [c for rb in runbooks.values() for c in rb.chunks]
        texts = [c.text for c in self.chunks]
        self.bm25 = BM25([tokens(t) for t in texts])
        self.embed = embedder or LsaEmbedder(texts)
        self.chunk_vecs = self.embed(texts)
        self.rrf_k = rrf_k

    def _rank_runbooks(self, chunk_scores: np.ndarray) -> list[tuple[str, float, str]]:
        best: dict[str, tuple[float, str]] = {}
        for c, s in zip(self.chunks, chunk_scores, strict=True):
            if c.runbook_id not in best or s > best[c.runbook_id][0]:
                best[c.runbook_id] = (float(s), c.ref)
        return sorted(((rb, s, ref) for rb, (s, ref) in best.items()), key=lambda x: -x[1])

    def bm25_only(self, query: str) -> list[tuple[str, float, str]]:
        return self._rank_runbooks(self.bm25.scores(tokens(query)))

    def dense_only(self, query: str) -> list[tuple[str, float, str]]:
        q = self.embed([query])[0]
        return self._rank_runbooks(self.chunk_vecs @ q)

    def search(self, query: str, k: int = 5) -> list[Hit]:
        sparse, dense = self.bm25_only(query), self.dense_only(query)
        r_s = {rb: i + 1 for i, (rb, _, _) in enumerate(sparse)}
        r_d = {rb: i + 1 for i, (rb, _, _) in enumerate(dense)}
        ref_s = {rb: ref for rb, _, ref in sparse}
        fused = {rb: 1 / (self.rrf_k + r_s[rb]) + 1 / (self.rrf_k + r_d[rb]) for rb in self.runbooks}
        top = sorted(fused, key=lambda rb: -fused[rb])[:k]
        return [Hit(rb, round(fused[rb], 5), ref_s[rb], r_s[rb], r_d[rb]) for rb in top]
