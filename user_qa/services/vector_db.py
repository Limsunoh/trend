"""
벡터DB 관련 코드: SearchResult, VectorDBService
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings
from django.conf import settings
from sentence_transformers import SentenceTransformer

from common.redis_services import EmbeddingCacheService

logger = logging.getLogger(__name__)


def _get_setting(name: str, default: Any = None) -> Any:
    return getattr(settings, name, default)


@dataclass
class SearchResult:
    id: str
    document: str
    metadata: Dict[str, Any]
    distance: float


def _infer_type(doc_id: str, meta: Optional[Dict[str, Any]] = None) -> str:
    """metadata에 type/doc_type이 없거나 누락된 레거시 데이터까지 포함해 타입을 안정적으로 판별."""
    meta = meta or {}
    t = (meta.get("type") or meta.get("doc_type") or "").strip()
    if t:
        return t
    doc_id = str(doc_id or "")
    if doc_id.startswith("news:"):
        return "news"
    if doc_id.startswith("social:"):
        return "social"
    return ""


class VectorDBService:
    """
    Chroma Persistent Vector DB service
    - collection: trend_docs (default)
    - embeddings: SentenceTransformer(settings.EMBEDDING_MODEL)
    """

    def __init__(self, collection_name: str | None = None):
        self.persist_dir: str = str(_get_setting("CHROMA_PERSIST_DIR", "./chroma_db"))
        self.collection_name: str = collection_name or _get_setting(
            "CHROMA_COLLECTION", "trend_docs"
        )

        model_name: str = _get_setting(
            "EMBEDDING_MODEL",
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        )
        self.embedder = SentenceTransformer(model_name)

        self.client = chromadb.PersistentClient(
            path=self.persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        vectors = self.embedder.encode(
            texts,
            batch_size=64,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        return [v.tolist() for v in vectors]

    def embed_texts_cached(self, texts: List[str]) -> List[List[float]]:
        """Redis 캐시를 활용한 임베딩. 쿼리 검색용."""
        try:
            cache = EmbeddingCacheService()
            cached = cache.get_vectors_batch(texts)
        except Exception:
            return self.embed_texts(texts)

        results: List[Optional[List[float]]] = []
        miss_indices: List[int] = []
        miss_texts: List[str] = []

        for i, text in enumerate(texts):
            vec = cached.get(text)
            if vec is not None:
                results.append(vec)
            else:
                results.append(None)
                miss_indices.append(i)
                miss_texts.append(text)

        if miss_texts:
            new_vecs = self.embed_texts(miss_texts)
            try:
                cache.set_vectors_batch(list(zip(miss_texts, new_vecs)))
            except Exception:
                pass
            for idx, vec in zip(miss_indices, new_vecs):
                results[idx] = vec

        return results

    def upsert_documents(
        self,
        ids: List[str],
        documents: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        if not documents:
            return
        embeddings = self.embed_texts(documents)
        self.collection.upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )

    def delete_old_documents(self, cutoff_iso: str) -> None:
        """published_at < cutoff_iso인 문서를 배치 조회 후 삭제합니다."""
        try:
            batch_size = 10000
            offset = 0
            ids_to_delete: list[str] = []

            while True:
                results = self.collection.get(
                    offset=offset,
                    limit=batch_size,
                    include=["metadatas"],
                )
                if not results["ids"]:
                    break

                for doc_id, meta in zip(results["ids"], results["metadatas"]):
                    pub = meta.get("published_at", "")
                    if pub and pub < cutoff_iso:
                        ids_to_delete.append(doc_id)

                if len(results["ids"]) < batch_size:
                    break
                offset += batch_size

            if ids_to_delete:
                for i in range(0, len(ids_to_delete), 5000):
                    batch = ids_to_delete[i : i + 5000]
                    self.collection.delete(ids=batch)

            logger.info(
                f"[VectorDB] published_at < {cutoff_iso} 문서 "
                f"{len(ids_to_delete)}건 삭제 완료"
            )
        except Exception as e:
            logger.warning(f"[VectorDB] 오래된 문서 삭제 실패: {e}")

    def similarity_search(
        self,
        query_text: str,
        top_k: int = 5,
        distance_threshold: float = 0.10,
        fetch_multiplier: int = 2,
        *,
        balance_types: bool = True,
    ) -> List[SearchResult]:
        """
        유사도 검색
        """
        q_emb = self.embed_texts_cached([query_text])[0]
        fetch_k = max(top_k * fetch_multiplier, top_k + 5)

        res = self.collection.query(
            query_embeddings=[q_emb],
            n_results=fetch_k,
            include=["documents", "metadatas", "distances"],
        )

        ids = res.get("ids", [[]])[0]
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        dists = res.get("distances", [[]])[0]

        candidates: List[SearchResult] = []
        all_distances = []
        for _id, doc, meta, dist in zip(ids, docs, metas, dists):
            distance = float(dist)
            all_distances.append(distance)
            if distance <= distance_threshold:
                candidates.append(
                    SearchResult(
                        id=_id,
                        document=doc,
                        metadata=meta or {},
                        distance=distance,
                    )
                )

        if all_distances:
            logger.debug(
                f"[similarity_search] 가져온 결과 {len(all_distances)}개, "
                f"거리 범위: {min(all_distances):.4f} ~ {max(all_distances):.4f}, "
                f"임계값: {distance_threshold:.4f}"
            )

        candidates.sort(key=lambda x: x.distance)

        if not balance_types:
            return candidates[:top_k]

        news_results = [
            r for r in candidates if _infer_type(r.id, r.metadata) == "news"
        ]
        social_results = [
            r for r in candidates if _infer_type(r.id, r.metadata) == "social"
        ]
        balanced_results = []

        if news_results:
            news_count = min(len(news_results), max(2, int(top_k * 0.7)))
            social_count = top_k - news_count
            balanced_results = news_results[:news_count]
            if social_count > 0 and social_results:
                balanced_results.extend(social_results[:social_count])
        else:
            balanced_results = candidates[:top_k]

        if len(balanced_results) < top_k:
            remaining = [r for r in candidates if r not in balanced_results]
            balanced_results.extend(remaining[: top_k - len(balanced_results)])

        return balanced_results[:top_k]

    def batch_similarity_search(
        self,
        query_texts: List[str],
        top_k: int = 5,
        distance_threshold: float = 0.10,
        fetch_multiplier: int = 2,
    ) -> List[List[SearchResult]]:
        """
        여러 쿼리를 한 번에 임베딩 + 검색 (배치 처리).
        """
        if not query_texts:
            return []

        q_embs = self.embed_texts_cached(query_texts)
        fetch_k = max(top_k * fetch_multiplier, top_k + 5)

        res = self.collection.query(
            query_embeddings=q_embs,
            n_results=fetch_k,
            include=["documents", "metadatas", "distances"],
        )

        all_results: List[List[SearchResult]] = []
        for qi in range(len(query_texts)):
            ids = res.get("ids", [[]])[qi] if qi < len(res.get("ids", [])) else []
            docs = (
                res.get("documents", [[]])[qi]
                if qi < len(res.get("documents", []))
                else []
            )
            metas = (
                res.get("metadatas", [[]])[qi]
                if qi < len(res.get("metadatas", []))
                else []
            )
            dists = (
                res.get("distances", [[]])[qi]
                if qi < len(res.get("distances", []))
                else []
            )

            candidates: List[SearchResult] = []
            for _id, doc, meta, dist in zip(ids, docs, metas, dists):
                distance = float(dist)
                if distance <= distance_threshold:
                    candidates.append(
                        SearchResult(
                            id=_id,
                            document=doc,
                            metadata=meta or {},
                            distance=distance,
                        )
                    )
            candidates.sort(key=lambda x: x.distance)
            all_results.append(candidates[:top_k])

        return all_results

    def keyword_search(
        self,
        query_text: str,
        keywords: List[str],
        top_k: int = 20,
    ) -> List[SearchResult]:
        """
        키워드 포함 문서를 필터링한 후 시맨틱 유사도로 정렬.
        """
        if not keywords:
            return []

        q_emb = self.embed_texts_cached([query_text])[0]
        all_results: List[SearchResult] = []
        seen_ids: set = set()

        for keyword in keywords:
            if not keyword or len(keyword) < 2:
                continue
            try:
                res = self.collection.query(
                    query_embeddings=[q_emb],
                    n_results=top_k * 2,
                    where_document={"$contains": keyword},
                    include=["documents", "metadatas", "distances"],
                )

                ids = res.get("ids", [[]])[0]
                docs = res.get("documents", [[]])[0]
                metas = res.get("metadatas", [[]])[0]
                dists = res.get("distances", [[]])[0]

                for _id, doc, meta, dist in zip(ids, docs, metas, dists):
                    if _id not in seen_ids:
                        seen_ids.add(_id)
                        all_results.append(
                            SearchResult(
                                id=_id,
                                document=doc,
                                metadata=meta or {},
                                distance=float(dist),
                            )
                        )
            except Exception as e:
                logger.warning(f"[keyword_search] 키워드 '{keyword}' 검색 실패: {e}")
                continue

        all_results.sort(key=lambda x: x.distance)
        return all_results[:top_k]
