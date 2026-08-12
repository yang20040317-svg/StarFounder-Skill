from datetime import datetime, timedelta, timezone


def build_item(title: str, source_project: str = "new-project") -> dict:
    """
    构造迭代检测所需的最小知识条目。
    """
    return {
        "title": title,
        "content": "API 后端服务的稳定性实践",
        "type": "pattern",
        "domain": "backend",
        "slug": "candidate",
        "source_project": source_project,
    }


def test_detect_iterations_covers_four_relations(learn_module, base_entry, empty_index):
    """
    固定标题样例应分别触发 CONFIRM、EXTEND、CONFLICT 与 NEW。
    """
    empty_index["entries"] = [base_entry]
    result = learn_module.detect_iterations(
        [
            build_item("API 服务容错重试策略"),
            build_item("服务容错降级实践"),
            build_item("API 服务不要同步调用"),
            build_item("前端无障碍颜色规范"),
        ],
        empty_index,
    )

    assert len(result["confirmed"]) == 1
    assert len(result["extended"]) == 1
    assert len(result["conflicts"]) == 1
    assert len(result["new_items"]) == 1


def test_confirm_records_cross_ref_and_increases_weight(learn_module, base_entry, empty_index):
    """
    CONFIRM 必须增加权重、刷新引用时间并留下来源关系证据。
    """
    empty_index["entries"] = [base_entry]
    original_reference_time = base_entry["lastReferencedAt"]
    confirmed = [{"item": build_item(base_entry["title"]), "matched_entry": base_entry}]

    logs = learn_module.update_cross_refs(empty_index, confirmed, [], [])

    assert base_entry["weight"] == 12
    assert base_entry["lastReferencedAt"] >= original_reference_time
    assert base_entry["crossRefs"][-1]["relation"] == learn_module.RELATION_CONFIRM
    assert base_entry["crossRefs"][-1]["source"] == "new-project"
    assert len(logs) == 1


def test_extend_updates_cross_ref_weight_version_and_iteration(learn_module, base_entry, empty_index):
    """
    EXTEND 必须同步更新关系、权重、版本和迭代次数。
    """
    empty_index["entries"] = [base_entry]
    extended = [{"item": build_item("API 服务容错重试实践清单"), "matched_entry": base_entry}]

    logs = learn_module.update_cross_refs(empty_index, [], extended, [])

    assert base_entry["weight"] == 11
    assert base_entry["version"] == 2
    assert base_entry["iterationCount"] == 1
    assert base_entry["crossRefs"][-1]["relation"] == learn_module.RELATION_EXTEND
    assert base_entry["crossRefs"][-1]["source"] == "new-project"
    assert len(logs) == 1


def test_weight_decay_uses_30_day_units_and_has_floor(learn_module, base_entry, empty_index):
    """
    权重按完整 30 天衰减且不得低于 1。
    """
    now = datetime(2026, 8, 4, tzinfo=timezone.utc)
    base_entry["weight"] = 4
    base_entry["lastReferencedAt"] = (now - timedelta(days=95)).isoformat()
    empty_index["entries"] = [base_entry]

    logs = learn_module.apply_weight_decay(empty_index, now)

    assert base_entry["weight"] == 1
    assert len(logs) == 1


def test_weight_decay_is_idempotent_within_same_period(learn_module, base_entry, empty_index):
    """
    同一维护周期重复执行不得对同一段未引用时间重复扣权。
    """
    now = datetime(2026, 8, 4, tzinfo=timezone.utc)
    base_entry["lastReferencedAt"] = (now - timedelta(days=65)).isoformat()
    empty_index["entries"] = [base_entry]

    first_logs = learn_module.apply_weight_decay(empty_index, now)
    second_logs = learn_module.apply_weight_decay(empty_index, now)

    assert base_entry["weight"] == 8
    assert len(first_logs) == 1
    assert not second_logs


def test_decay_creates_reachable_retirement_candidate(learn_module, base_entry, empty_index):
    """
    默认权重 10 的旧知识应能经独立维护自然降到退役阈值。
    """
    now = datetime(2026, 8, 4, tzinfo=timezone.utc)
    old_time = now - timedelta(days=151)
    base_entry["createdAt"] = old_time.isoformat()
    base_entry["updatedAt"] = old_time.isoformat()
    base_entry["lastReferencedAt"] = old_time.isoformat()
    base_entry["iterationCount"] = 1
    empty_index["entries"] = [base_entry]

    learn_module.apply_weight_decay(empty_index, now)
    candidates = learn_module.retire_scan(empty_index, now)

    assert base_entry["weight"] == 5
    assert len(candidates) == 1
    assert "90天未更新且权重≤5" in candidates[0]["retireReasons"]


def test_retire_scan_includes_hollow(learn_module, empty_index):
    """
    空洞卡（充实度 < 40 且未人工标记 core）应直接进退役候选，
    不必等 180 天老化窗口，且原因标注为「内容空洞」。
    """
    now = datetime(2026, 8, 4, tzinfo=timezone.utc)
    # NOTE: 正文仅占位腔、无任何实质内容，充实度必低于阈值；
    # core 缺失（非 True）即视为可被自动退役。
    hollow_entry = {
        "id": "entry-hollow",
        "title": "Agent 架构",
        "domain": "ai",
        "type": "principle",
        "layer": "L1-principles",
        "slug": "agent-architecture",
        "sourceProject": "baseline",
        "tags": [],
        "version": 1,
        "weight": 10,
        "iterationCount": 0,
        "crossRefs": [],
        "createdAt": now.isoformat(),
        "updatedAt": now.isoformat(),
        "lastReferencedAt": now.isoformat(),
        "status": "active",
        # 占位腔内容，充实度必然 < 40
        "content": "待补充更多内容，此处先占位。",
    }
    empty_index["entries"] = [hollow_entry]

    candidates = learn_module.retire_scan(empty_index, now)

    assert len(candidates) == 1
    assert candidates[0]["id"] == "entry-hollow"
    reason = ", ".join(candidates[0]["retireReasons"])
    assert "空洞" in reason
    assert "hollow" in candidates[0]["retireCategory"]


def test_ensure_same_title_link_is_bidirectional_and_idempotent(learn_module):
    """
    存量回填的孤儿重算依赖 _ensure_same_title_link：两张同名 base slug 的卡
    应建立双向 RELATION_SAME_TITLE，且重复调用不重复追加（幂等）。
    """
    a = {"id": "a-1", "slug": "门控函数", "crossRefs": []}
    b = {"id": "b-1", "slug": "门控函数-2", "crossRefs": []}

    added_first = learn_module._ensure_same_title_link(a, b)
    assert added_first is True
    # a -> b 与 b -> a 双向都存在
    assert any(
        r["source"] == "b-1" and r["relation"] == learn_module.RELATION_SAME_TITLE
        for r in a["crossRefs"]
    )
    assert any(
        r["source"] == "a-1" and r["relation"] == learn_module.RELATION_SAME_TITLE
        for r in b["crossRefs"]
    )

    added_second = learn_module._ensure_same_title_link(a, b)
    assert added_second is False  # 已存在则不再新增
    assert len(a["crossRefs"]) == 1
    assert len(b["crossRefs"]) == 1


def test_retire_scan_excludes_core_from_hollow(learn_module, empty_index):
    """
    retire_scan 必须排除人工标记 core:true 的卡，哪怕它内容空洞。
    这是批量退役的安全逃生阀。
    """
    now = datetime(2026, 8, 4, tzinfo=timezone.utc)
    hollow_core = {
        "id": "entry-core-hollow",
        "title": "核心架构原则",
        "domain": "ai",
        "type": "principle",
        "layer": "L1-principles",
        "slug": "core-architecture",
        "sourceProject": "baseline",
        "tags": [],
        "version": 1,
        "weight": 10,
        "iterationCount": 0,
        "crossRefs": [],
        "createdAt": now.isoformat(),
        "updatedAt": now.isoformat(),
        "lastReferencedAt": now.isoformat(),
        "status": "active",
        "core": True,  # 人工标记核心，即使空洞也豁免
        "content": "待补充更多内容，此处先占位。",
    }
    empty_index["entries"] = [hollow_core]

    candidates = learn_module.retire_scan(empty_index, now)
    assert candidates == [], "core:true 的空洞卡不应进退役候选"


def test_lifecycle_dry_run_does_not_persist_decay(
    learn_module, base_entry, empty_index, monkeypatch
):
    """
    dry-run 只展示预计衰减与候选，不得保存或修改加载后的索引。
    """
    now = datetime.now(timezone.utc)
    base_entry["lastReferencedAt"] = (now - timedelta(days=65)).isoformat()
    empty_index["entries"] = [base_entry]
    save_calls = []
    monkeypatch.setattr(learn_module, "load_index", lambda: empty_index)
    monkeypatch.setattr(learn_module, "save_index", lambda index: save_calls.append(index))

    report = learn_module.cmd_lifecycle_maintenance(dry_run=True)

    assert "dry-run 未修改索引" in report
    assert "权重 10 → 8" in report
    assert base_entry["weight"] == 10
    assert not save_calls
