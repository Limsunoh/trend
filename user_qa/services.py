"""
벡터DB 및 RAG 서비스
"""

import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import chromadb
from chromadb.config import Settings as ChromaSettings
from django.conf import settings
from django.db.models import Max

from common.redis_services import RAGCacheService
from data_collector.models import NewsArticle, SocialMediaPost

from .models import QueryHistory

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
        self.collection_name: str = collection_name or _get_setting(
            "CHROMA_COLLECTION", "trend_docs"
        )

        model_name: str = _get_setting(
            "EMBEDDING_MODEL",
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        )
        from sentence_transformers import SentenceTransformer

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
        balance_types: bool = True,  # ✅ 추가
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

        logger.debug(f"[keyword_search] 키워드 {keywords} → {len(all_results)}개 결과")

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
        "최근",
        "요즘",
        "오늘",
        "내일",
        "어제",
        "지금",
        "우리",
        "그들",
        "여기",
        "거기",
        "어떻게",
        "무엇",
        "언제",
        "어디",
        "왜",
        "누가",
        "얼마나",
        "정말",
        "아주",
        "매우",
        "너무",
        "조금",
        "많이",
        "적게",
        "그리고",
        "하지만",
        "그러나",
        "또한",
        "그래서",
        "따라서",
        "대통령",
        "장관",
        "의원",
        "기자",
        "교수",
        "대표",
        "사장",
        "생각",
        "의견",
        "반응",
        "전망",
        "분석",
        "정리",
        "요약",
        "상황",
        "현황",
        "동향",
        "추세",
        "변화",
        "영향",
        "결과",
        # 감정/상태 표현 (엔티티가 아닌 일반 감성어)
        "불안",
        "불안해",
        "불안한",
        "걱정",
        "걱정돼",
        "무서워",
        "답답",
        "답답해",
        "짜증",
        "화나",
        "힘들",
        "미치",
        "미치겠",
        "심각",
        "심각해",
        "궁금",
        "궁금해",
        "좋은",
        "나쁜",
        "안좋",
        # 의문/탐색 표현 (엔티티가 아닌 질문 구성어)
        "무슨일",
        "어쩌다",
        "어떡해",
        "어쩌면",
        "뭐야",
    }

    # 1. 공백 기준 토큰 분리 → 조사 제거 → 엔티티 판별
    tokens = query.split()
    for token in tokens:
        # 영문 고유명사 (대문자로 시작하거나 전체 대문자)
        eng_match = re.match(r"^([A-Z][a-zA-Z]*|[A-Z]{2,})\b", token)
        if eng_match:
            word = eng_match.group(1)
            if len(word) >= 2 and word not in entities:
                entities.append(word)
            continue

        # 한글이 포함되지 않은 토큰은 스킵
        if not re.search(r"[가-힣]", token):
            continue

        # 한글 토큰: 조사 제거
        stripped = _strip_ko_particles(token)

        # 불용어/일반 단어 제외
        if stripped in _STOP_TOKENS or stripped in common_words:
            continue

        # 2-4글자 순수 한글 → 엔티티 후보
        if re.match(r"^[가-힣]{2,4}$", stripped) and stripped not in entities:
            entities.append(stripped)
            continue

        # 5글자 이상: 동사/어미 접미사를 제거하여 명사 추출
        # 예: "비트코인알려줘" → "비트코인", "트럼프어떻게생각해" → "트럼프"
        if len(stripped) >= 5 and re.match(r"^[가-힣]+$", stripped):
            for suffix in _VERB_SUFFIXES:
                if stripped.endswith(suffix) and len(stripped) > len(suffix):
                    candidate = stripped[: -len(suffix)]
                    if (
                        2 <= len(candidate) <= 4
                        and candidate not in _STOP_TOKENS
                        and candidate not in common_words
                        and candidate not in entities
                    ):
                        entities.append(candidate)
                    break

    # 2. 한글 복합어/기관명 (전체 텍스트에서 검색)
    # 예: 삼성전자, 현대자동차, 민주당, 국민의힘
    compound_pattern = re.compile(
        r"([가-힣]{3,}(?:전자|자동차|그룹|증권|은행|보험|제약|바이오|엔터|미디어|당|의힘|연합|연대|회의|위원회|청와대|국회|정부))"
    )
    for match in compound_pattern.finditer(query):
        word = match.group(1)
        if word not in entities:
            entities.append(word)

    # 최대 3개만 반환
    return entities[:3]


_STOP_TOKENS = {
    "관련",
    "관련된",
    "이슈",
    "알려줘",
    "뉴스",
    "소식",
    "정리",
    "오늘",
    "요즘",
    "사건",
    "이벤트",
    "트렌드",
    "대해",
    "대한",
    "대해서",
    "무엇",
    "어떤",
    "어떻게",
    "알려",
    "설명",
    "해줘",
}

# 5글자 이상 토큰에서 동사/어미 접미사를 제거하기 위한 패턴 (긴 것부터 매칭)
_VERB_SUFFIXES = [
    "어떻게생각해",
    "어떻게됐어",
    "어떻게해",
    "알려줘봐",
    "알려줘요",
    "알려주세요",
    "알려달라",
    "알려줄래",
    "해줘요",
    "봐줘요",
    "줘봐요",
    "있나요",
    "있어요",
    "인가요",
    "일까요",
    "인데요",
    "알려줘",
    "해줘",
    "봐줘",
    "줘봐",
    "할까",
    "일까",
    "인가",
    "뭐야",
    "뭐냐",
    "뭐임",
    "있어",
    "있나",
    "있냐",
    "인지",
    "인데",
    "이야",
    "했던",
    "한다",
    "했다",
    "하는",
    "줘",
    "해",
]

# 한국어 조사 제거 패턴 (긴 조사를 먼저 매칭하여 오동작 방지)
_KO_PARTICLE_RE = re.compile(
    r"(?:에서의|으로의|에서도|으로도|에서는|이라는|"
    r"관련|관한|따른|대해|대한|관해|통해|위해|위한|"
    r"에서|으로|에게|한테|부터|까지|처럼|보다|라고|이라|라는|에는|에도|"
    r"은|는|이|가|을|를|에|의|와|과|로|도|만|께|된)$"
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
        if len(stripped) >= 5 and re.match(r"^[가-힣]+$", stripped):
            for suffix in _VERB_SUFFIXES:
                if stripped.endswith(suffix) and len(stripped) > len(suffix):
                    candidate = stripped[: -len(suffix)]
                    if len(candidate) >= 2:
                        stripped = candidate
                    break
        toks.add(stripped)
    return toks - _STOP_TOKENS


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

    if any(kw in q_lower for kw in ["어떻게", "어떤", "어때"]):
        expanded.append(f"{entity_str} 현황 전망")
    if any(kw in q_lower for kw in ["주가", "주식", "증시"]):
        expanded.append(f"{entity_str} 실적 증시 시장")
    if any(kw in q_lower for kw in ["반응", "여론", "의견"]):
        expanded.append(f"{entity_str} 평가 영향 분석")
    if any(kw in q_lower for kw in ["정책", "법", "제도"]):
        expanded.append(f"{entity_str} 법안 제도 시행")

    # 기본: 엔티티 + "뉴스" (뉴스 헤드라인 스타일 매칭)
    if len(expanded) == 1:
        expanded.append(f"{entity_str} 뉴스")

    # 국가 미지정 시 "한국" 변형 추가 → 한국 콘텐츠 우선 검색
    _country_names = {
        "한국",
        "미국",
        "일본",
        "중국",
        "영국",
        "독일",
        "프랑스",
        "러시아",
        "북한",
        "대만",
        "호주",
        "캐나다",
        "인도",
        "이란",
        "이스라엘",
        "korea",
        "usa",
        "us",
        "japan",
        "china",
        "uk",
    }
    has_country = any(c in q_lower for c in _country_names)
    if not has_country:
        expanded.append(f"한국 {entity_str}")

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
        SocialMediaPost.objects.filter(q_filter, source__platform="reddit")
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

        results.append(
            SearchResult(
                id=f"reddit_db:{post.id}",
                document=document,
                metadata=meta,
                distance=0.5,  # DB 검색이므로 중간 거리값 부여
            )
        )

    if results:
        logger.info(f"[Reddit DB 검색] 키워드={search_terms} → {len(results)}개 발견")

    return results


# ========================================
# 공통 단어 사전 (한 곳에서 관리)
# ========================================

# 강도 접두어: "가장 ~", "제일 ~", "최고로 ~" 등
INTENSITY_PREFIXES = [
    "가장",
    "제일",
    "최고로",
    "최고",
    "젤",
    "완전",
    "엄청",
    "진짜",
    "되게",
    "매우",
    "정말",
    "너무",
]

# 인기/주목 수식어: "~ 유명한", "~ 핫한" 등
POPULARITY_WORDS = [
    "유명",
    "핫",
    "인기",
    "뜨는",
    "뜨거운",
    "뜨고",
    "화제",
    "주목",
    "난리",
    "대박",
    "이슈",
]

# 탐색적 트렌드 신호 단어: 특정 주제 없는 탐색적 쿼리에서 trend_enhanced 라우팅
TREND_SIGNAL_WORDS = [
    "트렌드",
    "이슈",
    "재밌",
    "재미있",
    "흥미",
    "볼만",
    "큰",
    "컸",
    "많은",
    "궁금",
    "요즘",
    "대충",
    "놓친",
    "못본",
    "못 본",
    "빠진",
    "주요",
    "중요한",
    "핵심",
]

# 키워드 수식어: "키워드" 앞에 붙어서 분석 의도를 나타내는 단어
KEYWORD_QUALIFIERS = [
    "핫",
    "인기",
    "급상승",
    "급등",
    "뜨는",
    "뜨고",
    "트렌드",
    "많이",
    "자주",
    "요즘",
    "최근",
    "상위",
    "톱",
    "top",
    "hot",
    "popular",
]

# 뉴스 출처 감지 키워드
NEWS_INDICATORS = [
    "뉴스",
    "기사",
    "보도",
    "언론",
    "신문",
    "매체",
    "보도자료",
    "속보",
    "헤드라인",
    "방송",
    "취재",
    "리포트",
    "보도내용",
    "news",
    "article",
    "press",
    "report",
]

# 커뮤니티 출처 감지 키워드
COMMUNITY_INDICATORS = [
    "커뮤니티",
    "게시글",
    "게시판",
    "반응",
    "여론",
    "댓글",
    "디시",
    "dcinside",
    "레딧",
    "reddit",
    "갤러리",
    "유저",
    "네티즌",
    "온라인반응",
    "온라인 반응",
    "sns",
    "소셜",
    "트위터",
    "엑스",
    "인스타",
    "페이스북",
    "유튜브",
    "블로그",
    "카페",
    "클리앙",
    "루리웹",
    "에펨코리아",
]

# 분석 의도 감지 — 직접 매칭되는 구문 (띄어쓰기 무관 매칭은 아래 함수에서 처리)
_ANALYSIS_DIRECT_PHRASES = [
    "분석 결과",
    "분석결과",
    "플랫폼 비교",
    "플랫폼비교",
    "시간차 분석",
    "시간차분석",
    "트렌드 분석",
    "트렌드분석",
    "트렌드 동기화",
    "동기화 분석",
    "시간대별 분석",
    "시간대별 트렌드",
    "참여도 분석",
    "참여도 키워드",
    "많이 언급",
    "자주 언급",
    "자주 등장",
    "surge",
    "engagement",
    # 자연어 동의어 (플랫폼 속도/비교)
    "반영이 빨라",
    "반영이 느려",
    "반영 속도",
    "먼저 반영",
    "빠른 플랫폼",
    "느린 플랫폼",
    "플랫폼별 비교",
]

# 시스템 메타 질문 감지 패턴 ("기준이 뭐야?", "어떻게 계산해?" 등)
_META_QUESTION_PATTERNS = [
    "기준이 뭐",
    "기준이 뭔",
    "기준이 무엇",
    "어떤 기준",
    "어떻게 계산",
    "어떻게 분석",
    "어떻게 선정",
    "어떻게 판단",
    "무슨 뜻",
    "무슨 의미",
    "알고리즘",
    "방법론",
    "급상승 기준",
    "인기 기준",
    "트렌드 기준",
    "어떤 방식",
    "어떤 방법",
]

# 메타 질문에 대한 시스템 설명 (LLM context로 전달)
_META_EXPLANATIONS = {
    "급상승": (
        "급상승 키워드는 최근 수집된 뉴스와 SNS 데이터에서 "
        "일정 기간(기본 7일) 동안 언급 빈도가 급격히 증가한 키워드를 의미합니다. "
        "이전 기간 대비 출현 빈도의 증가율(surge ratio)을 계산하고, "
        "서지 임계값(기본 2.0배)을 초과하면 급상승 키워드로 선정됩니다. "
        "뉴스와 SNS 각각에서 별도로 급상승 키워드를 추출합니다."
    ),
    "인기": (
        "인기 키워드는 뉴스 기사와 커뮤니티 게시글에서 "
        "가장 높은 출현 빈도(frequency)를 기록한 키워드입니다. "
        "뉴스 상위 키워드, SNS 상위 키워드, 양쪽 공통 키워드로 구분하여 분석합니다."
    ),
    "플랫폼": (
        "플랫폼 비교 분석은 동일 키워드가 뉴스와 SNS에서 "
        "얼마나 다르게 언급되는지 비교합니다. "
        "공통 키워드, 뉴스 고유 키워드, SNS 고유 키워드로 구분하여 "
        "각 플랫폼의 트렌드 특성을 파악합니다."
    ),
    "시간차": (
        "시간차 분석은 특정 이슈가 뉴스와 SNS 중 "
        "어느 플랫폼에서 먼저 등장했는지 시간 순서를 분석합니다. "
        "동기화 분석은 두 플랫폼 간 키워드 출현 시점의 상관관계를 측정합니다."
    ),
    "참여도": (
        "참여도 키워드 분석은 커뮤니티에서 댓글, 추천 등 "
        "사용자 참여가 높은 게시글의 키워드를 식별합니다. "
        "평균 참여 점수(avg_engagement_score)를 기준으로 순위를 매깁니다."
    ),
    "트렌드": (
        "트렌드 분석은 뉴스 기사와 SNS/커뮤니티 게시글을 자동 수집하고, "
        "키워드 빈도 분석, 급상승 탐지, 플랫폼 비교, 시간차 분석, "
        "시간대별 트렌드, 참여도 분석을 수행합니다. "
        "분석 결과는 최신 수집 데이터를 기반으로 주기적으로 자동 갱신됩니다."
    ),
}


def _has_news_intent(q: str) -> bool:
    """쿼리에 뉴스 출처 의도가 있는지 판별 (대소문자 무시)"""
    q_l = q.lower()
    return any(kw in q_l for kw in NEWS_INDICATORS)


def _has_community_intent(q: str) -> bool:
    """쿼리에 커뮤니티 출처 의도가 있는지 판별 (대소문자 무시)"""
    q_l = q.lower()
    return any(kw in q_l for kw in COMMUNITY_INDICATORS)


def _apply_negation(q: str):
    """
    부정/배제 패턴을 감지하여 뉴스/커뮤니티 의도를 override.
    "뉴스 없이", "뉴스 빼고" → 뉴스 OFF
    "SNS만", "커뮤니티만" → 커뮤니티 ON + 뉴스 OFF

    Returns: (news_override, community_override)
        True=강제 ON, False=강제 OFF, None=기본 감지 유지
    """
    q_l = q.lower()
    news_ovr = None
    comm_ovr = None

    # "X 없이 / 빼고 / 제외 / 말고 / 없는 / 빼줘" → 해당 출처 OFF
    for src_words, target in [
        (["뉴스", "기사"], "news"),
        (["sns", "커뮤니티", "소셜"], "community"),
    ]:
        for sw in src_words:
            if re.search(
                rf"{sw}\s*(?:는\s*)?(?:없이|없는|빼고|빼줘|제외|말고|안\s)",
                q_l,
            ):
                if target == "news":
                    news_ovr = False
                else:
                    comm_ovr = False

    # "X만" → 해당 출처만 ON
    for sw, target in [
        ("뉴스만", "news"),
        ("기사만", "news"),
        ("sns만", "community"),
        ("커뮤니티만", "community"),
        ("소셜만", "community"),
    ]:
        if sw in q_l:
            if target == "news":
                news_ovr, comm_ovr = True, False
            else:
                comm_ovr, news_ovr = True, False

    return news_ovr, comm_ovr


def _detect_source_intent(query_text: str) -> str:
    """
    사용자가 뉴스/커뮤니티/분석결과 중 어떤 출처를 원하는지 키워드 기반으로 판별.
    LLM 호출 없이 순수 키워드 매칭 + 조합 매칭 + 부정 표현 처리.

    Returns: "news", "community", "analysis", "analysis+search",
             "trend_enhanced", or "any"
    """
    q = (query_text or "").strip().lower()

    # ── 1) 분석 의도: 직접 구문 매칭 또는 "키워드" + 수식어 조합 ──
    has_keyword_word = "키워드" in q
    has_qualifier = any(qual in q for qual in KEYWORD_QUALIFIERS)

    has_analysis = (
        any(phrase in q for phrase in _ANALYSIS_DIRECT_PHRASES)
        or (has_keyword_word and has_qualifier)
        or (has_keyword_word and any(w in q for w in POPULARITY_WORDS))
    )

    # 토큰 분리 매칭: "플랫폼" + "비교"/"분석"/"차이" 각각 존재 시 분석 의도
    if not has_analysis and "플랫폼" in q:
        if any(w in q for w in ["비교", "분석", "차이"]):
            has_analysis = True

    # ── 2) 순위/인기도 감지: 강도 접두어 + 인기 수식어 ──
    has_intensity = any(p in q for p in INTENSITY_PREFIXES)
    has_popularity = any(w in q for w in POPULARITY_WORDS)
    has_ranking = has_intensity and has_popularity

    # ── 3) 뉴스/커뮤니티 감지 ──
    has_news = _has_news_intent(q)
    has_community = _has_community_intent(q)

    # ── 3.5) 부정/배제 패턴 적용 ("뉴스 없이", "SNS만" 등) ──
    news_ovr, comm_ovr = _apply_negation(q)
    if news_ovr is not None:
        has_news = news_ovr
    if comm_ovr is not None:
        has_community = comm_ovr
    # 한쪽만 명시적 OFF이고 다른 쪽 언급 없으면 → 반대 출처 ON 추론
    # 예: "뉴스 없는 걸로 보여줘" → 뉴스 OFF, 커뮤니티 ON
    if news_ovr is False and comm_ovr is None and not has_community:
        has_community = True
    if comm_ovr is False and news_ovr is None and not has_news:
        has_news = True

    # 복합 의도: 분석 결과 + 뉴스/커뮤니티 (예: "키워드 분석을 토대로 관련 뉴스 알려줘")
    if has_analysis and (has_news or has_community):
        return "analysis+search"
    if has_analysis:
        return "analysis"

    # 트렌드 보강 검색: 인기 수식어 감지
    # Case 1: 강도 접두어 + 인기 수식어 ("가장 유명한 ~", "제일 핫한 ~")
    # Case 2: 인기 수식어 단독 ("핫한 내용", "유명한 소식", "인기있는 이슈")
    if has_ranking or has_popularity:
        if has_news and not has_community:
            return "trend_enhanced:news"
        elif has_community and not has_news:
            return "trend_enhanced:community"
        return "trend_enhanced"

    # Case 3: 트렌드 신호 단어 + 탐색적 쿼리 (특정 주제 없음)
    # "재밌는 이슈 있어?", "대충 요즘 트렌드만 알려줘", "뭐가 제일 컸어?"
    # 단, 부정/배제 패턴으로 출처가 명시적으로 지정된 경우는 건너뜀
    has_negation_applied = news_ovr is not None or comm_ovr is not None
    has_trend_signal = any(w in q for w in TREND_SIGNAL_WORDS)
    if has_trend_signal and not has_negation_applied:
        topic_words = _extract_topic_from_query(query_text)
        if not topic_words:
            if has_news and not has_community:
                return "trend_enhanced:news"
            elif has_community and not has_news:
                return "trend_enhanced:community"
            return "trend_enhanced"

    if has_news and not has_community:
        return "news"
    if has_community and not has_news:
        return "community"
    return "any"


# ── 분석 결과 검색 (TrendAnalysisResult → LLM context) ──


def _gen_keyword_phrases(qualifiers: list) -> list:
    """수식어 × '키워드' 조합 자동 생성 (띄어쓰기 유/무 모두 포함)"""
    phrases = []
    for q in qualifiers:
        phrases.append(f"{q} 키워드")
        phrases.append(f"{q}키워드")
    return phrases


# hot_keywords / surge_keywords 감지용 수식어 (KEYWORD_QUALIFIERS · POPULARITY_WORDS 에서 파생)
_HOT_KW_QUALIFIERS = [
    "인기",
    "인기있는",
    "인기 있는",
    "핫",
    "핫한",
    "뜨는",
    "뜨고 있는",
    "요즘",
    "최근",
    "트렌드",
    "상위",
    "톱",
    "top",
    "hot",
    "popular",
]
_SURGE_KW_QUALIFIERS = ["급상승", "급상승하는", "급등", "급등하는"]

# 쿼리 키워드 → analysis_type 매핑 (hot/surge 는 조합 자동 생성)
_ANALYSIS_TYPE_KEYWORDS = {
    "keywords": [
        "키워드 분석",
        "키워드분석",
        "뉴스 키워드",
        "sns 키워드",
        "커뮤니티 키워드",
        "많이 언급",
        "자주 언급",
        "자주 등장",
    ],
    "compare_platforms": [
        "플랫폼 비교",
        "플랫폼비교",
        "뉴스 sns 비교",
        "뉴스 커뮤니티 비교",
        "뉴스와 커뮤니티",
        "뉴스랑 커뮤니티",
        "플랫폼별 비교",
        "플랫폼별 키워드",
    ],
    "hot_keywords": _gen_keyword_phrases(_HOT_KW_QUALIFIERS),
    "surge_keywords": _gen_keyword_phrases(_SURGE_KW_QUALIFIERS) + ["surge"],
    "time_lag": [
        "시간차 분석",
        "시간차분석",
        "반영이 빨라",
        "반영이 느려",
        "반영 속도",
        "먼저 반영",
        "빠른 플랫폼",
        "느린 플랫폼",
    ],
    "trend_synchronization": ["트렌드 동기화", "동기화 분석"],
    "hourly_trends": ["시간대별 분석", "시간대별 트렌드"],
    "engagement_keywords": ["참여도 분석", "참여도 키워드", "engagement"],
}

# "키워드" + 수식어 조합 → analysis_type 매핑 (KEYWORD_QUALIFIERS 기반)
_KEYWORD_QUALIFIER_TO_TYPE = {
    "hot_keywords": [
        q
        for q in KEYWORD_QUALIFIERS
        if q not in ("급상승", "급등", "트렌드", "많이", "자주")
    ],
    "surge_keywords": ["급상승", "급등"],
    "keywords": ["많이", "자주", "트렌드"],
}


def _detect_analysis_types(query_text: str) -> List[str]:
    """쿼리에서 관련 analysis_type 목록을 추출한다."""
    q = (query_text or "").strip().lower()
    matched = []

    # 1) 직접 매칭
    for atype, keywords in _ANALYSIS_TYPE_KEYWORDS.items():
        if any(kw in q for kw in keywords):
            matched.append(atype)

    # 2) "키워드" + 수식어 조합 매칭 (직접 매칭에서 못 잡은 경우)
    if not matched and "키워드" in q:
        for atype, qualifiers in _KEYWORD_QUALIFIER_TO_TYPE.items():
            if any(qual in q for qual in qualifiers):
                matched.append(atype)
                break
        # 수식어 없이 "키워드" 단독이면 hot_keywords로 기본 매핑
        if not matched:
            matched.append("hot_keywords")

    return matched


def _fetch_analysis_context(
    query_text: str, max_results: int = 3
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    TrendAnalysisResult에서 관련 분석 결과를 조회하여 LLM context 문자열로 변환.
    """
    from analyzer.models import TrendAnalysisResult

    matched_types = _detect_analysis_types(query_text)

    # 특정 분석 유형이 감지되면 해당 유형만, 아니면 최신 결과 전체
    if matched_types:
        qs = TrendAnalysisResult.objects.filter(
            analysis_type__in=matched_types,
            status="success",
        ).order_by("-created_at")[:max_results]
    else:
        qs = TrendAnalysisResult.objects.filter(
            status="success",
        ).order_by(
            "-created_at"
        )[:max_results]

    if not qs.exists():
        return "", []

    blocks = []
    sources = []

    for result in qs:
        # 분석 유형 한글 라벨
        type_labels = {
            "keywords": "키워드 분석",
            "compare_platforms": "플랫폼 비교 분석",
            "hot_keywords": "인기 키워드 분석",
            "surge_keywords": "급상승 키워드 분석",
            "time_lag": "시간차 분석",
            "trend_synchronization": "트렌드 동기화 분석",
            "hourly_trends": "시간대별 트렌드 분석",
            "engagement_keywords": "참여도 키워드 분석",
        }
        label = type_labels.get(result.analysis_type, result.analysis_type)

        # summary가 있으면 summary 우선, 없으면 result_data에서 핵심 추출
        summary_data = result.summary or {}
        result_data = result.result_data or {}

        # 핵심 정보만 추출 (LLM context 크기 제한)
        context_parts = [
            f"[분석결과] {label} | 기간: {result.days or '?'}일 | 날짜: {result.created_at.strftime('%Y-%m-%d %H:%M')}"
        ]

        # top_keywords 추출 (있으면)
        for key in [
            "top_keywords",
            "news_surge_keywords",
            "sns_surge_keywords",
            "engagement_keywords",
            "viral_keywords",
            "synchronized_keywords",
            "common_keywords",
        ]:
            items = result_data.get(key, [])
            if items and isinstance(items, list):
                top_items = items[:10]
                lines = []
                for item in top_items:
                    if isinstance(item, dict):
                        kw = item.get("keyword", "")
                        freq = (
                            item.get("frequency")
                            or item.get("growth_ratio")
                            or item.get("correlation")
                            or ""
                        )
                        if kw:
                            lines.append(f"  - {kw}: {freq}")
                if lines:
                    context_parts.append(f"{key}:")
                    context_parts.extend(lines)

        # 통계 요약
        stats = (
            result_data.get("statistics") or result_data.get("summary") or summary_data
        )
        if stats and isinstance(stats, dict):
            stats_lines = []
            for k, v in list(stats.items())[:8]:
                stats_lines.append(f"  - {k}: {v}")
            if stats_lines:
                context_parts.append("통계:")
                context_parts.extend(stats_lines)

        # news/sns 결과가 있는 compare_platforms 등
        for platform_key in ["news", "sns"]:
            platform_data = result_data.get(platform_key, {})
            if isinstance(platform_data, dict):
                top_kws = platform_data.get("top_keywords", [])[:5]
                if top_kws:
                    kw_strs = [
                        f"{item.get('keyword', '')}({item.get('frequency', ''):.3f})"
                        for item in top_kws
                        if isinstance(item, dict)
                    ]
                    if kw_strs:
                        context_parts.append(
                            f"{platform_key} 상위 키워드: {', '.join(kw_strs)}"
                        )

        block_text = "\n".join(context_parts)
        blocks.append(block_text)

        sources.append(
            {
                "id": f"analysis:{result.id}",
                "distance": 0.0,
                "url": None,
                "title": f"{label} ({result.created_at.strftime('%Y-%m-%d')})",
                "type": "analysis",
                "platform": result.platform,
                "publisher": None,
                "category": result.analysis_type,
                "identifier": None,
                "source_display": label,
                "published_at": result.created_at.isoformat(),
                "excerpt": block_text[:300],
            }
        )

    context = (
        "[EVIDENCE_QUALITY: adequate]\n[SOURCE_FILTER: analysis]\n\n"
        + "\n\n---\n\n".join(blocks)
    )
    return context, sources


def _extract_keywords_from_analysis(
    query_text: str, max_keywords: int = 10
) -> List[str]:
    """
    분석 결과(TrendAnalysisResult)에서 상위 키워드를 추출한다.
    compound intent("analysis+search")에서 벡터 검색 쿼리를 만들기 위해 사용.
    """
    from analyzer.models import TrendAnalysisResult

    matched_types = _detect_analysis_types(query_text)

    if matched_types:
        qs = TrendAnalysisResult.objects.filter(
            analysis_type__in=matched_types,
            status="success",
        ).order_by("-created_at")[:3]
    else:
        qs = TrendAnalysisResult.objects.filter(
            status="success",
        ).order_by(
            "-created_at"
        )[:3]

    keywords = []
    keyword_keys = [
        "top_keywords",
        "news_surge_keywords",
        "sns_surge_keywords",
        "engagement_keywords",
        "viral_keywords",
        "synchronized_keywords",
        "common_keywords",
        "hot_keywords",
    ]

    for result in qs:
        result_data = result.result_data or {}

        for key in keyword_keys:
            items = result_data.get(key, [])
            if items and isinstance(items, list):
                for item in items[:5]:
                    if isinstance(item, dict):
                        kw = (item.get("keyword") or "").strip()
                        if kw and kw not in keywords:
                            keywords.append(kw)

        # news/sns 하위 구조에서도 추출
        for platform_key in ["news", "sns"]:
            platform_data = result_data.get(platform_key, {})
            if isinstance(platform_data, dict):
                for item in platform_data.get("top_keywords", [])[:5]:
                    if isinstance(item, dict):
                        kw = (item.get("keyword") or "").strip()
                        if kw and kw not in keywords:
                            keywords.append(kw)

        if len(keywords) >= max_keywords:
            break

    return keywords[:max_keywords]


def _extract_topic_from_query(query_text: str) -> List[str]:
    """
    쿼리에서 순위/인기도 수식어와 불용어를 제거한 뒤 주제 키워드를 추출.
    예: "요즘 가장 유명한 국제정세 뉴스에 대해 알려줘" → ["국제정세"]
        "가장 핫한 AI 소식" → ["AI"]
        "제일 인기있는 정치 이슈" → ["정치"]
        "요즘 가장 유명한 내용은 뭐야?" → [] (주제 없음)
    """
    q = (query_text or "").strip()
    if not q:
        return []

    # 제거할 패턴: 공유 상수(INTENSITY_PREFIXES 등) + 일반 불용어
    _noise_words = (
        set(INTENSITY_PREFIXES)
        | set(POPULARITY_WORDS)
        | set(TREND_SIGNAL_WORDS)
        | {f"{w}한" for w in POPULARITY_WORDS}  # "유명한", "핫한" 등
        | {f"{w}는" for w in TREND_SIGNAL_WORDS}  # "재밌는", "흥미로운" 등
        | {"인기있는", "인기 있는", "재밌는", "재미있는", "흥미로운"}
        | set(NEWS_INDICATORS)
        | set(COMMUNITY_INDICATORS)
        | {
            # 시간 표현
            "지금",
            "현재",
            "오늘",
            # 일반 불용어
            "내용",
            "이슈",
            "소식",
            "정보",
            "많이",
            "대해",
            "대해서",
            "관련",
            "관련된",
            "관해",
            "관해서",
            "알려줘",
            "알려주세요",
            "알려",
            "뭐야",
            "뭐",
            "뭔가",
            "어때",
            "뭐가",
            "뭘",
            "뭐를",
            "뭐든",
            "어디",
            "어디서",
            "언제",
            "얼마나",
            "컸어",
            "많지",
            "있지",
            "없지",
            "됐어",
            "했어",
            # 감정/상태 표현 (주제가 아닌 수식어)
            "불안",
            "불안해",
            "불안한",
            "걱정",
            "걱정돼",
            "무서워",
            "답답",
            "답답해",
            "짜증",
            "화나",
            "힘들",
            "미치겠",
            "심각",
            "심각해",
            "궁금",
            "궁금해",
            "안좋",
            "나쁜",
            "좋은",
            # 의문/탐색 표현 (질문 구성어)
            "무슨일",
            "무슨일이",
            "어쩌다",
            "어떡해",
            "어쩌면",
            "진짜",
            "너무",
            # 조사·어미·기능어
            "에",
            "은",
            "는",
            "이",
            "가",
            "을",
            "를",
            "의",
            "로",
            "으로",
            "에서",
            "에게",
            "한테",
            "들",
            "좀",
            "해줘",
            "없이",
            "있는",
            "없는",
            "있어",
            "없어",
            "있는지",
            "없는지",
            "있나",
            "없나",
            "있을",
            "없을",
            "있게",
            "없게",
        }
    )

    # 토큰 분리 후 노이즈 제거
    # 동사 어미도 제거 (조사 제거만으로는 "무슨일이야" → "무슨일" 변환 불가)
    _topic_verb_suffixes = [
        "이야",
        "인가",
        "일까",
        "인지",
        "인데",
        "이냐",
        "해줘",
        "해봐",
        "할까",
        "했어",
        "하는",
        "한다",
        "뭐야",
        "뭐냐",
        "뭐임",
        "있어",
        "있나",
        "없어",
        "줘",
        "해",
    ]
    tokens = q.split()
    topics = []
    for token in tokens:
        # 조사 제거
        cleaned = _strip_ko_particles(token)
        # 동사 어미 제거 (긴 접미사부터 매칭)
        for suf in _topic_verb_suffixes:
            if cleaned.endswith(suf) and len(cleaned) > len(suf) + 1:
                cleaned = cleaned[: -len(suf)]
                break
        if cleaned.lower() in _noise_words or len(cleaned) < 2:
            continue
        # 영문은 그대로
        if re.match(r"^[a-zA-Z]+$", cleaned) and len(cleaned) >= 2:
            topics.append(cleaned)
            continue
        # 한글 2글자 이상
        if re.match(r"^[가-힣]{2,}$", cleaned):
            topics.append(cleaned)

    return topics[:3]


def _get_trending_keywords_by_topic(
    topic_words: List[str],
    max_keywords: int = 10,
    platform: Optional[str] = None,
) -> Tuple[List[str], str]:
    """
    TrendAnalysisResult에서 topic_words와 관련된 상위 키워드를 추출.
    topic_words가 빈 리스트면 전체 상위 키워드를 반환.

    Args:
        topic_words: 주제 키워드 리스트
        max_keywords: 최대 키워드 수
        platform: "news" 또는 "community" — 해당 플랫폼 키워드 우선 수집

    Returns:
        (키워드 리스트, 분석 결과 요약 텍스트)
    """
    from analyzer.models import TrendAnalysisResult

    # 최신 성공 분석 결과 조회 (hot_keywords, keywords, surge_keywords 우선)
    priority_types = ["hot_keywords", "keywords", "surge_keywords", "compare_platforms"]
    qs = TrendAnalysisResult.objects.filter(
        status="success",
        analysis_type__in=priority_types,
    ).order_by("-created_at")[:5]

    if not qs.exists():
        # fallback: 모든 타입에서
        qs = TrendAnalysisResult.objects.filter(
            status="success",
        ).order_by(
            "-created_at"
        )[:5]

    # 플랫폼별로 우선 수집할 키워드 키 분류
    _news_keys = [
        "top_keywords",
        "news_hot_keywords",
        "news_surge_keywords",
    ]
    _sns_keys = [
        "top_keywords",
        "sns_hot_keywords",
        "sns_surge_keywords",
        "engagement_keywords",
        "viral_keywords",
    ]
    _common_keys = [
        "hot_keywords",
        "common_keywords",
        "synchronized_keywords",
    ]

    # 트렌드 키워드로 의미없는 범용 단어 필터
    _trending_stopwords = {
        "기간",
        "전달",
        "이후",
        "이상",
        "이하",
        "대비",
        "관련",
        "이번",
        "현재",
        "최근",
        "지난",
        "올해",
        "내년",
        "작년",
        "오늘",
        "내일",
        "대표",
        "위원",
        "관계자",
        "측",
        "사람",
        "경우",
        "부분",
        "상황",
        "시작",
        "진행",
        "발표",
        "설명",
        "의견",
        "입장",
        "결과",
        "내용",
        "문제",
        "방법",
        "시간",
        "이유",
        "정도",
        "사실",
        "가능",
        "예정",
        "계획",
        "참여",
        "지원",
        "제공",
        "운영",
        "활동",
        "조사",
        "요청",
    }

    def _extract_freq_from_item(item: dict) -> float:
        """키워드 항목에서 빈도/중요도 값 추출 (다양한 필드명 대응)"""
        # 1) 직접 frequency 값 (keywords, hourly_trends, engagement)
        freq = item.get("frequency")
        if freq:
            try:
                return float(freq)
            except (ValueError, TypeError):
                pass

        # 2) news_frequency + sns_frequency 합산 (common_keywords용)
        nf = item.get("news_frequency", 0) or 0
        sf = item.get("sns_frequency", 0) or 0
        if nf or sf:
            try:
                return float(nf) + float(sf)
            except (ValueError, TypeError):
                pass

        # 3) current_frequency (surge_keywords)
        cf = item.get("current_frequency")
        if cf:
            try:
                return float(cf)
            except (ValueError, TypeError):
                pass

        # 4) growth_ratio (surge_keywords — 이전 대비 증가 배수)
        gr = item.get("growth_ratio")
        if gr:
            try:
                return float(gr)
            except (ValueError, TypeError):
                pass

        # 5) correlation (trend_synchronization)
        corr = item.get("correlation")
        if corr:
            try:
                return float(corr)
            except (ValueError, TypeError):
                pass

        # 6) avg_engagement_score (engagement_keywords)
        eng = item.get("avg_engagement_score")
        if eng:
            try:
                return float(eng)
            except (ValueError, TypeError):
                pass

        return 0.0

    def _collect_from_list(items, analysis_type, out):
        """리스트에서 (keyword, freq, type) 튜플 추출"""
        if not items or not isinstance(items, list):
            return
        for item in items:
            if isinstance(item, dict):
                kw = (item.get("keyword") or "").strip()
                if kw:
                    out.append((kw, _extract_freq_from_item(item), analysis_type))

    def _is_valid_trending_kw(kw: str) -> bool:
        """범용 불용어를 트렌드 키워드에서 제외"""
        return kw not in _trending_stopwords and len(kw) >= 2

    # 플랫폼별로 분리 수집
    primary_items = []  # 요청 플랫폼 키워드 (우선)
    secondary_items = []  # 반대 플랫폼 키워드 (보충)
    common_items = []  # 공통/교차 키워드

    for result in qs:
        result_data = result.result_data or {}

        # 최상위 + nested result 두 레벨 모두 탐색
        search_layers = [result_data]
        nested_result = result_data.get("result", {})
        if isinstance(nested_result, dict):
            search_layers.append(nested_result)

        for layer in search_layers:
            # 뉴스 전용 키워드
            for key in _news_keys:
                items_list = layer.get(key, [])
                if items_list and isinstance(items_list, list):
                    target = primary_items if platform == "news" else secondary_items
                    _collect_from_list(items_list, result.analysis_type, target)

            # SNS 전용 키워드
            for key in _sns_keys:
                if key == "top_keywords":
                    continue  # news와 중복되므로 하위 구조에서 처리
                items_list = layer.get(key, [])
                if items_list and isinstance(items_list, list):
                    target = (
                        primary_items if platform == "community" else secondary_items
                    )
                    _collect_from_list(items_list, result.analysis_type, target)

            # 공통 키워드 (양쪽 공통)
            for key in _common_keys:
                items_list = layer.get(key, [])
                if items_list and isinstance(items_list, list):
                    _collect_from_list(items_list, result.analysis_type, common_items)

        # news/sns 하위 구조 (keywords 타입: news.top_keywords, sns.top_keywords)
        for platform_key in ["news", "sns"]:
            platform_data = result_data.get(platform_key, {})
            if isinstance(platform_data, dict):
                sub_items = platform_data.get("top_keywords", [])
                if sub_items:
                    if platform == "news" and platform_key == "news":
                        _collect_from_list(
                            sub_items, result.analysis_type, primary_items
                        )
                    elif platform == "community" and platform_key == "sns":
                        _collect_from_list(
                            sub_items, result.analysis_type, primary_items
                        )
                    elif platform_key == "news":
                        target = (
                            secondary_items
                            if platform == "community"
                            else primary_items
                        )
                        _collect_from_list(sub_items, result.analysis_type, target)
                    else:  # sns
                        target = (
                            secondary_items if platform == "news" else primary_items
                        )
                        _collect_from_list(sub_items, result.analysis_type, target)

    # 플랫폼 지정 시: primary(해당 플랫폼)만 사용, 부족하면 common → secondary 순서로 보충
    # 플랫폼 미지정 시: 전부 합산 (기존 동작)
    if platform in ("news", "community") and primary_items:
        all_kw_items = primary_items + common_items
        # primary + common으로 충분하면 secondary(반대 플랫폼) 미사용
        if len(set(kw for kw, _, _ in all_kw_items)) < max_keywords:
            all_kw_items.extend(secondary_items)
    else:
        all_kw_items = primary_items + common_items + secondary_items

    if not all_kw_items:
        return [], ""

    # 불용어 필터
    all_kw_items = [
        (kw, freq, at) for kw, freq, at in all_kw_items if _is_valid_trending_kw(kw)
    ]

    if not all_kw_items:
        return [], ""

    # 주제 필터: topic_words가 있으면 관련 키워드만 필터
    topic_matched = False
    if topic_words:
        # 복합어를 2글자 단위로 분해하여 부분 매칭 확대
        # 예: "국제정세" → ["국제정세", "국제", "정세"]
        topic_lower = []
        for t in topic_words:
            t_low = t.lower()
            topic_lower.append(t_low)
            # 3글자 이상 한글 복합어는 2글자 단위로도 분해
            if len(t_low) >= 3 and re.match(r"^[가-힣]+$", t_low):
                for i in range(len(t_low) - 1):
                    chunk = t_low[i : i + 2]
                    if chunk not in topic_lower:
                        topic_lower.append(chunk)

        filtered = []
        for kw, freq, atype in all_kw_items:
            kw_lower = kw.lower()
            if any(t in kw_lower or kw_lower in t for t in topic_lower):
                filtered.append((kw, freq, atype))

        if filtered:
            all_kw_items = filtered
            topic_matched = True

    # 중복 제거 + 동일 키워드는 더 높은 빈도를 선택
    kw_best: Dict[str, Tuple[float, str]] = {}  # kw → (best_freq, atype)
    for kw, freq, atype in all_kw_items:
        try:
            freq_val = float(freq) if freq else 0
        except (ValueError, TypeError):
            freq_val = 0
        if kw not in kw_best or freq_val > kw_best[kw][0]:
            kw_best[kw] = (freq_val, atype)

    unique_items = [(kw, fv, at) for kw, (fv, at) in kw_best.items()]

    unique_items.sort(key=lambda x: x[1], reverse=True)
    top_items = unique_items[:max_keywords]

    keywords = [item[0] for item in top_items]

    # 주제 관련 키워드를 못 찾았으면 주제 단어 자체를 키워드로 사용
    if topic_words and not topic_matched:
        keywords = topic_words + keywords[: max_keywords - len(topic_words)]

    # 요약 텍스트 (LLM context에 포함)
    if topic_matched:
        summary_lines = [
            f"[분석결과] '{', '.join(topic_words)}' 관련 트렌드 키워드 (중요도순):"
        ]
    else:
        summary_lines = ["[분석결과] 트렌드 상위 키워드 (중요도순):"]
    for kw, freq, atype in top_items:
        if freq >= 1.0:
            # growth_ratio 등 배수 값
            freq_str = f"{freq:.1f}x"
        elif freq > 0:
            # 상대 빈도 → 퍼센트 표시
            freq_str = f"{freq * 100:.2f}%"
        else:
            freq_str = "-"
        summary_lines.append(f"  - {kw} ({freq_str})")

    summary_text = "\n".join(summary_lines)
    return keywords, summary_text


def _detect_time_scope(query_text: str, intent_time_focus: str = "") -> "tuple":
    """
    쿼리의 시간 범위를 (range_start_dt, range_end_dt, scope_days) 튜플로 반환.
    - range_start_dt: datetime(KST) 범위 시작 (inclusive), None=제약없음
    - range_end_dt:   datetime(KST) 범위 끝 (exclusive), None=현재까지
    - scope_days:     int 근사 범위 (recency 가중치용), 0=제약없음

    KST 자정 기준으로 캘린더 일 경계 사용.
    예: "어제" → (어제00:00 KST, 오늘00:00 KST, 2) → 어제 하루만
    """
    from datetime import datetime, timedelta, timezone

    KST = timezone(timedelta(hours=9))
    now_kst = datetime.now(KST)
    today_midnight = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)

    q = (query_text or "").strip().lower()

    # 특정 날짜 패턴: "3월 16일", "3/16", "03월 16일" 등
    import re as _re

    _date_match = _re.search(r"(\d{1,2})\s*[월/\.]\s*(\d{1,2})\s*일?", q)
    if _date_match:
        month = int(_date_match.group(1))
        day = int(_date_match.group(2))
        year = now_kst.year
        try:
            target = today_midnight.replace(month=month, day=day)
            # 미래 날짜면 작년으로
            if target > now_kst:
                target = target.replace(year=year - 1)
            return (target, target + timedelta(days=1), 1)
        except ValueError:
            pass  # 잘못된 날짜(2월 30일 등)는 무시

    # 강한 시간 신호 (좁은 범위)
    if any(kw in q for kw in ["오늘", "today", "방금", "지금"]):
        return (today_midnight, None, 1)
    if any(kw in q for kw in ["어제", "yesterday"]):
        return (today_midnight - timedelta(days=1), today_midnight, 2)
    if any(kw in q for kw in ["이번주", "이번 주", "금주"]):
        # 이번주 월요일 00:00 KST ~ 현재
        weekday = today_midnight.weekday()  # 0=월
        this_week_start = today_midnight - timedelta(days=weekday)
        return (this_week_start, None, 7)
    if any(kw in q for kw in ["지난주", "저번주", "저번 주", "지난 주"]):
        weekday = today_midnight.weekday()
        this_week_start = today_midnight - timedelta(days=weekday)
        last_week_start = this_week_start - timedelta(days=7)
        return (last_week_start, this_week_start, 14)

    # 중간 시간 신호
    if any(
        kw in q
        for kw in [
            "최근",
            "최신",
            "요즘",
            "요새",
            "핫한",
            "핫이슈",
            "트렌드",
            "트렌딩",
            "인기",
            "화제",
            "떠오르는",
        ]
    ):
        return (today_midnight - timedelta(days=14), None, 14)
    if any(kw in q for kw in ["이번달", "이번 달", "금월"]):
        this_month_start = today_midnight.replace(day=1)
        return (this_month_start, None, 30)
    if any(kw in q for kw in ["지난달", "저번달", "저번 달", "지난 달"]):
        this_month_start = today_midnight.replace(day=1)
        last_month_start = (this_month_start - timedelta(days=1)).replace(day=1)
        return (last_month_start, this_month_start, 60)

    # intent_info의 time_focus 활용
    if intent_time_focus == "recent":
        return (today_midnight - timedelta(days=14), None, 14)
    if intent_time_focus == "current":
        return (today_midnight - timedelta(days=30), None, 30)

    return (None, None, 0)


def _recency_score(published_at: str, now_ts: float) -> float:
    """
    published_at ISO 문자열 → 최근일수록 높은 점수 (0.0~1.0).
    decay: 7일 지나면 0.5, 30일 지나면 ~0.19, 90일 지나면 ~0.07
    """
    if not published_at:
        return 0.0
    try:
        from datetime import datetime

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


class OpenAIResponsesLLM:
    """
    ✅ OpenAI Responses API 기반 LLM 래퍼 (안정성/호환성 강화)
    - SDK 응답 구조가 dict/object 어느 쪽이든 텍스트 추출
    - 모델이 지원하지 않는 파라미터로 400 나면 자동 제거 후 1회 재시도
    """

    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY") or getattr(
            settings, "OPENAI_API_KEY", None
        )
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY가 설정되어 있지 않습니다. (.env 확인)")

        # ✅ httpx 주입으로 'proxies' 충돌 방어
        try:
            import httpx
            from openai import OpenAI

            _llm_timeout = int(os.getenv("OPENAI_API_TIMEOUT", 45))
            http_client = httpx.Client(
                timeout=httpx.Timeout(_llm_timeout, connect=10.0)
            )
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

    def _extract_text_recursive(
        self, obj: Any, depth: int = 0, max_depth: int = 3
    ) -> List[str]:
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
                                        if (
                                            isinstance(text_val, str)
                                            and text_val.strip()
                                        ):
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
                                    if c.get("type") in (
                                        "text",
                                        "output_text",
                                        "text_delta",
                                    ):
                                        text_val = c.get("text") or c.get("content")
                                        if (
                                            isinstance(text_val, str)
                                            and text_val.strip()
                                        ):
                                            chunks.append(text_val.strip())
                                    # text 필드가 직접 있는 경우
                                    elif (
                                        "text" in c
                                        and isinstance(c["text"], str)
                                        and c["text"].strip()
                                    ):
                                        chunks.append(c["text"].strip())
                        # text 필드가 직접 있는 경우
                        if (
                            "text" in item
                            and isinstance(item["text"], str)
                            and item["text"].strip()
                        ):
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
                                        if (
                                            isinstance(text_val, str)
                                            and text_val.strip()
                                        ):
                                            chunks.append(text_val.strip())
                                    elif isinstance(s, str) and s.strip():
                                        chunks.append(s.strip())
                            elif isinstance(summary, str) and summary.strip():
                                chunks.append(summary.strip())

                        content = getattr(item, "content", None)
                        if isinstance(content, str) and content.strip():
                            chunks.append(content.strip())
                        elif hasattr(item, "text") and isinstance(
                            getattr(item, "text"), str
                        ):
                            text_val = getattr(item, "text")
                            if text_val.strip():
                                chunks.append(text_val.strip())

            # output이 dict인 경우
            elif isinstance(out, dict):
                if (
                    "text" in out
                    and isinstance(out["text"], str)
                    and out["text"].strip()
                ):
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
                if "output_text" in res_dict and isinstance(
                    res_dict["output_text"], str
                ):
                    if res_dict["output_text"].strip():
                        return res_dict["output_text"].strip()

                # output 확인
                if "output" in res_dict:
                    out = res_dict["output"]
                    if isinstance(out, list) and len(out) > 0:
                        for item in out:
                            if isinstance(item, dict):
                                if (
                                    "text" in item
                                    and isinstance(item["text"], str)
                                    and item["text"].strip()
                                ):
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
                    logger.debug(
                        f"[LLM 텍스트 추출] 재귀적 탐색으로 텍스트 발견 (길이={len(longest)})"
                    )
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
        final_model = (
            model
            or getattr(settings, "OPENAI_MODEL", None)
            or os.getenv("OPENAI_MODEL", "gpt-4o")
        )

        # ✅ 기본값(없으면 settings/.env 사용)
        # 한국어 3~5문장 기준: 토큰 소비가 영어 대비 2~3배 → 800이 적정
        default_max = int(
            os.getenv(
                "OPENAI_MAX_OUTPUT_TOKENS",
                getattr(settings, "OPENAI_MAX_OUTPUT_TOKENS", 800),
            )
        )
        if max_output_tokens is None or int(max_output_tokens) <= 0:
            max_output_tokens = default_max

        # ✅ 비용 절감을 위한 상한선 설정
        MAX_HARD_CAP = int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS_CAP", 1200))
        if max_output_tokens > MAX_HARD_CAP:
            max_output_tokens = MAX_HARD_CAP

        # ✅ 최소 방어
        if max_output_tokens < 16:
            max_output_tokens = 16

        # ✅ gpt-5 계열은 temperature 지원이 안 나는 경우가 많아서 "있을 때만" + "모델 허용일 때만" 넣음
        # (여기서는 안전하게 gpt-5*이면 temperature를 payload에서 제외)
        supports_temperature = not str(final_model).startswith("gpt-5")

        # ── System Prompt ──
        # 설계 원칙: LlamaIndex(사전지식 금지) + LangChain(문장 수 제한) + Anthropic(context 상단 배치)
        system_prompt = (
            "당신은 뉴스·커뮤니티 트렌드 Q&A 어시스턴트입니다.\n"
            "아래 규칙을 반드시 따르세요.\n\n"
            "1. CONTEXT에 제공된 자료만 사용하여 답변하세요. CONTEXT에 없는 내용은 답변하지 마세요. "
            "사전 지식이나 추측을 섞지 마세요.\n"
            "2. [뉴스] 자료는 사실로, [커뮤니티] 자료는 '온라인 반응'으로, [분석결과] 자료는 데이터 기반 분석으로 인용하세요.\n"
            "3. 답변은 3~5문장 이내로 작성하세요. 핵심 트렌드 1~2가지로 요약하세요.\n"
            "4. 다음 표현은 절대 사용하지 마세요: '관련 자료가 부족하지만', '자료가 부족하지만', "
            "'관련 자료에 따르면', '검색 결과에 따르면'. "
            "CONTEXT 자료를 바탕으로 자연스럽게 답변하세요.\n"
            "5. 번호 매기기(1. 2. 3.)나 항목 나열을 하지 마세요. 핵심 이슈를 하나의 흐름으로 자연스럽게 풀어 설명하세요.\n"
            "6. 한국어 존댓말(~합니다, ~있습니다)로 작성하세요.\n"
            "7. 완전한 문장으로 끝내세요. 추가 질문이나 제안은 붙이지 마세요.\n"
            "8. 뉴스와 커뮤니티 간 비교·대조를 요청받았을 때, CONTEXT에 양쪽 자료가 모두 있으면 "
            "각 출처의 관점 차이를 설명하세요. 한쪽 자료만 있으면 비교가 불가능하다고 답변하세요.\n"
            "9. 이 서비스는 한국 사용자를 위한 서비스입니다. 질문에 특정 국가가 명시되지 않으면 "
            "한국 기준으로 답변하세요. CONTEXT에 한국 관련 자료와 다른 나라 자료가 섞여 있으면 "
            "한국 관련 자료를 우선하여 답변하세요. CONTEXT에 한국 관련 자료가 없고 다른 나라 자료만 있으면 "
            "해당 주제에 대한 한국 정보가 없다고 답변하세요. 다른 나라 정보로 대체하지 마세요."
        )
        if instructions:
            system_prompt += f"\n\n[추가 지시사항]\n{instructions}"

        # ── User Prompt ──
        # Anthropic 방식: 긴 CONTEXT를 상단에, 질문을 하단에 배치 (성능 향상)
        context_length = len(context) if context else 0
        logger.debug(
            f"[LLM 프롬프트] 질문 길이={len(query_text)}, CONTEXT 길이={context_length}"
        )
        if context_length < 50:
            logger.warning(f"[LLM 프롬프트] CONTEXT가 너무 짧음 ({context_length}자)")

        # 국가 미지정 시 한국 기준 안내를 질문에 직접 첨부
        _q_lower_llm = query_text.lower()
        _country_mentioned = any(
            c in _q_lower_llm
            for c in [
                "한국",
                "미국",
                "일본",
                "중국",
                "영국",
                "독일",
                "프랑스",
                "러시아",
                "북한",
                "대만",
                "호주",
                "캐나다",
                "인도",
                "이란",
                "korea",
                "usa",
                "japan",
                "china",
                "uk",
            ]
        )
        _korea_hint = (
            "\n(특정 국가가 명시되지 않았으므로 한국 기준으로 답변하세요. "
            "CONTEXT에 한국 자료가 없으면 해당 정보가 없다고 답변하세요.)"
            if not _country_mentioned
            else ""
        )

        user_prompt = (
            f"[CONTEXT]\n{context}\n\n"
            f"---\n\n"
            f"위 CONTEXT만을 근거로 다음 질문에 답변하세요.\n"
            f"[질문] {query_text}{_korea_hint}"
        )
        logger.debug(f"[LLM 프롬프트] 전체 프롬프트 길이={len(user_prompt)}")

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
                logger.info(
                    f"[LLM] gpt-5 모델, 사용자 요청에 따라 reasoning effort를 '{reasoning_effort}'로 설정"
                )
            else:
                # reasoning을 'low'로 설정하여 reasoning 토큰 사용량 최소화
                payload["reasoning"] = {"effort": "low"}
                logger.info(
                    "[LLM] gpt-5 모델이므로 reasoning effort를 'low'로 설정 (output 토큰 확보)"
                )
        elif reasoning_effort and reasoning_effort.strip():
            # 다른 모델은 요청한 대로 설정
            payload["reasoning"] = {"effort": reasoning_effort.strip()}

        if supports_temperature and temperature is not None:
            payload["temperature"] = temperature

        logger.debug(
            f"[LLM 호출 시작] model={final_model} max_output_tokens={max_output_tokens}"
        )
        logger.debug(
            f"[LLM payload] reasoning 설정: {payload.get('reasoning', 'None')}"
        )
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
                    _wait = 2**_attempt
                    logger.warning(
                        f"[LLM] 일시적 오류, {_wait}s 후 재시도 ({_attempt+1}/{_max_retries}): {_net_err}"
                    )
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
                "output_type": (
                    type(getattr(res, "output", None)).__name__
                    if hasattr(res, "output")
                    else None
                ),
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

            logger.error(
                f"[LLM 빈 응답] model={final_model} 소요={dt:.2f}s response_id={response_id}"
            )
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

        logger.info(
            f"[LLM 호출 완료] model={final_model} 소요={dt:.2f}s 글자수={len(text)}"
        )
        return LLMResult(text=text, raw=res)

    def classify_intent(
        self, query_text: str, *, model: Optional[str] = None
    ) -> Dict[str, Any]:
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
        final_model = (
            model
            or getattr(settings, "OPENAI_MODEL", None)
            or os.getenv("OPENAI_MODEL", "gpt-4o")
        )

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
            if sentiment_focus not in (
                "neutral",
                "positive",
                "negative",
                "controversial",
            ):
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
            logger.warning(
                f"[IntentRouter] classify_intent 실패: {type(e).__name__}: {str(e)}"
            )
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
        final_model = (
            model
            or getattr(settings, "OPENAI_MODEL", None)
            or os.getenv("OPENAI_MODEL", "gpt-4o")
        )

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
            logger.warning(
                f"[reformulate_query] 실패, 원본 사용: {type(e).__name__}: {str(e)}"
            )
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
            has_strong_signal = bool(
                re.search(r"[A-Z]{2,}|[0-9]|[#@]|\".+?\"|'.+?'", q)
            )
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
                "요즘",
                "최근",
                "이슈",
                "뉴스",
                "기사",
                "사건",
                "소식",
                "정리",
                "알려줘",
                "뭐",
                "무슨",
                "있어",
                "있냐",
                "있나요",
                "관련",
                "좀",
                "좀요",
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
        final_model = model or _get_setting("OPENAI_MODEL", "gpt-4o")
        final_temperature = (
            temperature
            if temperature is not None
            else float(_get_setting("OPENAI_TEMPERATURE", 0.25))
        )
        final_max_tokens = (
            int(_get_setting("OPENAI_MAX_OUTPUT_TOKENS", 700))
            if (max_output_tokens is None or int(max_output_tokens) <= 0)
            else int(max_output_tokens)
        )
        if final_max_tokens < 16:
            final_max_tokens = 16

        # ✅ 2) 최신 데이터 버전(수집 시각) 계산: 새 뉴스/소셜 들어오면 버전이 바뀜
        latest_news = NewsArticle.objects.aggregate(Max("collected_at"))[
            "collected_at__max"
        ]
        latest_social = SocialMediaPost.objects.aggregate(Max("collected_at"))[
            "collected_at__max"
        ]

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
            cached_response = self.cache_service.get_cached_response(
                _cache_query, cache_context=cache_context
            )
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
        if bool(_get_setting("RAG_INTENT_ROUTER_ENABLED", True)) or bool(
            use_intent_router
        ):
            if self._should_skip_intent_llm(query_text):
                logger.info(f"[IntentRouter] 스킵(룰 매칭): query='{query_text}'")
            else:
                intent_info = self.llm.classify_intent(
                    query_text=query_text, model=final_model
                )
                logger.info(f"[IntentRouter] {intent_info}")

        # ========================================
        # 분석 결과 의도 감지 → DB 직접 조회 (벡터 검색 불필요)
        # ========================================
        source_intent = _detect_source_intent(query_text)
        logger.info(f"[RAG 검색] source_intent={source_intent}")

        # ========================================
        # 메타 질문 핸들러 (시스템 기준/방법론에 대한 질문)
        # 분석 의도가 동시에 감지된 경우, 분석 파이프라인을 우선 (메타 건너뜀)
        # ========================================
        q_lower_for_meta = (query_text or "").lower()
        is_meta_question = any(
            p in q_lower_for_meta for p in _META_QUESTION_PATTERNS
        ) and source_intent not in ("analysis", "analysis+search")
        if is_meta_question:
            # 가장 관련성 높은 설명 선택
            meta_parts = []
            for key, explanation in _META_EXPLANATIONS.items():
                if key in q_lower_for_meta:
                    meta_parts.append(explanation)
            if not meta_parts:
                meta_parts.append(_META_EXPLANATIONS["트렌드"])

            meta_context = "[시스템 설명]\n" + "\n\n".join(meta_parts)
            logger.info(
                f"[RAG 메타] 시스템 설명 질문 감지, 키: {[k for k in _META_EXPLANATIONS if k in q_lower_for_meta]}"
            )

            llm_result = self.llm.answer(
                query_text=query_text,
                context=meta_context,
                model=final_model,
                temperature=final_temperature,
                max_output_tokens=final_max_tokens,
                reasoning_effort=reasoning_effort,
                instructions=instructions,
            )
            answer = (
                llm_result.text
                if isinstance(llm_result, LLMResult)
                else str(llm_result)
            )

            try:
                history = QueryHistory.objects.create(
                    query_text=query_text,
                    answer_text=answer,
                    sources=[{"type": "system_meta", "title": "시스템 설명"}],
                )
                history_id = history.id
            except Exception as e:
                logger.error(f"[RAG] QueryHistory 저장 실패: {e}")
                history_id = None

            return {
                "answer": answer,
                "sources": [{"type": "analysis", "title": "시스템 설명"}],
                "query": query_text,
                "history_id": history_id,
                "model": final_model,
            }

        if source_intent == "analysis":
            _t_analysis = time.time()
            analysis_context, analysis_sources = _fetch_analysis_context(query_text)

            if analysis_context:
                logger.info(
                    f"[RAG 분석] 분석 결과 {len(analysis_sources)}건 조회 ({time.time() - _t_analysis:.2f}s)"
                )

                # LLM에 분석 결과 context 전달
                llm_result = self.llm.answer(
                    query_text=query_text,
                    context=analysis_context,
                    model=final_model,
                    temperature=final_temperature,
                    max_output_tokens=final_max_tokens,
                    reasoning_effort=reasoning_effort,
                    instructions=instructions,
                )
                answer = (
                    llm_result.text
                    if isinstance(llm_result, LLMResult)
                    else str(llm_result)
                )

                # QueryHistory 저장
                try:
                    history = QueryHistory.objects.create(
                        query_text=query_text,
                        answer_text=answer,
                        sources=analysis_sources,
                    )
                    history_id = history.id
                except Exception as e:
                    logger.error(f"[RAG] QueryHistory 저장 실패: {e}")
                    history_id = None

                logger.info(
                    f"[RAG 타이밍] 전체 파이프라인(분석): {time.time() - _t_pipeline:.2f}s"
                )
                return {
                    "answer": answer,
                    "sources": analysis_sources,
                    "query": query_text,
                    "history_id": history_id,
                    "model": final_model,
                }
            else:
                logger.info("[RAG 분석] 분석 결과 없음, 일반 검색으로 fallback")

        # ========================================
        # 복합 의도: 분석 결과 + 뉴스/커뮤니티 검색 결합
        # ========================================
        if source_intent == "analysis+search":
            _t_compound = time.time()
            analysis_context, analysis_sources = _fetch_analysis_context(query_text)
            analysis_keywords = _extract_keywords_from_analysis(query_text)

            if analysis_keywords:
                # 분석 결과에서 추출한 키워드로 벡터 검색
                search_query_for_compound = " ".join(analysis_keywords[:5])
                logger.info(
                    f"[RAG 복합] 분석 키워드로 벡터 검색: {analysis_keywords[:5]}"
                )

                retrieval_k = max(int(top_k) * 6, int(top_k) + 20)
                compound_candidates = self.vector_db.similarity_search(
                    search_query_for_compound,
                    top_k=retrieval_k,
                    distance_threshold=0.75,
                    fetch_multiplier=3,
                    balance_types=False,
                )

                # 키워드 검색도 병행
                kw_candidates = self.vector_db.keyword_search(
                    query_text=search_query_for_compound,
                    keywords=analysis_keywords[:5],
                    top_k=retrieval_k,
                )

                # 병합 (중복 제거)
                seen = set()
                merged = []
                for r in kw_candidates + compound_candidates:
                    if r.id not in seen:
                        seen.add(r.id)
                        merged.append(r)

                # 뉴스/커뮤니티 필터 (사용자가 뉴스 또는 커뮤니티를 명시한 경우)
                want_news = _has_news_intent(query_text or "")
                want_community = _has_community_intent(query_text or "")
                # 부정/배제 패턴 적용
                n_ovr, c_ovr = _apply_negation(query_text or "")
                if n_ovr is not None:
                    want_news = n_ovr
                if c_ovr is not None:
                    want_community = c_ovr

                if want_news and not want_community:
                    typed = [
                        r for r in merged if _infer_type(r.id, r.metadata) == "news"
                    ]
                    if typed:
                        merged = typed
                elif want_community and not want_news:
                    typed = [
                        r for r in merged if _infer_type(r.id, r.metadata) == "social"
                    ]
                    if typed:
                        merged = typed

                # 상위 N개만 사용
                merged = merged[: int(top_k)]

                if merged:
                    # 뉴스/커뮤니티 context 생성
                    search_context, search_sources = _build_context_and_sources(
                        merged,
                        max_doc_chars=700,
                        evidence_quality="adequate",
                        source_intent="any",
                    )

                    # 분석 결과 + 뉴스/커뮤니티 context 결합
                    combined_context = ""
                    if analysis_context:
                        combined_context += analysis_context + "\n\n---\n\n"
                    combined_context += search_context

                    combined_sources = analysis_sources + search_sources

                    llm_result = self.llm.answer(
                        query_text=query_text,
                        context=combined_context,
                        model=final_model,
                        temperature=final_temperature,
                        max_output_tokens=final_max_tokens,
                        reasoning_effort=reasoning_effort,
                        instructions=instructions,
                    )
                    answer = (
                        llm_result.text
                        if isinstance(llm_result, LLMResult)
                        else str(llm_result)
                    )

                    try:
                        history = QueryHistory.objects.create(
                            query_text=query_text,
                            answer_text=answer,
                            sources=combined_sources,
                        )
                        history_id = history.id
                    except Exception as e:
                        logger.error(f"[RAG] QueryHistory 저장 실패: {e}")
                        history_id = None

                    logger.info(
                        f"[RAG 타이밍] 복합 의도 파이프라인: {time.time() - _t_compound:.2f}s "
                        f"(분석 {len(analysis_sources)}건 + 검색 {len(search_sources)}건)"
                    )
                    return {
                        "answer": answer,
                        "sources": combined_sources,
                        "query": query_text,
                        "history_id": history_id,
                        "model": final_model,
                    }

            # 분석 키워드 추출 실패 시 분석 결과만으로 응답 (fallback)
            if analysis_context:
                llm_result = self.llm.answer(
                    query_text=query_text,
                    context=analysis_context,
                    model=final_model,
                    temperature=final_temperature,
                    max_output_tokens=final_max_tokens,
                    reasoning_effort=reasoning_effort,
                    instructions=instructions,
                )
                answer = (
                    llm_result.text
                    if isinstance(llm_result, LLMResult)
                    else str(llm_result)
                )
                try:
                    history = QueryHistory.objects.create(
                        query_text=query_text,
                        answer_text=answer,
                        sources=analysis_sources,
                    )
                    history_id = history.id
                except Exception as e:
                    logger.error(f"[RAG] QueryHistory 저장 실패: {e}")
                    history_id = None

                return {
                    "answer": answer,
                    "sources": analysis_sources,
                    "query": query_text,
                    "history_id": history_id,
                    "model": final_model,
                }

            # 분석 결과도 없으면 일반 검색으로 fallback
            logger.info("[RAG 복합] 분석 결과 없음, 일반 검색으로 fallback")
            source_intent = "any"

        # ========================================
        # 트렌드 보강 검색: "가장 유명한", "제일 핫한" 등
        # 분석 결과에서 상위 키워드를 추출 → 벡터 검색 쿼리 보강
        # ========================================
        _trend_fallback_intent = "any"
        if source_intent.startswith("trend_enhanced"):
            # "trend_enhanced:news" → fallback은 "news"로
            if ":" in source_intent:
                _trend_fallback_intent = source_intent.split(":")[1]
            _t_trend = time.time()

            # 쿼리에서 주제 키워드 추출 (예: "국제정세", "정치", "AI")
            topic_words = _extract_topic_from_query(query_text)
            logger.info(f"[RAG 트렌드] 주제 추출: {topic_words}")

            # 분석 결과에서 주제 관련 상위 키워드 가져오기
            # 플랫폼 정보 전달: "news" → 뉴스 키워드 우선, "community" → SNS 우선
            _kw_platform = None
            if _trend_fallback_intent == "news":
                _kw_platform = "news"
            elif _trend_fallback_intent == "community":
                _kw_platform = "community"
            trending_keywords, trend_summary = _get_trending_keywords_by_topic(
                topic_words,
                max_keywords=10,
                platform=_kw_platform,
            )
            logger.info(f"[RAG 트렌드] 추출된 트렌드 키워드: {trending_keywords[:5]}")

            if trending_keywords:
                # 트렌드 키워드로 벡터 검색 (주제 단어를 앞에 배치하여 시맨틱 검색 방향 설정)
                trend_search_query = " ".join(trending_keywords[:5])
                if topic_words:
                    trend_search_query = (
                        " ".join(topic_words) + " " + trend_search_query
                    )

                retrieval_k = max(int(top_k) * 6, int(top_k) + 20)
                trend_candidates = self.vector_db.similarity_search(
                    trend_search_query,
                    top_k=retrieval_k,
                    distance_threshold=0.75,
                    fetch_multiplier=3,
                    balance_types=False,
                )

                # 키워드 검색도 병행 (주제 단어도 키워드에 포함)
                search_keywords = list(trending_keywords[:5])
                for tw in topic_words:
                    if tw not in search_keywords:
                        search_keywords.insert(0, tw)
                trend_kw_candidates = self.vector_db.keyword_search(
                    query_text=trend_search_query,
                    keywords=search_keywords[:7],
                    top_k=retrieval_k,
                )

                # 병합 (중복 제거, 키워드 매칭 우선)
                seen = set()
                merged = []
                for r in trend_kw_candidates + trend_candidates:
                    if r.id not in seen:
                        seen.add(r.id)
                        merged.append(r)

                # 뉴스/커뮤니티 필터 (intent에서 이미 감지된 정보 활용)
                want_news = _trend_fallback_intent == "news"
                want_community = _trend_fallback_intent == "community"
                if not want_news and not want_community:
                    # fallback에 정보 없으면 쿼리에서 직접 판별
                    want_news = _has_news_intent(query_text or "")
                    want_community = _has_community_intent(query_text or "")
                    # 부정/배제 패턴 적용
                    n_ovr, c_ovr = _apply_negation(query_text or "")
                    if n_ovr is not None:
                        want_news = n_ovr
                    if c_ovr is not None:
                        want_community = c_ovr

                if want_news and not want_community:
                    typed = [
                        r for r in merged if _infer_type(r.id, r.metadata) == "news"
                    ]
                    if typed:
                        merged = typed
                elif want_community and not want_news:
                    typed = [
                        r for r in merged if _infer_type(r.id, r.metadata) == "social"
                    ]
                    if typed:
                        merged = typed

                # 키워드 overlap + 거리 기반 재랭킹 (일반 파이프라인과 동일한 품질 필터)
                merged = rank_results_generic(
                    query_text=query_text,
                    results=merged,
                    final_k=int(top_k) * 2,
                    min_keyword_hits=1,
                )

                # 시간 필터 (일반 파이프라인과 동일 - KST 캘린더 범위)
                _t_range_start, _t_range_end, _t_scope = _detect_time_scope(
                    query_text,
                    intent_time_focus=intent_info.get("time_focus", ""),
                )
                if _t_range_start is not None:
                    from datetime import datetime, timezone

                    _trend_recent = []
                    for r in merged:
                        pa = (r.metadata or {}).get("published_at", "")
                        if pa:
                            try:
                                doc_dt = datetime.fromisoformat(pa)
                                if doc_dt.tzinfo is None:
                                    doc_dt = doc_dt.replace(tzinfo=timezone.utc)
                                if doc_dt >= _t_range_start:
                                    if _t_range_end is None or doc_dt < _t_range_end:
                                        _trend_recent.append(r)
                            except (ValueError, TypeError):
                                pass
                    _scope_lbl = (
                        f"{_t_range_start.strftime('%m/%d')}~{_t_range_end.strftime('%m/%d')}"
                        if _t_range_end
                        else f"{_t_range_start.strftime('%m/%d')}~현재"
                    )
                    if _trend_recent:
                        logger.info(
                            f"[RAG 트렌드 시간필터] {_scope_lbl}: "
                            f"{len(_trend_recent)}개 (전체 {len(merged)}개에서 필터)"
                        )
                        merged = _trend_recent
                    else:
                        # 시간 필터 결과가 없으면 시간순 정렬 유지
                        merged.sort(
                            key=lambda r: (r.metadata or {}).get("published_at", ""),
                            reverse=True,
                        )
                        logger.info(
                            f"[RAG 트렌드 시간필터] {_scope_lbl} 결과 없음, "
                            f"전체 {len(merged)}개를 시간순 정렬"
                        )

                # 거리 게이트: 너무 먼 결과 제거
                hard_dist = float(_get_setting("RAG_HARD_DISTANCE_THRESHOLD", 1.05))
                gated = [r for r in merged if r.distance <= hard_dist]
                if gated:
                    merged = gated

                # 뉴스/커뮤니티 균형 선택 (명시적 필터가 없는 경우만)
                final_k = int(top_k)
                if not want_news and not want_community and len(merged) > final_k:
                    news_pool = [
                        r for r in merged if _infer_type(r.id, r.metadata) == "news"
                    ]
                    social_pool = [
                        r for r in merged if _infer_type(r.id, r.metadata) == "social"
                    ]

                    if news_pool and social_pool:
                        # 뉴스 70% 목표, 부족하면 상대 타입으로 보충
                        news_target = max(2, int(final_k * 0.7))
                        news_take = min(len(news_pool), news_target)
                        social_take = min(len(social_pool), final_k - news_take)
                        if news_take + social_take < final_k:
                            news_take = min(len(news_pool), final_k - social_take)
                        merged = news_pool[:news_take] + social_pool[:social_take]
                        merged.sort(key=lambda r: r.distance)
                    else:
                        merged = merged[:final_k]
                else:
                    merged = merged[:final_k]

                if merged:
                    search_context, search_sources = _build_context_and_sources(
                        merged,
                        max_doc_chars=700,
                        evidence_quality="adequate",
                        source_intent="any",
                    )

                    # 트렌드 요약 + 뉴스/커뮤니티 context 결합
                    combined_context = trend_summary + "\n\n---\n\n" + search_context

                    trend_source = {
                        "id": "trend:summary",
                        "distance": 0.0,
                        "url": None,
                        "title": "트렌드 분석 상위 키워드",
                        "type": "analysis",
                        "platform": None,
                        "publisher": None,
                        "category": "trend_enhanced",
                        "identifier": None,
                        "source_display": "트렌드 분석",
                        "published_at": None,
                        "excerpt": trend_summary[:300],
                    }
                    combined_sources = [trend_source] + search_sources

                    llm_result = self.llm.answer(
                        query_text=query_text,
                        context=combined_context,
                        model=final_model,
                        temperature=final_temperature,
                        max_output_tokens=final_max_tokens,
                        reasoning_effort=reasoning_effort,
                        instructions=instructions,
                    )
                    answer = (
                        llm_result.text
                        if isinstance(llm_result, LLMResult)
                        else str(llm_result)
                    )

                    try:
                        history = QueryHistory.objects.create(
                            query_text=query_text,
                            answer_text=answer,
                            sources=combined_sources,
                        )
                        history_id = history.id
                    except Exception as e:
                        logger.error(f"[RAG] QueryHistory 저장 실패: {e}")
                        history_id = None

                    logger.info(
                        f"[RAG 타이밍] 트렌드 보강 파이프라인: {time.time() - _t_trend:.2f}s "
                        f"(트렌드 키워드: {trending_keywords[:3]}, 검색 결과: {len(search_sources)}건)"
                    )
                    return {
                        "answer": answer,
                        "sources": combined_sources,
                        "query": query_text,
                        "history_id": history_id,
                        "model": final_model,
                    }

            # 트렌드 키워드로 적절한 결과를 못 찾음 → 원래 의도로 fallback
            logger.info(
                f"[RAG 트렌드] 트렌드 보강 실패, fallback intent={_trend_fallback_intent}"
            )
            source_intent = _trend_fallback_intent

        # ========================================
        # LLM 기반 쿼리 재구성 (대화형 → 검색용)
        # ========================================
        # 명확한 쿼리(엔티티 2개+ 또는 짧고 구체적)는 재구성 스킵하여 지연/비용 절감
        pre_entities = _extract_key_entities(query_text)
        query_tokens = query_text.split()
        skip_reformulate = (len(pre_entities) >= 2) or (
            len(pre_entities) >= 1 and len(query_tokens) <= 4
        )

        _t_stage = time.time()
        if skip_reformulate:
            reformulated_query = query_text
            logger.info(
                f"[RAG 검색] 명확한 쿼리이므로 재구성 스킵: '{query_text}' (엔티티: {pre_entities})"
            )
        else:
            reformulated_query = self.llm.reformulate_query(
                query_text, model=final_model
            )
            logger.info(
                f"[RAG 검색] 원본: '{query_text}' → 재구성: '{reformulated_query}'"
            )
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
        candidate_distance_threshold = float(
            _get_setting("RAG_CANDIDATE_DISTANCE_THRESHOLD", 0.75)
        )

        expanded_queries = _expand_query_for_search(search_query, key_entities)
        logger.info(f"[RAG 검색] 쿼리 확장: {expanded_queries}")

        semantic_candidates = []
        seen_semantic_ids: set = set()
        for eq in expanded_queries:
            eq_results = self.vector_db.similarity_search(
                eq,
                top_k=retrieval_k,
                distance_threshold=candidate_distance_threshold,
                fetch_multiplier=3,
                balance_types=False,
            )
            for r in eq_results:
                if r.id not in seen_semantic_ids:
                    seen_semantic_ids.add(r.id)
                    semantic_candidates.append(r)
        logger.info(
            f"[RAG 검색] 시맨틱 검색 결과: {len(semantic_candidates)}개 (쿼리 {len(expanded_queries)}개)"
        )

        # 3) 키워드 검색 (후보군 B) - 엔티티가 있을 때만
        keyword_candidates: List[SearchResult] = []
        if key_entities:
            keyword_candidates = self.vector_db.keyword_search(
                query_text=reformulated_query,  # 재구성된 쿼리로 유사도 계산
                keywords=key_entities,
                top_k=retrieval_k,
            )
            logger.info(
                f"[RAG 검색] 키워드 검색 결과: {len(keyword_candidates)}개 (엔티티: {key_entities})"
            )

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

        logger.info(
            f"[RAG 검색] 병합된 후보군: {len(candidates)}개 (키워드: {len(keyword_candidates)}, 시맨틱: {len(semantic_candidates)})"
        )

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

        logger.info(
            f"[RAG 타이밍] 검색(시맨틱+키워드+Reddit): {time.time() - _t_stage:.2f}s"
        )

        if not candidates:
            logger.warning(f"[RAG 검색] 검색 결과 없음: query={query_text}")
            return {
                "answer": f"'{query_text}'에 대한 관련 정보를 찾을 수 없습니다. 다른 키워드로 검색해보세요.",
                "sources": [],
                "query": query_text,
                "model": final_model,
            }

        # ========================================
        # STEP -1: 극도로 모호한 질문 / 대화형 후속 질문 조기 거부
        # ========================================
        _q_lower = query_text.strip().lower()

        # (A-0) 시스템 메타 질문 감지 ("너 누구야?", "뭘 할 수 있어?" 등)
        _meta_patterns = [
            "너 누구",
            "넌 누구",
            "당신은 누구",
            "뭘 할 수 있",
            "뭐 할 수 있",
            "무엇을 할 수",
            "어떤 기능",
            "사용법",
            "사용 방법",
            "어떻게 써",
            "어떻게 사용",
        ]
        if any(p in _q_lower for p in _meta_patterns):
            return {
                "answer": (
                    "저는 뉴스와 커뮤니티 트렌드 데이터를 기반으로 답변하는 "
                    "Q&A 어시스턴트입니다.\n\n"
                    "다음과 같은 질문에 답변할 수 있습니다:\n"
                    '- 최신 뉴스 요약 (예: "오늘 주요 뉴스 알려줘")\n'
                    '- 특정 주제 검색 (예: "AI 관련 최신 소식")\n'
                    '- 커뮤니티 반응 (예: "레딧에서 한국에 대해 뭐라고 해?")\n'
                    '- 트렌드 분석 (예: "요즘 가장 많이 언급된 키워드")'
                ),
                "sources": [],
                "query": query_text,
                "model": final_model,
            }

        # (A) 대화형 후속 질문 감지 (이전 답변 참조형)
        # "그거 믿어도 돼?", "출처가 어디야?", "더 자세히", "요약해줘" 등
        # 검색 가능한 주제(엔티티)가 없는 대화형 질문
        _followup_patterns = [
            "믿어도",
            "믿을 수",
            "신뢰",
            "정확해",
            "맞아",
            "출처가",
            "출처는",
            "출처를",
            "근거가",
            "근거는",
            "더 자세히",
            "더 알려",
            "더 설명",
            "좀 더",
            "요약해",
            "정리해줘",
            "다시 말해",
            "다시 설명",
            "왜 그래",
            "왜 그런",
            "무슨 말",
            "무슨 뜻",
            "뭔 말",
            "뭔 소리",
        ]
        _is_followup = any(p in _q_lower for p in _followup_patterns)
        if _is_followup:
            # 실제 검색 주제가 있는지 확인 (엔티티 추출)
            _followup_stop = {
                "믿어",
                "출처",
                "근거",
                "신뢰",
                "정확",
                "요약",
                "정리",
                "자세히",
                "설명",
                "알려",
                "보여",
                "말해",
                "얘기",
                "어디",
                "뭐야",
                "뭔지",
                "어때",
                "맞아",
                "맞는",
                "그거",
                "이거",
                "저거",
                "그건",
                "이건",
                "더",
                "좀",
                "해줘",
                "해주",
                "해봐",
                "할래",
                "할까",
                "다시",
                "왜",
                "뭔",
                "무슨",
                "진짜",
                "확실",
                "사실",
            }
            _fu_tokens = re.findall(r"[가-힣]{2,}", query_text)
            # 부분 문자열 매칭: "믿어도"→"믿어" 포함, "출처가"→"출처" 포함
            _fu_meaningful = [
                t
                for t in _fu_tokens
                if not any(s in t or t in s for s in _followup_stop)
            ]
            if not _fu_meaningful:
                return {
                    "answer": (
                        "이전 대화 맥락을 참조할 수 없어 답변이 어렵습니다. "
                        "궁금한 주제나 키워드를 포함해서 다시 질문해 주세요.\n"
                        '예: "삼성전자 관련 뉴스 출처 알려줘",'
                        ' "AI 트렌드 자세히 알려줘"'
                    ),
                    "sources": [],
                    "query": query_text,
                    "model": final_model,
                }

        # (B) 극도로 모호한 질문 (불용어만으로 구성)
        _vague_stop = {
            "그거",
            "이거",
            "저거",
            "뭐",
            "어떻게",
            "됐어",
            "됐나",
            "됐냐",
            "어때",
            "있어",
            "없어",
            "했어",
            "할까",
            "인가",
            "인지",
            "그래서",
            "좀",
            "혹시",
            "그런데",
            "근데",
            "아까",
            "거기",
            "여기",
            "자세히",
            "알려줘",
            "알려줘요",
            "알려주세요",
            "설명해",
            "설명해줘",
            "말해줘",
            "말해봐",
            "얘기해",
            "얘기해줘",
            "보여줘",
            "더",
            "좀더",
            "다시",
            "한번",
            "한번더",
        }
        _vague_tokens = re.findall(r"[가-힣]{2,}", query_text)
        _vague_meaningful = [t for t in _vague_tokens if t not in _vague_stop]
        if len(_vague_meaningful) == 0 and len(query_text.strip()) < 20:
            return {
                "answer": (
                    "질문이 너무 모호하여 관련 정보를 검색할 수 없습니다. "
                    "구체적인 키워드나 주제를 포함해 다시 질문해 주세요."
                ),
                "sources": [],
                "query": query_text,
                "model": final_model,
            }

        # ========================================
        # STEP 0: 시간 스코프 감지 + 날짜 기반 사전 필터
        # ========================================
        range_start_dt, range_end_dt, time_scope_days = _detect_time_scope(
            query_text,
            intent_time_focus=intent_info.get("time_focus", ""),
        )
        _now_ts = time.time()

        if range_start_dt is not None:
            from datetime import datetime, timezone

            recent_candidates = []
            for r in candidates:
                pa = (r.metadata or {}).get("published_at", "")
                if not pa:
                    continue
                try:
                    doc_dt = datetime.fromisoformat(pa.replace("Z", "+00:00"))
                    if doc_dt.tzinfo is None:
                        doc_dt = doc_dt.replace(tzinfo=timezone.utc)
                    # 범위 필터: range_start <= doc_dt < range_end
                    if doc_dt >= range_start_dt:
                        if range_end_dt is None or doc_dt < range_end_dt:
                            recent_candidates.append(r)
                except (ValueError, TypeError):
                    pass

            scope_label = (
                f"{range_start_dt.strftime('%m/%d %H:%M')}~{range_end_dt.strftime('%m/%d %H:%M')}"
                if range_end_dt
                else f"{range_start_dt.strftime('%m/%d %H:%M')}~현재"
            )

            # 시간 필터 후 결과가 충분하면 사용, 아니면 원본 유지
            if len(recent_candidates) >= max(int(top_k), 3):
                logger.info(
                    f"[RAG 시간필터] {scope_label}: {len(recent_candidates)}개 "
                    f"(전체 {len(candidates)}개에서 필터)"
                )
                candidates = recent_candidates
            elif recent_candidates:
                # 결과가 부족해도 1개 이상이면 해당 기간 결과 사용
                logger.info(
                    f"[RAG 시간필터] {scope_label}: {len(recent_candidates)}개 (부족하지만 사용)"
                )
                candidates = recent_candidates
            else:
                # 해당 기간 결과가 0개면 시간순 정렬로 fallback
                candidates.sort(
                    key=lambda r: (r.metadata or {}).get("published_at", ""),
                    reverse=True,
                )
                logger.info(
                    f"[RAG 시간필터] {scope_label} 결과 0개, "
                    f"전체 {len(candidates)}개를 시간순으로 정렬"
                )

        # ========================================
        # STEP A: 의도 기반 소스 타입 사전 필터링 (랭킹 전에 적용)
        # ========================================
        # source_intent는 상단에서 이미 감지됨
        if source_intent == "news":
            typed = [r for r in candidates if _infer_type(r.id, r.metadata) == "news"]
            if typed:
                logger.info(
                    f"[RAG 필터] news intent → 후보군 {len(candidates)}개에서 뉴스 {len(typed)}개로 사전 필터"
                )
                candidates = typed
            else:
                logger.warning(
                    f"[RAG 필터] news intent이지만 뉴스 후보 없음, {len(candidates)}개 전체 후보 유지"
                )
        elif source_intent == "community":
            typed = [r for r in candidates if _infer_type(r.id, r.metadata) == "social"]
            if typed:
                logger.info(
                    f"[RAG 필터] community intent → 후보군 {len(candidates)}개에서 소셜 {len(typed)}개로 사전 필터"
                )
                candidates = typed
            else:
                logger.warning(
                    f"[RAG 필터] community intent이지만 소셜 후보 없음, {len(candidates)}개 전체 후보 유지"
                )

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
        # STEP B-2: 키워드 매칭 문서의 distance 보정
        # ========================================
        _dist_skip_words = {
            "자세히",
            "알려줘",
            "알려주세요",
            "설명해",
            "설명해줘",
            "말해줘",
            "보여줘",
            "뉴스",
            "기사",
            "소식",
            "정보",
            "내용",
            "관련",
            "최근",
            "최신",
            "오늘",
            "어제",
            "인기",
            "핫한",
            "주요",
            "가장",
            "제일",
            "뭐야",
            "뭐가",
            "어때",
            "있어",
        }
        _filtered_entities = [e for e in key_entities if e not in _dist_skip_words]
        if _filtered_entities:
            for r in results:
                meta = r.metadata or {}
                combined = f"{meta.get('title', '')}\n{meta.get('excerpt', '')}\n{r.document or ''}"
                combined_lower = combined.lower()
                match_count = sum(
                    1 for ent in _filtered_entities if ent.lower() in combined_lower
                )
                if match_count > 0 and r.distance > 0.40:
                    # cosine 거리 0.80 초과는 보정 제외 (우연한 키워드 매칭)
                    if r.distance > 0.80:
                        continue
                    old_dist = r.distance
                    reduction = min(match_count * 0.05, 0.10)
                    # distance가 높을수록 보정 효과 감소
                    if r.distance > 0.60:
                        reduction *= 0.5
                    r.distance = max(r.distance - reduction, 0.30)
                    logger.debug(
                        f"[RAG distance 보정] entity {match_count}개 매칭: "
                        f"distance {old_dist:.3f} → {r.distance:.3f}"
                    )

        # ========================================
        # STEP C: 거리 게이트 (하드 → 소프트 → fallback 단계적 적용)
        # ========================================
        hard_distance = float(_get_setting("RAG_HARD_DISTANCE_THRESHOLD", 1.05))
        force_low_quality = False
        gated = [r for r in results if r.distance <= hard_distance]
        if len(gated) >= max(int(top_k) // 2, 1):
            # 충분한 결과가 하드 게이트 통과
            results = gated
        elif gated:
            # 하드 게이트 통과는 적지만 있음 → 소프트 범위로 보충
            soft_gated = [
                r
                for r in results
                if r.distance <= hard_distance * 1.3 and r not in gated
            ]
            results = gated + soft_gated
        else:
            # 모든 문서가 하드 게이트 초과 → 거리순 정렬 후 top_k 유지
            results.sort(key=lambda r: r.distance)
            results = results[: int(top_k)]
            force_low_quality = True

        # ========================================
        # STEP E: 키워드 매칭 + 최신성 기반 정렬 → top_k 선택
        # ========================================
        # 정렬 우선순위:
        #   1) 엔티티 직접 매칭 보너스 (가장 강력)
        #   2) 키워드 overlap
        #   3) 최신성 가산 (시간 민감 쿼리일수록 강하게)
        #   4) 시맨틱 거리 (tiebreaker)
        final_distance_cutoff = float(_get_setting("RAG_DISTANCE_THRESHOLD", 0.15))
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
                entity_bonus = (
                    sum(1 for ent in key_entities if ent.lower() in combined_lower) * 10
                )

            within_soft = 1 if r.distance <= final_distance_cutoff else 0
            # 최신성 점수 (0.0~1.0, 가중치 적용)
            recency = (
                _recency_score(meta.get("published_at", ""), _now_ts) * recency_weight
            )
            # 뉴스 미세 우선
            news_boost = 0.01 if _infer_type(r.id, r.metadata) == "news" else 0

            score = entity_bonus + overlap + within_soft + recency + news_boost
            return (-score, r.distance)

        results.sort(key=_sort_key)

        # 뉴스/커뮤니티 균형 선택 (source_intent=="any"일 때 70:30)
        final_k = int(top_k)
        if source_intent == "any" and len(results) > final_k:
            news_pool = [r for r in results if _infer_type(r.id, r.metadata) == "news"]
            social_pool = [
                r for r in results if _infer_type(r.id, r.metadata) == "social"
            ]

            if news_pool and social_pool:
                # 뉴스 70% 목표, 부족하면 상대 타입으로 보충
                news_target = max(2, int(final_k * 0.7))
                news_take = min(len(news_pool), news_target)
                social_take = min(len(social_pool), final_k - news_take)
                # 소셜도 부족하면 남은 슬롯을 뉴스로 보충
                if news_take + social_take < final_k:
                    news_take = min(len(news_pool), final_k - social_take)
                results = news_pool[:news_take] + social_pool[:social_take]
                results.sort(key=_sort_key)
            else:
                results = results[:final_k]
        else:
            results = results[:final_k]

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
                src = (
                    (r.metadata or {}).get("publisher")
                    or (r.metadata or {}).get("source_name")
                    or "unknown"
                )
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
                "analysis": f"'{query_text}'에 관련된 분석 결과를 찾을 수 없습니다. 먼저 분석을 실행해주세요.",
                "any": f"'{query_text}'에 대해 충분히 관련성 높은 정보를 찾을 수 없습니다. 다른 키워드로 검색해보세요.",
            }
            logger.warning(
                f"[RAG 검색] 품질 게이트 통과 결과 0건: query={query_text}, intent={source_intent}"
            )
            return {
                "answer": insufficient_msg.get(source_intent, insufficient_msg["any"]),
                "sources": [],
                "query": query_text,
                "model": final_model,
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
        social_count = sum(
            1 for r in results if _infer_type(r.id, r.metadata) == "social"
        )

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
            logger.error("[RAG 검색] CONTEXT가 비어있음. 검색 결과를 확인하세요.")
            return {
                "answer": f"'{query_text}'에 대한 관련 정보를 찾을 수 없습니다. 다른 키워드로 검색해보세요.",
                "sources": [],
                "query": query_text,
                "model": final_model,
            }

        # intent_instruction이 있으면 instructions에 합류
        final_instructions = instructions or ""
        if intent_instruction:
            final_instructions = (
                f"{final_instructions}\n{intent_instruction}".strip()
                if final_instructions
                else intent_instruction
            )

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
            answer = (
                llm_result.text
                if isinstance(llm_result, LLMResult)
                else str(llm_result)
            )
            logger.debug(
                f"[RAGService.query] 추출된 answer 길이: {len(answer) if answer else 0}"
            )
            logger.debug(
                f"[RAGService.query] 추출된 answer 내용 (처음 200자): {answer[:200] if answer else 'None'}"
            )

            # ✅ 답변이 중간에 잘린 경우 감지 및 처리
            if answer:
                # 마지막 문장이 완전하지 않은 경우 감지
                incomplete_endings = [
                    "하지만",
                    "그리고",
                    "또한",
                    "또",
                    "그런데",
                    "그러나",
                    "따라서",
                    "그래서",
                    "그러므로",
                    "뿐만",
                    "뿐만 아니라",
                ]
                answer_stripped = answer.strip()

                # 마지막 문장이 마침표/느낌표/물음표로 끝나지 않고, 접속사로 끝나는 경우
                if answer_stripped and not answer_stripped[-1] in [
                    ".",
                    "!",
                    "?",
                    "。",
                    "！",
                    "？",
                ]:
                    # 마지막 문장이 접속사로 끝나는지 확인
                    last_sentence = answer_stripped.split("\n")[-1].strip()
                    if any(
                        last_sentence.endswith(ending) for ending in incomplete_endings
                    ):
                        # 중간에 잘린 것으로 판단하여 마지막 불완전한 문장 제거
                        sentences = answer_stripped.split("\n")
                        # 완전한 문장만 남기기 (마침표로 끝나는 문장)
                        complete_sentences = []
                        for sent in sentences:
                            sent = sent.strip()
                            if sent and (
                                sent[-1] in [".", "!", "?", "。", "！", "？"]
                                or sent.startswith("•")
                                or sent.startswith("-")
                                or sent.startswith("*")
                            ):
                                complete_sentences.append(sent)
                            elif sent and not any(
                                sent.endswith(ending) for ending in incomplete_endings
                            ):
                                complete_sentences.append(sent)

                        if complete_sentences:
                            answer = "\n".join(complete_sentences)
                            logger.warning(
                                f"[RAGService.query] 답변이 중간에 잘린 것으로 감지되어 수정함 (원본 길이: {len(answer_stripped)}, 수정 후: {len(answer)})"
                            )
                        else:
                            # 완전한 문장이 없으면 마지막 문장을 제거하고 요약 bullet만 남기기
                            bullet_lines = [
                                line
                                for line in sentences
                                if line.strip().startswith(("•", "-", "*"))
                            ]
                            if bullet_lines:
                                answer = "\n".join(bullet_lines)
                                logger.warning(
                                    "[RAGService.query] 답변이 중간에 잘린 것으로 감지되어 요약 bullet만 남김"
                                )

            # 답변이 너무 짧으면 경고
            if answer and len(answer) < 50:
                logger.warning(
                    f"[RAGService.query] 답변이 너무 짧음 ({len(answer)}자). LLM 응답이 제대로 추출되지 않았을 수 있습니다."
                )
        except Exception as e:
            logger.error(
                f"[RAGService.query] LLM 호출 예외: {type(e).__name__}: {str(e)}",
                exc_info=True,
            )
            answer = f"LLM 호출 중 오류가 발생했습니다: {str(e)}"

        logger.info(f"[RAG 타이밍] LLM 답변 생성: {time.time() - _t_stage:.2f}s")
        logger.info(f"[RAG 타이밍] 전체 파이프라인: {time.time() - _t_pipeline:.2f}s")

        # "정보 없음" 답변이면 출처를 비워서 혼란 방지
        _no_info_signals = [
            "정보가 없습니다",
            "정보는 없습니다",
            "정보를 찾을 수 없",
            "정보가 부족",
            "정보가 포함되어 있지 않",
            "자료가 없습니다",
            "자료가 부족",
            "자료가 없어",
            "제공된 context에 없",
            "제공된 context에는 없",
            "context에 포함되어 있지 않",
            "context에는 포함되어 있지 않",
            "관련 정보가 없",
            "관련 자료가 없",
            "관련된 정보가 없",
            "비교할 수 있는 자료가 없",
            "비교가 불가능",
            "확인되지 않",
            "찾을 수 없습니다",
            "제공하기 어렵",
            "답변드리기 어렵",
            "요청하신 내용에 대한 관련",
        ]
        _answer_lower = answer.lower().replace(" ", "")
        if any(sig.replace(" ", "") in _answer_lower for sig in _no_info_signals):
            sources = []

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

        self.cache_service.cache_response(
            _cache_query, response, cache_context=cache_context
        )
        return response


# ✅ 프로세스 단위 싱글턴: 매 요청마다 모델/클라이언트를 재생성하지 않음
_rag_service_instance: Optional["RAGService"] = None


def get_rag_service() -> "RAGService":
    """RAGService를 프로세스 단위로 재사용하여 모델 재로딩 방지"""
    global _rag_service_instance
    if _rag_service_instance is None:
        _rag_service_instance = RAGService()
    return _rag_service_instance
