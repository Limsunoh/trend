"""
벡터DB 및 RAG 서비스
"""
import os
import time
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from django.conf import settings

import chromadb
from chromadb.config import Settings as ChromaSettings
from sentence_transformers import SentenceTransformer

from common.redis_services import RAGCacheService
from .models import QueryHistory
from django.db.models import Max
from data_collector.models import NewsArticle, SocialMediaPost


logger = logging.getLogger(__name__)

def _get_setting(name: str, default: Any = None) -> Any:
    return getattr(settings, name, default)


@dataclass
class SearchResult:
    id: str
    document: str
    metadata: Dict[str, Any]
    distance: float


@dataclass
class LLMResult:
    text: str
    raw: Any = None


class VectorDBService:
    """
    Chroma Persistent Vector DB service
    - collection: trend_docs (default)
    - embeddings: SentenceTransformer(settings.EMBEDDING_MODEL)
    """

    def __init__(self, collection_name: str | None = None):
        self.persist_dir: str = str(_get_setting("CHROMA_PERSIST_DIR", "./chroma_db"))
        self.collection_name: str = collection_name or _get_setting("CHROMA_COLLECTION", "trend_docs")

        model_name: str = _get_setting(
            "EMBEDDING_MODEL",
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        )
        self.embedder = SentenceTransformer(model_name)

        self.client = chromadb.PersistentClient(
            path=self.persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(name=self.collection_name)

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        vectors = self.embedder.encode(
            texts,
            batch_size=64,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
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

    def similarity_search(
        self,
        query_text: str,
        top_k: int = 5,
        distance_threshold: float = 0.15,
        fetch_multiplier: int = 2,
        *,
        balance_types: bool = True,   # ✅ 추가
    ) -> List[SearchResult]:
        """
        유사도 검색

        balance_types=True  : (기존) 뉴스/소셜 균형 선택 로직 적용
        balance_types=False : 후보군만 거리순으로 반환(재랭킹 전용)
        """
        q_emb = self.embed_texts([query_text])[0]

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
            logger.debug(f"[similarity_search] 임계값 이하 결과: {len(candidates)}개")

        candidates.sort(key=lambda x: x.distance)

        # ✅ 재랭킹 후보군 용도면 "강제 균형" 제거
        if not balance_types:
            return candidates[:top_k]

        # ---------------------------
        # (기존 로직 유지) 타입별로 균형 있게 선택
        # ---------------------------
        news_results = [r for r in candidates if _infer_type(r.id, r.metadata) == "news"]
        social_results = [r for r in candidates if _infer_type(r.id, r.metadata) == "social"]
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

    def keyword_search(
        self,
        query_text: str,
        keywords: List[str],
        top_k: int = 20,
    ) -> List[SearchResult]:
        """
        키워드 포함 문서를 필터링한 후 시맨틱 유사도로 정렬.

        Args:
            query_text: 시맨틱 유사도 계산용 쿼리
            keywords: 문서에 포함되어야 할 키워드 리스트 (OR 조건)
            top_k: 반환할 최대 결과 수

        Returns:
            키워드 포함 문서 중 시맨틱 유사도 순으로 정렬된 결과
        """
        if not keywords:
            return []

        q_emb = self.embed_texts([query_text])[0]

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

        # 거리순 정렬
        all_results.sort(key=lambda x: x.distance)

        logger.debug(
            f"[keyword_search] 키워드 {keywords} → {len(all_results)}개 결과"
        )

        return all_results[:top_k]


def _extract_key_entities(query_text: str) -> List[str]:
    """
    쿼리에서 핵심 엔티티(인명, 기관명, 고유명사 등)를 추출.
    하이브리드 검색의 키워드 필터링에 사용.

    공백 기준으로 토큰을 분리한 뒤 조사를 제거하여,
    문자열 중간에서 잘못된 엔티티가 추출되는 것을 방지.

    예: "요즘 커뮤니티에서 이재명에 대해 어떻게 생각해?" → ["이재명"]
    예: "트럼프 관세 정책 반응" → ["트럼프"]
    예: "삼성전자 주가 전망" → ["삼성전자"]

    Returns:
        추출된 엔티티 리스트 (최대 3개)
    """
    query = (query_text or "").strip()
    if not query:
        return []

    entities: List[str] = []

    common_words = {
        "최근", "요즘", "오늘", "내일", "어제", "지금", "우리", "그들", "여기", "거기",
        "어떻게", "무엇", "언제", "어디", "왜", "누가", "얼마나",
        "정말", "아주", "매우", "너무", "조금", "많이", "적게",
        "그리고", "하지만", "그러나", "또한", "그래서", "따라서",
        "대통령", "장관", "의원", "기자", "교수", "대표", "사장",
        "생각", "의견", "반응", "전망", "분석", "정리", "요약",
        "상황", "현황", "동향", "추세", "변화", "영향", "결과",
    }

    # 1. 공백 기준 토큰 분리 → 조사 제거 → 엔티티 판별
    tokens = query.split()
    for token in tokens:
        # 영문 고유명사 (대문자로 시작하거나 전체 대문자)
        eng_match = re.match(r'^([A-Z][a-zA-Z]*|[A-Z]{2,})\b', token)
        if eng_match:
            word = eng_match.group(1)
            if len(word) >= 2 and word not in entities:
                entities.append(word)
            continue

        # 한글이 포함되지 않은 토큰은 스킵
        if not re.search(r'[가-힣]', token):
            continue

        # 한글 토큰: 조사 제거
        stripped = _strip_ko_particles(token)

        # 불용어/일반 단어 제외
        if stripped in _STOP_TOKENS or stripped in common_words:
            continue

        # 2-4글자 순수 한글 → 엔티티 후보
        if re.match(r'^[가-힣]{2,4}$', stripped) and stripped not in entities:
            entities.append(stripped)
            continue

        # 5글자 이상: 동사/어미 접미사를 제거하여 명사 추출
        # 예: "비트코인알려줘" → "비트코인", "트럼프어떻게생각해" → "트럼프"
        if len(stripped) >= 5 and re.match(r'^[가-힣]+$', stripped):
            for suffix in _VERB_SUFFIXES:
                if stripped.endswith(suffix) and len(stripped) > len(suffix):
                    candidate = stripped[:-len(suffix)]
                    if (2 <= len(candidate) <= 4
                            and candidate not in _STOP_TOKENS
                            and candidate not in common_words
                            and candidate not in entities):
                        entities.append(candidate)
                    break

    # 2. 한글 복합어/기관명 (전체 텍스트에서 검색)
    # 예: 삼성전자, 현대자동차, 민주당, 국민의힘
    compound_pattern = re.compile(r'([가-힣]{3,}(?:전자|자동차|그룹|증권|은행|보험|제약|바이오|엔터|미디어|당|의힘|연합|연대|회의|위원회|청와대|국회|정부))')
    for match in compound_pattern.finditer(query):
        word = match.group(1)
        if word not in entities:
            entities.append(word)

    # 최대 3개만 반환
    return entities[:3]


_STOP_TOKENS = {
    "관련", "관련된", "이슈", "알려줘", "뉴스", "소식", "정리", "오늘", "요즘", "사건", "이벤트", "트렌드",
    "대해", "대한", "대해서", "무엇", "어떤", "어떻게", "알려", "설명", "해줘",
}

# 5글자 이상 토큰에서 동사/어미 접미사를 제거하기 위한 패턴 (긴 것부터 매칭)
_VERB_SUFFIXES = [
    "어떻게생각해", "어떻게됐어", "어떻게해",
    "알려줘봐", "알려줘요", "알려주세요", "알려달라", "알려줄래",
    "해줘요", "봐줘요", "줘봐요",
    "있나요", "있어요", "인가요", "일까요", "인데요",
    "알려줘", "해줘", "봐줘", "줘봐", "할까", "일까", "인가",
    "뭐야", "뭐냐", "뭐임",
    "있어", "있나", "있냐", "인지", "인데", "이야",
    "했던", "한다", "했다", "하는",
    "줘", "해",
]

# 한국어 조사 제거 패턴 (긴 조사를 먼저 매칭하여 오동작 방지)
_KO_PARTICLE_RE = re.compile(
    r'(?:에서의|으로의|에서도|으로도|에서는|이라는|'
    r'관련|관한|따른|대해|대한|관해|통해|위해|위한|'
    r'에서|으로|에게|한테|부터|까지|처럼|보다|라고|이라|라는|에는|에도|'
    r'은|는|이|가|을|를|에|의|와|과|로|도|만|께|된)$'
)


def _strip_ko_particles(token: str) -> str:
    """한국어 토큰에서 조사를 제거하여 어근을 추출 (간단 버전)"""
    stripped = _KO_PARTICLE_RE.sub("", token)
    # 어근이 2글자 미만이면 원본 유지 (과잉 제거 방지)
    if len(stripped) >= 2:
        return stripped
    return token


def _tokens_ko_simple(s: str) -> set[str]:
    """
    "완전 무관 제거" 목적의 초간단 토큰화 (한글/영문/숫자 2글자 이상)
    - 한국어 조사를 제거하여 "시진핑에" → "시진핑"으로 정규화
    - 동사/어미 접미사를 제거하여 "뉴스알려줘" → "뉴스"로 정규화
    """
    s = (s or "").lower()
    raw_toks = set(re.findall(r"[0-9a-zA-Z가-힣]{2,}", s))
    toks = set()
    for t in raw_toks:
        stripped = _strip_ko_particles(t)
        # 5글자 이상 한글 토큰: 동사/어미 접미사 제거 (예: "뉴스알려줘" → "뉴스")
        if len(stripped) >= 5 and re.match(r'^[가-힣]+$', stripped):
            for suffix in _VERB_SUFFIXES:
                if stripped.endswith(suffix) and len(stripped) > len(suffix):
                    candidate = stripped[:-len(suffix)]
                    if len(candidate) >= 2:
                        stripped = candidate
                    break
        toks.add(stripped)
    return toks - _STOP_TOKENS

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
            # 토큰화에서 놓쳤지만 substring으로는 존재하는 경우에만 추가
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
    (2) 후보군을 '키워드 포함(overlap) 우선'으로 재랭킹하여 top_k 선택

    - overlap(키워드 포함 개수) > 0 인 문서를 최우선
    - overlap이 같으면 distance(작을수록 유사)로 정렬
    - 그래도 부족하면 overlap=0 후보를 distance 순으로 보충
    """
    if not results:
        return []

    scored: List[Tuple[int, float, SearchResult]] = []  # (overlap, distance, result)
    for r in results:
        meta = r.metadata or {}
        title = meta.get("title") or ""
        excerpt = meta.get("excerpt") or ""
        doc = getattr(r, "document", "") or ""
        combined = f"{title}\n{excerpt}\n{doc}"

        overlap = _keyword_overlap_count(query_text, combined)
        dist = getattr(r, "distance", 1.0) or 1.0
        scored.append((overlap, dist, r))

    # 1) overlap 우선(내림차순) + distance 보조(오름차순)
    scored.sort(key=lambda x: (-x[0], x[1]))

    # 2) 먼저 overlap >= min_keyword_hits 를 채움
    picked = [r for (ov, _d, r) in scored if ov >= min_keyword_hits][:final_k]

    # 3) 부족하면 나머지(ov < min_keyword_hits) 중 distance 좋은 순으로 보충
    if len(picked) < final_k:
        rest = [r for (ov, _d, r) in scored if r not in picked]
        picked.extend(rest[: final_k - len(picked)])

    return picked[:final_k]



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


def _search_reddit_by_title(
    query_text: str,
    key_entities: List[str],
    limit: int = 5,
) -> List[SearchResult]:
    """
    Reddit 글을 DB에서 제목 키워드 매칭으로 직접 검색.
    벡터 검색에서 누락될 수 있는 본문 없는 Reddit 글을 보완.

    1) 추출된 엔티티가 제목에 포함된 Reddit 글 검색
    2) 엔티티 없으면 쿼리 토큰으로 제목 검색
    3) SearchResult 포맷으로 변환하여 반환
    """
    from django.db.models import Q

    search_terms = key_entities[:3] if key_entities else []

    # 엔티티가 없으면 쿼리에서 2글자 이상 토큰 추출
    if not search_terms:
        tokens = _tokens_ko_simple(query_text)
        search_terms = list(tokens)[:3]

    if not search_terms:
        return []

    # 제목에 키워드가 포함된 Reddit 글 검색 (OR 조건)
    q_filter = Q()
    for term in search_terms:
        q_filter |= Q(title__icontains=term) | Q(original_title__icontains=term)

    posts = (
        SocialMediaPost.objects
        .filter(q_filter, source__platform="reddit")
        .select_related("source")
        .order_by("-published_at")[:limit]
    )

    results: List[SearchResult] = []
    for post in posts:
        src = post.source
        # 제목 + 본문(있으면) 결합하여 document로 사용
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
        # None 값 제거 (Chroma 호환)
        meta = {k: v for k, v in meta.items() if v is not None}

        results.append(SearchResult(
            id=f"reddit_db:{post.id}",
            document=document,
            metadata=meta,
            distance=0.5,  # DB 검색이므로 중간 거리값 부여
        ))

    if results:
        logger.info(
            f"[Reddit DB 검색] 키워드={search_terms} → {len(results)}개 발견"
        )

    return results


def _detect_source_intent(query_text: str) -> str:
    """
    사용자가 뉴스/커뮤니티 중 어떤 출처를 원하는지 키워드 기반으로 판별.
    LLM 호출 없이 순수 키워드 매칭.

    Returns: "news", "community", or "any"
    """
    q = (query_text or "").strip().lower()

    news_keywords = [
        "뉴스", "기사", "보도", "언론", "신문", "매체",
        "보도자료", "속보", "헤드라인",
        "방송", "취재", "리포트", "보도내용",
        "news", "article", "press", "report",
    ]
    community_keywords = [
        "커뮤니티", "게시글", "게시판", "반응", "여론", "댓글",
        "디시", "dcinside", "레딧", "reddit",
        "갤러리", "유저", "네티즌", "온라인반응", "온라인 반응",
        "SNS", "소셜", "트위터", "엑스", "인스타", "페이스북",
        "유튜브", "블로그", "카페", "클리앙", "루리웹", "에펨코리아",
    ]

    has_news = any(kw in q for kw in news_keywords)
    has_community = any(kw in q for kw in community_keywords)

    if has_news and not has_community:
        return "news"
    if has_community and not has_news:
        return "community"
    return "any"


def _detect_time_scope(query_text: str, intent_time_focus: str = "") -> int:
    """
    쿼리의 시간 범위를 일(day) 단위로 반환.
    0 = 시간 제약 없음, N = 최근 N일 이내 문서 우선/필터.

    예: "오늘 이슈" → 1, "최근 뉴스" → 7, "요즘 핫한" → 14
    """
    q = (query_text or "").strip().lower()

    # 강한 시간 신호 (좁은 범위)
    if any(kw in q for kw in ["오늘", "today", "방금", "지금"]):
        return 1
    if any(kw in q for kw in ["어제", "yesterday"]):
        return 2
    if any(kw in q for kw in ["이번주", "이번 주", "금주"]):
        return 7

    # 중간 시간 신호
    if any(kw in q for kw in ["최근", "최신", "요즘", "요새", "핫한", "핫이슈",
                                "트렌드", "트렌딩", "인기", "화제", "떠오르는"]):
        return 14
    if any(kw in q for kw in ["이번달", "이번 달", "금월"]):
        return 30

    # intent_info의 time_focus 활용
    if intent_time_focus == "recent":
        return 14
    if intent_time_focus == "current":
        return 30

    return 0


def _recency_score(published_at: str, now_ts: float) -> float:
    """
    published_at ISO 문자열 → 최근일수록 높은 점수 (0.0~1.0).
    decay: 7일 지나면 0.5, 30일 지나면 ~0.19, 90일 지나면 ~0.07
    """
    if not published_at:
        return 0.0
    try:
        from datetime import datetime, timezone
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

        # LLM이 이해하기 쉬운 출처 라벨 (publisher=None 등 raw 값 노출 방지)
        if doc_type == "news":
            source_label = meta.get("publisher") or "뉴스"
        elif doc_type == "social":
            _parts = [p for p in [meta.get("platform"), meta.get("identifier") or meta.get("category")] if p]
            source_label = "/".join(_parts) if _parts else "커뮤니티"
        else:
            source_label = doc_type or "기타"

        type_tag = "[뉴스]" if doc_type == "news" else "[커뮤니티]" if doc_type == "social" else "[기타]"

        blocks.append(
            f"{type_tag} 출처: {source_label} | 날짜: {meta.get('published_at', '')} | 관련도: {r.distance:.3f}\n"
            f"{(r.document or '')[:max_doc_chars]}"
        )

        sources.append({
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
        })

    header_lines = [f"[EVIDENCE_QUALITY: {evidence_quality}]"]
    if source_intent != "any":
        header_lines.append(f"[SOURCE_FILTER: {source_intent}]")
    header = "\n".join(header_lines)

    context_body = "\n\n---\n\n".join(blocks)
    return f"{header}\n\n{context_body}", sources


class OpenAIResponsesLLM:
    """
    ✅ OpenAI Responses API 기반 LLM 래퍼 (안정성/호환성 강화)
    - SDK 응답 구조가 dict/object 어느 쪽이든 텍스트 추출
    - 모델이 지원하지 않는 파라미터로 400 나면 자동 제거 후 1회 재시도
    """

    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY") or getattr(settings, "OPENAI_API_KEY", None)
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY가 설정되어 있지 않습니다. (.env 확인)")

        # ✅ httpx 주입으로 'proxies' 충돌 방어
        try:
            import httpx
            from openai import OpenAI

            _llm_timeout = int(os.getenv("OPENAI_API_TIMEOUT", 45))
            http_client = httpx.Client(timeout=httpx.Timeout(_llm_timeout, connect=10.0))
            self.client = OpenAI(api_key=api_key, http_client=http_client)
        except Exception as e:
            raise RuntimeError(
                f"OpenAI 클라이언트 초기화 실패: {e}\n"
                f"권장: pip install -U openai httpx"
            )

    def _response_to_dict(self, res: Any) -> Dict[str, Any]:
        """
        응답 객체를 dict로 변환 (디버깅용)
        """
        try:
            if hasattr(res, "model_dump"):
                return res.model_dump()
            elif hasattr(res, "dict"):
                return res.dict()
            elif hasattr(res, "__dict__"):
                return res.__dict__.copy()
            elif isinstance(res, dict):
                return res
        except Exception:
            pass
        return {}

    def _extract_text_recursive(self, obj: Any, depth: int = 0, max_depth: int = 3) -> List[str]:
        """
        객체를 재귀적으로 탐색하여 텍스트를 찾음
        """
        if depth > max_depth:
            return []
        
        texts = []
        
        # 문자열인 경우
        if isinstance(obj, str) and obj.strip():
            texts.append(obj.strip())
        
        # 딕셔너리인 경우
        elif isinstance(obj, dict):
            # 우선순위가 높은 키부터 확인
            priority_keys = ["text", "content", "output_text", "message", "output"]
            for key in priority_keys:
                if key in obj:
                    found = self._extract_text_recursive(obj[key], depth + 1, max_depth)
                    if found:
                        texts.extend(found)
            
            # 나머지 키들도 확인
            for key, value in obj.items():
                if key not in priority_keys:
                    found = self._extract_text_recursive(value, depth + 1, max_depth)
                    if found:
                        texts.extend(found)
        
        # 리스트인 경우
        elif isinstance(obj, list):
            for item in obj:
                found = self._extract_text_recursive(item, depth + 1, max_depth)
                if found:
                    texts.extend(found)
        
        # 객체인 경우 (속성 확인)
        elif hasattr(obj, "__dict__"):
            # 우선순위 속성 확인
            priority_attrs = ["text", "content", "output_text", "message", "output"]
            for attr in priority_attrs:
                if hasattr(obj, attr):
                    value = getattr(obj, attr)
                    found = self._extract_text_recursive(value, depth + 1, max_depth)
                    if found:
                        texts.extend(found)
        
        return texts

    def _extract_text(self, res: Any) -> str:
        """
        OpenAI 응답에서 텍스트를 최대한 안전하게 추출
        """
        # 방법 1: output_text 속성 직접 확인
        text = getattr(res, "output_text", None)
        if isinstance(text, str) and text.strip():
            return text.strip()

        # 방법 2: output 배열 처리
        out = getattr(res, "output", None)
        if out is not None:
            chunks = []
            
            # output이 리스트인 경우
            if isinstance(out, list):
                for item in out:
                    # item이 dict인 경우
                    if isinstance(item, dict):
                        item_type = item.get("type")
                        
                        # reasoning 타입인 경우 summary 확인
                        if item_type == "reasoning":
                            summary = item.get("summary")
                            if isinstance(summary, list) and len(summary) > 0:
                                # summary가 리스트인 경우 텍스트 추출
                                for s in summary:
                                    if isinstance(s, dict):
                                        text_val = s.get("text") or s.get("content")
                                        if isinstance(text_val, str) and text_val.strip():
                                            chunks.append(text_val.strip())
                                    elif isinstance(s, str) and s.strip():
                                        chunks.append(s.strip())
                            # summary가 문자열인 경우
                            elif isinstance(summary, str) and summary.strip():
                                chunks.append(summary.strip())
                        
                        # content 필드 확인
                        content = item.get("content")
                        if isinstance(content, str) and content.strip():
                            chunks.append(content.strip())
                        elif isinstance(content, list):
                            # content가 리스트인 경우 (예: [{"type": "text", "text": "..."}])
                            for c in content:
                                if isinstance(c, dict):
                                    # type이 text 또는 output_text인 경우
                                    if c.get("type") in ("text", "output_text", "text_delta"):
                                        text_val = c.get("text") or c.get("content")
                                        if isinstance(text_val, str) and text_val.strip():
                                            chunks.append(text_val.strip())
                                    # text 필드가 직접 있는 경우
                                    elif "text" in c and isinstance(c["text"], str) and c["text"].strip():
                                        chunks.append(c["text"].strip())
                        # text 필드가 직접 있는 경우
                        if "text" in item and isinstance(item["text"], str) and item["text"].strip():
                            chunks.append(item["text"].strip())
                    # item이 객체인 경우
                    else:
                        item_type = getattr(item, "type", None)
                        
                        # reasoning 타입인 경우 summary 확인
                        if item_type == "reasoning":
                            summary = getattr(item, "summary", None)
                            if isinstance(summary, list) and len(summary) > 0:
                                for s in summary:
                                    if hasattr(s, "text"):
                                        text_val = getattr(s, "text")
                                        if isinstance(text_val, str) and text_val.strip():
                                            chunks.append(text_val.strip())
                                    elif isinstance(s, str) and s.strip():
                                        chunks.append(s.strip())
                            elif isinstance(summary, str) and summary.strip():
                                chunks.append(summary.strip())
                        
                        content = getattr(item, "content", None)
                        if isinstance(content, str) and content.strip():
                            chunks.append(content.strip())
                        elif hasattr(item, "text") and isinstance(getattr(item, "text"), str):
                            text_val = getattr(item, "text")
                            if text_val.strip():
                                chunks.append(text_val.strip())
            
            # output이 dict인 경우
            elif isinstance(out, dict):
                if "text" in out and isinstance(out["text"], str) and out["text"].strip():
                    chunks.append(out["text"].strip())
                if "content" in out:
                    content = out["content"]
                    if isinstance(content, str) and content.strip():
                        chunks.append(content.strip())
                    elif isinstance(content, list):
                        for c in content:
                            if isinstance(c, dict) and "text" in c:
                                text_val = c.get("text")
                                if isinstance(text_val, str) and text_val.strip():
                                    chunks.append(text_val.strip())
            
            if chunks:
                joined = "\n".join(chunks).strip()
                if joined:
                    return joined

        # 방법 3: choices 배열 확인 (일부 모델)
        choices = getattr(res, "choices", None)
        if isinstance(choices, list) and len(choices) > 0:
            choice = choices[0]
            if isinstance(choice, dict):
                message = choice.get("message", {})
                if isinstance(message, dict) and "content" in message:
                    content = message["content"]
                    if isinstance(content, str) and content.strip():
                        return content.strip()
            elif hasattr(choice, "message"):
                message = getattr(choice, "message")
                content = getattr(message, "content", None)
                if isinstance(content, str) and content.strip():
                    return content.strip()

        # 방법 4: text 속성 직접 확인
        text_attr = getattr(res, "text", None)
        if isinstance(text_attr, str) and text_attr.strip():
            return text_attr.strip()

        # 방법 5: dict로 변환해서 확인
        try:
            res_dict = self._response_to_dict(res)
            if res_dict:
                # output_text 확인
                if "output_text" in res_dict and isinstance(res_dict["output_text"], str):
                    if res_dict["output_text"].strip():
                        return res_dict["output_text"].strip()
                
                # output 확인
                if "output" in res_dict:
                    out = res_dict["output"]
                    if isinstance(out, list) and len(out) > 0:
                        for item in out:
                            if isinstance(item, dict):
                                if "text" in item and isinstance(item["text"], str) and item["text"].strip():
                                    return item["text"].strip()
                                if "content" in item:
                                    content = item["content"]
                                    if isinstance(content, str) and content.strip():
                                        return content.strip()
                
                # text 직접 확인
                if "text" in res_dict and isinstance(res_dict["text"], str):
                    if res_dict["text"].strip():
                        return res_dict["text"].strip()
        except Exception:
            pass

        # 방법 6: 재귀적 탐색 (최후의 수단)
        try:
            recursive_texts = self._extract_text_recursive(res)
            if recursive_texts:
                # 가장 긴 텍스트를 반환 (일반적으로 가장 완전한 답변)
                longest = max(recursive_texts, key=len)
                if longest.strip():
                    logger.debug(f"[LLM 텍스트 추출] 재귀적 탐색으로 텍스트 발견 (길이={len(longest)})")
                    return longest.strip()
        except Exception as e:
            logger.debug(f"[LLM 텍스트 추출] 재귀적 탐색 실패: {str(e)}")

        return ""

    def answer(
        self,
        query_text: str,
        context: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
        instructions: Optional[str] = None,
    ) -> LLMResult:
        final_model = model or getattr(settings, "OPENAI_MODEL", None) or os.getenv("OPENAI_MODEL", "gpt-5")

        # ✅ 기본값(없으면 settings/.env 사용) - 답변이 중간에 끊기지 않도록 충분한 토큰 확보
        # gpt-5는 reasoning 토큰이 output_tokens에서 차감되므로 충분히 높게 설정
        # 예: reasoning 500 + 실제 출력 500 = 최소 1000 필요
        default_max = int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS", getattr(settings, "OPENAI_MAX_OUTPUT_TOKENS", 1500)))
        if max_output_tokens is None or int(max_output_tokens) <= 0:
            max_output_tokens = default_max

        # ✅ 비용 절감을 위한 상한선 설정
        # gpt-5 reasoning 고려하여 2000으로 상향
        MAX_HARD_CAP = int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS_CAP", 2000))
        if max_output_tokens > MAX_HARD_CAP:
            max_output_tokens = MAX_HARD_CAP


        # ✅ 최소 방어
        if max_output_tokens < 16:
            max_output_tokens = 16

        # ✅ gpt-5 계열은 temperature 지원이 안 나는 경우가 많아서 "있을 때만" + "모델 허용일 때만" 넣음
        # (여기서는 안전하게 gpt-5*이면 temperature를 payload에서 제외)
        supports_temperature = not str(final_model).startswith("gpt-5")

        system_lines = []
        system_lines.append("당신은 뉴스/커뮤니티 트렌드 분석 Q&A 어시스턴트입니다.")
        system_lines.append("답변은 한국어로, 자연스럽고 친근한 대화체로 작성하세요.")
        system_lines.append(
            "CONTEXT에는 [뉴스]와 [커뮤니티] 두 종류의 자료가 포함될 수 있습니다. "
            "각 자료 앞에 [뉴스] 또는 [커뮤니티] 태그가 붙어 있습니다."
        )
        system_lines.append(
            "[뉴스] 자료는 언론 보도이므로 사실 기반 정보로 인용할 수 있습니다. "
            "[커뮤니티] 자료는 온라인 커뮤니티 게시글이므로 '온라인에서는 ~라는 반응이 있다', "
            "'커뮤니티에서는 ~라는 의견이 나온다' 등 여론/반응으로만 인용하세요."
        )
        system_lines.append("절대로 커뮤니티 게시글의 내용을 뉴스 보도처럼 사실로 단정하지 마세요.")
        system_lines.append(
            "뉴스와 커뮤니티 정보가 상충할 경우, 뉴스를 사실로 우선 제시하고 "
            "커뮤니티는 '일부에서는 다른 반응도 있다'는 정도로만 언급하세요."
        )
        system_lines.append(
            "CONTEXT에 [EVIDENCE_QUALITY: low]가 표시되어 있으면, "
            "'수집된 자료가 제한적이어서' 또는 '관련 자료가 부족하지만'이라는 전제를 반드시 붙이세요."
        )
        system_lines.append("CONTEXT에 없는 사실을 만들어내지 마세요.")
        system_lines.append("각 정보의 출처 유형([뉴스] 또는 [커뮤니티])을 답변 내에서 자연스럽게 구분해 주세요.")
        system_lines.append("답변은 1~3문단으로 핵심만 간결하게 작성하세요. 불필요하게 늘리지 마세요.")
        system_lines.append("기사 제목을 나열하지 말고, 이슈를 자연스럽게 풀어 설명하세요.")
        system_lines.append("답변은 완전한 문장으로 끝내고, 추가 질문이나 제안은 붙이지 마세요.")


        if instructions:
            system_lines.append(f"[추가 지시사항]\n{instructions}")

        system_prompt = "\n".join(system_lines)

        # CONTEXT 길이 확인 및 로깅
        context_length = len(context) if context else 0
        logger.debug(f"[LLM 프롬프트] 질문 길이={len(query_text)}, CONTEXT 길이={context_length}")
        
        # CONTEXT가 너무 짧으면 경고
        if context_length < 50:
            logger.warning(f"[LLM 프롬프트] CONTEXT가 너무 짧음 ({context_length}자)")
        
        user_prompt = (
            f"[질문]\n{query_text}\n\n"
            f"[CONTEXT]\n{context}\n\n"
            f"[지시사항]\n"
            f"핵심: CONTEXT만을 근거로 답변하세요. CONTEXT에 없는 사실을 만들어내지 마세요.\n\n"
            f"출처 구분:\n"
            f"- [뉴스] 자료 → 사실 정보로 직접 인용 가능\n"
            f"- [커뮤니티] 자료 → '온라인에서는 ~반응', '커뮤니티에서는 ~의견' 형태로만 인용\n\n"
            f"근거 부족 시:\n"
            f"- CONTEXT가 질문과 전혀 관련 없거나 [EVIDENCE_QUALITY: low]이면 "
            f"'현재 수집된 데이터에서 관련 근거가 적어요.'라고 전제하고 가능한 범위에서만 답변\n\n"
            f"형식: 완전한 문장으로 마무리하세요. 추가 질문이나 제안은 붙이지 마세요.\n"
        )
        
        # 프롬프트 길이 확인
        prompt_length = len(user_prompt)
        logger.debug(f"[LLM 프롬프트] 전체 프롬프트 길이={prompt_length}")

        payload: Dict[str, Any] = {
            "model": final_model,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_output_tokens": max_output_tokens,
        }

        # reasoning effort (선택)
        # gpt-5는 reasoning 토큰이 max_output_tokens를 모두 사용할 수 있어서
        # 실제 텍스트 출력을 위해 reasoning을 비활성화하거나 낮춤
        if str(final_model).startswith("gpt-5"):
            # gpt-5는 기본적으로 reasoning을 사용하므로, 항상 'low'로 설정하여 output 토큰 확보
            # 사용자가 명시적으로 요청한 경우에만 그대로 사용
            if reasoning_effort and reasoning_effort.strip():
                payload["reasoning"] = {"effort": reasoning_effort.strip()}
                logger.info(f"[LLM] gpt-5 모델, 사용자 요청에 따라 reasoning effort를 '{reasoning_effort}'로 설정")
            else:
                # reasoning을 'low'로 설정하여 reasoning 토큰 사용량 최소화
                payload["reasoning"] = {"effort": "low"}
                logger.info(f"[LLM] gpt-5 모델이므로 reasoning effort를 'low'로 설정 (output 토큰 확보)")
        elif reasoning_effort and reasoning_effort.strip():
            # 다른 모델은 요청한 대로 설정
            payload["reasoning"] = {"effort": reasoning_effort.strip()}

        if supports_temperature and temperature is not None:
            payload["temperature"] = temperature

        logger.debug(f"[LLM 호출 시작] model={final_model} max_output_tokens={max_output_tokens}")
        logger.debug(f"[LLM payload] reasoning 설정: {payload.get('reasoning', 'None')}")
        logger.info(
            f"[LLM 호출 시작] model={final_model} max_output_tokens={max_output_tokens} "
            f"temperature={'(미전송)' if (not supports_temperature) else temperature} "
            f"reasoning={payload.get('reasoning', 'None')}"
        )

        t0 = time.time()
        _max_retries = 2
        for _attempt in range(_max_retries + 1):
            try:
                res = self.client.responses.create(**payload)
                break
            except (ConnectionError, TimeoutError, OSError) as _net_err:
                if _attempt < _max_retries:
                    _wait = 2 ** _attempt
                    logger.warning(f"[LLM] 일시적 오류, {_wait}s 후 재시도 ({_attempt+1}/{_max_retries}): {_net_err}")
                    time.sleep(_wait)
                else:
                    raise
        dt = time.time() - t0

        text = self._extract_text(res)
        if not text.strip():
            # ✅ 빈 응답이면 raw 구조를 로그로 남겨 원인 추적 가능하게
            response_id = getattr(res, "id", None)
            
            # 디버깅을 위한 응답 구조 로깅
            debug_info = {
                "response_id": response_id,
                "response_type": type(res).__name__,
                "has_output_text": hasattr(res, "output_text"),
                "output_text_value": getattr(res, "output_text", None),
                "has_output": hasattr(res, "output"),
                "output_type": type(getattr(res, "output", None)).__name__ if hasattr(res, "output") else None,
                "has_choices": hasattr(res, "choices"),
                "has_text": hasattr(res, "text"),
            }
            
            # output이 있으면 일부 구조 확인
            if hasattr(res, "output"):
                out = getattr(res, "output")
                if isinstance(out, list) and len(out) > 0:
                    debug_info["output_length"] = len(out)
                    debug_info["output_first_item_type"] = type(out[0]).__name__
                    if isinstance(out[0], dict):
                        debug_info["output_first_item_keys"] = list(out[0].keys())[:5]
                        # 첫 번째 항목의 내용 일부 확인
                        first_item = out[0]
                        if "content" in first_item:
                            content = first_item["content"]
                            if isinstance(content, list) and len(content) > 0:
                                debug_info["content_first_item"] = str(content[0])[:200]
                            else:
                                debug_info["content_value"] = str(content)[:200]
                elif isinstance(out, dict):
                    debug_info["output_keys"] = list(out.keys())[:5]
                    # output dict의 내용 일부 확인
                    for key in ["text", "content", "message"]:
                        if key in out:
                            debug_info[f"output_{key}"] = str(out[key])[:200]
            
            # 응답 객체의 모든 속성 확인
            if hasattr(res, "__dict__"):
                debug_info["response_attrs"] = list(res.__dict__.keys())[:10]
            elif hasattr(res, "__slots__"):
                debug_info["response_slots"] = list(res.__slots__)[:10]
            
            logger.error(f"[LLM 빈 응답] model={final_model} 소요={dt:.2f}s response_id={response_id}")
            logger.error(f"[LLM 디버그 정보] {debug_info}")
            
            # raw 응답을 dict로 변환 시도 (디버깅용)
            try:
                raw_dict = self._response_to_dict(res)
                if raw_dict:
                    # JSON 직렬화 가능한 부분만 추출
                    json_safe_dict = {}
                    for key, value in raw_dict.items():
                        try:
                            import json
                            json.dumps(value)  # 직렬화 가능한지 테스트
                            json_safe_dict[key] = value
                        except (TypeError, ValueError):
                            json_safe_dict[key] = str(type(value).__name__)
                    logger.error(f"[LLM raw 응답 구조] {str(json_safe_dict)[:2000]}")
            except Exception as e:
                logger.error(f"[LLM raw 응답 변환 실패] {str(e)}")
            
            # 응답 객체를 문자열로 직접 변환 시도
            try:
                logger.error(f"[LLM 응답 객체 str] {str(res)[:1000]}")
                logger.error(f"[LLM 응답 객체 repr] {repr(res)[:1000]}")
            except Exception as e:
                logger.error(f"[LLM 응답 객체 변환 실패] {str(e)}")
            
            return LLMResult(text="답변 생성에 실패했습니다. (빈 응답)", raw=res)

        logger.info(f"[LLM 호출 완료] model={final_model} 소요={dt:.2f}s 글자수={len(text)}")
        return LLMResult(text=text, raw=res)

    def classify_intent(self, query_text: str, *, model: Optional[str] = None) -> Dict[str, Any]:
        """
        ✅ 질문 분석 + 검색 힌트 생성용 LLM 호출 (한 번에 처리)
        - 외부 지식/사실 판단 없이 "질문 자체"만 구조적으로 분석
        - 반드시 아래 JSON 스키마로 반환:
          {
            "main_intent": "summary" | "list" | "analysis" | "fact" | "unknown",
            "topic_entity": string,
            "time_focus": "recent" | "current" | "past" | "unspecified",
            "sentiment_focus": "neutral" | "positive" | "negative" | "controversial",
            "information_scope": "broad" | "specific",
            "core_question": string,
            "search_hint": string
          }
        - 토큰 사용량은 환경변수 RAG_INTENT_MAX_OUTPUT_TOKENS로 제어(기본 200)
        """
        final_model = model or getattr(settings, "OPENAI_MODEL", None) or os.getenv("OPENAI_MODEL", "gpt-5")

        system_prompt = (
            "너는 사용자의 질문을 이해하고 분석하는 전문가야.\n"
            "사용자의 질문이 무엇을 의도하는지, 어떤 정보를 원하는지 구조적으로 해석해.\n"
            "외부 지식이나 사실 판단은 하지 말고, 질문 자체만 분석해.\n\n"
            "반드시 JSON만 출력해. 코드블록 금지.\n"
            "아래 스키마를 정확히 따라:\n"
            "{\n"
            '  "main_intent": "summary" | "list" | "analysis" | "fact" | "unknown",\n'
            '  "topic_entity": string,\n'
            '  "time_focus": "recent" | "current" | "past" | "unspecified",\n'
            '  "sentiment_focus": "neutral" | "positive" | "negative" | "controversial",\n'
            '  "information_scope": "broad" | "specific",\n'
            '  "core_question": string,\n'
            '  "search_hint": string\n'
            "}\n\n"
            "필드 설명:\n"
            "- main_intent: 사용자가 원하는 답변 형식\n"
            "  - summary: 전반적인 정리\n"
            "  - list: 여러 항목 나열\n"
            "  - analysis: 원인, 배경, 의미 분석\n"
            "  - fact: 단일 사실 확인\n"
            "- topic_entity: 질문의 핵심 인물/기관/주제 (없으면 빈 문자열)\n"
            "- time_focus: 시간적 범위 힌트\n"
            "- sentiment_focus: 질문의 뉘앙스\n"
            "- information_scope:\n"
            "  - broad: 전체적인 흐름\n"
            "  - specific: 특정 사건/사안\n"
            "- core_question: 사용자가 진짜로 알고 싶은 내용을 한 문장으로 재서술\n"
            "- search_hint: 검색에 쓸 수 있는 짧은 핵심 힌트 문구 (자연어)\n"
        )

        user_prompt = f"질문: {query_text}\nJSON만 출력:"

        payload: Dict[str, Any] = {
            "model": final_model,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_output_tokens": int(os.getenv("RAG_INTENT_MAX_OUTPUT_TOKENS", "200")),
        }

        # gpt-5 계열은 reasoning이 출력 토큰을 잡아먹을 수 있으니 낮게
        if str(final_model).startswith("gpt-5"):
            payload["reasoning"] = {"effort": "low"}

        try:
            res = self.client.responses.create(**payload)
            text = (self._extract_text(res) or "").strip()
            import json
            data = json.loads(text) if text else {}
            if not isinstance(data, dict):
                return {
                    "main_intent": "unknown",
                    "topic_entity": "",
                    "time_focus": "unspecified",
                    "sentiment_focus": "neutral",
                    "information_scope": "broad",
                    "core_question": "",
                    "search_hint": "",
                }

            main_intent = data.get("main_intent")
            if main_intent not in ("summary", "list", "analysis", "fact", "unknown"):
                main_intent = "unknown"

            topic_entity = (data.get("topic_entity") or "").strip()

            time_focus = data.get("time_focus")
            if time_focus not in ("recent", "current", "past", "unspecified"):
                time_focus = "unspecified"

            sentiment_focus = data.get("sentiment_focus")
            if sentiment_focus not in ("neutral", "positive", "negative", "controversial"):
                sentiment_focus = "neutral"

            information_scope = data.get("information_scope")
            if information_scope not in ("broad", "specific"):
                information_scope = "broad"

            core_question = (data.get("core_question") or "").strip()
            search_hint = (data.get("search_hint") or "").strip()
            if len(search_hint) > 120:
                search_hint = search_hint[:120].strip()

            return {
                "main_intent": main_intent,
                "topic_entity": topic_entity,
                "time_focus": time_focus,
                "sentiment_focus": sentiment_focus,
                "information_scope": information_scope,
                "core_question": core_question,
                "search_hint": search_hint,
            }
        except Exception as e:
            logger.warning(f"[IntentRouter] classify_intent 실패: {type(e).__name__}: {str(e)}")
            return {
                "main_intent": "unknown",
                "topic_entity": "",
                "time_focus": "unspecified",
                "sentiment_focus": "neutral",
                "information_scope": "broad",
                "core_question": "",
                "search_hint": "",
            }

    def reformulate_query(self, query_text: str, *, model: Optional[str] = None) -> str:
        """
        대화형 질문을 검색에 적합한 자연어 문장으로 재구성.

        예:
        - "요즘 살이 많이 쪘어 어떻게 해야할까?" → "다이어트 체중감량 건강한 식단 운동 방법"
        - "잠을 못자겠어 힘들다" → "불면증 수면장애 숙면 방법 수면 개선"
        - "주식으로 돈 벌고싶어" → "주식투자 수익 투자전략 주식 추천"

        Args:
            query_text: 사용자의 원본 질문
            model: 사용할 LLM 모델 (기본값: settings에서 가져옴)

        Returns:
            검색에 적합하게 재구성된 쿼리 문자열
        """
        final_model = model or getattr(settings, "OPENAI_MODEL", None) or os.getenv("OPENAI_MODEL", "gpt-5")

        system_prompt = (
            "너는 사용자의 대화형 질문을 뉴스/게시글 검색에 적합한 형태로 변환하는 전문가야.\n\n"
            "규칙:\n"
            "1. 사용자의 질문 의도를 파악하고, 관련 뉴스나 게시글을 찾을 수 있는 핵심 키워드들을 자연어 문장으로 나열해.\n"
            "2. 고유명사(인명, 기관명, 브랜드명)가 있으면 반드시 포함해.\n"
            "3. 암묵적인 의도도 명시적 키워드로 변환해. (예: '살쪘어' → '다이어트', '잠못자' → '불면증')\n"
            "4. 검색에 불필요한 조사, 어미, 감정 표현은 제거해.\n"
            "5. 3~8개의 핵심 키워드를 공백으로 구분해서 출력해.\n"
            "6. 키워드만 출력해. 설명이나 문장 형태로 쓰지 마.\n\n"
            "예시:\n"
            "- '요즘 살이 많이 쪘어 어떻게 해야할까?' → '다이어트 체중감량 운동 식단 건강'\n"
            "- '이재명 요즘 뭐해?' → '이재명 대통령 정책 행보 일정'\n"
            "- '비트코인 사도 될까?' → '비트코인 투자 시세 전망 가상화폐'\n"
            "- '트럼프가 또 무슨 말 했어?' → '트럼프 발언 미국 정책 뉴스'\n"
        )

        user_prompt = f"질문: {query_text}\n검색 키워드:"

        payload: Dict[str, Any] = {
            "model": final_model,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_output_tokens": int(os.getenv("RAG_REFORMULATE_MAX_TOKENS", "100")),
        }

        if str(final_model).startswith("gpt-5"):
            payload["reasoning"] = {"effort": "low"}

        try:
            res = self.client.responses.create(**payload)
            reformulated = (self._extract_text(res) or "").strip()

            # 빈 결과면 원본 반환
            if not reformulated:
                logger.warning(f"[reformulate_query] 빈 결과, 원본 사용: {query_text}")
                return query_text

            # 너무 길면 자르기
            if len(reformulated) > 200:
                reformulated = reformulated[:200].strip()

            logger.info(f"[reformulate_query] '{query_text}' → '{reformulated}'")
            return reformulated

        except Exception as e:
            logger.warning(f"[reformulate_query] 실패, 원본 사용: {type(e).__name__}: {str(e)}")
            return query_text


class RAGService:
    """RAG 질의응답 서비스 (캐싱 통합 + OpenAI LLM 연동)"""

    def __init__(self):
        self.vector_db = VectorDBService()
        self.cache_service = RAGCacheService()
        self.llm = OpenAIResponsesLLM()

    def _should_skip_intent_llm(self, query_text: str) -> bool:
        """
        LLM 의도분석을 돌리면 오히려 망가질 가능성이 큰 케이스를 룰로 스킵.

        스킵 대상(요약):
        - 너무 짧고(정보 부족) + 고유 단서가 거의 없음
        - 대상(entity) 없이 너무 일반적/막연한 질문(예: "요즘 뭐 이슈야?")

        목적:
        - LLM이 억지로 entity/search_hint를 만들어 검색이 흔들리는 것을 방지
        """
        q = (query_text or "").strip()
        if not q:
            return True

        # 1) 너무 짧으면 LLM이 억지로 엔티티를 만들 가능성이 큼 (한국어 기준 7자 이하 위험)
        if len(q) <= 7:
            # 단, 강한 신호가 있으면 예외로 통과
            has_strong_signal = bool(re.search(r"[A-Z]{2,}|[0-9]|[#@]|\".+?\"|'.+?'", q))
            # 한글 2~6자 덩어리(인명/기관) 가능성
            has_korean_chunk = bool(re.search(r"[가-힣]{2,6}", q))
            if not (has_strong_signal or has_korean_chunk):
                return True

        # 2) 너무 일반적인 질문 패턴(대상 없는 '요즘 뭐 이슈야' 류)
        generic_patterns = [
            r"요즘\s*(뭐|무슨)\s*(이슈|뉴스|일|사건)\s*(야|임|있어|있냐|있나요)?",
            r"(뭐가|무슨)\s*(이슈|뉴스)\s*(야|있어|있냐|있나요)?",
            r"(최근|요즘)\s*(이슈|뉴스|핫한거|핫한\s*이슈)\s*(정리|알려|뭐야)?",
            r"(이슈|뉴스)\s*(알려줘|정리해줘)$",
        ]
        if any(re.search(p, q) for p in generic_patterns):
            # 문장 안에 의미 있는 토큰이 없으면 스킵
            stop_words = {
                "요즘", "최근", "이슈", "뉴스", "기사", "사건", "소식", "정리", "알려줘",
                "뭐", "무슨", "있어", "있냐", "있나요", "관련", "좀", "좀요",
            }
            tokens = re.findall(r"[가-힣]+|[A-Za-z]+|[0-9]+", q)
            meaningful = [t for t in tokens if t not in stop_words]
            if not meaningful:
                return True

        return False

    def query(
        self,
        query_text: str,
        top_k: int = 5,
        include_sources: bool = True,
        *,
        use_intent_router: bool = False,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
        instructions: Optional[str] = None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        _t_pipeline = time.time()

        # ✅ 빈 쿼리 검사를 가장 먼저 수행 (불필요한 DB/캐시 호출 방지)
        query_text = (query_text or "").strip()
        if not query_text:
            logger.debug("[RAGService.query] 빈 쿼리")
            return {"answer": "질문(query)이 비어있습니다.", "sources": [], "query": ""}

        logger.debug("[RAGService.query] 캐시 확인 중...")

        # ✅ 1) 최종 옵션 먼저 확정 (캐시 키 + LLM 호출 양쪽에서 공유)
        final_model = model or _get_setting("OPENAI_MODEL", "gpt-5")
        final_temperature = temperature if temperature is not None else float(_get_setting("OPENAI_TEMPERATURE", 0.25))
        final_max_tokens = (
            int(_get_setting("OPENAI_MAX_OUTPUT_TOKENS", 700))
            if (max_output_tokens is None or int(max_output_tokens) <= 0)
            else int(max_output_tokens)
        )
        if final_max_tokens < 16:
            final_max_tokens = 16

        # ✅ 2) 최신 데이터 버전(수집 시각) 계산: 새 뉴스/소셜 들어오면 버전이 바뀜
        latest_news = NewsArticle.objects.aggregate(Max("collected_at"))["collected_at__max"]
        latest_social = SocialMediaPost.objects.aggregate(Max("collected_at"))["collected_at__max"]

        # ✅ 벡터DB 문서 수를 포함하여 backfill/임베딩 변경 시 캐시 자동 무효화
        try:
            _vc = self.vector_db.collection.count()
        except Exception:
            _vc = 0
        data_version = (
            f"news:{latest_news.isoformat() if latest_news else 'none'}"
            f"|social:{latest_social.isoformat() if latest_social else 'none'}"
            f"|vc:{_vc}"
        )

        cache_context = {
            "top_k": int(top_k),
            "include_sources": bool(include_sources),
            "use_intent_router": bool(use_intent_router),
            "model": final_model,
            "temperature": final_temperature,
            "max_output_tokens": int(final_max_tokens),
            "reasoning_effort": (reasoning_effort or "").strip(),
            "instructions": (instructions or "").strip(),
            "data_version": data_version,
            "hard_dist": float(_get_setting("RAG_HARD_DISTANCE_THRESHOLD", 1.05)),
            "weak_rel": float(_get_setting("RAG_WEAK_RELEVANCE_THRESHOLD", 0.65)),
        }

        # ✅ 3) 캐시 조회 (정규화된 키 사용)
        _cache_query = re.sub(r"\s+", " ", query_text).strip().rstrip("?？！!.")
        if not force_refresh:
            cached_response = self.cache_service.get_cached_response(_cache_query, cache_context=cache_context)
            if cached_response:
                logger.debug("[RAGService.query] 캐시된 응답 반환 (캐시 히트)")
                return cached_response

        logger.debug("[RAGService.query] 캐시 미스 - 새로 처리 시작")

        # ✅ (선택) 질문 분석: search_hint/topic_entity를 뽑아 검색 안정화
        intent_info = {
            "main_intent": "unknown",
            "topic_entity": "",
            "time_focus": "unspecified",
            "sentiment_focus": "neutral",
            "information_scope": "broad",
            "core_question": "",
            "search_hint": "",
        }
        if bool(_get_setting("RAG_INTENT_ROUTER_ENABLED", True)) or bool(use_intent_router):
            if self._should_skip_intent_llm(query_text):
                logger.info(f"[IntentRouter] 스킵(룰 매칭): query='{query_text}'")
            else:
                intent_info = self.llm.classify_intent(query_text=query_text, model=final_model)
                logger.info(f"[IntentRouter] {intent_info}")

        # ========================================
        # LLM 기반 쿼리 재구성 (대화형 → 검색용)
        # ========================================
        # 명확한 쿼리(엔티티 2개+ 또는 짧고 구체적)는 재구성 스킵하여 지연/비용 절감
        pre_entities = _extract_key_entities(query_text)
        query_tokens = query_text.split()
        skip_reformulate = (
            (len(pre_entities) >= 2)
            or (len(pre_entities) >= 1 and len(query_tokens) <= 4)
        )

        _t_stage = time.time()
        if skip_reformulate:
            reformulated_query = query_text
            logger.info(f"[RAG 검색] 명확한 쿼리이므로 재구성 스킵: '{query_text}' (엔티티: {pre_entities})")
        else:
            reformulated_query = self.llm.reformulate_query(query_text, model=final_model)
            logger.info(f"[RAG 검색] 원본: '{query_text}' → 재구성: '{reformulated_query}'")
        logger.info(f"[RAG 타이밍] 쿼리 재구성: {time.time() - _t_stage:.2f}s")

        # ========================================
        # 하이브리드 검색: 시맨틱 + 키워드
        # ========================================

        # 1) 핵심 엔티티 추출 (키워드 검색용) - 원본 쿼리 + 재구성 쿼리 + intent topic_entity
        entities_from_original = _extract_key_entities(query_text)
        entities_from_reformulated = _extract_key_entities(reformulated_query)
        key_entities = list(set(entities_from_original + entities_from_reformulated))
        if intent_info.get("topic_entity"):
            topic = intent_info["topic_entity"].strip()
            if topic and topic not in _STOP_TOKENS and topic not in key_entities:
                key_entities.append(topic)
        logger.info(f"[RAG 검색] 추출된 엔티티: {key_entities}")

        # 2) 시맨틱 검색 (후보군 A) - 재구성된 쿼리 + search_hint 결합
        search_query = reformulated_query
        if intent_info.get("search_hint"):
            hint = intent_info["search_hint"].strip()
            if hint and hint != reformulated_query:
                search_query = f"{reformulated_query} {hint}"

        retrieval_k = max(int(top_k) * 8, int(top_k) + 30)
        candidate_distance_threshold = float(_get_setting("RAG_CANDIDATE_DISTANCE_THRESHOLD", 1.5))

        semantic_candidates = self.vector_db.similarity_search(
            search_query,
            top_k=retrieval_k,
            distance_threshold=candidate_distance_threshold,
            fetch_multiplier=3,
            balance_types=False,
        )
        logger.info(f"[RAG 검색] 시맨틱 검색 결과: {len(semantic_candidates)}개")

        # 3) 키워드 검색 (후보군 B) - 엔티티가 있을 때만
        keyword_candidates: List[SearchResult] = []
        if key_entities:
            keyword_candidates = self.vector_db.keyword_search(
                query_text=reformulated_query,  # 재구성된 쿼리로 유사도 계산
                keywords=key_entities,
                top_k=retrieval_k,
            )
            logger.info(f"[RAG 검색] 키워드 검색 결과: {len(keyword_candidates)}개 (엔티티: {key_entities})")

        # 4) 후보군 병합 (A + B, 중복 제거)
        seen_ids: set = set()
        candidates: List[SearchResult] = []

        # 키워드 매칭 결과 우선 추가 (더 신뢰도 높음)
        for r in keyword_candidates:
            if r.id not in seen_ids:
                seen_ids.add(r.id)
                candidates.append(r)

        # 시맨틱 결과 추가
        for r in semantic_candidates:
            if r.id not in seen_ids:
                seen_ids.add(r.id)
                candidates.append(r)

        logger.info(f"[RAG 검색] 병합된 후보군: {len(candidates)}개 (키워드: {len(keyword_candidates)}, 시맨틱: {len(semantic_candidates)})")

        # ========================================
        # 5) Reddit 제목 DB 검색 (벡터 검색 보완)
        # ========================================
        # Reddit 글은 본문이 없는 경우가 많아 벡터 검색에서 누락될 수 있음.
        # DB에서 제목 키워드 매칭으로 직접 찾아서 후보군에 병합.
        reddit_db_results = _search_reddit_by_title(
            query_text=query_text,
            key_entities=key_entities,
            limit=5,
        )
        reddit_added = 0
        for r in reddit_db_results:
            if r.id not in seen_ids:
                seen_ids.add(r.id)
                candidates.append(r)
                reddit_added += 1
        if reddit_added:
            logger.info(f"[RAG 검색] Reddit 제목 DB 검색으로 {reddit_added}개 추가")

        logger.info(f"[RAG 타이밍] 검색(시맨틱+키워드+Reddit): {time.time() - _t_stage:.2f}s")

        if not candidates:
            logger.warning(f"[RAG 검색] 검색 결과 없음: query={query_text}")
            return {
                "answer": f"'{query_text}'에 대한 관련 정보를 찾을 수 없습니다. 다른 키워드로 검색해보세요.",
                "sources": [],
                "query": query_text,
            }

        # ========================================
        # STEP 0: 시간 스코프 감지 + 날짜 기반 사전 필터
        # ========================================
        time_scope_days = _detect_time_scope(
            query_text,
            intent_time_focus=intent_info.get("time_focus", ""),
        )
        _now_ts = time.time()

        if time_scope_days > 0:
            from datetime import datetime, timezone, timedelta
            cutoff_dt = datetime.now(timezone.utc) - timedelta(days=time_scope_days)

            recent_candidates = []
            for r in candidates:
                pa = (r.metadata or {}).get("published_at", "")
                if not pa:
                    continue
                try:
                    doc_dt = datetime.fromisoformat(pa.replace("Z", "+00:00"))
                    if doc_dt >= cutoff_dt:
                        recent_candidates.append(r)
                except (ValueError, TypeError):
                    pass

            # 시간 필터 후 결과가 충분하면 사용, 아니면 원본 유지
            if len(recent_candidates) >= max(int(top_k), 3):
                logger.info(
                    f"[RAG 시간필터] {time_scope_days}일 이내: {len(recent_candidates)}개 "
                    f"(전체 {len(candidates)}개에서 필터)"
                )
                candidates = recent_candidates
            else:
                logger.info(
                    f"[RAG 시간필터] {time_scope_days}일 이내 {len(recent_candidates)}개로 부족, "
                    f"전체 {len(candidates)}개 유지"
                )

        # ========================================
        # STEP A: 소스 의도 판별 (LLM 호출 없이 키워드 기반)
        # ========================================
        source_intent = _detect_source_intent(query_text)
        logger.info(f"[RAG 검색] source_intent={source_intent}")

        # ========================================
        # STEP B: 키워드 포함(overlap) 우선으로 재랭킹 (over-fetch for filtering headroom)
        # ========================================
        min_hits = 2
        if intent_info.get("topic_entity"):
            min_hits = 1

        results = rank_results_generic(
            query_text=query_text,
            results=candidates,
            final_k=int(top_k) * 2,
            min_keyword_hits=min_hits,
        )

        # ========================================
        # STEP C: 의도 기반 소스 타입 필터링 (타입만 필터, 거리는 Step D에서 처리)
        # ========================================
        hard_distance = float(_get_setting("RAG_HARD_DISTANCE_THRESHOLD", 1.05))

        if source_intent == "news":
            typed = [r for r in results if _infer_type(r.id, r.metadata) == "news"]
            if typed:
                results = typed
                logger.info(f"[RAG 필터] news intent → {len(typed)}개 뉴스 선택")
            else:
                logger.warning(f"[RAG 필터] news intent이지만 뉴스 결과 없음, {len(results)}개 전체 결과로 대체")
        elif source_intent == "community":
            typed = [r for r in results if _infer_type(r.id, r.metadata) == "social"]
            if typed:
                results = typed
                logger.info(f"[RAG 필터] community intent → {len(typed)}개 소셜 선택")
            else:
                logger.warning(f"[RAG 필터] community intent이지만 소셜 결과 없음, {len(results)}개 전체 결과로 대체")

        # ========================================
        # STEP D: 거리 게이트 (하드 → 소프트 → fallback 단계적 적용)
        # ========================================
        force_low_quality = False
        gated = [r for r in results if r.distance <= hard_distance]
        if len(gated) >= max(int(top_k) // 2, 1):
            # 충분한 결과가 하드 게이트 통과
            results = gated
        elif gated:
            # 하드 게이트 통과는 적지만 있음 → 소프트 범위로 보충
            soft_gated = [r for r in results if r.distance <= hard_distance * 1.3 and r not in gated]
            results = gated + soft_gated
        else:
            # 모든 문서가 하드 게이트 초과 → 거리순 정렬 후 top_k 유지
            results.sort(key=lambda r: r.distance)
            results = results[:int(top_k)]
            force_low_quality = True

        # ========================================
        # STEP E: 키워드 매칭 + 최신성 기반 정렬 → top_k 선택
        # ========================================
        # 정렬 우선순위:
        #   1) 엔티티 직접 매칭 보너스 (가장 강력)
        #   2) 키워드 overlap
        #   3) 최신성 가산 (시간 민감 쿼리일수록 강하게)
        #   4) 시맨틱 거리 (tiebreaker)
        final_distance_cutoff = float(_get_setting("RAG_DISTANCE_THRESHOLD", 0.25))
        has_entities = bool(key_entities)
        # 시간 민감 쿼리면 recency 가중치를 높임
        recency_weight = 5.0 if time_scope_days > 0 else 1.0

        def _sort_key(r):
            meta = r.metadata or {}
            combined = f"{meta.get('title', '')}\n{meta.get('excerpt', '')}\n{r.document or ''}"
            overlap = _keyword_overlap_count(query_text, combined)

            # 엔티티 직접 매칭 보너스
            entity_bonus = 0
            if has_entities:
                combined_lower = combined.lower()
                entity_bonus = sum(1 for ent in key_entities if ent.lower() in combined_lower) * 10

            within_soft = 1 if r.distance <= final_distance_cutoff else 0
            # 최신성 점수 (0.0~1.0, 가중치 적용)
            recency = _recency_score(meta.get("published_at", ""), _now_ts) * recency_weight
            # 뉴스 미세 우선
            news_boost = 0.01 if _infer_type(r.id, r.metadata) == "news" else 0

            score = entity_bonus + overlap + within_soft + recency + news_boost
            return (-score, r.distance)

        results.sort(key=_sort_key)
        results = results[:int(top_k)]

        # ========================================
        # STEP E-2: 결과 다양성 보장 (같은 출처 편중 방지)
        # ========================================
        if len(results) > 2:
            from collections import defaultdict as _ddict
            _src_counts = _ddict(int)
            _max_per_source = max(len(results) // 2, 2)
            _diversified = []
            _overflow = []
            for r in results:
                src = (r.metadata or {}).get("publisher") or (r.metadata or {}).get("source_name") or "unknown"
                if _src_counts[src] < _max_per_source:
                    _diversified.append(r)
                    _src_counts[src] += 1
                else:
                    _overflow.append(r)
            # 부족분을 overflow에서 채움
            while len(_diversified) < int(top_k) and _overflow:
                _diversified.append(_overflow.pop(0))
            results = _diversified

        # ========================================
        # STEP F: 품질 게이트 통과 결과 0건 → "근거 부족" 응답 (fallback 없음)
        # ========================================
        if not results:
            insufficient_msg = {
                "news": f"'{query_text}'에 관련된 뉴스 기사를 찾을 수 없습니다. 다른 키워드로 검색해보세요.",
                "community": f"'{query_text}'에 관련된 커뮤니티 게시글을 찾을 수 없습니다. 다른 키워드로 검색해보세요.",
                "any": f"'{query_text}'에 대해 충분히 관련성 높은 정보를 찾을 수 없습니다. 다른 키워드로 검색해보세요.",
            }
            logger.warning(
                f"[RAG 검색] 품질 게이트 통과 결과 0건: query={query_text}, intent={source_intent}"
            )
            return {
                "answer": insufficient_msg.get(source_intent, insufficient_msg["any"]),
                "sources": [],
                "query": query_text,
            }

        # ========================================
        # STEP G: 근거 품질 시그널 계산 (LLM 컨텍스트에 전달)
        # ========================================
        distances = [r.distance for r in results]
        avg_distance = sum(distances) / len(distances)
        weak_threshold = float(_get_setting("RAG_WEAK_RELEVANCE_THRESHOLD", 0.65))

        if force_low_quality:
            evidence_quality = "low"
        else:
            # 키워드 매칭(엔티티 포함)된 결과가 과반이면 근거 충분으로 판정
            # → 키워드 검색으로 확실히 엔티티가 포함된 문서인데 시맨틱 거리만으로 "low" 처리되는 문제 방지
            keyword_matched = 0
            if key_entities:
                for r in results:
                    meta = r.metadata or {}
                    combined = f"{meta.get('title', '')}\n{meta.get('excerpt', '')}\n{r.document or ''}"
                    combined_lower = combined.lower()
                    if any(ent.lower() in combined_lower for ent in key_entities):
                        keyword_matched += 1

            if keyword_matched > len(results) // 2:
                evidence_quality = "adequate"
            elif avg_distance <= weak_threshold:
                evidence_quality = "adequate"
            else:
                evidence_quality = "low"

        news_count = sum(1 for r in results if _infer_type(r.id, r.metadata) == "news")
        social_count = sum(1 for r in results if _infer_type(r.id, r.metadata) == "social")

        logger.info(
            f"[RAG 검색] 최종 {len(results)}개 (뉴스:{news_count}, 소셜:{social_count}), "
            f"거리: 최소={min(distances):.4f}, 최대={max(distances):.4f}, "
            f"평균={avg_distance:.4f}, evidence_quality={evidence_quality}"
        )

        # 결과 수에 따라 문서당 최대 길이 동적 조절 (개선 6)
        if len(results) <= 2:
            max_doc_chars = 1200
        elif len(results) <= 4:
            max_doc_chars = 900
        else:
            max_doc_chars = 700

        context, sources = _build_context_and_sources(
            results,
            max_doc_chars=max_doc_chars,
            evidence_quality=evidence_quality,
            source_intent=source_intent,
        )

        # intent의 main_intent로 답변 형식 가이드 추가 (개선 3)
        intent_instruction = ""
        main_intent = intent_info.get("main_intent", "")
        if main_intent == "list":
            intent_instruction = "답변을 항목별로 정리하여 제시하세요."
        elif main_intent == "analysis":
            intent_instruction = "원인, 배경, 의미를 구조적으로 분석하여 설명하세요."
        elif main_intent == "comparison":
            intent_instruction = "비교 대상의 차이점과 공통점을 중심으로 설명하세요."
        
        # CONTEXT가 비어있는지 확인
        if not context or not context.strip():
            logger.error(f"[RAG 검색] CONTEXT가 비어있음. 검색 결과를 확인하세요.")
            return {
                "answer": f"'{query_text}'에 대한 관련 정보를 찾을 수 없습니다. 다른 키워드로 검색해보세요.",
                "sources": [],
                "query": query_text,
            }

        # intent_instruction이 있으면 instructions에 합류
        final_instructions = instructions or ""
        if intent_instruction:
            final_instructions = f"{final_instructions}\n{intent_instruction}".strip() if final_instructions else intent_instruction

        _t_stage = time.time()
        logger.debug(f"[RAGService.query] LLM 호출 시작 - context 길이: {len(context)}")
        try:
            llm_result = self.llm.answer(
                query_text=query_text,
                context=context,
                model=final_model,
                temperature=final_temperature,
                max_output_tokens=final_max_tokens,
                reasoning_effort=reasoning_effort,
                instructions=final_instructions or None,
            )
            logger.debug(f"[RAGService.query] LLM 응답 받음 - type: {type(llm_result)}")
            # LLMResult 객체에서 텍스트 추출
            answer = llm_result.text if isinstance(llm_result, LLMResult) else str(llm_result)
            logger.debug(f"[RAGService.query] 추출된 answer 길이: {len(answer) if answer else 0}")
            logger.debug(f"[RAGService.query] 추출된 answer 내용 (처음 200자): {answer[:200] if answer else 'None'}")
            
            # ✅ 답변이 중간에 잘린 경우 감지 및 처리
            if answer:
                # 마지막 문장이 완전하지 않은 경우 감지
                incomplete_endings = ['하지만', '그리고', '또한', '또', '그런데', '그러나', '따라서', '그래서', '그러므로', '뿐만', '뿐만 아니라']
                answer_stripped = answer.strip()
                
                # 마지막 문장이 마침표/느낌표/물음표로 끝나지 않고, 접속사로 끝나는 경우
                if answer_stripped and not answer_stripped[-1] in ['.', '!', '?', '。', '！', '？']:
                    # 마지막 문장이 접속사로 끝나는지 확인
                    last_sentence = answer_stripped.split('\n')[-1].strip()
                    if any(last_sentence.endswith(ending) for ending in incomplete_endings):
                        # 중간에 잘린 것으로 판단하여 마지막 불완전한 문장 제거
                        sentences = answer_stripped.split('\n')
                        # 완전한 문장만 남기기 (마침표로 끝나는 문장)
                        complete_sentences = []
                        for sent in sentences:
                            sent = sent.strip()
                            if sent and (sent[-1] in ['.', '!', '?', '。', '！', '？'] or sent.startswith('•') or sent.startswith('-') or sent.startswith('*')):
                                complete_sentences.append(sent)
                            elif sent and not any(sent.endswith(ending) for ending in incomplete_endings):
                                complete_sentences.append(sent)
                        
                        if complete_sentences:
                            answer = '\n'.join(complete_sentences)
                            logger.warning(f"[RAGService.query] 답변이 중간에 잘린 것으로 감지되어 수정함 (원본 길이: {len(answer_stripped)}, 수정 후: {len(answer)})")
                        else:
                            # 완전한 문장이 없으면 마지막 문장을 제거하고 요약 bullet만 남기기
                            bullet_lines = [line for line in sentences if line.strip().startswith(('•', '-', '*'))]
                            if bullet_lines:
                                answer = '\n'.join(bullet_lines)
                                logger.warning(f"[RAGService.query] 답변이 중간에 잘린 것으로 감지되어 요약 bullet만 남김")
            
            # 답변이 너무 짧으면 경고
            if answer and len(answer) < 50:
                logger.warning(f"[RAGService.query] 답변이 너무 짧음 ({len(answer)}자). LLM 응답이 제대로 추출되지 않았을 수 있습니다.")
        except Exception as e:
            logger.error(f"[RAGService.query] LLM 호출 예외: {type(e).__name__}: {str(e)}", exc_info=True)
            answer = f"LLM 호출 중 오류가 발생했습니다: {str(e)}"

        logger.info(f"[RAG 타이밍] LLM 답변 생성: {time.time() - _t_stage:.2f}s")
        logger.info(f"[RAG 타이밍] 전체 파이프라인: {time.time() - _t_pipeline:.2f}s")

        history = QueryHistory.objects.create(
            query_text=query_text,
            answer_text=answer,
            sources=sources if include_sources else [],
            top_k=top_k,
            collection=self.vector_db.collection_name,
        )

        response = {
            "answer": answer,
            "sources": history.sources,
            "query": query_text,
            "history_id": history.id,
            "model": final_model,
        }

        self.cache_service.cache_response(_cache_query, response, cache_context=cache_context)
        return response


# ✅ 프로세스 단위 싱글턴: 매 요청마다 모델/클라이언트를 재생성하지 않음
_rag_service_instance: Optional["RAGService"] = None


def get_rag_service() -> "RAGService":
    """RAGService를 프로세스 단위로 재사용하여 모델 재로딩 방지"""
    global _rag_service_instance
    if _rag_service_instance is None:
        _rag_service_instance = RAGService()
    return _rag_service_instance
