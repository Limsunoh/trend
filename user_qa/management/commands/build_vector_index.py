from __future__ import annotations

from typing import Dict, List, Any, Optional

from django.core.management.base import BaseCommand

from user_qa.services import VectorDBService
from data_collector.models import NewsArticle, SocialMediaPost


# -------------------------
# 1) Chunking (텍스트가 길면 잘라서 저장)
# -------------------------
def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 150) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []

    chunks: List[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + chunk_size, n)
        chunks.append(text[start:end])
        if end == n:
            break
        start = max(0, end - overlap)
    return chunks


# -------------------------
# 2) 임베딩 텍스트 생성 (임베딩 대상 = title + body/summary)
# -------------------------
def build_embedding_text(title: Optional[str], body: Optional[str]) -> str:
    parts = []
    if title and title.strip():
        parts.append(title.strip())
    if body and body.strip():
        parts.append(body.strip())
    return "\n\n".join(parts).strip()


# -------------------------
# 3) 메타데이터 정리 (값 있는 것만 자동으로 남기기)
#    - Chroma metadata는 None 금지
#    - str/int/float/bool만 허용
# -------------------------
def only_valid_metadata(meta: Dict[str, Any]) -> Dict[str, Any]:
    cleaned: Dict[str, Any] = {}
    for k, v in meta.items():
        if v is None:
            continue
        if isinstance(v, (str, int, float, bool)):
            cleaned[k] = v
        else:
            cleaned[k] = str(v)
    return cleaned


class Command(BaseCommand):
    help = "DB(NewsArticle, SocialMediaPost) → 임베딩 → Chroma VectorDB에 저장합니다."

    def add_arguments(self, parser):
        parser.add_argument("--collection", type=str, default="trend_docs")
        parser.add_argument("--limit-news", type=int, default=5000)
        parser.add_argument("--limit-social", type=int, default=5000)
        parser.add_argument("--chunk-size", type=int, default=1000)
        parser.add_argument("--overlap", type=int, default=150)

    def handle(self, *args, **opts):
        collection = opts["collection"]
        limit_news = opts["limit_news"]
        limit_social = opts["limit_social"]
        chunk_size = opts["chunk_size"]
        overlap = opts["overlap"]

        vdb = VectorDBService(collection_name=collection)

        self.stdout.write(self.style.SUCCESS(f"[VectorDB] collection={collection}"))
        self.stdout.write(self.style.SUCCESS(f"[Chunk] chunk_size={chunk_size}, overlap={overlap}"))

        news_count = self._index_news(vdb, limit_news, chunk_size, overlap)
        social_count = self._index_social(vdb, limit_social, chunk_size, overlap)

        self.stdout.write(self.style.SUCCESS(f"✅ 완료: news_chunks={news_count}, social_chunks={social_count}"))

    # ---------------------------------------
    # NewsArticle
    # - 임베딩: title + description(요약/본문)
    # - metadata(필터링): category, publisher(뉴스소스), author 등
    # ---------------------------------------
    def _index_news(self, vdb: VectorDBService, limit: int, chunk_size: int, overlap: int) -> int:
        qs = NewsArticle.objects.select_related("source").order_by("-published_at")[:limit]

        ids: List[str] = []
        docs: List[str] = []
        metas: List[Dict[str, Any]] = []

        total_chunks = 0

        for obj in qs:
            title = obj.title
            desc = obj.description  # NewsArticle에는 content가 없고 description이 핵심

            text = build_embedding_text(title, desc)
            if not text:
                continue  # 임베딩할 의미 텍스트 자체가 없으면 skip

            published_at = obj.published_at.isoformat() if obj.published_at else None

            # ✅ 뉴스에서 “중요한 2가지”
            # - publisher: 뉴스소스(중앙일보/네이버 등)
            # - category: 기사 카테고리(없으면 소스 카테고리 fallback)
            publisher = obj.source.publisher if obj.source else None
            category = obj.category or (obj.source.category if obj.source else None)

            chunks = chunk_text(text, chunk_size=chunk_size, overlap=overlap)
            for i, ch in enumerate(chunks):
                doc_id = f"news:{obj.id}:{i}"

                # 임베딩과 분리된 “필터/출처용 메타데이터”
                raw_meta = {
                    "type": "news",
                    "db_id": int(obj.id),
                    "source_id": int(obj.source_id) if obj.source_id is not None else None,
                    "url": obj.url,
                    "published_at": published_at,

                    # ✅ 필터링 핵심
                    "publisher": publisher,   # ex) 중앙일보, 네이버 등
                    "category": category,     # ex) 경제/정치/IT 등

                    # (선택) author로도 필터하고 싶으면 유지
                    "author": obj.author,

                    "chunk_index": int(i),
                }

                ids.append(doc_id)
                docs.append(ch)
                metas.append(only_valid_metadata(raw_meta))

                total_chunks += 1

                # batch upsert
                if len(docs) >= 512:
                    vdb.upsert_documents(ids=ids, documents=docs, metadatas=metas)
                    ids, docs, metas = [], [], []

        if docs:
            vdb.upsert_documents(ids=ids, documents=docs, metadatas=metas)

        return total_chunks

    # ---------------------------------------
    # SocialMediaPost
    # - 임베딩: title + content
    # - metadata(필터링): platform(dcinside/reddit), category(소스 카테고리), author 등
    # ---------------------------------------
    def _index_social(self, vdb: VectorDBService, limit: int, chunk_size: int, overlap: int) -> int:
        qs = SocialMediaPost.objects.select_related("source").order_by("-published_at")[:limit]

        ids: List[str] = []
        docs: List[str] = []
        metas: List[Dict[str, Any]] = []

        total_chunks = 0

        for obj in qs:
            title = obj.title
            content = obj.content

            text = build_embedding_text(title, content)
            if not text:
                continue

            published_at = obj.published_at.isoformat() if obj.published_at else None

            # ✅ 소셜에서 “중요한 2가지”
            # - platform: dcinside/reddit
            # - category: 소셜 카테고리(너 프로젝트에서 source.category)
            platform = obj.source.platform if obj.source else None
            category = obj.source.category if obj.source else None

            # 추가로, “어디 소스냐”를 더 좁히고 싶으면 identifier도 같이 메타로 넣는 게 좋음
            # reddit: subreddit identifier / dcinside: 갤러리 identifier
            identifier = obj.source.identifier if obj.source else None
            source_display = obj.source.display_name if obj.source else None

            chunks = chunk_text(text, chunk_size=chunk_size, overlap=overlap)
            for i, ch in enumerate(chunks):
                doc_id = f"social:{obj.id}:{i}"

                raw_meta = {
                    "type": "social",
                    "db_id": int(obj.id),
                    "source_id": int(obj.source_id) if obj.source_id is not None else None,
                    "url": obj.url,
                    "published_at": published_at,

                    # ✅ 필터링 핵심
                    "platform": platform,   # dcinside / reddit
                    "category": category,   # 너가 정의한 소셜 카테고리

                    # ✅ 더 세밀한 범위 제한(추천)
                    "identifier": identifier,          # subreddit / gallery id/name
                    "source_display": source_display,  # UI 표시용

                    # (선택) author 필터
                    "author": obj.author,

                    "chunk_index": int(i),
                }

                ids.append(doc_id)
                docs.append(ch)
                metas.append(only_valid_metadata(raw_meta))

                total_chunks += 1

                if len(docs) >= 512:
                    vdb.upsert_documents(ids=ids, documents=docs, metadatas=metas)
                    ids, docs, metas = [], [], []

        if docs:
            vdb.upsert_documents(ids=ids, documents=docs, metadatas=metas)

        return total_chunks
