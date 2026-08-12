from pathlib import Path
from unittest.mock import patch

import pytest


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_scan_gate_passes_high_quality_template(learn_module):
    """
    带完整决策字段与充实正文的 template 应通过 scan gate。
    """
    content = (FIXTURE_DIR / "template-sample.md").read_text(encoding="utf-8")
    md_file = Path("/fake/template-sample.md")

    passed, reasons = learn_module._scan_gate(md_file, content, "template-sample")

    templates = [a for a in passed if a["type"] == "template"]
    assert len(templates) == 1
    assert templates[0].get("decision_complete") is True
    assert not reasons


def test_scan_gate_blocks_bare_code_snapshot(learn_module):
    """
    只有裸函数 + 标题、无决策上下文的代码块属于「代码快照」，
    scan gate 应阻止其进入知识库。
    """
    content = (
        "# 工具函数\n\n"
        "## 数据清洗函数\n\n"
        "```python\n"
        "def clean_data(rows):\n"
        "    result = []\n"
        "    for row in rows:\n"
        "        if row:\n"
        "            result.append(row.strip())\n"
        "    return result\n"
        "```\n"
    )
    md_file = Path("/fake/bare-function.md")

    passed, reasons = learn_module._scan_gate(md_file, content, "bare-function")

    assert not passed
    assert any("缺少决策字段" in r for r in reasons)


def test_scan_gate_blocks_hollow_principle(learn_module):
    """
    正文仅为占位腔、无实质信息的 principle 不应通过 scan gate。
    """
    content = "## 设计原理\n\n待补充更多内容，此处先占位。\n"
    md_file = Path("/fake/hollow-principle.md")

    passed, reasons = learn_module._scan_gate(md_file, content, "hollow-principle")

    assert not passed
    assert any("未达门槛" in r or "占位" in r for r in reasons)


def test_precheck_reports_pass_and_block(learn_module, tmp_path, monkeypatch):
    """
    precheck 命令应全量复核扫描根下的 MD，输出通过/拦截报告，不写入知识库。
    """
    good_md = tmp_path / "good.md"
    good_md.write_text(
        (
            FIXTURE_DIR / "template-sample.md"
        ).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    bad_md = tmp_path / "bad.md"
    bad_md.write_text(
        "# 占位\n\n## 空洞原则\n\n待补充更多内容，此处先占位。\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(learn_module, "_get_scan_roots", lambda workspace=None: [tmp_path])
    monkeypatch.setattr(
        learn_module, "_scan_md_files", lambda roots: sorted([good_md, bad_md])
    )

    report = learn_module.cmd_precheck()

    assert "✅ 会通过：1 个" in report
    assert "🚫 会被拦截：1 个" in report
    assert "bad.md" in report
    assert "good.md" in report


def test_scan_gate_blocks_hollow_even_with_valid_template(
    learn_module, tmp_path, monkeypatch
):
    """
    同一个 MD 里若同时有高质量 template 和空洞 principle，
    gate 应只放行高质量 template，丢弃空洞 principle。
    """
    good_template = (
        FIXTURE_DIR / "template-sample.md"
    ).read_text(encoding="utf-8")
    content = good_template + "\n\n## 空洞原则\n\n待补充更多内容，此处先占位。\n"
    md_file = tmp_path / "mixed.md"
    md_file.write_text(content, encoding="utf-8")

    passed, reasons = learn_module._scan_gate(md_file, content, "mixed")

    assert any(a["type"] == "template" for a in passed)
    assert not any(a.get("title", "").startswith("空洞原则") for a in passed)
    # mixed 文件中 principle 被原始提取规则过滤，不进入 passed
