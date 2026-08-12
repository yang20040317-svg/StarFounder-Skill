from pathlib import Path

import pytest

# 知识库物理目录，测试在此写入临时卡片并清理，避免污染真实条目。
_KB = Path(__file__).resolve().parent.parent / "knowledge" / "L1-principles"


def _write_card(slug: str, body: str) -> dict:
    """写入一张临时 L1 卡片到知识库目录，返回对应的索引 entry。"""
    path = _KB / f"{slug}.md"
    path.write_text(
        "# 临时卡片\n\n"
        "- **领域**: general\n- **类型**: principle\n- **状态**: active\n\n---\n\n"
        f"## 核心内容\n\n{body}\n",
        encoding="utf-8",
    )
    return {"title": slug, "layer": "L1-principles", "slug": slug, "type": "principle", "status": "active"}


def _cleanup(slug: str):
    path = _KB / f"{slug}.md"
    if path.exists():
        path.unlink()


@pytest.fixture
def temp_slug():
    slug = "_test_fulfillment_tmp"
    yield slug
    _cleanup(slug)


def test_rich_card_scores_high(learn_module, temp_slug):
    """实质内容充实的卡片应得到较高充实度。"""
    body = (
        "处理用户输入前必须校验类型与边界，避免越权访问与注入风险。"
        "校验失败应返回结构化错误而非裸异常。所有外部调用需带超时与重试。"
    )
    entry = _write_card(temp_slug, body)
    result = learn_module.score_content_fulfillment(entry)

    assert result["score"] >= 70
    assert not result["hollow"]
    assert result["placeholder_hits"] == []


def test_placeholder_card_is_penalized(learn_module, temp_slug):
    """含模板腔占位短语的卡片应被扣分并标记命中。"""
    body = (
        "### 参数\n\n由模板中的变量和配置项决定\n\n"
        "### 返回值\n\n由代码片段实际执行结果决定。\n"
    )
    entry = _write_card(temp_slug, body)
    result = learn_module.score_content_fulfillment(entry)

    assert len(result["placeholder_hits"]) >= 1
    assert result["score"] < 70


def test_hollow_card_flagged(learn_module, temp_slug):
    """内容极度单薄且无实质描述的卡片应判为空洞。"""
    body = "待补充"
    entry = _write_card(temp_slug, body)
    result = learn_module.score_content_fulfillment(entry)

    assert result["hollow"] is True
    assert result["score"] < learn_module.HOLLOW_SCORE_THRESHOLD


def test_audit_aggregates_metrics(learn_module, temp_slug):
    """批量审计应产出平均充实度、空洞率与占位填充率。"""
    rich = _write_card(temp_slug, "校验用户输入类型与边界，失败返回结构化错误，外部调用带超时重试。")
    hollow = {
        "title": "_hollow",
        "layer": "L1-principles",
        "slug": "_hollow",
        "type": "principle",
        "status": "active",
    }
    # 构造一张不落盘的空心卡片：直接评估占位 body 通过临时文件
    _write_card("_hollow", "由模板中的变量和配置项决定")
    try:
        audit = learn_module.audit_content_fulfillment([rich, hollow])
        assert audit["count"] == 2
        assert 0 <= audit["avg_score"] <= 100
        assert 0 <= audit["hollow_rate"] <= 100
        assert 0 <= audit["placeholder_rate"] <= 100
        assert len(audit["worst"]) <= 5
    finally:
        _cleanup("_hollow")


def test_empty_library(learn_module):
    """无活跃卡片时审计返回空聚合，不抛错。"""
    audit = learn_module.audit_content_fulfillment([])
    assert audit["count"] == 0
    assert audit["avg_score"] == 0
