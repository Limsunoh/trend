"""
RAG 파이프라인 메인 로직: RAGService, get_rag_service()
"""

import logging
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from django.db.models import Max

from common.redis_services import RAGCacheService
from data_collector.models import NewsArticle, SocialMediaPost
from user_qa.models import QueryHistory

from .constants import (
    _META_EXPLANATIONS,
    _META_QUESTION_PATTERNS,
    _STOP_TOKENS,
    DISTANCE_SKIP_WORDS,
    FOLLOWUP_PATTERNS,
    FOLLOWUP_STOP_WORDS,
    GENERIC_QUERY_PATTERNS,
    GENERIC_STOP_WORDS,
    INCOMPLETE_ENDINGS,
    META_IDENTITY_PATTERNS,
    NO_INFO_SIGNALS,
    VAGUE_STOP_WORDS,
)
from .llm import LLMResult, OpenAIResponsesLLM
from .query_analysis import (
    _apply_negation,
    _detect_source_intent,
    _detect_time_scope,
    _extract_key_entities,
    _extract_keywords_from_analysis,
    _extract_topic_from_query,
    _fetch_analysis_context,
    _get_trending_keywords_by_topic,
    _has_community_intent,
    _has_news_intent,
)
from .search import (
    _build_context_and_sources,
    _expand_query_for_search,
    _keyword_overlap_count,
    _recency_score,
    _search_reddit_by_title,
    rank_results_generic,
)
from .vector_db import SearchResult, VectorDBService, _get_setting, _infer_type

logger = logging.getLogger(__name__)


class RAGService:
    """RAG 질의응답 서비스 (캐싱 통합 + OpenAI LLM 연동)"""

    def __init__(self):
        self.vector_db = VectorDBService()
        self.cache_service = RAGCacheService()
        self.llm = OpenAIResponsesLLM()

    def _should_skip_intent_llm(self, query_text: str) -> bool:
        """LLM 의도분석을 돌리면 오히려 망가질 가능성이 큰 케이스를 룰로 스킵."""
        q = (query_text or "").strip()
        if not q:
            return True

        if len(q) <= 7:
            has_strong_signal = bool(
                re.search(r"[A-Z]{2,}|[0-9]|[#@]|\".+?\"|'.+?'", q)
            )
            has_korean_chunk = bool(re.search(r"[가-힣]{2,6}", q))
            if not (has_strong_signal or has_korean_chunk):
                return True

        if any(re.search(p, q) for p in GENERIC_QUERY_PATTERNS):
            tokens = re.findall(r"[가-힣]+|[A-Za-z]+|[0-9]+", q)
            meaningful = [t for t in tokens if t not in GENERIC_STOP_WORDS]
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

        query_text = (query_text or "").strip()
        if not query_text:
            logger.debug("[RAGService.query] 빈 쿼리")
            return {"answer": "질문(query)이 비어있습니다.", "sources": [], "query": ""}

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

        latest_news = NewsArticle.objects.aggregate(Max("collected_at"))[
            "collected_at__max"
        ]
        latest_social = SocialMediaPost.objects.aggregate(Max("collected_at"))[
            "collected_at__max"
        ]

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

        _cache_query = re.sub(r"\s+", " ", query_text).strip().rstrip("?？！!.")
        if not force_refresh:
            cached_response = self.cache_service.get_cached_response(
                _cache_query, cache_context=cache_context
            )
            if cached_response:
                return cached_response

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
            if not self._should_skip_intent_llm(query_text):
                intent_info = self.llm.classify_intent(
                    query_text=query_text, model=final_model
                )

        source_intent = _detect_source_intent(query_text)
        q_lower_for_meta = (query_text or "").lower()
        is_meta_question = any(
            p in q_lower_for_meta for p in _META_QUESTION_PATTERNS
        ) and source_intent not in ("analysis", "analysis+search")

        if is_meta_question:
            meta_parts = []
            for key, explanation in _META_EXPLANATIONS.items():
                if key in q_lower_for_meta:
                    meta_parts.append(explanation)
            if not meta_parts:
                meta_parts.append(_META_EXPLANATIONS["트렌드"])

            meta_context = "[시스템 설명]\n" + "\n\n".join(meta_parts)
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
            except Exception:
                history_id = None

            return {
                "answer": answer,
                "sources": [{"type": "analysis", "title": "시스템 설명"}],
                "query": query_text,
                "history_id": history_id,
                "model": final_model,
            }

        if source_intent == "analysis":
            analysis_context, analysis_sources = _fetch_analysis_context(query_text)

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
                except Exception:
                    history_id = None

                return {
                    "answer": answer,
                    "sources": analysis_sources,
                    "query": query_text,
                    "history_id": history_id,
                    "model": final_model,
                }
            else:
                source_intent = "any"

        if source_intent == "analysis+search":
            analysis_context, analysis_sources = _fetch_analysis_context(query_text)
            analysis_keywords = _extract_keywords_from_analysis(query_text)

            if analysis_keywords:
                search_query_for_compound = " ".join(analysis_keywords[:5])
                retrieval_k = max(int(top_k) * 6, int(top_k) + 20)
                compound_candidates = self.vector_db.similarity_search(
                    search_query_for_compound,
                    top_k=retrieval_k,
                    distance_threshold=0.75,
                    fetch_multiplier=3,
                    balance_types=False,
                )

                kw_candidates = self.vector_db.keyword_search(
                    query_text=search_query_for_compound,
                    keywords=analysis_keywords[:5],
                    top_k=retrieval_k,
                )

                seen = set()
                merged = []
                for r in kw_candidates + compound_candidates:
                    if r.id not in seen:
                        seen.add(r.id)
                        merged.append(r)

                want_news = _has_news_intent(query_text or "")
                want_community = _has_community_intent(query_text or "")
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

                merged = merged[: int(top_k)]

                if merged:
                    search_context, search_sources = _build_context_and_sources(
                        merged,
                        max_doc_chars=700,
                        evidence_quality="adequate",
                        source_intent="any",
                    )

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
                    except Exception:
                        history_id = None

                    return {
                        "answer": answer,
                        "sources": combined_sources,
                        "query": query_text,
                        "history_id": history_id,
                        "model": final_model,
                    }

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
                except Exception:
                    history_id = None

                return {
                    "answer": answer,
                    "sources": analysis_sources,
                    "query": query_text,
                    "history_id": history_id,
                    "model": final_model,
                }

            source_intent = "any"

        _trend_fallback_intent = "any"
        if source_intent.startswith("trend_enhanced"):
            if ":" in source_intent:
                _trend_fallback_intent = source_intent.split(":")[1]

            topic_words = _extract_topic_from_query(query_text)
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

            if trending_keywords:
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

                search_keywords = list(trending_keywords[:5])
                for tw in topic_words:
                    if tw not in search_keywords:
                        search_keywords.insert(0, tw)
                trend_kw_candidates = self.vector_db.keyword_search(
                    query_text=trend_search_query,
                    keywords=search_keywords[:7],
                    top_k=retrieval_k,
                )

                seen = set()
                merged = []
                for r in trend_kw_candidates + trend_candidates:
                    if r.id not in seen:
                        seen.add(r.id)
                        merged.append(r)

                want_news = _trend_fallback_intent == "news"
                want_community = _trend_fallback_intent == "community"
                if not want_news and not want_community:
                    want_news = _has_news_intent(query_text or "")
                    want_community = _has_community_intent(query_text or "")
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

                merged = rank_results_generic(
                    query_text=query_text,
                    results=merged,
                    final_k=int(top_k) * 2,
                    min_keyword_hits=1,
                )

                _t_range_start, _t_range_end, _t_scope = _detect_time_scope(
                    query_text,
                    intent_time_focus=intent_info.get("time_focus", ""),
                )
                if _t_range_start is not None:
                    _trend_recent = []
                    for r in merged:
                        pa = (r.metadata or {}).get("published_at", "")
                        if pa:
                            try:
                                doc_dt = datetime.fromisoformat(
                                    pa.replace("Z", "+00:00")
                                )
                                if doc_dt.tzinfo is None:
                                    doc_dt = doc_dt.replace(tzinfo=timezone.utc)
                                if doc_dt >= _t_range_start:
                                    if _t_range_end is None or doc_dt < _t_range_end:
                                        _trend_recent.append(r)
                            except (ValueError, TypeError):
                                pass
                    if _trend_recent:
                        merged = _trend_recent
                    else:
                        merged.sort(
                            key=lambda r: (r.metadata or {}).get("published_at", ""),
                            reverse=True,
                        )

                hard_dist = float(_get_setting("RAG_HARD_DISTANCE_THRESHOLD", 1.05))
                gated = [r for r in merged if r.distance <= hard_dist]
                if gated:
                    merged = gated

                final_k = int(top_k)
                if not want_news and not want_community and len(merged) > final_k:
                    news_pool = [
                        r for r in merged if _infer_type(r.id, r.metadata) == "news"
                    ]
                    social_pool = [
                        r for r in merged if _infer_type(r.id, r.metadata) == "social"
                    ]

                    if news_pool and social_pool:
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
                    except Exception:
                        history_id = None

                    return {
                        "answer": answer,
                        "sources": combined_sources,
                        "query": query_text,
                        "history_id": history_id,
                        "model": final_model,
                    }

            source_intent = _trend_fallback_intent

        pre_entities = _extract_key_entities(query_text)
        query_tokens = query_text.split()
        skip_reformulate = (len(pre_entities) >= 2) or (
            len(pre_entities) >= 1 and len(query_tokens) <= 4
        )

        if skip_reformulate:
            reformulated_query = query_text
        else:
            reformulated_query = self.llm.reformulate_query(
                query_text, model=final_model
            )

        entities_from_original = _extract_key_entities(query_text)
        entities_from_reformulated = _extract_key_entities(reformulated_query)
        key_entities = list(set(entities_from_original + entities_from_reformulated))
        if intent_info.get("topic_entity"):
            topic = intent_info["topic_entity"].strip()
            if topic and topic not in _STOP_TOKENS and topic not in key_entities:
                key_entities.append(topic)

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

        semantic_candidates = []
        seen_semantic_ids: set = set()
        batch_results = self.vector_db.batch_similarity_search(
            expanded_queries,
            top_k=retrieval_k,
            distance_threshold=candidate_distance_threshold,
            fetch_multiplier=3,
        )
        for eq_results in batch_results:
            for r in eq_results:
                if r.id not in seen_semantic_ids:
                    seen_semantic_ids.add(r.id)
                    semantic_candidates.append(r)

        keyword_candidates: List[SearchResult] = []
        if key_entities:
            keyword_candidates = self.vector_db.keyword_search(
                query_text=reformulated_query,
                keywords=key_entities,
                top_k=retrieval_k,
            )

        seen_ids: set = set()
        candidates: List[SearchResult] = []

        for r in keyword_candidates:
            if r.id not in seen_ids:
                seen_ids.add(r.id)
                candidates.append(r)

        for r in semantic_candidates:
            if r.id not in seen_ids:
                seen_ids.add(r.id)
                candidates.append(r)

        reddit_db_results = _search_reddit_by_title(
            query_text=query_text,
            key_entities=key_entities,
            limit=5,
        )
        for r in reddit_db_results:
            if r.id not in seen_ids:
                seen_ids.add(r.id)
                candidates.append(r)

        if not candidates:
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

        # (A-0) 시스템 메타 질문 감지
        if any(p in _q_lower for p in META_IDENTITY_PATTERNS):
            return {
                "answer": (
                    "저는 뉴스와 커뮤니티 트렌드 데이터를 기반으로 답변하는 Q&A 어시스턴트입니다.\n\n"
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

        # (A) 대화형 후속 질문 감지
        _is_followup = any(p in _q_lower for p in FOLLOWUP_PATTERNS)
        if _is_followup:
            _fu_tokens = re.findall(r"[가-힣]{2,}", query_text)
            _fu_meaningful = [
                t
                for t in _fu_tokens
                if not any(s in t or t in s for s in FOLLOWUP_STOP_WORDS)
            ]
            if not _fu_meaningful:
                return {
                    "answer": (
                        "이전 대화 맥락을 참조할 수 없어 답변이 어렵습니다. "
                        "궁금한 주제나 키워드를 포함해서 다시 질문해 주세요.\n"
                        '예: "삼성전자 관련 뉴스 출처 알려줘", "AI 트렌드 자세히 알려줘"'
                    ),
                    "sources": [],
                    "query": query_text,
                    "model": final_model,
                }

        # (B) 극도로 모호한 질문
        _vague_tokens = re.findall(r"[가-힣]{2,}", query_text)
        _vague_meaningful = [t for t in _vague_tokens if t not in VAGUE_STOP_WORDS]
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
            recent_candidates = []
            for r in candidates:
                pa = (r.metadata or {}).get("published_at", "")
                if not pa:
                    continue
                try:
                    doc_dt = datetime.fromisoformat(pa.replace("Z", "+00:00"))
                    if doc_dt.tzinfo is None:
                        doc_dt = doc_dt.replace(tzinfo=timezone.utc)
                    if doc_dt >= range_start_dt:
                        if range_end_dt is None or doc_dt < range_end_dt:
                            recent_candidates.append(r)
                except (ValueError, TypeError):
                    pass

            if len(recent_candidates) >= max(int(top_k), 3):
                candidates = recent_candidates
            elif recent_candidates:
                candidates = recent_candidates
            else:
                candidates.sort(
                    key=lambda r: (r.metadata or {}).get("published_at", ""),
                    reverse=True,
                )

        # ========================================
        # STEP A: 의도 기반 소스 타입 사전 필터링
        # ========================================
        if source_intent == "news":
            typed = [r for r in candidates if _infer_type(r.id, r.metadata) == "news"]
            if typed:
                candidates = typed
        elif source_intent == "community":
            typed = [r for r in candidates if _infer_type(r.id, r.metadata) == "social"]
            if typed:
                candidates = typed

        min_hits = 2
        if intent_info.get("topic_entity"):
            min_hits = 1

        results = rank_results_generic(
            query_text=query_text,
            results=candidates,
            final_k=int(top_k) * 2,
            min_keyword_hits=min_hits,
        )

        _filtered_entities = [e for e in key_entities if e not in DISTANCE_SKIP_WORDS]
        if _filtered_entities:
            for r in results:
                meta = r.metadata or {}
                combined = f"{meta.get('title', '')}\n{meta.get('excerpt', '')}\n{r.document or ''}"
                combined_lower = combined.lower()
                match_count = sum(
                    1 for ent in _filtered_entities if ent.lower() in combined_lower
                )
                if match_count > 0 and r.distance > 0.40:
                    if r.distance > 0.80:
                        continue
                    reduction = min(match_count * 0.05, 0.10)
                    if r.distance > 0.60:
                        reduction *= 0.5
                    r.distance = max(r.distance - reduction, 0.30)

        hard_distance = float(_get_setting("RAG_HARD_DISTANCE_THRESHOLD", 1.05))
        force_low_quality = False
        gated = [r for r in results if r.distance <= hard_distance]
        if len(gated) >= max(int(top_k) // 2, 1):
            results = gated
        elif gated:
            soft_gated = [
                r
                for r in results
                if r.distance <= hard_distance * 1.3 and r not in gated
            ]
            results = gated + soft_gated
        else:
            results.sort(key=lambda r: r.distance)
            results = results[: int(top_k)]
            force_low_quality = True

        final_distance_cutoff = float(_get_setting("RAG_DISTANCE_THRESHOLD", 0.15))
        has_entities = bool(key_entities)
        recency_weight = 5.0 if time_scope_days > 0 else 1.0

        def _sort_key(r):
            meta = r.metadata or {}
            combined = f"{meta.get('title', '')}\n{meta.get('excerpt', '')}\n{r.document or ''}"
            overlap = _keyword_overlap_count(query_text, combined)

            entity_bonus = 0
            if has_entities:
                combined_lower = combined.lower()
                entity_bonus = (
                    sum(1 for ent in key_entities if ent.lower() in combined_lower) * 10
                )

            within_soft = 1 if r.distance <= final_distance_cutoff else 0
            recency = (
                _recency_score(meta.get("published_at", ""), _now_ts) * recency_weight
            )
            news_boost = 0.01 if _infer_type(r.id, r.metadata) == "news" else 0

            score = entity_bonus + overlap + within_soft + recency + news_boost
            return (-score, r.distance)

        results.sort(key=_sort_key)

        final_k = int(top_k)
        if source_intent == "any" and len(results) > final_k:
            news_pool = [r for r in results if _infer_type(r.id, r.metadata) == "news"]
            social_pool = [
                r for r in results if _infer_type(r.id, r.metadata) == "social"
            ]

            if news_pool and social_pool:
                news_target = max(2, int(final_k * 0.7))
                news_take = min(len(news_pool), news_target)
                social_take = min(len(social_pool), final_k - news_take)
                if news_take + social_take < final_k:
                    news_take = min(len(news_pool), final_k - social_take)
                results = news_pool[:news_take] + social_pool[:social_take]
                results.sort(key=_sort_key)
            else:
                results = results[:final_k]
        else:
            results = results[:final_k]

        if len(results) > 2:
            _src_counts = defaultdict(int)
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
            while len(_diversified) < int(top_k) and _overflow:
                _diversified.append(_overflow.pop(0))
            results = _diversified

        if not results:
            insufficient_msg = {
                "news": f"'{query_text}'에 관련된 뉴스 기사를 찾을 수 없습니다. 다른 키워드로 검색해보세요.",
                "community": f"'{query_text}'에 관련된 커뮤니티 게시글을 찾을 수 없습니다. 다른 키워드로 검색해보세요.",
                "analysis": f"'{query_text}'에 관련된 분석 결과를 찾을 수 없습니다. 먼저 분석을 실행해주세요.",
                "any": f"'{query_text}'에 대해 충분히 관련성 높은 정보를 찾을 수 없습니다. 다른 키워드로 검색해보세요.",
            }
            return {
                "answer": insufficient_msg.get(source_intent, insufficient_msg["any"]),
                "sources": [],
                "query": query_text,
                "model": final_model,
            }

        distances = [r.distance for r in results]
        avg_distance = sum(distances) / len(distances)
        weak_threshold = float(_get_setting("RAG_WEAK_RELEVANCE_THRESHOLD", 0.65))

        if force_low_quality:
            evidence_quality = "low"
        else:
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

        intent_instruction = ""
        main_intent = intent_info.get("main_intent", "")
        if main_intent == "list":
            intent_instruction = "답변을 항목별로 정리하여 제시하세요."
        elif main_intent == "analysis":
            intent_instruction = "원인, 배경, 의미를 구조적으로 분석하여 설명하세요."
        elif main_intent == "comparison":
            intent_instruction = "비교 대상의 차이점과 공통점을 중심으로 설명하세요."

        if not context or not context.strip():
            return {
                "answer": f"'{query_text}'에 대한 관련 정보를 찾을 수 없습니다. 다른 키워드로 검색해보세요.",
                "sources": [],
                "query": query_text,
                "model": final_model,
            }

        final_instructions = instructions or ""
        if intent_instruction:
            final_instructions = (
                f"{final_instructions}\n{intent_instruction}".strip()
                if final_instructions
                else intent_instruction
            )

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
            answer = (
                llm_result.text
                if isinstance(llm_result, LLMResult)
                else str(llm_result)
            )

            if answer:
                answer_stripped = answer.strip()
                if answer_stripped and not answer_stripped[-1] in [
                    ".",
                    "!",
                    "?",
                    "。",
                    "！",
                    "？",
                ]:
                    last_sentence = answer_stripped.split("\n")[-1].strip()
                    if any(
                        last_sentence.endswith(ending) for ending in INCOMPLETE_ENDINGS
                    ):
                        sentences = answer_stripped.split("\n")
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
                                sent.endswith(ending) for ending in INCOMPLETE_ENDINGS
                            ):
                                complete_sentences.append(sent)

                        if complete_sentences:
                            answer = "\n".join(complete_sentences)
                        else:
                            bullet_lines = [
                                line
                                for line in sentences
                                if line.strip().startswith(("•", "-", "*"))
                            ]
                            if bullet_lines:
                                answer = "\n".join(bullet_lines)
        except Exception as e:
            answer = f"LLM 호출 중 오류가 발생했습니다: {str(e)}"

        _answer_lower = answer.lower().replace(" ", "")
        if any(sig.replace(" ", "") in _answer_lower for sig in NO_INFO_SIGNALS):
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


_rag_service_instance: Optional["RAGService"] = None


def get_rag_service() -> "RAGService":
    """RAGService를 프로세스 단위로 재사용하여 모델 재로딩 방지"""
    global _rag_service_instance
    if _rag_service_instance is None:
        _rag_service_instance = RAGService()
    return _rag_service_instance
