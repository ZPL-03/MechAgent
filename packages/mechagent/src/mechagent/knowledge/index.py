"""本地混合知识库索引。"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class KnowledgeHit:
    """知识库检索命中结果。

    Args:
        doc_id: 文档块标识。
        source: 来源文件。
        score: 检索得分。
        text: 文本内容。

    Returns:
        KnowledgeHit: 检索命中结果。

    Raises:
        TypeError: 当字段类型不匹配时由 dataclass 构造阶段抛出。

    Example:
        >>> KnowledgeHit("a::chunk_1", "a.md", 1.0, "text")
        KnowledgeHit(doc_id='a::chunk_1', source='a.md', score=1.0, text='text')
    """

    doc_id: str
    source: str
    score: float
    text: str


def build_index(
    source_dir: Path,
    index_path: Path,
    chunk_size: int = 1200,
    chunk_overlap: int = 120,
) -> int:
    """构建本地 JSONL 文本块索引。

    Args:
        source_dir: Markdown、TXT、JSON 文档目录。
        index_path: JSONL 索引输出路径。
        chunk_size: 每个文本块最大字符数。
        chunk_overlap: 相邻文本块重叠字符数。

    Returns:
        int: 写入的文本块数量。

    Raises:
        FileNotFoundError: 当知识源目录不存在时抛出。
        ValueError: 当知识源目录为空或文档没有可索引文本时抛出。
        OSError: 当目录读取或索引写入失败时抛出。

    Example:
        >>> build_index(Path("knowledge/external"), Path("knowledge/index.jsonl"))
        2
    """

    if chunk_size <= 0:
        msg = "chunk_size 必须为正整数。"
        raise ValueError(msg)
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        msg = "chunk_overlap 必须位于 [0, chunk_size) 区间。"
        raise ValueError(msg)

    if not source_dir.exists():
        raise FileNotFoundError(source_dir)
    documents = sorted(_iter_documents(source_dir))
    if not documents:
        msg = f"知识源目录不包含可索引文档: {source_dir}"
        raise ValueError(msg)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str]] = []
    for path in documents:
        text = _read_document(path)
        document_id = _document_id(source_dir, path)
        for idx, chunk in enumerate(_chunk_text(text, chunk_size, chunk_overlap), start=1):
            rows.append(
                {
                    "doc_id": f"{document_id}::chunk_{idx}",
                    "source": str(path),
                    "text": chunk,
                }
            )
    if not rows:
        msg = f"知识源目录未生成可索引文本块: {source_dir}"
        raise ValueError(msg)
    index_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows),
        encoding="utf-8",
    )
    return len(rows)


def query_index(
    index_path: Path,
    query: str,
    top_k: int = 5,
    bm25_weight: float = 0.55,
    tfidf_weight: float = 0.45,
) -> list[KnowledgeHit]:
    """使用 BM25 与 TF-IDF 余弦融合检索本地索引。

    Args:
        index_path: JSONL 索引路径。
        query: 查询文本。
        top_k: 返回数量。
        bm25_weight: BM25 归一化得分权重。
        tfidf_weight: TF-IDF 余弦归一化得分权重。

    Returns:
        list[KnowledgeHit]: 检索命中结果。

    Raises:
        ValueError: 当查询为空或 top_k 非正时抛出。
        FileNotFoundError: 当索引文件不存在时抛出。

    Example:
        >>> query_index(Path("knowledge/index.jsonl"), "屈曲", top_k=3)
        []
    """

    if not query.strip():
        msg = "query 不能为空。"
        raise ValueError(msg)
    if top_k <= 0:
        msg = "top_k 必须为正整数。"
        raise ValueError(msg)
    if not math.isfinite(bm25_weight) or not math.isfinite(tfidf_weight):
        msg = "检索权重必须为有限数值。"
        raise ValueError(msg)
    if bm25_weight < 0 or tfidf_weight < 0 or bm25_weight + tfidf_weight <= 0:
        msg = "检索权重必须为非负数，且权重和必须大于 0。"
        raise ValueError(msg)
    query_terms = _tokenize(query)
    if not query_terms:
        msg = "query 必须包含可检索词元。"
        raise ValueError(msg)
    if not index_path.exists():
        raise FileNotFoundError(index_path)

    rows = _load_rows(index_path)
    if not rows:
        msg = f"知识库索引为空: {index_path}"
        raise ValueError(msg)
    tokenized_docs = [_tokenize(str(row["text"])) for row in rows]
    bm25_scores = _bm25_scores(tokenized_docs, query_terms)
    tfidf_scores = _tf_idf_cosine_scores(tokenized_docs, query_terms)
    scores = _fuse_scores(
        bm25_scores,
        tfidf_scores,
        bm25_weight=bm25_weight,
        tfidf_weight=tfidf_weight,
    )

    hits = []
    for row, score in zip(rows, scores):
        if score > 0:
            hits.append(
                KnowledgeHit(
                    doc_id=str(row["doc_id"]),
                    source=str(row["source"]),
                    score=score,
                    text=str(row["text"]),
                )
            )
    return sorted(hits, key=lambda item: item.score, reverse=True)[:top_k]


def _load_rows(index_path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line_number, line in enumerate(
        index_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            msg = f"知识库索引第 {line_number} 行不是合法 JSON。"
            raise ValueError(msg) from exc
        if not isinstance(raw, dict):
            msg = f"知识库索引第 {line_number} 行必须是 JSON 对象。"
            raise ValueError(msg)
        missing = [key for key in ("doc_id", "source", "text") if key not in raw]
        if missing:
            msg = f"知识库索引第 {line_number} 行缺少字段: {', '.join(missing)}。"
            raise ValueError(msg)
        doc_id = str(raw["doc_id"])
        source = str(raw["source"])
        text = str(raw["text"])
        empty_fields = [
            field_name
            for field_name, value in (("doc_id", doc_id), ("source", source), ("text", text))
            if not value.strip()
        ]
        if empty_fields:
            msg = f"知识库索引第 {line_number} 行字段不能为空: {', '.join(empty_fields)}。"
            raise ValueError(msg)
        rows.append(
            {
                "doc_id": doc_id,
                "source": source,
                "text": text,
            }
        )
    return rows


def _iter_documents(source_dir: Path) -> list[Path]:
    suffixes = {".md", ".txt", ".json"}
    return [
        path for path in source_dir.rglob("*") if path.is_file() and path.suffix.lower() in suffixes
    ]


def _read_document(path: Path) -> str:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        return json.dumps(data, ensure_ascii=False)
    return path.read_text(encoding="utf-8")


def _document_id(source_dir: Path, path: Path) -> str:
    relative = path.relative_to(source_dir).with_suffix("")
    return "_".join(part for part in relative.parts if part not in {".", ".."})


def _chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    chunks = []
    step = chunk_size - chunk_overlap
    for index in range(0, len(normalized), step):
        chunk = normalized[index : index + chunk_size]
        if chunk:
            chunks.append(chunk)
    return chunks


def _tokenize(text: str) -> list[str]:
    fragments = re.findall(r"[a-zA-Z][a-zA-Z0-9_+\-.]*|\d+(?:\.\d+)?|[\u4e00-\u9fff]+", text)
    tokens: list[str] = []
    for fragment in fragments:
        lowered = fragment.lower()
        if re.fullmatch(r"[\u4e00-\u9fff]+", lowered):
            tokens.extend(_chinese_ngrams(lowered))
        else:
            tokens.append(lowered)
    return tokens


def _chinese_ngrams(text: str) -> list[str]:
    tokens = list(text)
    for width in (2, 3):
        if len(text) >= width:
            tokens.extend(text[index : index + width] for index in range(len(text) - width + 1))
    return tokens


def _document_frequency(tokenized_docs: Iterable[list[str]]) -> dict[str, int]:
    doc_freq: dict[str, int] = {}
    for tokens in tokenized_docs:
        for term in set(tokens):
            doc_freq[term] = doc_freq.get(term, 0) + 1
    return doc_freq


def _bm25_scores(
    tokenized_docs: list[list[str]],
    query_terms: list[str],
    k1: float = 1.5,
    b: float = 0.75,
) -> list[float]:
    doc_count = len(tokenized_docs)
    if doc_count == 0 or not query_terms:
        return [0.0 for _ in tokenized_docs]
    doc_freq = _document_frequency(tokenized_docs)
    avg_len = sum(len(tokens) for tokens in tokenized_docs) / doc_count
    scores = []
    for tokens in tokenized_docs:
        if not tokens:
            scores.append(0.0)
            continue
        counts = Counter(tokens)
        doc_len = len(tokens)
        score = 0.0
        for term in query_terms:
            freq = counts.get(term, 0)
            if freq == 0:
                continue
            df = doc_freq.get(term, 0)
            idf = math.log(1.0 + (doc_count - df + 0.5) / (df + 0.5))
            denom = freq + k1 * (1.0 - b + b * doc_len / avg_len)
            score += idf * freq * (k1 + 1.0) / denom
        scores.append(score)
    return scores


def _tf_idf_cosine_scores(
    tokenized_docs: list[list[str]],
    query_terms: list[str],
) -> list[float]:
    doc_count = len(tokenized_docs)
    if doc_count == 0 or not query_terms:
        return [0.0 for _ in tokenized_docs]
    doc_freq = _document_frequency(tokenized_docs)
    query_vector = _tf_idf_vector(query_terms, doc_freq, doc_count)
    query_norm = _vector_norm(query_vector)
    scores = []
    for tokens in tokenized_docs:
        doc_vector = _tf_idf_vector(tokens, doc_freq, doc_count)
        denom = _vector_norm(doc_vector) * query_norm
        score = 0.0 if denom == 0 else _dot(doc_vector, query_vector) / denom
        scores.append(score)
    return scores


def _tf_idf_vector(
    tokens: list[str],
    doc_freq: dict[str, int],
    doc_count: int,
) -> dict[str, float]:
    counts = Counter(tokens)
    token_count = len(tokens)
    if token_count == 0:
        return {}
    return {
        term: (freq / token_count) * (math.log((doc_count + 1) / (doc_freq.get(term, 0) + 1)) + 1.0)
        for term, freq in counts.items()
    }


def _dot(left: dict[str, float], right: dict[str, float]) -> float:
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(term, 0.0) for term, value in left.items())


def _vector_norm(vector: dict[str, float]) -> float:
    return math.sqrt(sum(value * value for value in vector.values()))


def _fuse_scores(
    bm25_scores: list[float],
    tfidf_scores: list[float],
    bm25_weight: float,
    tfidf_weight: float,
) -> list[float]:
    weight_sum = bm25_weight + tfidf_weight
    bm25_norm = _normalize_scores(bm25_scores)
    tfidf_norm = _normalize_scores(tfidf_scores)
    return [
        (bm25_weight * bm25 + tfidf_weight * tfidf) / weight_sum
        for bm25, tfidf in zip(bm25_norm, tfidf_norm)
    ]


def _normalize_scores(scores: list[float]) -> list[float]:
    max_score = max(scores, default=0.0)
    if max_score <= 0:
        return [0.0 for _ in scores]
    return [score / max_score for score in scores]
