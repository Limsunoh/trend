"""
검색 확장, 랭킹, 컨텍스트 구성
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Tuple

from django.db.models import Q

from data_collector.models import SocialMediaPost

from .constants import SEARCH_EXPANSION_RULES
from .query_analysis import _tokens_ko_simple
from .vector_db import SearchResult, _infer_type

logger = logging.getLogger(__name__)


def _expand_query_for_search(query_text: str, key_entities: List[str]) -> List[str]:
    """
    구어체 쿼리를 뉴스 문체 변형으로 확장.
    LLM 호출 없이 패턴 기반으로 생성하여 시맨틱 검색 커버리지 향상.
    """
    expanded = [query_text]
    q_lower = query_text.lower()

    if not key_entities:
        return expanded

    entity_str = " ".join(key_entities[:3])

    # 상수로 분리된 확장 룰 적용
    for keywords, suffix in SEARCH_EXPANSION_RULES:
        if any(kw in q_lower for kw in keywords):
            expanded.append(f"{entity_str} {suffix}")

    # 기본: 엔티티 + "뉴스" (뉴스 헤드라인 스타일 매칭)
    if len(expanded) == 1:
        expanded.append(f"{entity_str} 뉴스")

    return expanded[:4]


def _keyword_overlap_count(query: str, text: str) -> int:
    """
    키워드 매칭 개수 계산.
    토큰 교집합 또는 substring 포함 중 하나만 카운트하여 이중 계산 방지.
    """
    q_tokens = _tokens_ko_simple(query)
    if not q_tokens:
        return 0
    t_tokens = _tokens_ko_simple(text)
    text_lower = text.lower()

    score = 0
    for word in q_tokens:
        if word in t_tokens:
            score += 1
        elif word in text_lower:
            score += 1
    return score


def rank_results_generic(
    query_text: str,
    results: List[SearchResult],
    *,
    final_k: int,
    min_keyword_hits: int = 1,
) -> List[SearchResult]:
    """
    후보군을 '키워드 포함(overlap) 우선'으로 재랭킹하여 top_k 선택
    """
    if not results:
        return []

    scored: List[Tuple[int, float, SearchResult]] = []
    for r in results:
        meta = r.metadata or {}
        title = meta.get("title") or ""
        excerpt = meta.get("excerpt") or ""
        doc = getattr(r, "document", "") or ""
        combined = f"{title}\n{excerpt}\n{doc}"

        overlap = _keyword_overlap_count(query_text, combined)
        dist = getattr(r, "distance", 1.0) or 1.0
        scored.append((overlap, dist, r))

    scored.sort(key=lambda x: (-x[0], x[1]))
    picked = [r for (ov, _d, r) in scored if ov >= min_keyword_hits][:final_k]

    if len(picked) < final_k:
        rest = [r for (ov, _d, r) in scored if r not in picked]
        picked.extend(rest[: final_k - len(picked)])

    return picked[:final_k]


def _search_reddit_by_title(
    query_text: str,
    key_entities: List[str],
    limit: int = 5,
) -> List[SearchResult]:
    """
    Reddit 글을 DB에서 제목 키워드 매칭으로 직접 검색.
    벡터 검색에서 누락될 수 있는 본문 없는 Reddit 글을 보완.
    """
    search_terms = key_entities[:3] if key_entities else []

    if not search_terms:
        tokens = _tokens_ko_simple(query_text)
        search_terms = list(tokens)[:3]

    if not search_terms:
        return []

    q_filter = Q()
    for term in search_terms:
        q_filter |= Q(title__icontains=term) | Q(original_title__icontains=term)

    posts = (
        SocialMediaPost.objects.filter(q_filter, source__platform="reddit")
        .select_related("source")
        .order_by("-published_at")[:limit]
    )

    results: List[SearchResult] = []
    for post in posts:
        src = post.source
        title = (post.title or "").strip()
        content = (post.content or "").strip()
        document = f"{title}\n{content}".strip() if content else title

        meta = {
            "type": "social",
            "db_id": post.id,
            "source_id": post.source_id,
            "url": post.url or "",
            "title": title[:200],
            "published_at": post.published_at.isoformat() if post.published_at else "",
            "platform": getattr(src, "platform", "reddit"),
            "identifier": getattr(src, "identifier", ""),
            "source_display": getattr(src, "display_name", ""),
            "author": post.author or "",
            "likes_count": post.likes_count,
            "comments_count": post.comments_count,
        }
        meta = {k: v for k, v in meta.items() if v is not None}

        results.append(
            SearchResult(
                id=f"reddit_db:{post.id}",
                document=document,
                metadata=meta,
                distance=0.5,
            )
        )

    if results:
        logger.info(f"[Reddit DB 검색] 키워드={search_terms} → {len(results)}개 발견")

    return results


def _recency_score(published_at: str, now_ts: float) -> float:
    """
    published_at ISO 문자열 → 최근일수록 높은 점수 (0.0~1.0).
    """
    if not published_at:
        return 0.0
    try:
        dt = datetime.fromisoformat(published_at)
        days_ago = max((now_ts - dt.timestamp()) / 86400, 0)
        return 1.0 / (1.0 + days_ago / 7.0)
    except Exception:
        return 0.0


def _build_context_and_sources(
    results: List[SearchResult],
    max_doc_chars: int = 1200,
    *,
    evidence_quality: str = "adequate",
    source_intent: str = "any",
) -> Tuple[str, List[Dict[str, Any]]]:
    blocks: List[str] = []
    sources: List[Dict[str, Any]] = []

    for r in results:
        meta = r.metadata or {}
        url = meta.get("url")
        doc_type = _infer_type(r.id, meta)

        if doc_type == "news":
            source_label = meta.get("publisher") or "뉴스"
        elif doc_type == "social":
            _parts = [
                p
                for p in [
                    meta.get("platform"),
                    meta.get("identifier") or meta.get("category"),
                ]
                if p
            ]
            source_label = "/".join(_parts) if _parts else "커뮤니티"
        else:
            source_label = doc_type or "기타"

        type_tag = (
            "[뉴스]"
            if doc_type == "news"
            else "[커뮤니티]" if doc_type == "social" else "[기타]"
        )

        blocks.append(
            f"{type_tag} 출처: {source_label} | 날짜: {meta.get('published_at', '')} | 관련도: {r.distance:.3f}\n"
            f"{(r.document or '')[:max_doc_chars]}"
        )

        sources.append(
            {
                "id": r.id,
                "distance": r.distance,
                "url": url,
                "title": meta.get("title") or "",
                "type": (doc_type or None),
                "platform": meta.get("platform"),
                "publisher": meta.get("publisher"),
                "category": meta.get("category"),
                "identifier": meta.get("identifier"),
                "source_display": meta.get("source_display"),
                "published_at": meta.get("published_at"),
                "excerpt": (r.document or "")[:300],
            }
        )

    header_lines = []
    if source_intent != "any":
        header_lines.append(f"[SOURCE_FILTER: {source_intent}]")
    if evidence_quality == "low":
        header_lines.append(
            "[EVIDENCE_QUALITY: LOW] 검색된 자료의 관련성이 낮을 수 있습니다. "
            "자료 내용을 바탕으로 답변하되, 관련 자료가 전혀 없다면 솔직하게 알려주세요."
        )
    header = "\n".join(header_lines)

    context_body = "\n\n---\n\n".join(blocks)
    return f"{header}\n\n{context_body}", sources
