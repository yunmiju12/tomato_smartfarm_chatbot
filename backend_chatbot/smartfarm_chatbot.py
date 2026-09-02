import os
import re
import sqlite3
import hashlib
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


@dataclass
class Settings:
    excel_path: Path = (
        BASE_DIR / "source" / "tomato_project" / "tomato_chapter2-10_data.xlsx"
    )
    sqlite_path: Path = BASE_DIR / "smartfarm_tomato.db"
    chroma_path: Path = BASE_DIR / "vectordb" / "chroma_rec"
    chroma_collection: str = "chroma_rec"
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_model: str = os.getenv(
        "OPENROUTER_MODEL", "google/gemma-4-26b-a4b-it:free"
    )
    openrouter_models: str = os.getenv(
        "OPENROUTER_MODELS",
        "poolside/laguna-m.1:free,openai/gpt-oss-20b:free,nvidia/nemotron-nano-9b-v2:free,google/gemma-4-26b-a4b-it:free",
    )
    openrouter_base_url: str = os.getenv(
        "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
    )
    llm_timeout_seconds: int = int(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
    use_semantic_search: bool = os.getenv("SMARTFARM_USE_SEMANTIC_SEARCH", "1") == "1"
    use_reranker: bool = os.getenv("SMARTFARM_USE_RERANKER", "1") == "1"
    embedding_model: str = os.getenv("SMARTFARM_EMBEDDING_MODEL", "BAAI/bge-m3")
    reranker_model: str = os.getenv(
        "SMARTFARM_RERANKER_MODEL", "BAAI/bge-reranker-v2-m3"
    )
    retrieval_candidate_k: int = int(os.getenv("SMARTFARM_RETRIEVAL_CANDIDATE_K", "20"))

    @property
    def model_candidates(self) -> List[str]:
        models = [
            model.strip()
            for model in self.openrouter_models.split(",")
            if model.strip()
        ]
        if self.openrouter_model and self.openrouter_model not in models:
            models.append(self.openrouter_model)
        return models


settings = Settings()
llm_executor = ThreadPoolExecutor(max_workers=2)


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, description="사용자 질문")
    use_llm: bool = Field(
        True, description="LangChain + OpenRouter LLM으로 최종 답변을 생성할지 여부"
    )


class ChatResponse(BaseModel):
    question: str
    route: Literal["SQL", "RAG", "HYBRID", "GENERAL"]
    route_reason: str
    target_greenhouse: Optional[str]
    generated_sql: Optional[str]
    sensor_data: List[Dict[str, Any]]
    retrieved_docs: List[Dict[str, Any]]
    answer: str
    llm_used: bool = False
    llm_model: Optional[str] = None
    llm_error: Optional[str] = None


class TomatoDatabase:
    def __init__(self, excel_path: Path, sqlite_path: Path):
        self.excel_path = excel_path
        self.sqlite_path = sqlite_path
        self.conn = sqlite3.connect(sqlite_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

    def build(self, force: bool = False) -> None:
        if self.sqlite_path.exists() and not force:
            tables = self._tables()
            if {
                "greenhouse_sensors",
                "environment_standards",
                "greenhouse_meta",
            } <= tables:
                return

        if not self.excel_path.exists():
            raise FileNotFoundError(f"Excel file not found: {self.excel_path}")

        sensor_df = pd.read_excel(self.excel_path, sheet_name="센서_시간대144")
        sensor_df["timestamp"] = pd.to_datetime(
            sensor_df["날짜"].astype(str) + " " + sensor_df["시간"].astype(str),
            errors="coerce",
        )
        sensor_final = pd.DataFrame(
            {
                "greenhouse_id": sensor_df["온실번호"]
                .astype(str)
                .str.strip()
                .str.upper(),
                "temperature": pd.to_numeric(sensor_df["온도(℃)"], errors="coerce"),
                "humidity": pd.to_numeric(sensor_df["습도(%)"], errors="coerce"),
                "co2": pd.to_numeric(sensor_df["CO2(ppm)"], errors="coerce"),
                "light_lux": pd.to_numeric(sensor_df.get("광량(lux)"), errors="coerce"),
                "irrigation_l": pd.to_numeric(
                    sensor_df.get("관수량(L/회)"), errors="coerce"
                ),
                "growth_stage": sensor_df.get("생육단계", ""),
                "day_night": sensor_df.get("주야구분", ""),
                "ventilation": sensor_df.get("환기상태", ""),
                "disease": sensor_df.get("병해충·질병", ""),
                "risk_level": sensor_df.get("위험도", ""),
                "risk_score": pd.to_numeric(sensor_df.get("위험점수"), errors="coerce"),
                "reason": sensor_df.get("이상원인", ""),
                "action_guide": sensor_df.get("권장조치", ""),
                "timestamp": sensor_df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
        sensor_final.to_sql(
            "greenhouse_sensors", self.conn, if_exists="replace", index=False
        )

        std_df = pd.read_excel(
            self.excel_path, sheet_name="추출_환경기준&추출_병해충기준"
        )
        std_final = pd.DataFrame(
            {
                "category": std_df["구분"].astype(str).str.strip(),
                "standard_name": std_df["기준명"].astype(str).str.strip(),
                "normal_range": std_df["정상/권장 범위"].astype(str).str.strip(),
                "danger_condition": std_df["위험/주의 기준"].astype(str).str.strip(),
                "management_tip": std_df["관리 활용"].astype(str).str.strip(),
                "chapter": std_df.get("근거 챕터", ""),
                "pdf_page": std_df.get("PDF page", ""),
            }
        )
        std_final.to_sql(
            "environment_standards", self.conn, if_exists="replace", index=False
        )

        self.conn.execute("DROP TABLE IF EXISTS greenhouse_meta")
        self.conn.execute(
            "CREATE TABLE greenhouse_meta (greenhouse_id TEXT PRIMARY KEY, aliases TEXT)"
        )
        for greenhouse_id in sorted(sensor_final["greenhouse_id"].dropna().unique()):
            number = int(re.search(r"\d+", greenhouse_id).group())
            aliases = {
                greenhouse_id.lower(),
                greenhouse_id.replace("-", "").lower(),
                f"{number}번",
                f"{number}호",
                f"{number}방",
                f"{number}동",
                f"{number}번온실",
                f"{number}온실",
                f"gh{number:02d}",
                f"gh-{number:02d}",
            }
            if number == 1:
                aliases.update({"토마토방", "토마토온실", "토마토하우스"})
            self.conn.execute(
                "INSERT INTO greenhouse_meta VALUES (?, ?)",
                (greenhouse_id, ",".join(sorted(aliases))),
            )
        self.conn.commit()

    def _tables(self) -> set[str]:
        rows = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        return {row["name"] for row in rows}

    def detect_greenhouse(self, question: str) -> Optional[str]:
        clean = question.replace(" ", "").lower()
        direct = re.search(r"(?:gh[-_ ]?0*)(\d+)", clean)
        if direct:
            return f"GH-{int(direct.group(1)):02d}"
        korean_direct = re.search(r"(\d+)(?:번|호|방|동)", clean)
        if korean_direct:
            return f"GH-{int(korean_direct.group(1)):02d}"
        if "토마토방" in clean:
            return "GH-01"

        for row in self.conn.execute(
            "SELECT greenhouse_id, aliases FROM greenhouse_meta"
        ):
            aliases = [alias for alias in row["aliases"].split(",") if alias]
            if any(alias in clean for alias in aliases):
                return row["greenhouse_id"]
        return None

    def query_sensor(
        self, question: str, greenhouse_id: Optional[str]
    ) -> tuple[str, List[Dict[str, Any]]]:
        clean = question.replace(" ", "").lower()

        target = greenhouse_id or "GH-01"
        metric_sql = "temperature, humidity, co2, light_lux, irrigation_l, risk_score"
        conditions = ["greenhouse_id = ?"]
        params: List[Any] = [target]

        date_match = re.search(r"(\d{1,2})월(\d{1,2})일", clean)
        if date_match:
            month, day = date_match.groups()
            conditions.append("timestamp LIKE ?")
            params.append(f"2026-{int(month):02d}-{int(day):02d}%")

        time_match = re.search(r"(오전|오후)?(\d{1,2})시", clean)
        if time_match:
            ampm, hour_text = time_match.groups()
            hour = int(hour_text)
            if ampm == "오후" and hour < 12:
                hour += 12
            elif ampm == "오전" and hour == 12:
                hour = 0
            conditions.append("timestamp LIKE ?")
            params.append(f"% {hour:02d}:%")

        where_sql = " AND ".join(conditions)

        if any(word in clean for word in ["평균", "avg", "average"]):
            sql = f"""
                SELECT greenhouse_id,
                       AVG(temperature) AS temperature,
                       AVG(humidity) AS humidity,
                       AVG(co2) AS co2,
                       AVG(light_lux) AS light_lux,
                       AVG(irrigation_l) AS irrigation_l,
                       AVG(risk_score) AS risk_score
                FROM greenhouse_sensors
                WHERE {where_sql}
                GROUP BY greenhouse_id
            """
        elif any(word in clean for word in ["최고", "최대", "가장높", "max"]):
            sql = f"""
                SELECT greenhouse_id,
                       MAX(temperature) AS temperature,
                       MAX(humidity) AS humidity,
                       MAX(co2) AS co2,
                       MAX(light_lux) AS light_lux,
                       MAX(irrigation_l) AS irrigation_l,
                       MAX(risk_score) AS risk_score
                FROM greenhouse_sensors
                WHERE {where_sql}
                GROUP BY greenhouse_id
            """
        elif any(word in clean for word in ["최저", "최소", "가장낮", "min"]):
            sql = f"""
                SELECT greenhouse_id,
                       MIN(temperature) AS temperature,
                       MIN(humidity) AS humidity,
                       MIN(co2) AS co2,
                       MIN(light_lux) AS light_lux,
                       MIN(irrigation_l) AS irrigation_l,
                       MIN(risk_score) AS risk_score
                FROM greenhouse_sensors
                WHERE {where_sql}
                GROUP BY greenhouse_id
            """
        else:
            sql = f"""
                SELECT greenhouse_id, {metric_sql}, growth_stage, day_night, ventilation,
                       disease, risk_level, reason, action_guide, timestamp
                FROM greenhouse_sensors
                WHERE {where_sql}
                ORDER BY timestamp DESC
                LIMIT 1
            """

        rows = self.conn.execute(sql, tuple(params)).fetchall()
        return " ".join(sql.split()), [dict(row) for row in rows]

    def query_standards(self, question: str) -> List[Dict[str, Any]]:
        clean = question.replace(" ", "").lower()
        categories = []
        if any(word in clean for word in ["온도", "기온", "덥", "춥"]):
            categories.append("온도")
        if any(word in clean for word in ["습도", "과습", "건조"]):
            categories.append("습도")
        if any(word in clean for word in ["co2", "이산화탄소"]):
            categories.append("CO2")
        if not categories:
            return []
        marks = ",".join("?" for _ in categories)
        rows = self.conn.execute(
            f"""
            SELECT category, standard_name, normal_range, danger_condition, management_tip, chapter, pdf_page
            FROM environment_standards
            WHERE category IN ({marks})
            LIMIT 5
            """,
            tuple(categories),
        ).fetchall()
        return [dict(row) for row in rows]


class ChromaKnowledgeBase:
    def __init__(
        self,
        chroma_path: Path,
        collection_name: str,
        use_semantic_search: bool = True,
        use_reranker: bool = True,
        embedding_model: str = "BAAI/bge-m3",
        reranker_model: str = "BAAI/bge-reranker-v2-m3",
        candidate_k: int = 20,
    ):
        self.chroma_path = chroma_path
        self.collection_name = collection_name
        self.use_semantic_search = use_semantic_search
        self.use_reranker = use_reranker
        self.embedding_model = embedding_model
        self.reranker_model = reranker_model
        self.candidate_k = candidate_k
        self._collection = None
        self._embedder = None
        self._reranker = None

    def search(self, question: str, limit: int = 4) -> List[Dict[str, Any]]:
        if not (self.chroma_path / "chroma.sqlite3").exists():
            return []

        candidate_limit = max(limit, self.candidate_k)
        candidates: List[Dict[str, Any]] = []
        if self.use_semantic_search:
            candidates.extend(self._semantic_search(question, candidate_limit))

        candidates.extend(self._sqlite_keyword_search(question, candidate_limit))
        candidates = self._dedupe_docs(candidates)
        if not candidates:
            return []

        if self.use_reranker:
            reranked = self._rerank(question, candidates, limit)
            if reranked:
                return reranked

        return sorted(
            candidates,
            key=lambda item: (
                item.get("keyword_score", 0),
                item.get("semantic_score", float("-inf")),
            ),
            reverse=True,
        )[:limit]

    def _semantic_search(self, question: str, limit: int) -> List[Dict[str, Any]]:
        try:
            import chromadb
            from sentence_transformers import SentenceTransformer

            if self._collection is None:
                client = chromadb.PersistentClient(path=str(self.chroma_path))
                self._collection = client.get_collection(self.collection_name)
            if self._embedder is None:
                self._embedder = SentenceTransformer(self.embedding_model)

            query_embedding = self._embedder.encode([question]).tolist()
            result = self._collection.query(
                query_embeddings=query_embedding, n_results=limit
            )
            docs = result.get("documents", [[]])[0]
            metadatas = result.get("metadatas", [[]])[0]
            distances = result.get("distances", [[]])[0]
            return [
                {
                    "text": self._clean_response_text(text),
                    "metadata": self._clean_metadata(meta or {}),
                    "score": distance,
                    "semantic_distance": distance,
                    "semantic_score": -float(distance),
                    "retrieval_method": "bge-m3",
                }
                for text, meta, distance in zip(docs, metadatas, distances)
            ]
        except Exception as exc:
            print(f"[Warning] bge-m3 semantic search failed: {exc}")
            return []

    def _sqlite_keyword_search(self, question: str, limit: int) -> List[Dict[str, Any]]:
        stopwords = {
            "알려줘",
            "분석해줘",
            "종합",
            "지금",
            "현재",
            "방법",
            "조치",
            "위험",
            "온실",
            "높은데",
            "낮은데",
            "어떻게",
            "까지",
        }
        keywords = [
            word
            for word in re.findall(r"[가-힣A-Za-z0-9]+", question)
            if len(word) >= 2 and word not in stopwords
        ]
        if not keywords:
            return []

        db_path = self.chroma_path / "chroma.sqlite3"
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        clauses = " OR ".join(["fts.string_value LIKE ?"] * len(keywords))
        params = [f"%{word}%" for word in keywords]
        rows = conn.execute(
            f"""
            SELECT e.id AS internal_id, e.embedding_id, fts.string_value AS text
            FROM embeddings e
            JOIN embedding_fulltext_search fts ON fts.rowid = e.id
            WHERE {clauses}
            LIMIT ?
            """,
            (*params, max(limit * 15, 30)),
        ).fetchall()

        docs = []
        for row in rows:
            meta_rows = conn.execute(
                "SELECT key, string_value, int_value, float_value FROM embedding_metadata WHERE id = ?",
                (row["internal_id"],),
            ).fetchall()
            metadata = {
                m["key"]: m["string_value"] or m["int_value"] or m["float_value"]
                for m in meta_rows
            }
            raw_text = row["text"]
            score = sum(len(word) for word in keywords if word in raw_text)
            score += sum(
                10
                for word in keywords
                if word and word in str(metadata.get("chapter_title", ""))
            )
            score += sum(
                10
                for word in keywords
                if word and word in str(metadata.get("category", ""))
            )
            docs.append(
                {
                    "text": self._clean_response_text(raw_text),
                    "metadata": self._clean_metadata(metadata),
                    "score": score,
                    "keyword_score": score,
                    "retrieval_method": "keyword",
                }
            )
        conn.close()
        return sorted(docs, key=lambda item: item["score"] or 0, reverse=True)[:limit]

    def _dedupe_docs(self, docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        merged: Dict[str, Dict[str, Any]] = {}
        for doc in docs:
            key = self._doc_key(doc.get("text", ""))
            if key not in merged:
                merged[key] = doc
                continue
            existing = merged[key]
            if len(doc.get("text", "")) > len(existing.get("text", "")):
                existing["text"] = doc.get("text", "")
            existing["keyword_score"] = max(
                existing.get("keyword_score", 0), doc.get("keyword_score", 0)
            )
            existing["semantic_score"] = max(
                existing.get("semantic_score", float("-inf")),
                doc.get("semantic_score", float("-inf")),
            )
            methods = set(str(existing.get("retrieval_method", "")).split("+"))
            methods.update(str(doc.get("retrieval_method", "")).split("+"))
            existing["retrieval_method"] = "+".join(
                sorted(method for method in methods if method)
            )
        return list(merged.values())

    def _rerank(
        self, question: str, docs: List[Dict[str, Any]], limit: int
    ) -> List[Dict[str, Any]]:
        try:
            from sentence_transformers import CrossEncoder

            if self._reranker is None:
                self._reranker = CrossEncoder(self.reranker_model)

            pairs = [(question, doc.get("text", "")) for doc in docs]
            scores = self._reranker.predict(pairs)
            for doc, score in zip(docs, scores):
                doc["rerank_score"] = float(score)
                doc["score"] = float(score)
                method = str(doc.get("retrieval_method", ""))
                if "reranker" not in method:
                    doc["retrieval_method"] = (
                        f"{method}+reranker" if method else "reranker"
                    )
            return sorted(
                docs,
                key=lambda item: item.get("rerank_score", float("-inf")),
                reverse=True,
            )[:limit]
        except Exception as exc:
            print(f"[Warning] reranker failed: {exc}")
            return []

    def _clean_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        cleaned = {}
        for key, value in metadata.items():
            if key == "chroma:document":
                continue
            cleaned[key] = (
                self._clean_response_text(value) if isinstance(value, str) else value
            )
        return cleaned

    def _clean_response_text(self, text: Any) -> str:
        return re.sub(r"\s+", " ", str(text).replace("\\n", " ")).strip()

    def _doc_key(self, text: str) -> str:
        normalized = self._clean_response_text(text).lower()
        return hashlib.sha256(normalized.encode("utf-8", errors="ignore")).hexdigest()


class LangChainOpenRouterClient:
    def __init__(self, api_key: str, models: List[str], base_url: str):
        self.api_key = api_key
        self.models = models
        self.base_url = base_url.rstrip("/")
        self._llms: Dict[str, ChatOpenAI] = {}
        self._prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "너는 토마토 스마트팜 운영 지원 챗봇이다. "
                    "반드시 제공된 센서/SQL 근거와 문서/RAG 근거만 사용한다. "
                    "근거에 없는 내용은 추측하지 않는다. "
                    "사용자가 물어본 내용에만 답하고, 불필요한 항목은 덧붙이지 않는다. "
                    "한국어로 간결하고 완결된 문장으로 답한다."
                    "모든 답변은 존댓말 '-습니다/-합니다' 체로 통일한다."
                    "오타나 부자연스러운 표현 없이 간결하게 작성한다."
                    # 추가
                    "PDF 문서 내용을 원문 그대로 길게 복사하지 말고, 핵심만 요약한다. "
                    "사용자의 질문 유형에 맞는 형식으로 답한다. "
                    "병해충 증상·진단·방제 질문인 경우에는 다음 형식으로 답한다: "
                    "1) 판단 요약 "
                    "2) 의심 가능성 "
                    "3) 확인할 증상 "
                    "4) 권장 조치 "
                    "5) 주의사항 "
                    "각 항목은 1~2문장으로 짧게 작성한다. "
                    "병명은 단정하지 말고 '가능성'으로 표현한다. "
                    "단, 온도·습도·CO2·착과 조건 등 재배 기준을 묻는 질문은 "
                    "위 진단 형식을 강제하지 말고 기준값, 현재 상태, 관리 방법 중심으로 답한다. ",
                ),
                (
                    "human",
                    "질문: {question}\n\n"
                    "라우팅: {route}\n\n"
                    "센서/SQL 근거:\n{sensor_context}\n\n"
                    "문서/RAG 근거:\n{doc_context}\n\n"
                    "공통 규칙:\n"
                    "1. 사용자가 물어본 항목을 가장 먼저 답한다.\n"
                    "2. 질문과 직접 관련 없는 센서값, 병해충, 기준 DB는 길게 설명하지 않는다.\n"
                    "3. 숫자는 소수점 첫째 자리까지만 반올림한다.\n"
                    "4. action_guide는 사용자가 조치, 해결, 대응, 관리 방법을 물었거나 위험도 질문일 때 반드시 포함한다.\n"
                    "5. reason은 사용자가 원인, 이유, 위험도, 분석을 물었을 때 포함한다.\n"
                    "6. disease는 사용자가 병해충, 질병, 의심 병명을 물었거나 sensor_context에 disease가 있고 위험도 질문일 때 포함한다.\n"
                    "7. 기준 DB의 normal_range는 사용자가 기준, 적정, 범위, 판단, 높은지/낮은지를 물었을 때만 비교에 사용한다.\n"
                    "8. 문서/RAG 근거가 있으면 문서 내용을 요약하되, 질문과 맞지 않는 문서는 사용하지 않는다.\n"
                    "9. 답변은 최대 5문장으로 끝내고, 중간에 끊기지 않게 한다.\n"
                    "10. 근거가 부족하면 부족하다고 말한다.\n"
                    "11.기준에 낮/밤 조건이 나뉘어 있으면 현재 데이터의 주야 구분을 확인하거나, 주야 기준을 나누어 설명한다.\n\n"
                    "라우팅별 답변 방식:\n"
                    "- SQL: 사용자가 요청한 센서값 또는 온실 상태만 답한다. 위험도/조치 질문이면 reason과 action_guide를 포함한다.\n"
                    "- RAG: 문서 근거만 사용해 재배·병해충 지식을 설명하고, 가능하면 출처를 짧게 붙인다.\n"
                    "- HYBRID: 센서 상태를 먼저 말하고, 필요한 경우 기준 DB 또는 문서 근거로 판단과 조치를 덧붙인다.\n"
                    "- GENERAL: 챗봇의 지원 범위만 안내하고 RAG/SQL 근거를 억지로 사용하지 않는다.\n\n"
                    "위 규칙에 따라 최종 답변을 작성해줘.",
                ),
            ]
        )

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _get_llm(self, model: str) -> ChatOpenAI:
        if model not in self._llms:
            import httpx

            self._llms[model] = ChatOpenAI(
                model=model,
                api_key=self.api_key,
                base_url=self.base_url,
                temperature=0.2,
                max_completion_tokens=700,
                timeout=settings.llm_timeout_seconds,
                max_retries=0,
                default_headers={
                    "HTTP-Referer": "http://localhost:8000",
                    "X-Title": "SmartFarm Chatbot",
                },
                http_client=httpx.Client(
                    timeout=httpx.Timeout(
                        float(settings.llm_timeout_seconds), connect=5.0
                    )
                ),
            )
        return self._llms[model]

    def complete(
        self,
        question: str,
        route: str,
        sensor_data: List[Dict[str, Any]],
        docs: List[Dict[str, Any]],
    ) -> tuple[str, str]:
        if not self.available:
            return "", ""

        sensor_context = self._format_sensor_context(sensor_data)
        doc_context = self._format_doc_context(docs)
        messages = self._prompt.format_messages(
            question=question,
            route=route,
            sensor_context=sensor_context,
            doc_context=doc_context,
        )
        errors = []
        for model in self.models:
            try:
                response = self._get_llm(model).invoke(messages)
                answer = str(response.content).strip()
                if answer:
                    return answer, model
                errors.append(f"{model}: empty response")
            except Exception as exc:
                errors.append(f"{model}: {type(exc).__name__}: {exc}")
        raise RuntimeError(" | ".join(errors))

    def _format_sensor_context(self, sensor_data: List[Dict[str, Any]]) -> str:
        if not sensor_data:
            return "없음"
        return "\n".join(str(item) for item in sensor_data[:5])

    def _format_doc_context(self, docs: List[Dict[str, Any]]) -> str:
        if not docs:
            return "없음"
        lines = []
        for idx, doc in enumerate(docs[:4], start=1):
            meta = doc.get("metadata", {})
            lines.append(
                f"[문서 {idx}] "
                f"출처={meta.get('source', '-')}, "
                f"챕터={meta.get('chapter_title', '-')}, "
                f"페이지={meta.get('pdf_page', '-')}\n"
                f"{doc.get('text', '')[:800]}"
            )
        return "\n\n".join(lines)


class SmartFarmRouter:
    sql_keywords = {
        "온도",
        "습도",
        "co2",
        "이산화탄소",
        "센서",
        "수치",
        "측정",
        "현재",
        "지금",
        "평균",
        "최고",
        "최저",
        "최대",
        "최소",
        "광량",
        "관수",
        "위험도",
        "위험점수",
    }
    rag_keywords = {
        "병",
        "병해충",
        "해충",
        "곰팡이",
        "바이러스",
        "재배",
        "방제",
        "원인",
        "증상",
        "대책",
        "관리",
        "가이드",
        "기준",
        "생육",
        "착과",
        "잎",
        "뿌리",
        "열매",
    }

    def __init__(
        self,
        db: TomatoDatabase,
        kb: ChromaKnowledgeBase,
        llm: LangChainOpenRouterClient,
    ):
        self.db = db
        self.kb = kb
        self.llm = llm

    def route(self, question: str) -> tuple[str, str, Optional[str]]:
        clean = question.replace(" ", "").lower()
        greenhouse_id = self.db.detect_greenhouse(question)
        has_sql = greenhouse_id is not None or any(
            word in clean for word in self.sql_keywords
        )
        has_rag = any(word in clean for word in self.rag_keywords)

        if has_sql and has_rag:
            return (
                "HYBRID",
                "센서 수치와 재배/병해충 지식이 함께 필요한 질문입니다.",
                greenhouse_id,
            )
        if has_sql:
            return (
                "SQL",
                "센서값, 통계, 온실 번호 등 정형 데이터 질문입니다.",
                greenhouse_id,
            )
        if has_rag:
            return (
                "RAG",
                "재배법, 병해충, 방제처럼 문서 지식 검색이 필요한 질문입니다.",
                greenhouse_id,
            )
        return (
            "GENERAL",
            "명확한 라우팅 키워드가 없어 기본 상담으로 처리합니다.",
            greenhouse_id,
        )

    def answer(self, question: str, use_llm: bool = True) -> ChatResponse:
        route, reason, greenhouse_id = self.route(question)
        generated_sql = None
        sensor_data: List[Dict[str, Any]] = []
        docs: List[Dict[str, Any]] = []

        if route in {"SQL", "HYBRID"}:
            generated_sql, sensor_data = self.db.query_sensor(question, greenhouse_id)
            sensor_data.extend(self.db.query_standards(question))

        if route in {"RAG", "HYBRID", "GENERAL"}:
            docs = self.kb.search(question)

        llm_answer = ""
        llm_model = None
        llm_error = None
        if use_llm:
            try:
                future = llm_executor.submit(
                    self.llm.complete, question, route, sensor_data, docs
                )
                llm_answer, llm_model = future.result(
                    timeout=settings.llm_timeout_seconds * max(len(self.llm.models), 1)
                )
            except TimeoutError:
                llm_error = f"LLM timeout after trying {len(self.llm.models)} model(s)"
            except Exception as exc:
                llm_error = f"{type(exc).__name__}: {exc}"

        fallback = self._fallback_answer(route, sensor_data, docs)
        final_answer = self._clean_answer(llm_answer or fallback)
        return ChatResponse(
            question=question,
            route=route,
            route_reason=reason,
            target_greenhouse=greenhouse_id,
            generated_sql=generated_sql,
            sensor_data=sensor_data,
            retrieved_docs=docs,
            answer=final_answer,
            llm_used=bool(llm_answer),
            llm_model=llm_model,
            llm_error=llm_error,
        )

    def _clean_answer(self, answer: str) -> str:
        text = str(answer).replace("\\n", "\n")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _fallback_answer(
        self, 
        route: str, 
        sensor_data: List[Dict[str, Any]], 
        docs: List[Dict[str, Any]]
    ) -> str:
        def fmt(value: Any, unit: str = "") -> str:
            if value is None or value == "" or value == "-":
                return "-"
            try:
                return f"{float(value):.1f}{unit}"
            except (TypeError, ValueError):
                return f"{value}{unit}"

        parts = []

        if route in {"SQL", "HYBRID"}:
            real_sensor_rows = [
                item for item in sensor_data
                if item.get("greenhouse_id") and (
                    item.get("temperature") is not None
                    or item.get("humidity") is not None
                    or item.get("co2") is not None
                )
            ]
        
            standard_rows = [
                item for item in sensor_data
                if item.get("standard_name") or item.get("normal_range")
            ]
        
            if real_sensor_rows:
                first = real_sensor_rows[0]
        
                parts.append(
                    "센서 조회 결과: "
                    f"{first.get('greenhouse_id', '-')}, "
                    f"온도 {fmt(first.get('temperature'), '℃')}, "
                    f"습도 {fmt(first.get('humidity'), '%')}, "
                    f"CO2 {fmt(first.get('co2'), 'ppm')}, "
                    f"위험도 {first.get('risk_level', '-')}, "
                    f"위험점수 {fmt(first.get('risk_score'))}"
                )
        
                if first.get("disease"):
                    parts.append(f"의심 병해충/질병: {first['disease']}")
        
                if first.get("reason"):
                    parts.append(f"주요 원인: {first['reason']}")
        
                if first.get("action_guide"):
                    parts.append(f"권장조치: {first['action_guide']}")
        
            else:
                parts.append(
                    "해당 날짜와 온실에 저장된 센서 데이터가 없습니다. "
                    "온실 번호와 날짜를 확인하거나, 해당 날짜의 데이터가 DB에 저장되어 있는지 확인해 주세요."
                )
        
            for standard in standard_rows:
                parts.append(
                    "기준 DB 비교: "
                    f"{standard.get('standard_name', '-')}: "
                    f"정상/권장 범위 {standard.get('normal_range', '-')}. "
                    f"주의 기준 {standard.get('danger_condition', '-')}. "
                    f"관리 기준 {standard.get('management_tip', '-')}"
                )

        # if route in {"SQL", "HYBRID"} and sensor_data:
        #     first = sensor_data[0]
        #     parts.append(
        #         "센서 조회 결과: "
        #         f"{first.get('greenhouse_id', '-')}, "
        #         f"온도 {fmt(first.get('temperature'), '℃')}, "
        #         f"습도 {fmt(first.get('humidity'), '%')}, "
        #         f"CO2 {fmt(first.get('co2'), 'ppm')}, "
        #         f"위험도 {first.get('risk_level', '-')}, "
        #         f"위험점수 {fmt(first.get('risk_score'))}"
        #     )

        #     if first.get("disease"):
        #         parts.append(f"의심 병해충/질병: {first['disease']}")

        #     if first.get("reason"):
        #         parts.append(f"주요 원인: {first['reason']}")

        #     if first.get("action_guide"):
        #         parts.append(f"권장조치: {first['action_guide']}")

        #     standards = [
        #         item for item in sensor_data[1:]
        #         if item.get("standard_name") or item.get("normal_range")
        #     ]

        #     for standard in standards:
        #         parts.append(
        #             "기준 DB 비교: "
        #             f"{standard.get('standard_name', '-')}: "
        #             f"정상/권장 범위 {standard.get('normal_range', '-')}. "
        #             f"주의 기준 {standard.get('danger_condition', '-')}. "
        #             f"관리 기준 {standard.get('management_tip', '-')}"
        #         )

        if docs:
            top = docs[0]
            meta = top.get("metadata", {})
            parts.append(
                "문서 검색 결과: "
                f"{top.get('text', '')[:500]}\n"
                f"출처: {meta.get('source', '-')}, "
                f"{meta.get('chapter_title', '-')}, "
                f"p.{meta.get('pdf_page', '-')}"
            )

        if not parts:
            parts.append(
                "관련 센서 데이터나 문서 근거를 찾지 못했습니다. "
                "온실 번호, 센서 항목, 병해충명을 더 구체적으로 질문해 주세요."
            )

        return "\n\n".join(parts)


class LangChainSmartFarmRouter(SmartFarmRouter):
    sql_metric_keywords = {
        "온도",
        "기온",
        "습도",
        "co2",
        "이산화탄소",
        "광량",
        "관수",
        "급액",
        "배액",
        "위험도",
        "위험점수",
        "센서",
        "수치",
        "측정값",
    }
    sql_query_keywords = {
        "현재",
        "지금",
        "최근",
        "오늘",
        "조회",
        "알려줘",
        "보여줘",
        "측정",
        "상태",
        "평균",
        "최고",
        "최저",
        "최대",
        "최소",
        "몇",
        "얼마",
        "값",
        "수치",
        "데이터",
    }
    rag_keywords = {
        "병",
        "병해충",
        "해충",
        "곰팡이",
        "바이러스",
        "재배",
        "방제",
        "원인",
        "증상",
        "대책",
        "관리",
        "가이드",
        "기준",
        "생육",
        "착과",
        "육묘",
        "파종",
        "수확",
        "예방",
        "적정",
        "적합",
        "방법",
        "환경",
        "잎곰팡이",
        "가루이",
        "총채벌레",
    }
    general_keywords = {
        "안녕",
        "고마워",
        "감사",
        "너는",
        "챗봇",
        "도움말",
        "가격",
        "시세",
    }

    def __init__(
        self,
        db: TomatoDatabase,
        kb: ChromaKnowledgeBase,
        llm: LangChainOpenRouterClient,
    ):
        super().__init__(db, kb, llm)
        self.sql_chain = RunnableLambda(self._load_sql_context)
        self.rag_chain = RunnableLambda(self._load_rag_context)
        self.llm_chain = RunnableLambda(self._load_llm_answer)
        self.answer_chain = (
            RunnableLambda(self._build_initial_state)
            | self.sql_chain
            | self.rag_chain
            | self.llm_chain
            | RunnableLambda(self._build_response)
        )

    def route(self, question: str) -> tuple[str, str, Optional[str]]:
        clean = question.replace(" ", "").lower()
        greenhouse_id = self.db.detect_greenhouse(
            question
        ) or self._detect_greenhouse_by_korean(question)

        if any(word in clean for word in self.general_keywords):
            return (
                "GENERAL",
                "일반 대화 또는 현재 시스템 범위 밖 질문입니다.",
                greenhouse_id,
            )

        has_metric = any(word in clean for word in self.sql_metric_keywords)
        has_sql_query = any(word in clean for word in self.sql_query_keywords)
        has_sql = greenhouse_id is not None or (has_metric and has_sql_query)
        has_rag = any(word in clean for word in self.rag_keywords)

        knowledge_only = any(
            word in clean
            for word in ["기준", "적정", "적합", "방법", "예방", "방제", "원인", "증상"]
        )
        if (
            has_rag
            and knowledge_only
            and greenhouse_id is None
            and not (has_metric and has_sql_query)
        ):
            return (
                "RAG",
                "재배 기준이나 병해충 지식 검색이 필요한 질문입니다.",
                greenhouse_id,
            )

        if has_sql and has_rag:
            return (
                "HYBRID",
                "센서 수치와 재배/병해충 지식이 함께 필요한 질문입니다.",
                greenhouse_id,
            )
        if has_sql:
            return (
                "SQL",
                "센서값, 통계, 온실 번호 등 정형 데이터 질문입니다.",
                greenhouse_id,
            )
        if has_rag:
            return (
                "RAG",
                "재배법, 병해충, 방제처럼 문서 지식 검색이 필요한 질문입니다.",
                greenhouse_id,
            )
        return (
            "GENERAL",
            "명확한 라우팅 키워드가 없어 기본 상담으로 처리합니다.",
            greenhouse_id,
        )

    def answer(self, question: str, use_llm: bool = True) -> ChatResponse:
        return self.answer_chain.invoke({"question": question, "use_llm": use_llm})

    def _detect_greenhouse_by_korean(self, question: str) -> Optional[str]:
        match = re.search(
            r"(\d+)\s*(?:번|호)?\s*(?:온실|하우스|house|greenhouse)", question.lower()
        )
        if match:
            return f"GH-{int(match.group(1)):02d}"
        return None

    def _build_initial_state(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        question = str(payload["question"]).strip()
        route, reason, greenhouse_id = self.route(question)
        return {
            "question": question,
            "use_llm": bool(payload.get("use_llm", True)),
            "route": route,
            "route_reason": reason,
            "target_greenhouse": greenhouse_id,
            "generated_sql": None,
            "sensor_data": [],
            "retrieved_docs": [],
            "llm_answer": "",
            "llm_model": None,
            "llm_error": None,
        }

    def _load_sql_context(self, state: Dict[str, Any]) -> Dict[str, Any]:
        if state["route"] not in {"SQL", "HYBRID"}:
            return state

        generated_sql, sensor_data = self.db.query_sensor(
            state["question"], state["target_greenhouse"]
        )
        standards = self.db.query_standards(state["question"])
        return {
            **state,
            "generated_sql": generated_sql,
            "sensor_data": sensor_data + standards,
        }

    def _load_rag_context(self, state: Dict[str, Any]) -> Dict[str, Any]:
        if state["route"] not in {"RAG", "HYBRID"}:
            return state
        if self._is_standard_judgement(state["question"], state["target_greenhouse"]):
            return state
        return {**state, "retrieved_docs": self.kb.search(state["question"])}

    def _load_llm_answer(self, state: Dict[str, Any]) -> Dict[str, Any]:
        if not state["use_llm"]:
            return state

        try:
            future = llm_executor.submit(
                self.llm.complete,
                state["question"],
                state["route"],
                state["sensor_data"],
                state["retrieved_docs"],
            )
            llm_answer, llm_model = future.result(
                timeout=settings.llm_timeout_seconds * max(len(self.llm.models), 1)
            )
            return {**state, "llm_answer": llm_answer, "llm_model": llm_model}
        except TimeoutError:
            return {
                **state,
                "llm_error": f"LLM timeout after trying {len(self.llm.models)} model(s)",
            }
        except Exception as exc:
            return {**state, "llm_error": f"{type(exc).__name__}: {exc}"}

    def _build_response(self, state: Dict[str, Any]) -> ChatResponse:
        # GENERAL fallback에서 질문 내용을 사용할 수 있게 저장
        self._last_question = state["question"]

        fallback = self._fallback_answer(
            state["route"], 
            state["sensor_data"], 
            state["retrieved_docs"]
        )
        final_answer = self._clean_answer(state["llm_answer"] or fallback)
        return ChatResponse(
            question=state["question"],
            route=state["route"],
            route_reason=state["route_reason"],
            target_greenhouse=state["target_greenhouse"],
            generated_sql=state["generated_sql"],
            sensor_data=state["sensor_data"],
            retrieved_docs=state["retrieved_docs"],
            answer=final_answer,
            llm_used=bool(state["llm_answer"]),
            llm_model=state["llm_model"],
            llm_error=state["llm_error"],
        )

    def _fallback_answer(
        self,
        route: str,
        sensor_data: List[Dict[str, Any]],
        docs: List[Dict[str, Any]],
    ) -> str:
        if route == "GENERAL":
            question = getattr(self, "_last_question", "")
            clean = question.replace(" ", "").lower()
    
            if any(word in clean for word in ["안녕", "하이", "hello", "너는", "어떤", "챗봇"]):
                return (
                    "안녕하세요. 토마토 스마트팜 운영을 도와주는 챗봇입니다. "
                    "온실 번호와 날짜를 함께 말하면 온도, 습도, CO2 상태를 조회할 수 있습니다."
                )
    
            if any(word in clean for word in ["고마워", "감사"]):
                return "도움이 되었다면 다행입니다. 언제든지 온실 센서값 조회, 재배 기준, 병해충 관리 질문을 해주세요."
    
            if any(word in clean for word in ["도움말", "사용법", "뭐할수"]):
                return (
                    "저는 온실 센서값 조회, 날짜별 온도·습도 확인, 토마토 재배 기준, 병해충 대응 방법을 안내할 수 있습니다. "
                    "예시는 '1번 온실 7월 7일 온도 알려줘', '토마토방 현재 상태 알려줘', '잎곰팡이병 대처 방법 알려줘'입니다."
                )
    
            if any(word in clean for word in ["가격", "시세", "판매", "전망"]):
                return (
                    "온실 센서값, 재배 기준, 병해충 관리 질문을 도와드릴 수 있습니다."
                )
    
            return (
                "토마토 스마트팜 챗봇입니다. "
                "온실 번호, 날짜, 센서 항목을 함께 입력하면 더 정확하게 답변할 수 있습니다."
            )
    
        return super()._fallback_answer(route, sensor_data, docs)

    def _is_standard_judgement(
        self, question: str, greenhouse_id: Optional[str]
    ) -> bool:
        clean = question.replace(" ", "").lower()
        return (
            greenhouse_id is not None
            and any(
                word in clean for word in ["온도", "기온", "습도", "co2", "이산화탄소"]
            )
            and any(
                word in clean
                for word in ["기준", "적정", "범위", "판단", "높", "낮", "초과", "미만"]
            )
            and not any(
                word in clean
                for word in [
                    "병",
                    "병해충",
                    "해충",
                    "곰팡이",
                    "방제",
                    "조치",
                    "원인",
                    "증상",
                ]
            )
        )


db = TomatoDatabase(settings.excel_path, settings.sqlite_path)
db.build()
kb = ChromaKnowledgeBase(
    settings.chroma_path,
    settings.chroma_collection,
    settings.use_semantic_search,
    settings.use_reranker,
    settings.embedding_model,
    settings.reranker_model,
    settings.retrieval_candidate_k,
)
llm = LangChainOpenRouterClient(
    settings.openrouter_api_key, settings.model_candidates, settings.openrouter_base_url
)
router = LangChainSmartFarmRouter(db, kb, llm)

app = FastAPI(title="SmartFarm Tomato Chatbot", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://192.168.0.76:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root() -> Dict[str, str]:
    return {
        "message": "SmartFarm Tomato Chatbot API",
        "docs": "/docs",
        "chat": "POST /api/chat",
    }


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "sqlite_path": str(settings.sqlite_path),
        "chroma_path": str(settings.chroma_path),
        "openrouter_configured": llm.available,
        "openrouter_base_url": settings.openrouter_base_url,
        "openrouter_model": settings.openrouter_model,
        "openrouter_models": settings.model_candidates,
        "llm_client": "LangChain ChatOpenAI",
        "chain_orchestration": "LangChain RunnableLambda pipeline",
        "chain_steps": [
            "route",
            "sql_context",
            "rag_context",
            "llm_or_fallback",
            "response",
        ],
        "llm_timeout_seconds": settings.llm_timeout_seconds,
        "semantic_search": settings.use_semantic_search,
        "embedding_model": settings.embedding_model,
        "reranker_enabled": settings.use_reranker,
        "reranker_model": settings.reranker_model,
        "retrieval_candidate_k": settings.retrieval_candidate_k,
    }


@app.post("/api/chat", response_model=ChatResponse)
def chat(payload: ChatRequest) -> ChatResponse:
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="질문을 입력해 주세요.")
    return router.answer(question, use_llm=payload.use_llm)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("smartfarm_chatbot:app", host="127.0.0.1", port=8000, reload=True)