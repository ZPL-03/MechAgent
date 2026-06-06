"""知识库索引测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts import build_knowledge as build_knowledge_script
from scripts import index_knowledge as index_knowledge_script

from mechagent.knowledge import build_index, query_index, standardize_documents


def test_build_and_query_knowledge_index(tmp_path: Path) -> None:
    source_dir = tmp_path / "external"
    source_dir.mkdir()
    (source_dir / "beam.md").write_text(
        "悬臂梁 端点载荷 Euler Bernoulli 挠度 解析解",
        encoding="utf-8",
    )
    index_path = tmp_path / "index.jsonl"

    count = build_index(source_dir, index_path)
    hits = query_index(index_path, "悬臂梁", top_k=1)

    assert count == 1
    assert len(hits) == 1
    assert hits[0].doc_id == "beam::chunk_1"


def test_hybrid_retriever_handles_chinese_without_spaces(tmp_path: Path) -> None:
    source_dir = tmp_path / "external"
    source_dir.mkdir()
    (source_dir / "beam.md").write_text(
        "悬臂梁端点载荷Euler-Bernoulli挠度解析解",
        encoding="utf-8",
    )
    (source_dir / "plate.md").write_text(
        "四边简支矩形薄板均布载荷弯曲Navier级数",
        encoding="utf-8",
    )
    index_path = tmp_path / "index.jsonl"
    build_index(source_dir, index_path)

    hits = query_index(index_path, "薄板弯曲", top_k=1)

    assert len(hits) == 1
    assert hits[0].doc_id == "plate::chunk_1"


def test_build_index_rejects_invalid_overlap(tmp_path: Path) -> None:
    source_dir = tmp_path / "external"
    index_path = tmp_path / "index.jsonl"

    try:
        build_index(source_dir, index_path, chunk_size=10, chunk_overlap=10)
    except ValueError as exc:
        assert "chunk_overlap" in str(exc)
    else:
        raise AssertionError("非法 chunk_overlap 必须抛出 ValueError。")


def test_build_index_rejects_missing_source_dir(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        build_index(tmp_path / "missing", tmp_path / "index.jsonl")


def test_build_index_rejects_empty_source_dir(tmp_path: Path) -> None:
    source_dir = tmp_path / "external"
    source_dir.mkdir()

    with pytest.raises(ValueError, match="不包含可索引文档"):
        build_index(source_dir, tmp_path / "index.jsonl")


def test_build_index_rejects_documents_without_indexable_text(tmp_path: Path) -> None:
    source_dir = tmp_path / "external"
    source_dir.mkdir()
    (source_dir / "empty.md").write_text("  \n\t", encoding="utf-8")

    with pytest.raises(ValueError, match="未生成可索引文本块"):
        build_index(source_dir, tmp_path / "index.jsonl")


def test_query_index_rejects_queries_without_searchable_tokens(tmp_path: Path) -> None:
    index_path = tmp_path / "index.jsonl"
    index_path.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="可检索词元"):
        query_index(index_path, "!!!", top_k=1)


def test_query_index_rejects_empty_index_file(tmp_path: Path) -> None:
    index_path = tmp_path / "index.jsonl"
    index_path.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="索引为空"):
        query_index(index_path, "悬臂梁", top_k=1)


def test_query_index_reports_empty_required_fields(tmp_path: Path) -> None:
    index_path = tmp_path / "index.jsonl"
    index_path.write_text(
        '{"doc_id": "doc::chunk_1", "source": "doc.md", "text": ""}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="字段不能为空: text"):
        query_index(index_path, "悬臂梁", top_k=1)


def test_query_index_reports_invalid_jsonl_line(tmp_path: Path) -> None:
    index_path = tmp_path / "index.jsonl"
    index_path.write_text("{bad json", encoding="utf-8")

    with pytest.raises(ValueError, match="第 1 行不是合法 JSON"):
        query_index(index_path, "悬臂梁", top_k=1)


def test_query_index_reports_non_object_jsonl_line(tmp_path: Path) -> None:
    index_path = tmp_path / "index.jsonl"
    index_path.write_text('["doc"]', encoding="utf-8")

    with pytest.raises(ValueError, match="第 1 行必须是 JSON 对象"):
        query_index(index_path, "悬臂梁", top_k=1)


def test_query_index_reports_missing_required_fields(tmp_path: Path) -> None:
    index_path = tmp_path / "index.jsonl"
    index_path.write_text('{"doc_id": "doc::chunk_1", "text": "悬臂梁"}', encoding="utf-8")

    with pytest.raises(ValueError, match="缺少字段: source"):
        query_index(index_path, "悬臂梁", top_k=1)


def test_query_index_rejects_non_finite_weights(tmp_path: Path) -> None:
    index_path = tmp_path / "index.jsonl"
    index_path.write_text(
        '{"doc_id": "doc::chunk_1", "source": "doc.md", "text": "悬臂梁"}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="有限数值"):
        query_index(index_path, "悬臂梁", bm25_weight=float("nan"), tfidf_weight=0.45)


def test_standardize_documents_uses_relative_stable_names(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    nested_dir = source_dir / "beam"
    nested_dir.mkdir(parents=True)
    (nested_dir / "case.TXT").write_text("悬臂梁资料", encoding="utf-8")
    output_dir = tmp_path / "external"

    count = standardize_documents(source_dir.resolve(), output_dir)

    assert count == 1
    assert (output_dir / "beam_case.md").exists()


def test_standardize_documents_rejects_missing_source_dir(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        standardize_documents(tmp_path / "missing", tmp_path / "external")


def test_standardize_documents_rejects_empty_source_dir(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    source_dir.mkdir()

    with pytest.raises(ValueError, match="不包含可标准化文档"):
        standardize_documents(source_dir, tmp_path / "external")


def test_standardize_documents_keeps_colliding_names_unique(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw"
    (source_dir / "beam").mkdir(parents=True)
    (source_dir / "beam" / "case.txt").write_text("nested", encoding="utf-8")
    (source_dir / "beam_case.txt").write_text("flat", encoding="utf-8")
    output_dir = tmp_path / "external"

    count = standardize_documents(source_dir, output_dir)

    assert count == 2
    names = sorted(path.name for path in output_dir.glob("*.md"))
    assert names == ["beam_case.md", "beam_case_2.md"]
    contents = [path.read_text(encoding="utf-8") for path in sorted(output_dir.glob("*.md"))]
    assert "nested" in "\n".join(contents)
    assert "flat" in "\n".join(contents)


def test_build_index_uses_relative_doc_ids_for_nested_files(tmp_path: Path) -> None:
    source_dir = tmp_path / "external"
    (source_dir / "beam").mkdir(parents=True)
    (source_dir / "plate").mkdir(parents=True)
    (source_dir / "beam" / "case.md").write_text("悬臂梁 端点载荷", encoding="utf-8")
    (source_dir / "plate" / "case.md").write_text("矩形板 均布压力", encoding="utf-8")
    index_path = tmp_path / "index.jsonl"

    count = build_index(source_dir, index_path)

    assert count == 2
    text = index_path.read_text(encoding="utf-8")
    assert "beam_case::chunk_1" in text
    assert "plate_case::chunk_1" in text


def test_build_knowledge_script_uses_configured_paths(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "beam.txt").write_text("悬臂梁资料", encoding="utf-8")
    external_dir = tmp_path / "external"
    config_path = tmp_path / "mechagent.yaml"
    config_path.write_text(
        f"""
knowledge:
  raw_dir: {raw_dir.as_posix()}
  external_dir: {external_dir.as_posix()}
  index_path: {(tmp_path / "index.jsonl").as_posix()}
""".strip(),
        encoding="utf-8",
    )

    result = build_knowledge_script.main(["--config", str(config_path)])

    assert result == 0
    assert (external_dir / "beam.md").exists()


def test_index_knowledge_script_uses_configured_chunk_settings(tmp_path: Path) -> None:
    external_dir = tmp_path / "external"
    external_dir.mkdir()
    (external_dir / "beam.md").write_text("abcdefghij", encoding="utf-8")
    index_path = tmp_path / "index.jsonl"
    config_path = tmp_path / "mechagent.yaml"
    config_path.write_text(
        f"""
knowledge:
  raw_dir: {(tmp_path / "raw").as_posix()}
  external_dir: {external_dir.as_posix()}
  index_path: {index_path.as_posix()}
  chunk_size: 5
  chunk_overlap: 0
""".strip(),
        encoding="utf-8",
    )

    result = index_knowledge_script.main(["--config", str(config_path)])

    assert result == 0
    lines = index_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
