from pathlib import Path

import pytest

# L2 模板物理目录，测试在此写入临时卡片并清理。
_TPL_DIR = Path(__file__).resolve().parent.parent / "knowledge" / "L2-assets" / "templates"


def _write_template(slug: str, body: str) -> dict:
    """写入一张临时模板卡片，返回对应索引 entry。"""
    path = _TPL_DIR / f"{slug}.md"
    path.write_text(
        "# 临时模板\n\n"
        "- **领域**: general\n- **类型**: template\n- **状态**: active\n\n---\n\n"
        f"## 核心内容\n\n{body}\n",
        encoding="utf-8",
    )
    return {
        "id": slug,
        "title": slug,
        "layer": "L2-assets",
        "slug": slug,
        "type": "template",
        "status": "active",
    }


def _cleanup(*slugs: str):
    for s in slugs:
        p = _TPL_DIR / f"{s}.md"
        if p.exists():
            p.unlink()


@pytest.fixture
def dup_pair():
    a = "tpl_dup_a"
    b = "tpl_dup_b"
    body_a = "FROM node:18\nRUN npm install\nCOPY . /app\nCMD [\"npm\", \"start\"]\n用于构建 Node 服务镜像的 Dockerfile 模板，固定基础版本便于复现。"
    body_b = "FROM node:18\nRUN npm install\nCOPY . /app\nCMD [\"npm\", \"start\"]\n构建 Node 服务镜像的 Dockerfile 模板，固定基础版本以复现环境。"
    ea, eb = _write_template(a, body_a), _write_template(b, body_b)
    yield [ea, eb]
    _cleanup(a, b)


def test_near_duplicate_pair_detected(learn_module, dup_pair):
    """高度相似的同主题模板应被检测为疑似重复。"""
    dups = learn_module.detect_template_duplicates(dup_pair)
    assert len(dups) == 1
    assert dups[0]["score"] >= learn_module.TEMPLATE_DUP_THRESHOLD


def test_distinct_templates_not_flagged(learn_module):
    """主题完全不同的模板不应被判为重复。"""
    a = _write_template("tpl_distinct_a", "FROM python:3.11\nRUN pip install flask\n用于 Python Web 服务镜像。")
    b = _write_template("tpl_distinct_b", "version: '3'\nservices:\n  db:\n    image: postgres\n用于本地数据库编排的 docker-compose 模板。")
    try:
        dups = learn_module.detect_template_duplicates([a, b])
        assert dups == []
    finally:
        _cleanup("tpl_distinct_a", "tpl_distinct_b")


def test_non_template_entries_excluded(learn_module):
    """非 template 类型条目不参与模板去重比对。"""
    entry = {
        "id": "p1", "title": "p1", "layer": "L1-principles",
        "slug": "p1", "type": "principle", "status": "active",
    }
    dups = learn_module.detect_template_duplicates([entry, entry])
    assert dups == []


def test_retired_entries_excluded(learn_module, dup_pair):
    """已退役的模板不参与比对。"""
    dup_pair[1]["status"] = "retired"
    dups = learn_module.detect_template_duplicates(dup_pair)
    assert dups == []


def test_fewer_than_two_returns_empty(learn_module):
    """不足两张模板时直接返回空，不抛错。"""
    assert learn_module.detect_template_duplicates([]) == []
    single = {
        "id": "only", "title": "only", "layer": "L2-assets",
        "slug": "only", "type": "template", "status": "active",
    }
    assert learn_module.detect_template_duplicates([single]) == []


def test_threshold_boundary(learn_module):
    """相似度恰好低于阈值的对不应被报告。"""
    a = _write_template("tpl_thr_a", "FROM node:18\nRUN npm ci\n构建 Node 镜像。")
    b = _write_template("tpl_thr_b", "FROM golang:1.22\nRUN go build\n构建 Go 二进制镜像。")
    try:
        dups = learn_module.detect_template_duplicates([a, b])
        assert all(d["score"] < learn_module.TEMPLATE_DUP_THRESHOLD for d in dups)
    finally:
        _cleanup("tpl_thr_a", "tpl_thr_b")


def test_cluster_groups_near_duplicates(learn_module):
    """三张互相似的模板应聚成一个簇，而非三对两两报告。"""
    b1 = "FROM node:18\nRUN npm install\nCOPY . /app\nCMD [\"npm\",\"start\"]\n构建 Node 服务镜像的 Dockerfile 模板，固定基础版本便于复现。"
    b2 = "FROM node:18\nRUN npm install\nCOPY . /app\nCMD [\"npm\",\"start\"]\n用于构建 Node 服务镜像的 Dockerfile 模板，固定基础版本以复现环境。"
    b3 = "FROM node:18\nRUN npm install\nCOPY . /app\nCMD [\"npm\",\"start\"]\nNode 服务镜像的 Dockerfile 模板，固定基础版本保证可复现构建。"
    e1, e2, e3 = _write_template("tpl_cl_a", b1), _write_template("tpl_cl_b", b2), _write_template("tpl_cl_c", b3)
    try:
        clusters = learn_module.cluster_template_duplicates([e1, e2, e3])
        assert len(clusters) == 1
        assert clusters[0]["size"] == 3
        assert clusters[0]["max_score"] >= learn_module.TEMPLATE_DUP_HIGH_CONFIDENCE
    finally:
        _cleanup("tpl_cl_a", "tpl_cl_b", "tpl_cl_c")


def test_cluster_excludes_distinct(learn_module):
    """互不相似的模板不应被聚入同一簇。"""
    e1 = _write_template("tpl_ce_a", "FROM python:3.11\nRUN pip install flask\n用于 Python Web 服务镜像。")
    e2 = _write_template("tpl_ce_b", "version: '3'\nservices:\n  db:\n    image: postgres\n用于本地数据库编排的 compose 模板。")
    try:
        clusters = learn_module.cluster_template_duplicates([e1, e2])
        assert clusters == []
    finally:
        _cleanup("tpl_ce_a", "tpl_ce_b")
