"""TF-IDF vectorization + Agglomerative clustering for shadow ontology."""
from __future__ import annotations
import re
from typing import Dict, List


def _mixed_tokenizer(text: str) -> List[str]:
    """Tokenize mixed CN/EN: word tokens + CJK character bigrams."""
    words = re.findall(r'[a-zA-Z_:]+|\d+', text)
    cjk = [c for c in text if '\u4e00' <= c <= '\u9fff']
    bigrams = [cjk[i] + cjk[i+1] for i in range(len(cjk) - 1)]
    return words + bigrams


def cluster_cases(
    documents: List[str],
    case_ids: List[str],
    distance_threshold: float = 0.7,
    min_cluster_size: int = 3,
) -> List[Dict]:
    """TF-IDF + Agglomerative clustering. Requires scikit-learn."""
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.cluster import AgglomerativeClustering
        from sklearn.metrics.pairwise import cosine_distances
    except ImportError:
        raise ImportError("Shadow ontology requires: pip install twin-runtime[analysis]")

    if len(documents) < min_cluster_size:
        return []

    vectorizer = TfidfVectorizer(
        tokenizer=_mixed_tokenizer,
        token_pattern=None,  # Suppress warning: custom tokenizer overrides token_pattern
        ngram_range=(1, 2),
        max_features=500,
        sublinear_tf=True,
    )
    tfidf = vectorizer.fit_transform(documents)
    distance_matrix = cosine_distances(tfidf)

    clustering = AgglomerativeClustering(
        metric='precomputed',
        linkage='average',
        distance_threshold=distance_threshold,
        n_clusters=None,
    )
    labels = clustering.fit_predict(distance_matrix)

    # Group by cluster, filter by min size
    clusters = {}
    for idx, label in enumerate(labels):
        clusters.setdefault(label, []).append(idx)

    result = []
    feature_names = vectorizer.get_feature_names_out()
    for label, indices in clusters.items():
        if len(indices) < min_cluster_size:
            continue
        cluster_tfidf = tfidf[indices].mean(axis=0).A1
        top_indices = cluster_tfidf.argsort()[-5:][::-1]
        top_terms = [feature_names[i] for i in top_indices]
        result.append({
            "label": label,
            "case_ids": [case_ids[i] for i in indices],
            "top_terms": top_terms,
            "size": len(indices),
        })
    return result
