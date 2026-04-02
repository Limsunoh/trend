"""
쿼리 분석, 의도 감지, 엔티티 추출, 분석 타입 함수 모음

사용자의 자연어 쿼리를 파싱하고, 정규식과 사전(Dictionary)을 기반으로
의도(Intent) 및 핵심 엔티티를 파악하는 로직을 담당합니다.
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from .constants import (
    _ANALYSIS_DIRECT_PHRASES,
    _ANALYSIS_TYPE_KEYWORDS,
    _KEYWORD_QUALIFIER_TO_TYPE,
    _KO_PARTICLE_RE,
    _STOP_TOKENS,
    _VERB_SUFFIXES,
    COMMON_WORDS,
    COMMUNITY_INDICATORS,
    INTENSITY_PREFIXES,
    KEYWORD_QUALIFIERS,
    NEWS_INDICATORS,
    POPULARITY_WORDS,
    TOPIC_NOISE_WORDS,
    TOPIC_VERB_SUFFIXES,
    TREND_SIGNAL_WORDS,
    TRENDING_STOPWORDS,
)

logger = logging.getLogger(__name__)


def _strip_ko_particles(token: str) -> str:
    """한국어 토큰에서 조사를 제거하여 어근을 추출 (간단 버전)."""
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
        # 5글자 이상 한글 토큰: 동사/어미 접미사 제거
        if len(stripped) >= 5 and re.match(r"^[가-힣]+$", stripped):
            for suffix in _VERB_SUFFIXES:
                if stripped.endswith(suffix) and len(stripped) > len(suffix):
                    candidate = stripped[: -len(suffix)]
                    if len(candidate) >= 2:
                        stripped = candidate
                    break
        toks.add(stripped)
    return toks - _STOP_TOKENS


def _extract_key_entities(query_text: str) -> List[str]:
    """
    쿼리에서 핵심 엔티티(인명, 기관명, 고유명사 등)를 추출.
    하이브리드 검색의 키워드 필터링에 사용.

    Returns:
        추출된 엔티티 리스트 (최대 3개)
    """
    query = (query_text or "").strip()
    if not query:
        return []

    entities: List[str] = []
    tokens = query.split()

    for token in tokens:
        # 영문 고유명사 매칭
        eng_match = re.match(r"^([A-Z][a-zA-Z]*|[A-Z]{2,})\b", token)
        if eng_match:
            word = eng_match.group(1)
            if len(word) >= 2 and word not in entities:
                entities.append(word)
            continue

        if not re.search(r"[가-힣]", token):
            continue

        stripped = _strip_ko_particles(token)

        # 상수로 분리된 불용어 및 COMMON_WORDS 사용
        if stripped in _STOP_TOKENS or stripped in COMMON_WORDS:
            continue

        if re.match(r"^[가-힣]{2,4}$", stripped) and stripped not in entities:
            entities.append(stripped)
            continue

        # 5글자 이상 동사/어미 정리
        if len(stripped) >= 5 and re.match(r"^[가-힣]+$", stripped):
            for suffix in _VERB_SUFFIXES:
                if stripped.endswith(suffix) and len(stripped) > len(suffix):
                    candidate = stripped[: -len(suffix)]
                    if (
                        2 <= len(candidate) <= 4
                        and candidate not in _STOP_TOKENS
                        and candidate not in COMMON_WORDS
                        and candidate not in entities
                    ):
                        entities.append(candidate)
                    break

    compound_pattern = re.compile(
        r"([가-힣]{3,}(?:전자|자동차|그룹|증권|은행|보험|제약|바이오|엔터|미디어|당|의힘|연합|연대|회의|위원회|청와대|국회|정부))"
    )
    for match in compound_pattern.finditer(query):
        word = match.group(1)
        if word not in entities:
            entities.append(word)

    return entities[:3]


def _has_news_intent(q: str) -> bool:
    """쿼리에 뉴스 출처 의도가 있는지 판별 (대소문자 무시)."""
    q_l = q.lower()
    return any(kw in q_l for kw in NEWS_INDICATORS)


def _has_community_intent(q: str) -> bool:
    """쿼리에 커뮤니티 출처 의도가 있는지 판별 (대소문자 무시)."""
    q_l = q.lower()
    return any(kw in q_l for kw in COMMUNITY_INDICATORS)


def _apply_negation(q: str) -> Tuple[Optional[bool], Optional[bool]]:
    """
    부정/배제 패턴을 감지하여 뉴스/커뮤니티 의도를 override.
    "뉴스 없이" → 뉴스 OFF, "SNS만" → 커뮤니티 ON + 뉴스 OFF

    Returns:
        (news_override, community_override) 튜플 반환.
        True=강제 ON, False=강제 OFF, None=기본 감지 유지
    """
    q_l = q.lower()
    news_ovr = None
    comm_ovr = None

    for src_words, target in [
        (["뉴스", "기사"], "news"),
        (["sns", "커뮤니티", "소셜"], "community"),
    ]:
        for sw in src_words:
            if re.search(
                rf"{sw}\s*(?:는\s*)?(?:없이|없는|빼고|빼줘|제외|말고|안\s)", q_l
            ):
                if target == "news":
                    news_ovr = False
                else:
                    comm_ovr = False

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
    사용자가 뉴스/커뮤니티/분석결과 중 어떤 출처를 원하는지 키워드 기반 판별.
    LLM 호출 없이 순수 키워드 매칭 + 조합 매칭 + 부정 표현 처리.

    Returns:
        "news", "community", "analysis", "analysis+search",
        "trend_enhanced", "trend_enhanced:news", "trend_enhanced:community", or "any"
    """
    q = (query_text or "").strip().lower()

    has_keyword_word = "키워드" in q
    has_qualifier = any(qual in q for qual in KEYWORD_QUALIFIERS)
    has_analysis = (
        any(phrase in q for phrase in _ANALYSIS_DIRECT_PHRASES)
        or (has_keyword_word and has_qualifier)
        or (has_keyword_word and any(w in q for w in POPULARITY_WORDS))
    )

    if not has_analysis and "플랫폼" in q:
        if any(w in q for w in ["비교", "분석", "차이"]):
            has_analysis = True

    has_intensity = any(p in q for p in INTENSITY_PREFIXES)
    has_popularity = any(w in q for w in POPULARITY_WORDS)
    has_ranking = has_intensity and has_popularity

    has_news = _has_news_intent(q)
    has_community = _has_community_intent(q)

    news_ovr, comm_ovr = _apply_negation(q)
    if news_ovr is not None:
        has_news = news_ovr
    if comm_ovr is not None:
        has_community = comm_ovr

    # 한쪽만 명시적 OFF이고 다른 쪽 언급 없으면 → 반대 출처 ON 추론
    if news_ovr is False and comm_ovr is None and not has_community:
        has_community = True
    if comm_ovr is False and news_ovr is None and not has_news:
        has_news = True

    if has_analysis and (has_news or has_community):
        return "analysis+search"
    if has_analysis:
        return "analysis"

    # 트렌드 보강 검색
    if has_ranking or has_popularity:
        if has_news and not has_community:
            return "trend_enhanced:news"
        elif has_community and not has_news:
            return "trend_enhanced:community"
        return "trend_enhanced"

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


def _detect_analysis_types(query_text: str) -> List[str]:
    """쿼리에서 관련된 analysis_type 목록을 추출한다."""
    q = (query_text or "").strip().lower()
    matched = []

    for atype, keywords in _ANALYSIS_TYPE_KEYWORDS.items():
        if any(kw in q for kw in keywords):
            matched.append(atype)

    if not matched and "키워드" in q:
        for atype, qualifiers in _KEYWORD_QUALIFIER_TO_TYPE.items():
            if any(qual in q for qual in qualifiers):
                matched.append(atype)
                break
        if not matched:
            matched.append("hot_keywords")

    return matched


def _fetch_analysis_context(
    query_text: str, max_results: int = 3
) -> Tuple[str, List[Dict[str, Any]]]:
    """TrendAnalysisResult에서 관련 분석 결과를 조회하여 LLM context 문자열로 변환."""
    # 앱 초기화 순환 참조 방지를 위해 함수 내 import 유지
    from analyzer.models import TrendAnalysisResult

    matched_types = _detect_analysis_types(query_text)

    if matched_types:
        qs = TrendAnalysisResult.objects.filter(
            analysis_type__in=matched_types,
            status="success",
        ).order_by("-created_at")[:max_results]
    else:
        qs = TrendAnalysisResult.objects.filter(status="success").order_by(
            "-created_at"
        )[:max_results]

    if not qs.exists():
        return "", []

    blocks = []
    sources = []

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

    keyword_keys = [
        "top_keywords",
        "news_surge_keywords",
        "sns_surge_keywords",
        "engagement_keywords",
        "viral_keywords",
        "synchronized_keywords",
        "common_keywords",
    ]

    for result in qs:
        label = type_labels.get(result.analysis_type, result.analysis_type)
        summary_data = result.summary or {}
        result_data = result.result_data or {}

        time_str = result.created_at.strftime("%Y-%m-%d %H:%M")
        context_parts = [
            f"[분석결과] {label} | 기간: {result.days or '?'}일 | 날짜: {time_str}"
        ]

        for key in keyword_keys:
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
    """분석 결과(TrendAnalysisResult)에서 상위 키워드를 추출하여 검색 쿼리에 병합."""
    from analyzer.models import TrendAnalysisResult

    matched_types = _detect_analysis_types(query_text)

    if matched_types:
        qs = TrendAnalysisResult.objects.filter(
            analysis_type__in=matched_types,
            status="success",
        ).order_by("-created_at")[:3]
    else:
        qs = TrendAnalysisResult.objects.filter(status="success").order_by(
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
    """쿼리에서 순위/인기도 수식어와 불용어를 제거한 뒤 주제 키워드만 추출."""
    q = (query_text or "").strip()
    if not q:
        return []

    tokens = q.split()
    topics = []

    for token in tokens:
        cleaned = _strip_ko_particles(token)

        # 상수로 분리된 TOPIC_VERB_SUFFIXES 사용
        for suf in TOPIC_VERB_SUFFIXES:
            if cleaned.endswith(suf) and len(cleaned) > len(suf) + 1:
                cleaned = cleaned[: -len(suf)]
                break

        # 상수로 분리된 TOPIC_NOISE_WORDS 사용
        if cleaned.lower() in TOPIC_NOISE_WORDS or len(cleaned) < 2:
            continue

        if re.match(r"^[a-zA-Z]+$", cleaned) and len(cleaned) >= 2:
            topics.append(cleaned)
            continue

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
    topic_words가 빈 리스트면 전체 상위 키워드를 반환합니다.
    """
    from analyzer.models import TrendAnalysisResult

    priority_types = ["hot_keywords", "keywords", "surge_keywords", "compare_platforms"]
    qs = TrendAnalysisResult.objects.filter(
        status="success",
        analysis_type__in=priority_types,
    ).order_by("-created_at")[:5]

    if not qs.exists():
        qs = TrendAnalysisResult.objects.filter(status="success").order_by(
            "-created_at"
        )[:5]

    _news_keys = ["top_keywords", "news_hot_keywords", "news_surge_keywords"]
    _sns_keys = [
        "top_keywords",
        "sns_hot_keywords",
        "sns_surge_keywords",
        "engagement_keywords",
        "viral_keywords",
    ]
    _common_keys = ["hot_keywords", "common_keywords", "synchronized_keywords"]

    def _extract_freq_from_item(item: dict) -> float:
        for k in [
            "frequency",
            "current_frequency",
            "growth_ratio",
            "correlation",
            "avg_engagement_score",
        ]:
            val = item.get(k)
            if val:
                try:
                    return float(val)
                except (ValueError, TypeError):
                    pass
        nf = item.get("news_frequency", 0) or 0
        sf = item.get("sns_frequency", 0) or 0
        if nf or sf:
            try:
                return float(nf) + float(sf)
            except (ValueError, TypeError):
                pass
        return 0.0

    def _collect_from_list(items, analysis_type, out):
        if not items or not isinstance(items, list):
            return
        for item in items:
            if isinstance(item, dict):
                kw = (item.get("keyword") or "").strip()
                if kw:
                    out.append((kw, _extract_freq_from_item(item), analysis_type))

    def _is_valid_trending_kw(kw: str) -> bool:
        # 상수로 분리된 TRENDING_STOPWORDS 사용
        return kw not in TRENDING_STOPWORDS and len(kw) >= 2

    primary_items = []
    secondary_items = []
    common_items = []

    for result in qs:
        result_data = result.result_data or {}
        search_layers = [result_data]
        nested_result = result_data.get("result", {})
        if isinstance(nested_result, dict):
            search_layers.append(nested_result)

        for layer in search_layers:
            for key in _news_keys:
                items_list = layer.get(key, [])
                if items_list and isinstance(items_list, list):
                    target = primary_items if platform == "news" else secondary_items
                    _collect_from_list(items_list, result.analysis_type, target)

            for key in _sns_keys:
                if key == "top_keywords":
                    continue
                items_list = layer.get(key, [])
                if items_list and isinstance(items_list, list):
                    target = (
                        primary_items if platform == "community" else secondary_items
                    )
                    _collect_from_list(items_list, result.analysis_type, target)

            for key in _common_keys:
                items_list = layer.get(key, [])
                if items_list and isinstance(items_list, list):
                    _collect_from_list(items_list, result.analysis_type, common_items)

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
                    else:
                        target = (
                            secondary_items if platform == "news" else primary_items
                        )
                        _collect_from_list(sub_items, result.analysis_type, target)

    if platform in ("news", "community") and primary_items:
        all_kw_items = primary_items + common_items
        if len(set(kw for kw, _, _ in all_kw_items)) < max_keywords:
            all_kw_items.extend(secondary_items)
    else:
        all_kw_items = primary_items + common_items + secondary_items

    if not all_kw_items:
        return [], ""

    all_kw_items = [
        (kw, freq, at) for kw, freq, at in all_kw_items if _is_valid_trending_kw(kw)
    ]

    if not all_kw_items:
        return [], ""

    topic_matched = False
    if topic_words:
        topic_lower = []
        for t in topic_words:
            t_low = t.lower()
            topic_lower.append(t_low)
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

    kw_best: Dict[str, Tuple[float, str]] = {}
    for kw, freq, atype in all_kw_items:
        try:
            freq_val = float(freq) if freq else 0.0
        except (ValueError, TypeError):
            freq_val = 0.0

        if kw not in kw_best or freq_val > kw_best[kw][0]:
            kw_best[kw] = (freq_val, atype)

    unique_items = [(kw, fv, at) for kw, (fv, at) in kw_best.items()]
    unique_items.sort(key=lambda x: x[1], reverse=True)
    top_items = unique_items[:max_keywords]

    keywords = [item[0] for item in top_items]

    if topic_words and not topic_matched:
        keywords = topic_words + keywords[: max_keywords - len(topic_words)]

    if topic_matched:
        summary_lines = [
            f"[분석결과] '{', '.join(topic_words)}' 관련 트렌드 키워드 (중요도순):"
        ]
    else:
        summary_lines = ["[분석결과] 트렌드 상위 키워드 (중요도순):"]

    for kw, freq, atype in top_items:
        if freq >= 1.0:
            freq_str = f"{freq:.1f}x"
        elif freq > 0:
            freq_str = f"{freq * 100:.2f}%"
        else:
            freq_str = "-"
        summary_lines.append(f"  - {kw} ({freq_str})")

    summary_text = "\n".join(summary_lines)
    return keywords, summary_text


def _detect_time_scope(
    query_text: str, intent_time_focus: str = ""
) -> Tuple[Optional[datetime], Optional[datetime], int]:
    """
    쿼리의 시간 범위를 감지하여 (시작시간, 종료시간, 기간_일수) 튜플로 반환.
    정규식을 통해 날짜를 파싱하거나 '이번주', '최근' 등의 키워드를 분석합니다.
    """
    KST = timezone(timedelta(hours=9))
    now_kst = datetime.now(KST)
    today_midnight = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)

    q = (query_text or "").strip().lower()

    date_match = re.search(r"(\d{1,2})\s*[월/\.]\s*(\d{1,2})\s*일?", q)
    if date_match:
        month = int(date_match.group(1))
        day = int(date_match.group(2))
        year = now_kst.year
        try:
            target = today_midnight.replace(month=month, day=day)
            if target > now_kst:
                target = target.replace(year=year - 1)
            return (target, target + timedelta(days=1), 1)
        except ValueError:
            pass

    if any(kw in q for kw in ["오늘", "today", "방금", "지금"]):
        return (today_midnight, None, 1)

    if any(kw in q for kw in ["어제", "yesterday"]):
        return (today_midnight - timedelta(days=1), today_midnight, 2)

    if any(kw in q for kw in ["이번주", "이번 주", "금주"]):
        weekday = today_midnight.weekday()
        this_week_start = today_midnight - timedelta(days=weekday)
        return (this_week_start, None, 7)

    if any(kw in q for kw in ["지난주", "저번주", "저번 주", "지난 주"]):
        weekday = today_midnight.weekday()
        this_week_start = today_midnight - timedelta(days=weekday)
        last_week_start = this_week_start - timedelta(days=7)
        return (last_week_start, this_week_start, 14)

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

    if intent_time_focus == "recent":
        return (today_midnight - timedelta(days=14), None, 14)
    if intent_time_focus == "current":
        return (today_midnight - timedelta(days=30), None, 30)

    return (None, None, 0)
