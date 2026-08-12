# -*- coding: utf-8 -*-
"""摄入前查重（治本方案）单元测试。"""
import sys, os
import re
import json
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import learn
from learn import (
    load_index, check_ingest_duplicates, find_entry_by_id,
    _load_card_body, _similarity_tokens_from_content, _similarity_tokens_from_entry,
    INGEST_DEDUP_THRESHOLD, _make_unique_slug, _resolve_same_title_collision,
    _link_same_title, add_to_index, _cluster_same_title_families, RELATION_SAME_TITLE,
)
import pytest


def _setup_isolated_template_index(tmp_path, monkeypatch):
    """创建只含一张 active template 的临时知识库，并 monkeypatch 到 learn 模块。"""
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    index_path = knowledge_dir / "index.json"
    index = {"entries": [], "domains": {}, "types": {}, "totalKnowledge": 1}

    layer_dir = knowledge_dir / "L2-assets" / "templates"
    layer_dir.mkdir(parents=True)
    slug = "test-existing-template"
    card_path = layer_dir / f"{slug}.md"
    body = "## 核心内容\n\n用装饰器在 API 入口处做 QPS 限流，超出阈值直接返回 429。"
    card_path.write_text(f"# 测试模板\n\n{body}\n", encoding="utf-8")

    now = datetime.now(timezone.utc).isoformat()
    entry = {
        "id": "test-tmpl-001",
        "title": "测试模板",
        "domain": "backend",
        "type": "template",
        "layer": "L2-assets",
        "slug": slug,
        "sourceProject": "test",
        "tags": [],
        "version": 1,
        "weight": 10,
        "iterationCount": 0,
        "crossRefs": [],
        "createdAt": now,
        "updatedAt": now,
        "lastReferencedAt": now,
        "status": "active",
    }
    index["entries"].append(entry)
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

    monkeypatch.setattr(learn, "KNOWLEDGE_DIR", knowledge_dir)
    monkeypatch.setattr(learn, "INDEX_PATH", index_path)
    monkeypatch.setattr(learn, "LAYER_DIRS", {
        "L1-principles": knowledge_dir / "L1-principles",
        "L2-assets": knowledge_dir / "L2-assets",
        "L3-classified": knowledge_dir / "L3-classified",
        "L4-iterations": knowledge_dir / "L4-iterations",
        "L5-retired": knowledge_dir / "L5-retired",
    })
    monkeypatch.setattr(learn, "L2_TYPE_DIRS", {
        "checklist": "checklists",
        "framework": "frameworks",
        "pattern": "frameworks",
        "decision": "frameworks",
        "pitfall": "pitfalls",
        "template": "templates",
    })
    return load_index(), entry


def _first_active_template(index):
    return next(
        e for e in index["entries"]
        if e.get("status") == "active" and e.get("type") == "template"
    )


def _hash_suffix_pattern():
    """旧版哈希孤儿卡的文件名后缀：6 位十六进制（如 -c2f4fd）。"""
    return re.compile(r"-[0-9a-f]{6}$")


def _make_entry(eid, slug, title, content, ktype="pattern"):
    """构造一条 active 索引条目（含核心内容，用于相似度比对）。"""
    return {
        "id": eid,
        "title": title,
        "domain": "backend",
        "type": ktype,
        "layer": "L2-assets",
        "slug": slug,
        "sourceProject": "existing",
        "tags": [],
        "version": 1,
        "weight": 10,
        "iterationCount": 0,
        "crossRefs": [],
        "createdAt": "2026-01-01T00:00:00+00:00",
        "updatedAt": "2026-01-01T00:00:00+00:00",
        "lastReferencedAt": "2026-01-01T00:00:00+00:00",
        "status": "active",
        "content": content,  # 内存侧正文，供相似度口径读取（真实卡由 _load_card_body 读取）
    }


def test_same_title_different_content_links_not_orphans():
    """
    同标题但不同义的卡（如两条「门控函数」）不应炸成哈希孤儿，
    而应保留标题字面（文件名不含随机哈希后缀）并通过 crossRef 互链。
    """
    # 1) slug 碰撞不再追加随机哈希，而是确定性序号。
    existing_slugs = {"gated-function"}
    assert _make_unique_slug("gated-function", existing_slugs) == "gated-function-2"
    assert not _hash_suffix_pattern().search(
        _make_unique_slug("gated-function", existing_slugs)
    )

    # 2) 两条不同义的「门控函数」通过 RELATION_SAME_TITLE 双向互链，且不新建孤儿。
    index = {
        "entries": [
            _make_entry(
                "aaaa1111", "gated-function", "门控函数",
                "## 核心内容\n\n用装饰器在 API 入口处做 QPS 限流，超出阈值直接返回 429。",
            )
        ],
        "domains": {},
        "types": {},
        "totalKnowledge": 1,
    }
    new_item = {
        "title": "门控函数",
        "type": "pattern",
        "domain": "backend",
        "slug": "gated-function-2",  # 由 _make_unique_slug 生成（确定性序号，非哈希）
        "source_project": "new-proj",
        "_raw": {
            "base_slug": "gated-function",
            "content": "## 核心内容\n\n用中间件在请求链路里做鉴权门禁，未带 token 直接拒绝访问。",
        },
    }
    new_id = "bbbb2222"
    action, targets = _resolve_same_title_collision(index, new_item, new_id, source_project="new-proj")

    # 不同义 → 走「linked」（而非 skip/unique），且 slug 无哈希后缀。
    assert action == "linked"
    assert not _hash_suffix_pattern().search(new_item["slug"])
    # 同源目标应包含已有的「门控函数」卡。
    assert any(t["id"] == "aaaa1111" for t in targets)

    # 模拟 cmd_ingest 写盘后建双向关联：新卡入 index 并补 RELATION_SAME_TITLE。
    add_to_index(
        index, knowledge_id=new_id, title=new_item["title"],
        domain=new_item["domain"], ktype=new_item["type"],
        layer="L2-assets", slug=new_item["slug"], source_project="new-proj",
    )
    _link_same_title(index, new_id, targets)

    # 双向关联：新卡指向已有卡，已有卡也指向新卡，且均为 SAME_TITLE 关系。
    new_entry = find_entry_by_id(index, new_id)
    existing = find_entry_by_id(index, "aaaa1111")
    new_links = [c for c in new_entry["crossRefs"] if c["relation"] == RELATION_SAME_TITLE]
    existing_links = [c for c in existing["crossRefs"] if c["relation"] == RELATION_SAME_TITLE]
    assert len(new_links) == 1 and new_links[0]["source"] == "aaaa1111"
    assert len(existing_links) == 1 and existing_links[0]["source"] == new_id


def test_same_title_high_similarity_is_skipped_not_orphaned():
    """
    同标题且高相似（真重复）不应新建，而是归因到已有卡（PREINGEST_DEDUP）。
    """
    index = {
        "entries": [
            _make_entry(
                "cccc3333", "gated-function", "门控函数",
                "## 核心内容\n\n用装饰器在 API 入口处做 QPS 限流，超出阈值直接返回 429。",
            )
        ],
    }
    new_item = {
        "title": "门控函数",
        "type": "pattern",
        "domain": "backend",
        "slug": "gated-function-2",
        "source_project": "new-proj",
        "_raw": {
            "base_slug": "gated-function",
            "content": "## 核心内容\n\n用装饰器在 API 入口处做 QPS 限流，超出阈值就直接返回 429 状态码。",
        },
    }
    action, targets = _resolve_same_title_collision(index, new_item, "dddd4444", source_project="new-proj")
    assert action == "skip"
    existing = find_entry_by_id(index, "cccc3333")
    assert any(c.get("relation") == "PREINGEST_DEDUP" for c in existing.get("crossRefs", []))


def test_same_title_families_clustered_by_dupcheck():
    """
    dupcheck 应能按 RELATION_SAME_TITLE 关联把同源卡家族聚合成簇，
    让同标题不同义的卡（正文相似度 < 阈值）被识别为「需人工归并」。
    """
    index = {
        "entries": [
            _make_entry("e1", "gated-function", "门控函数", "限流装饰器"),
            _make_entry("e2", "gated-function-2", "门控函数", "鉴权中间件"),
            _make_entry("e3", "gated-function-3", "门控函数", "网关路由守卫"),
            _make_entry("e4", "ret-code", "返回码规范", "HTTP 状态码约定"),  # 独立家族
        ],
        "domains": {}, "types": {}, "totalKnowledge": 4,
    }
    # 三条「门控函数」互相关联（模拟入库时双向建链后的结果）。
    for i, j in [("e1", "e2"), ("e2", "e3")]:
        index["entries"][0 if i == "e1" else 1].setdefault("crossRefs", []).append(
            {"source": j, "relation": RELATION_SAME_TITLE, "at": "2026-01-01T00:00:00+00:00"}
        )
        index["entries"][1 if i == "e1" else 2].setdefault("crossRefs", []).append(
            {"source": i, "relation": RELATION_SAME_TITLE, "at": "2026-01-01T00:00:00+00:00"}
        )

    families = _cluster_same_title_families(index["entries"])
    # 应聚出 1 个 3 元簇（门控函数家族），返回码规范不形成簇。
    assert len(families) == 1
    fam = families[0]
    assert fam["size"] == 3
    assert set(fam["ids"]) == {"e1", "e2", "e3"}



def test_high_similarity_is_skipped_and_attributed(tmp_path, monkeypatch):
    """高度相似的待入库项应被跳过新建，并归因到已有卡片。"""
    index, existing = _setup_isolated_template_index(tmp_path, monkeypatch)
    body = _load_card_body(existing)
    new_item = {
        "title": "近似副本模板",
        "type": "template",
        "domain": "backend",
        "source_project": "probe-project",
        "_raw": {"content": body},
    }
    result = check_ingest_duplicates([new_item], index)
    assert len(result["kept"]) == 0
    assert len(result["skipped"]) == 1
    s = result["skipped"][0]
    assert s["score"] >= 0.9
    matched = find_entry_by_id(index, s["matched_id"])
    assert any(c.get("relation") == "PREINGEST_DEDUP" for c in matched.get("crossRefs", []))


def test_low_similarity_is_kept():
    """主题完全不同的待入库项不应被误杀。"""
    index = load_index()
    new_item = {
        "title": "完全无关的新知识",
        "type": "template",
        "domain": "frontend",
        "source_project": "probe-project",
        "_raw": {"content": "## 核心内容\n\n这是一段关于 React 组件状态管理的全新模板，绝对不与任何已有知识重复。"},
    }
    result = check_ingest_duplicates([new_item], index)
    assert len(result["kept"]) == 1
    assert len(result["skipped"]) == 0


def test_threshold_constant_in_high_confidence_range():
    """摄入侧阈值应沿用 dupcheck 高置信基线上沿，确保不误杀不同主题。"""
    assert INGEST_DEDUP_THRESHOLD >= 0.6


def test_token_consistency_between_disk_and_memory(tmp_path, monkeypatch):
    """盘上卡片与内存正文（同一内容）的相似度 token 口径应一致。"""
    index, existing = _setup_isolated_template_index(tmp_path, monkeypatch)
    body = _load_card_body(existing)
    disk_tokens = _similarity_tokens_from_entry(existing)
    mem_tokens = _similarity_tokens_from_content(body, "template")
    assert len(disk_tokens & mem_tokens) == len(disk_tokens)
