from __future__ import annotations

from typing import Any, Dict, List, Optional

from django.core.management.base import BaseCommand
from django.db.models import F

from data_collector.models import NewsArticle, SocialMediaPost
from user_qa.services import VectorDBService
from user_qa.tasks import chunk_text


# -------------------------
# 임베딩 텍스트 생성 (임베딩 대상 = title + body/summary)
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
        parser.add_argument("--limit-news", type=int, default=0)
        parser.add_argument("--limit-social", type=int, default=0)
        parser.add_argument("--chunk-size", type=int, default=1000)
        parser.add_argument("--overlap", type=int, default=150)
        parser.add_argument(
            "--social-platform",
            type=str,
            default="all",
            choices=["all", "reddit", "dcinside"],
            help="소셜 임베딩 대상 플랫폼 선택 (all/reddit/dcinside)",
        )

    def handle(self, *args, **opts):
        collection = opts["collection"]
        limit_news = opts["limit_news"]
        limit_social = opts["limit_social"]
        chunk_size = opts["chunk_size"]
        overlap = opts["overlap"]
        social_platform = opts["social_platform"]

        vdb = VectorDBService(collection_name=collection)

        self.stdout.write(self.style.SUCCESS(f"[VectorDB] collection={collection}"))
        self.stdout.write(
            self.style.SUCCESS(f"[Chunk] chunk_size={chunk_size}, overlap={overlap}")
        )

        news_count = self._index_news(vdb, limit_news, chunk_size, overlap)
        social_count = self._index_social(
            vdb, limit_social, chunk_size, overlap, platform_opt=social_platform
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"✅ 완료: news_chunks={news_count}, social_chunks={social_count}"
            )
        )

    # ---------------------------------------
    # NewsArticle
    # - 임베딩: title + description(요약/본문)
    # - metadata(필터링): category, publisher(뉴스소스), author 등
    # ---------------------------------------
    def _index_news(
        self, vdb: VectorDBService, limit: int, chunk_size: int, overlap: int
    ) -> int:
        qs = NewsArticle.objects.select_related("source").order_by(
            F("published_at").desc(nulls_last=True)
        )
        if limit:
            qs = qs[:limit]

        ids: List[str] = []
        docs: List[str] = []
        metas: List[Dict[str, Any]] = []

        total_chunks = 0

        for obj in qs:
            title = obj.title
            desc = obj.description  # NewsArticle에는 content가 없고 description이 핵심

            published_at = obj.published_at.isoformat() if obj.published_at else None

            # ✅ 뉴스에서 "중요한 2가지"
            # - publisher: 뉴스소스(중앙일보/네이버 등)
            # - category: 기사 카테고리(없으면 소스 카테고리 fallback)
            publisher = obj.source.publisher if obj.source else None
            category = obj.category or (obj.source.category if obj.source else None)

            # 출처/분류/저자 정보를 포함하여 시맨틱 검색 품질 향상
            extra_parts = []
            if publisher:
                extra_parts.append(f"출처: {publisher}")
            if category:
                extra_parts.append(f"분류: {category}")
            if obj.author:
                extra_parts.append(f"기자: {obj.author}")
            extra_text = "\n".join(extra_parts)
            text = build_embedding_text(
                title, f"{desc}\n{extra_text}" if extra_text else desc
            )
            if not text:
                continue  # 임베딩할 의미 텍스트 자체가 없으면 skip

            chunks = chunk_text(text, chunk_size=chunk_size, overlap=overlap)
            for i, ch in enumerate(chunks):
                doc_id = f"news:{obj.id}:{i}"

                # 임베딩과 분리된 “필터/출처용 메타데이터”
                raw_meta = {
                    "type": "news",
                    "db_id": int(obj.id),
                    "source_id": (
                        int(obj.source_id) if obj.source_id is not None else None
                    ),
                    "url": obj.url,
                    "published_at": published_at,
                    # ✅ 필터링 핵심
                    "publisher": publisher,  # ex) 중앙일보, 네이버 등
                    "category": category,  # ex) 경제/정치/IT 등
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
    def _index_social(
        self,
        vdb: VectorDBService,
        limit: int,
        chunk_size: int,
        overlap: int,
        platform_opt: str = "all",
    ) -> int:
        qs = SocialMediaPost.objects.select_related("source").order_by(
            F("published_at").desc(nulls_last=True)
        )

        # ✅ 플랫폼 필터링 (source.platform 기반)
        if platform_opt and platform_opt != "all":
            qs = qs.filter(source__platform=platform_opt)

        if limit:
            qs = qs[:limit]

        ids: List[str] = []
        docs: List[str] = []
        metas: List[Dict[str, Any]] = []

        total_chunks = 0

        for obj in qs:
            # ✅ 임베딩 텍스트: title + content (+ original_* 선택적으로 합치기)
            title = obj.title
            content = obj.content

            # Reddit 같은 경우 번역본(title/content) + 원문(original_*) 둘 다 보관 중이니까,
            # 임베딩 품질 올리고 싶으면 함께 넣는 게 보통 유리함
            if obj.original_title and obj.original_title.strip():
                title = (title or "").strip()
                ot = obj.original_title.strip()
                if ot and ot not in title:
                    title = f"{title}\n(ORIGINAL) {ot}".strip()

            if obj.original_content and obj.original_content.strip():
                content = (content or "").strip()
                oc = obj.original_content.strip()
                if oc and oc not in content:
                    content = f"{content}\n\n(ORIGINAL)\n{oc}".strip()

            text = build_embedding_text(title, content)
            if not text:
                continue

            published_at = obj.published_at.isoformat() if obj.published_at else None

            # ✅ 소스 기반 필터 메타 (핵심)
            src_platform = obj.source.platform if obj.source else None
            src_category = obj.source.category if obj.source else None
            src_identifier = obj.source.identifier if obj.source else None
            src_display = obj.source.display_name if obj.source else None

            chunks = chunk_text(text, chunk_size=chunk_size, overlap=overlap)
            for i, ch in enumerate(chunks):
                doc_id = f"social:{obj.id}:{i}"

                # ✅ “검색/필터링/출처 확인”에 필요한 것 위주로 metadata 구성
                # Chroma metadata는 None 금지라 only_valid_metadata로 정리
                raw_meta = {
                    "type": "social",
                    "db_id": int(obj.id),
                    "source_id": (
                        int(obj.source_id) if obj.source_id is not None else None
                    ),
                    "url": obj.url,
                    "published_at": published_at,
                    # 필터링 핵심
                    "platform": src_platform,  # reddit / dcinside
                    "category": src_category,
                    "identifier": src_identifier,  # subreddit / gallery
                    "source_display": src_display,
                    # 선택: 작성자 필터
                    "author": obj.author,
                    # ✅ 플랫폼 공통 지표(모델에 존재하는 것만 넣기)
                    "likes_count": getattr(obj, "likes_count", None),
                    "comments_count": getattr(obj, "comments_count", None),
                    "views_count": getattr(obj, "views_count", None),
                    "shares_count": getattr(obj, "shares_count", None),
                    # ✅ DCInside/Reddit 등에서 유용한 원본 식별자
                    "platform_post_id": obj.platform_post_id,
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
