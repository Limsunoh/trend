"""
user_qa/tasks.py

✅ 목적
- DB에 저장된 뉴스/커뮤니티 데이터를 "자동 임베딩"해서 Chroma(VectorDB)에 upsert 하는 Celery 태스크들

✅ 성능 개선 포인트
1) VectorDBService(=임베딩 모델 로드 포함 가능)를 프로세스 내 캐싱 → 태스크마다 모델 재로딩 방지
2) upsert 배치 크기 기본값 상향 → Chroma I/O 왕복 횟수 감소
3) (필드가 있으면) is_processed 기반으로 "재임베딩 방지" + 처리 후 bulk_update

✅ 호환성/안정성
- data_collector 쪽에서 since_iso로 실수 호출해도 터지지 않게 since_iso 파라미터도 수용
- SocialMediaPost platform은 DB필드가 아니라 @property일 수 있으므로
  qs.filter(platform=...) 금지 → qs.filter(source__platform=...) 사용
"""

from __future__ import annotations

import logging
import re
from html import unescape
from typing import Any, Dict, List, Optional

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from data_collector.models import NewsArticle, SocialMediaPost
from user_qa.services import VectorDBService

logger = logging.getLogger(__name__)

# -------------------------
# ✅ VectorDBService 캐싱 (프로세스 단위 1회 생성)
# -------------------------
_VDB_CACHE: Dict[str, VectorDBService] = {}


def _get_collection_name(collection: Optional[str]) -> str:
    return collection or getattr(settings, "CHROMA_COLLECTION", "trend_docs")


def _get_vdb(collection_name: str) -> VectorDBService:
    """
    컬렉션명 단위로 VectorDBService를 캐싱해서 재사용.
    - Celery worker 프로세스가 살아있는 동안 모델/클라이언트가 재사용되어 속도 크게 개선됨.
    """
    vdb = _VDB_CACHE.get(collection_name)
    if vdb is None:
        logger.info(
            f"[VectorDB 초기화] 컬렉션={collection_name} (프로세스 내 최초 1회)"
        )
        vdb = VectorDBService(collection_name=collection_name)
        _VDB_CACHE[collection_name] = vdb
    return vdb


# -------------------------
# 공통 유틸: since 파싱
# -------------------------
def _parse_since(since: Optional[str]) -> Optional[timezone.datetime]:
    """
    since 문자열(ISO8601)을 timezone-aware datetime으로 변환.
    - since가 None이면 None 반환
    - 문자열이 naive이면 현재 TIME_ZONE 기준으로 aware 처리
    """
    if not since:
        return None

    dt = parse_datetime(since)
    if not dt:
        return None

    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())

    return dt


# -------------------------
# 공통 유틸: 텍스트 청크 분할
# -------------------------
def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 100) -> List[str]:
    """
    긴 텍스트를 chunk_size 단위로 자르고 overlap만큼 겹치게 만들어 검색 품질을 올림.
    ✅ 성능 개선: 기본 chunk_size를 약간 키우고(overlap 줄임) 청크 수를 줄여 속도 개선
    """
    text = (text or "").strip()
    if not text:
        return []
    if chunk_size <= 0:
        return [text]

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
# ✅ 임베딩 텍스트 구성 헬퍼 (뉴스/소셜 모델에 맞춤)
# -------------------------


def _strip_html(text: str) -> str:
    """RSS description 등에 섞인 HTML 제거(간단 버전)"""
    if not text:
        return ""
    text = unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _safe_join(*parts: str) -> str:
    cleaned = []
    for p in parts:
        p = (p or "").strip()
        if p:
            cleaned.append(p)
    return "\n".join(cleaned).strip()


def build_news_embedding_text(article) -> str:
    """
    NewsArticle 모델 기준: title/description/author/category/url + source.publisher/source.category
    """
    title = (getattr(article, "title", "") or "").strip()
    desc = _strip_html(getattr(article, "description", "") or "")
    category = (getattr(article, "category", "") or "").strip()

    # ✅ 임베딩 텍스트는 "내용 중심"으로만 구성 (메타데이터는 Chroma metadata로 따로 저장)
    # - 뉴스: title + description
    # - (필요 시) author/url 등을 본문에 섞고 싶다면 getattr(article, "author"|"url", "") 추가
    return _safe_join(title, desc, category)


def build_social_embedding_text(post) -> str:
    """
    SocialMediaPost 모델 기준:
    - title/content + original_title/original_content를 함께 포함하여 검색 품질 향상
    - build_vector_index.py와 동일한 로직으로 통일
    """
    title = (getattr(post, "title", "") or "").strip()
    content = (getattr(post, "content", "") or "").strip()

    # 원본이 존재하고 번역본과 다르면 함께 포함 (검색 품질 향상)
    original_title = (getattr(post, "original_title", "") or "").strip()
    if original_title and original_title not in title:
        title = f"{title}\n(ORIGINAL) {original_title}".strip()

    original_content = (getattr(post, "original_content", "") or "").strip()
    if original_content and original_content not in content:
        content = f"{content}\n\n(ORIGINAL)\n{original_content}".strip()

    # title/content 모두 비면 원본으로 보강
    if not title:
        title = original_title
    if not content:
        content = original_content

    return _safe_join(title, content)


def _only_valid_metadata(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Chroma metadata는 JSON-serializable 원시 타입 중심이 안전함.
    dict/list 같은 구조는 string으로 강제 변환.
    """
    cleaned: Dict[str, Any] = {}
    for k, v in (raw or {}).items():
        if v is None:
            continue
        if isinstance(v, (str, int, float, bool)):
            cleaned[k] = v
        else:
            cleaned[k] = str(v)
    return cleaned


def _make_doc_id(prefix: str, obj_id: int, chunk_index: int) -> str:
    """
    문서 ID를 안정적으로 생성
    - 같은 데이터 + 같은 chunk_index => 같은 ID
    - upsert 시 덮어씌우기 가능(중복 삽입 방지)
    """
    return f"{prefix}:{obj_id}:{chunk_index}"


def _model_has_field(model, field_name: str) -> bool:
    return any(f.name == field_name for f in model._meta.get_fields())


# -------------------------
# 뉴스 임베딩 태스크
# -------------------------
@shared_task(bind=True, max_retries=3)
def embed_recent_news_articles_task(
    self,
    since: Optional[str] = None,
    collection: Optional[str] = None,
    source_id: Optional[int] = None,
    limit: int = 5000,
    chunk_size: int = 1200,
    overlap: int = 100,
    upsert_batch: int = 768,  # ✅ 기본 256 -> 768로 상향 (I/O 왕복 감소)
    # ✅ 호환성: data_collector에서 since_iso로 실수 호출해도 안 터지게 받음
    since_iso: Optional[str] = None,
) -> Dict[str, Any]:
    """
    [자동 임베딩][뉴스]
    - NewsArticle을 조회해서 VectorDBService.upsert_documents()로 저장
    """
    try:
        collection_name = _get_collection_name(collection)
        # ✅ since_iso가 들어오면 since보다 우선 적용 (호환성)
        since_dt = _parse_since(since_iso or since)

        logger.info(
            f"[임베딩 시작][뉴스] 태스크ID={self.request.id} "
            f"since={since_dt.isoformat() if since_dt else '전체'} "
            f"컬렉션={collection_name} source_id={source_id} limit={limit} "
            f"(chunk_size={chunk_size}, overlap={overlap}, upsert_batch={upsert_batch})"
        )

        vdb = _get_vdb(collection_name)

        qs = NewsArticle.objects.select_related("source").all()

        if source_id:
            qs = qs.filter(source_id=source_id)

        # ✅ since 필터: 최소 collected_at 기준으로 필터링(항상 존재하는 경우가 많음)
        if since_dt:
            qs = qs.filter(collected_at__gte=since_dt)

        # ✅ 재임베딩 방지: is_processed 필드가 있으면 처리된 것 제외
        if _model_has_field(NewsArticle, "is_processed"):
            qs = qs.filter(is_processed=False)

        qs = qs.order_by("-collected_at")[:limit]
        total_targets = qs.count()
        logger.info(
            f"[임베딩 대상 조회 완료][뉴스] 태스크ID={self.request.id} 대상기사수={total_targets}"
        )

        ids: List[str] = []
        docs: List[str] = []
        metas: List[Dict[str, Any]] = []

        processed_ids: List[int] = []
        total_chunks = 0
        total_articles = 0

        for article in qs.iterator(chunk_size=500):
            total_articles += 1

            # ✅ 임베딩용 텍스트 구성 (모델 필드에 맞게 + HTML 제거 + source 메타 포함)
            text = build_news_embedding_text(article)
            if not text:
                logger.warning(f"[뉴스 임베딩 스킵] 텍스트 없음: news_id={article.id}")
                processed_ids.append(
                    article.id
                )  # 무한 재처리 방지(원하면 이 줄 삭제 가능)
                continue

            chunks = chunk_text(text, chunk_size=chunk_size, overlap=overlap)
            if not chunks:
                logger.warning(
                    f"[뉴스 임베딩 스킵] chunk 생성 실패: news_id={article.id}"
                )
                processed_ids.append(article.id)
                continue

            src = getattr(article, "source", None)

            # ✅ 메타데이터는 build_vector_index.py와 동일한 키로 통일
            # - type: news
            # - publisher: 뉴스 소스(중앙일보/네이버/뉴시스 등)
            # - category: 기사 카테고리(없으면 소스 카테고리 fallback)
            publisher = getattr(src, "publisher", None) if src else None
            category = getattr(article, "category", None) or (
                getattr(src, "category", None) if src else None
            )

            base_meta = _only_valid_metadata(
                {
                    "type": "news",
                    "title": (getattr(article, "title", "") or "")[:200],
                    "db_id": int(article.id),
                    "source_id": (
                        int(article.source_id)
                        if article.source_id is not None
                        else None
                    ),
                    "url": getattr(article, "url", "") or "",
                    "published_at": (
                        getattr(article, "published_at", None).isoformat()
                        if getattr(article, "published_at", None)
                        else ""
                    ),
                    "publisher": publisher,
                    "category": category or "",
                    "author": getattr(article, "author", "") or "",
                    "chunk_index": 0,  # 아래에서 i로 덮어씀
                }
            )

            for i, ch in enumerate(chunks):
                ids.append(_make_doc_id("news", article.id, i))
                docs.append(ch)
                # chunk_index는 청크별로 저장
                meta_i = dict(base_meta)
                meta_i["chunk_index"] = int(i)
                metas.append(meta_i)
                total_chunks += 1

                if len(docs) >= upsert_batch:
                    logger.info(
                        f"[임베딩 업서트 진행][뉴스] 태스크ID={self.request.id} "
                        f"배치문서수={len(docs)} 누적청크={total_chunks}"
                    )
                    vdb.upsert_documents(ids=ids, documents=docs, metadatas=metas)
                    ids, docs, metas = [], [], []

            processed_ids.append(article.id)

        if docs:
            logger.info(
                f"[임베딩 업서트 진행][뉴스] 태스크ID={self.request.id} "
                f"배치문서수={len(docs)} 누적청크={total_chunks}"
            )
            vdb.upsert_documents(ids=ids, documents=docs, metadatas=metas)

        # ✅ 처리 완료 표시(is_processed가 있으면)
        if processed_ids and _model_has_field(NewsArticle, "is_processed"):
            update_kwargs = {"is_processed": True}
            if _model_has_field(NewsArticle, "processed_at"):
                update_kwargs["processed_at"] = timezone.now()
            with transaction.atomic():
                NewsArticle.objects.filter(id__in=processed_ids).update(**update_kwargs)

        logger.info(
            f"[임베딩 완료][뉴스] 태스크ID={self.request.id} "
            f"처리기사={total_articles} 생성청크={total_chunks} 컬렉션={collection_name}"
        )

        return {
            "status": "ok",
            "task_id": str(self.request.id),
            "type": "news",
            "collection": collection_name,
            "since": since_dt.isoformat() if since_dt else None,
            "source_id": source_id,
            "limit": limit,
            "processed_articles": total_articles,
            "upserted_chunks": total_chunks,
        }

    except Exception as e:
        logger.error(
            f"[임베딩 실패][뉴스] 태스크ID={self.request.id} 에러={str(e)}",
            exc_info=True,
        )
        raise self.retry(exc=e, countdown=60)


# -------------------------
# 커뮤니티 임베딩 태스크
# -------------------------
@shared_task(bind=True, max_retries=3)
def embed_recent_social_posts_task(
    self,
    since: Optional[str] = None,
    collection: Optional[str] = None,
    source_id: Optional[int] = None,
    platform: Optional[str] = None,
    limit: int = 5000,
    chunk_size: int = 1200,
    overlap: int = 100,
    upsert_batch: int = 768,  # ✅ 기본 256 -> 768
    # ✅ 호환성
    since_iso: Optional[str] = None,
) -> Dict[str, Any]:
    """
    [자동 임베딩][커뮤니티]

    ⚠️ 중요:
    - SocialMediaPost의 platform은 DB필드가 아니라 @property일 수 있음
    - 따라서 qs.filter(platform=...) 금지 → qs.filter(source__platform=...) 사용
    """
    try:
        collection_name = _get_collection_name(collection)
        since_dt = _parse_since(since_iso or since)

        logger.info(
            f"[임베딩 시작][커뮤니티] 태스크ID={self.request.id} "
            f"플랫폼={platform or '전체'} since={since_dt.isoformat() if since_dt else '전체'} "
            f"컬렉션={collection_name} source_id={source_id} limit={limit} "
            f"(chunk_size={chunk_size}, overlap={overlap}, upsert_batch={upsert_batch})"
        )

        vdb = _get_vdb(collection_name)

        qs = SocialMediaPost.objects.select_related("source").all()

        if source_id:
            qs = qs.filter(source_id=source_id)

        # ✅ platform 필터는 반드시 source__platform으로!
        if platform:
            qs = qs.filter(source__platform=platform)

        if since_dt:
            qs = qs.filter(collected_at__gte=since_dt)

        # ✅ 재임베딩 방지
        if _model_has_field(SocialMediaPost, "is_processed"):
            qs = qs.filter(is_processed=False)

        qs = qs.order_by("-collected_at")[:limit]
        total_targets = qs.count()
        logger.info(
            f"[임베딩 대상 조회 완료][커뮤니티] 태스크ID={self.request.id} 대상게시물수={total_targets}"
        )

        ids: List[str] = []
        docs: List[str] = []
        metas: List[Dict[str, Any]] = []

        processed_ids: List[int] = []
        total_chunks = 0
        total_posts = 0

        for post in qs.iterator(chunk_size=500):
            total_posts += 1

            # ✅ 임베딩용 텍스트 구성 (original_* 보강 + source 메타 포함)
            text = build_social_embedding_text(post)
            if not text:
                logger.warning(f"[소셜 임베딩 스킵] 텍스트 없음: social_id={post.id}")
                processed_ids.append(
                    post.id
                )  # 무한 재처리 방지(원하면 이 줄 삭제 가능)
                continue

            chunks = chunk_text(text, chunk_size=chunk_size, overlap=overlap)
            if not chunks:
                logger.warning(
                    f"[소셜 임베딩 스킵] chunk 생성 실패: social_id={post.id}"
                )
                processed_ids.append(post.id)
                continue

            src = getattr(post, "source", None)

            # ✅ build_vector_index.py와 동일한 키로 통일
            # - type: social
            # - platform/category/identifier/source_display는 source에서 가져옴
            src_platform = getattr(src, "platform", None) if src else None
            src_category = getattr(src, "category", None) if src else None
            src_identifier = getattr(src, "identifier", None) if src else None
            src_display = getattr(src, "display_name", None) if src else None

            base_meta = _only_valid_metadata(
                {
                    "type": "social",
                    "title": (getattr(post, "title", "") or "")[:200],
                    "db_id": int(post.id),
                    "source_id": (
                        int(post.source_id) if post.source_id is not None else None
                    ),
                    "url": getattr(post, "url", "") or "",
                    "published_at": (
                        getattr(post, "published_at", None).isoformat()
                        if getattr(post, "published_at", None)
                        else ""
                    ),
                    # ✅ 필터링 핵심
                    "platform": src_platform,  # reddit / dcinside
                    "category": src_category or "",  # ex) 갤러리/서브레딧 카테고리
                    "identifier": src_identifier,  # subreddit / gallery
                    "source_display": src_display,  # UI 표기용 이름
                    # (선택) 작성자
                    "author": getattr(post, "author", "") or "",
                    # ✅ 플랫폼 공통 지표(모델에 존재하는 것만)
                    "likes_count": getattr(post, "likes_count", None),
                    "comments_count": getattr(post, "comments_count", None),
                    "views_count": getattr(post, "views_count", None),
                    "shares_count": getattr(post, "shares_count", None),
                    # ✅ 원본 식별자
                    "platform_post_id": getattr(post, "platform_post_id", None),
                    "chunk_index": 0,  # 아래에서 i로 덮어씀
                }
            )

            for i, ch in enumerate(chunks):
                ids.append(_make_doc_id("social", post.id, i))
                docs.append(ch)
                meta_i = dict(base_meta)
                meta_i["chunk_index"] = int(i)
                metas.append(meta_i)
                total_chunks += 1

                if len(docs) >= upsert_batch:
                    logger.info(
                        f"[임베딩 업서트 진행][커뮤니티] 태스크ID={self.request.id} "
                        f"배치문서수={len(docs)} 누적청크={total_chunks}"
                    )
                    vdb.upsert_documents(ids=ids, documents=docs, metadatas=metas)
                    ids, docs, metas = [], [], []

            processed_ids.append(post.id)

        if docs:
            logger.info(
                f"[임베딩 업서트 진행][커뮤니티] 태스크ID={self.request.id} "
                f"배치문서수={len(docs)} 누적청크={total_chunks}"
            )
            vdb.upsert_documents(ids=ids, documents=docs, metadatas=metas)

        # ✅ 처리 완료 표시(is_processed가 있으면)
        if processed_ids and _model_has_field(SocialMediaPost, "is_processed"):
            update_kwargs = {"is_processed": True}
            if _model_has_field(SocialMediaPost, "processed_at"):
                update_kwargs["processed_at"] = timezone.now()
            with transaction.atomic():
                SocialMediaPost.objects.filter(id__in=processed_ids).update(
                    **update_kwargs
                )

        logger.info(
            f"[임베딩 완료][커뮤니티] 태스크ID={self.request.id} "
            f"처리게시물={total_posts} 생성청크={total_chunks} 컬렉션={collection_name}"
        )

        return {
            "status": "ok",
            "task_id": str(self.request.id),
            "type": "social",
            "collection": collection_name,
            "since": since_dt.isoformat() if since_dt else None,
            "source_id": source_id,
            "platform": platform,
            "limit": limit,
            "processed_posts": total_posts,
            "upserted_chunks": total_chunks,
        }

    except Exception as e:
        logger.error(
            f"[임베딩 실패][커뮤니티] 태스크ID={self.request.id} 에러={str(e)}",
            exc_info=True,
        )
        raise self.retry(exc=e, countdown=60)
