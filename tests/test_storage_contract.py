from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("ktype", "directory"),
    [
        ("checklist", "checklists"),
        ("framework", "frameworks"),
        ("pattern", "frameworks"),
        ("decision", "frameworks"),
        ("pitfall", "pitfalls"),
        ("template", "templates"),
    ],
)
def test_l2_asset_type_resolves_to_classified_directory(
    learn_module, monkeypatch, tmp_path: Path, ktype: str, directory: str
):
    """
    L2 的逻辑层保持稳定，但物理文件必须按资产族分类，避免根目录混存。
    """
    monkeypatch.setitem(learn_module.LAYER_DIRS, "L2-assets", tmp_path / "L2-assets")

    path = learn_module.resolve_knowledge_card_path("L2-assets", "sample", ktype)

    assert path == tmp_path / "L2-assets" / directory / "sample.md"


def test_write_l2_card_creates_only_classified_directory(
    learn_module, monkeypatch, tmp_path: Path
):
    """
    写入接口必须执行目录契约，而不是依赖调用方自行拼接路径。
    """
    l2_root = tmp_path / "L2-assets"
    monkeypatch.setitem(learn_module.LAYER_DIRS, "L2-assets", l2_root)

    path = learn_module.write_knowledge_card(
        layer="L2-assets",
        slug="retry-pitfall",
        title="重试陷阱",
        domain="backend",
        ktype="pitfall",
        source_project="fixture",
        content="### 陷阱\n\n无限重试会放大故障。\n\n### 绕过方案\n\n限制次数并使用退避。",
    )

    assert path == l2_root / "pitfalls" / "retry-pitfall.md"
    assert path.is_file()
    assert not list(l2_root.glob("*.md"))


def test_l2_root_has_no_flat_markdown_cards(learn_module):
    """
    真实知识库必须满足文档声明的分类目录契约。
    """
    l2_root = learn_module.LAYER_DIRS["L2-assets"]

    assert not list(l2_root.glob("*.md"))
    assert {path.name for path in l2_root.iterdir() if path.is_dir()} == {
        "checklists",
        "frameworks",
        "pitfalls",
        "templates",
    }

    for entry in learn_module.load_index()["entries"]:
        if entry["layer"] != "L2-assets" or entry["status"] != "active":
            continue
        path = learn_module.resolve_knowledge_card_path(
            entry["layer"], entry["slug"], entry["type"]
        )
        assert path.is_file(), f"索引条目缺少分类资产文件: {entry['slug']}"
