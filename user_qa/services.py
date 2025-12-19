"""
벡터DB 및 RAG 서비스
"""
from common.redis_services import RAGCacheService

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from django.conf import settings

import chromadb
from chromadb.config import Settings as ChromaSettings
from sentence_transformers import SentenceTransformer


def _get_setting(name: str, default: Any = None) -> Any:
    return getattr(settings, name, default)


@dataclass
class SearchResult:
    id: str
    document: str
    metadata: Dict[str, Any]
    distance: float


class VectorDBService:
    """
    Chroma Persistent Vector DB service
    - collection: trend_docs (default)
    - embeddings: SentenceTransformer(settings.EMBEDDING_MODEL)
    """

    def __init__(self, collection_name: str | None = None):
        self.persist_dir: str = _get_setting("CHROMA_PERSIST_DIR", "./chroma_db")
        self.collection_name: str = collection_name or _get_setting("CHROMA_COLLECTION", "trend_docs")

        model_name: str = _get_setting(
            "EMBEDDING_MODEL",
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        )
        self.embedder = SentenceTransformer(model_name)

        # Persistent Chroma client
        self.client = chromadb.PersistentClient(
            path=self.persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(name=self.collection_name)

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        # normalize_embeddings=True 추천(코사인 유사도 검색에서 안정적)
        vectors = self.embedder.encode(
            texts,
            batch_size=64,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        # chroma는 python list 형태를 선호
        return [v.tolist() for v in vectors]

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

    def similarity_search(self, query_text: str, top_k: int = 5) -> List[SearchResult]:
        q_emb = self.embed_texts([query_text])[0]
        res = self.collection.query(
            query_embeddings=[q_emb],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )

        out: List[SearchResult] = []
        ids = res.get("ids", [[]])[0]
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        dists = res.get("distances", [[]])[0]

        for _id, doc, meta, dist in zip(ids, docs, metas, dists):
            out.append(SearchResult(id=_id, document=doc, metadata=meta or {}, distance=float(dist)))
        return out


class RAGService:
    """RAG 질의응답 서비스 (캐싱 통합)"""
    
    def __init__(self):
        # TODO: LLM 및 VectorDBService 초기화
        self.vector_db = VectorDBService()
        # 우선순위 1: RAG 질의응답 캐싱
        self.cache_service = RAGCacheService()
        pass
    
    def query(self, query_text, top_k=5, include_sources=True):
        """
        RAG 질의응답 (캐싱 적용)
        1. 캐시 확인
        2. 캐시 없으면 RAG 처리
        3. 결과 캐싱
        """
        # 캐시 확인
        cached_response = self.cache_service.get_cached_response(query_text)
        if cached_response:
            return cached_response
        
        # TODO: 
        # 1. 벡터DB에서 유사 문서 검색
        # 2. 검색된 문서를 컨텍스트로 LLM에 전달
        # 3. LLM 답변 생성
        response = {
            'answer': '',  # TODO: LLM 답변
            'sources': [],  # TODO: 출처 정보
            'query': query_text
        }
        
        # 결과 캐싱
        self.cache_service.cache_response(query_text, response)
        
        return response

