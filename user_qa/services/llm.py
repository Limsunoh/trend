"""
OpenAI API 호출 관련: LLMResult, OpenAIResponsesLLM
"""

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from django.conf import settings

try:
    import httpx
    from openai import OpenAI
except ImportError:
    httpx = None
    OpenAI = None

logger = logging.getLogger(__name__)


@dataclass
class LLMResult:
    text: str
    raw: Any = None


class OpenAIResponsesLLM:
    """
    OpenAI Responses API 기반 LLM 래퍼 (안정성/호환성 강화)
    - SDK 응답 구조가 dict/object 어느 쪽이든 텍스트 추출
    - 모델이 지원하지 않는 파라미터로 400 나면 자동 제거 후 1회 재시도
    """

    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY") or getattr(
            settings, "OPENAI_API_KEY", None
        )
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY가 설정되어 있지 않습니다. (.env 확인)")

        if OpenAI is None or httpx is None:
            raise RuntimeError(
                "OpenAI 라이브러리가 설치되지 않았습니다.\n"
                "권장: pip install -U openai httpx"
            )

        try:
            _llm_timeout = int(os.getenv("OPENAI_API_TIMEOUT", 45))
            http_client = httpx.Client(
                timeout=httpx.Timeout(_llm_timeout, connect=10.0)
            )
            self.client = OpenAI(api_key=api_key, http_client=http_client)
        except Exception as e:
            raise RuntimeError(f"OpenAI 클라이언트 초기화 실패: {e}")

    def _response_to_dict(self, res: Any) -> Dict[str, Any]:
        """응답 객체를 dict로 변환 (디버깅용)"""
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
        """객체를 재귀적으로 탐색하여 텍스트를 찾음"""
        if depth > max_depth:
            return []

        texts = []

        if isinstance(obj, str) and obj.strip():
            texts.append(obj.strip())
        elif isinstance(obj, dict):
            priority_keys = ["text", "content", "output_text", "message", "output"]
            for key in priority_keys:
                if key in obj:
                    found = self._extract_text_recursive(obj[key], depth + 1, max_depth)
                    if found:
                        texts.extend(found)
            for key, value in obj.items():
                if key not in priority_keys:
                    found = self._extract_text_recursive(value, depth + 1, max_depth)
                    if found:
                        texts.extend(found)
        elif isinstance(obj, list):
            for item in obj:
                found = self._extract_text_recursive(item, depth + 1, max_depth)
                if found:
                    texts.extend(found)
        elif hasattr(obj, "__dict__"):
            priority_attrs = ["text", "content", "output_text", "message", "output"]
            for attr in priority_attrs:
                if hasattr(obj, attr):
                    value = getattr(obj, attr)
                    found = self._extract_text_recursive(value, depth + 1, max_depth)
                    if found:
                        texts.extend(found)

        return texts

    def _extract_text(self, res: Any) -> str:
        """OpenAI 응답에서 텍스트를 최대한 안전하게 추출"""
        text = getattr(res, "output_text", None)
        if isinstance(text, str) and text.strip():
            return text.strip()

        out = getattr(res, "output", None)
        if out is not None:
            chunks = []
            if isinstance(out, list):
                for item in out:
                    if isinstance(item, dict):
                        item_type = item.get("type")
                        if item_type == "reasoning":
                            summary = item.get("summary")
                            if isinstance(summary, list) and len(summary) > 0:
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
                            elif isinstance(summary, str) and summary.strip():
                                chunks.append(summary.strip())

                        content = item.get("content")
                        if isinstance(content, str) and content.strip():
                            chunks.append(content.strip())
                        elif isinstance(content, list):
                            for c in content:
                                if isinstance(c, dict):
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
                                    elif (
                                        "text" in c
                                        and isinstance(c["text"], str)
                                        and c["text"].strip()
                                    ):
                                        chunks.append(c["text"].strip())
                        if (
                            "text" in item
                            and isinstance(item["text"], str)
                            and item["text"].strip()
                        ):
                            chunks.append(item["text"].strip())
                    else:
                        item_type = getattr(item, "type", None)
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

        text_attr = getattr(res, "text", None)
        if isinstance(text_attr, str) and text_attr.strip():
            return text_attr.strip()

        try:
            res_dict = self._response_to_dict(res)
            if res_dict:
                if "output_text" in res_dict and isinstance(
                    res_dict["output_text"], str
                ):
                    if res_dict["output_text"].strip():
                        return res_dict["output_text"].strip()
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
                if "text" in res_dict and isinstance(res_dict["text"], str):
                    if res_dict["text"].strip():
                        return res_dict["text"].strip()
        except Exception:
            pass

        try:
            recursive_texts = self._extract_text_recursive(res)
            if recursive_texts:
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

        default_max = int(
            os.getenv(
                "OPENAI_MAX_OUTPUT_TOKENS",
                getattr(settings, "OPENAI_MAX_OUTPUT_TOKENS", 800),
            )
        )
        if max_output_tokens is None or int(max_output_tokens) <= 0:
            max_output_tokens = default_max

        MAX_HARD_CAP = int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS_CAP", 1200))
        if max_output_tokens > MAX_HARD_CAP:
            max_output_tokens = MAX_HARD_CAP

        if max_output_tokens < 16:
            max_output_tokens = 16

        supports_temperature = not str(final_model).startswith("gpt-5")

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
            "9. CONTEXT에 있는 자료를 기반으로 답변하세요. 여러 국가의 자료가 있으면 "
            "모두 활용하여 답변하세요."
        )
        if instructions:
            system_prompt += f"\n\n[추가 지시사항]\n{instructions}"

        context_length = len(context) if context else 0
        logger.debug(
            f"[LLM 프롬프트] 질문 길이={len(query_text)}, CONTEXT 길이={context_length}"
        )
        if context_length < 50:
            logger.warning(f"[LLM 프롬프트] CONTEXT가 너무 짧음 ({context_length}자)")

        user_prompt = (
            f"[CONTEXT]\n{context}\n\n"
            f"---\n\n"
            f"위 CONTEXT만을 근거로 다음 질문에 답변하세요.\n"
            f"[질문] {query_text}"
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

        if str(final_model).startswith("gpt-5"):
            if reasoning_effort and reasoning_effort.strip():
                payload["reasoning"] = {"effort": reasoning_effort.strip()}
            else:
                payload["reasoning"] = {"effort": "low"}
        elif reasoning_effort and reasoning_effort.strip():
            payload["reasoning"] = {"effort": reasoning_effort.strip()}

        if supports_temperature and temperature is not None:
            payload["temperature"] = temperature

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
            response_id = getattr(res, "id", None)
            logger.error(
                f"[LLM 빈 응답] model={final_model} 소요={dt:.2f}s response_id={response_id}"
            )
            return LLMResult(text="답변 생성에 실패했습니다. (빈 응답)", raw=res)

        logger.info(
            f"[LLM 호출 완료] model={final_model} 소요={dt:.2f}s 글자수={len(text)}"
        )
        return LLMResult(text=text, raw=res)

    def classify_intent(
        self, query_text: str, *, model: Optional[str] = None
    ) -> Dict[str, Any]:
        """질문 분석 + 검색 힌트 생성용 LLM 호출 (한 번에 처리)"""
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
            "- topic_entity: 질문의 핵심 인물/기관/주제 (없으면 빈 문자열)\n"
            "- time_focus: 시간적 범위 힌트\n"
            "- sentiment_focus: 질문의 뉘앙스\n"
            "- information_scope: broad(전체적인 흐름) | specific(특정 사건/사안)\n"
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

        if str(final_model).startswith("gpt-5"):
            payload["reasoning"] = {"effort": "low"}

        try:
            res = self.client.responses.create(**payload)
            text = (self._extract_text(res) or "").strip()
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

            return {
                "main_intent": data.get("main_intent", "unknown"),
                "topic_entity": (data.get("topic_entity") or "").strip(),
                "time_focus": data.get("time_focus", "unspecified"),
                "sentiment_focus": data.get("sentiment_focus", "neutral"),
                "information_scope": data.get("information_scope", "broad"),
                "core_question": (data.get("core_question") or "").strip(),
                "search_hint": (data.get("search_hint") or "").strip()[:120],
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
        """대화형 질문을 검색에 적합한 자연어 문장으로 재구성."""
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
            "6. 키워드만 출력해. 설명이나 문장 형태로 쓰지 마.\n"
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

            if not reformulated:
                return query_text

            if len(reformulated) > 200:
                reformulated = reformulated[:200].strip()

            return reformulated
        except Exception as e:
            logger.warning(
                f"[reformulate_query] 실패, 원본 사용: {type(e).__name__}: {str(e)}"
            )
            return query_text
