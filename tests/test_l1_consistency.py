from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _make_principle(title: str, statement: str, action: str) -> dict:
    """构造一条 L1 卡片，结构对齐 _extract_principle_guidance 的输出。"""
    content = (
        f"### 原则陈述\n\n{statement}\n\n"
        f"### 推导依据\n\n{statement}\n\n"
        f"### 行动指引\n\n{action}"
    )
    return {"title": title, "content": content, "signal_count": 3}


def test_consistent_principle_is_kept(learn_module):
    """原则陈述与行动指引共享同一主题实体，应判为一致并保留。"""
    principle = _make_principle(
        "热度评分需对短文本降权",
        "热度评分必须校验内容长度与来源独立性，避免短期热闹误判为机会。",
        "计算热度前应校验内容长度与来源独立性，丢弃低信息密度内容。",
    )
    kept, dropped = learn_module.audit_l1_consistency([principle])

    assert len(kept) == 1
    assert not dropped


def test_low_overlap_principle_is_filtered(learn_module):
    """行动指引与原则陈述主题完全脱节，应被过滤并给出重叠度原因。"""
    principle = _make_principle(
        "数据库索引优化原则",
        "数据库查询必须为高频过滤字段建立复合索引以降低扫描行数。",
        "煮咖啡时应先研磨豆子再预热萃取头，保证风味稳定。",
    )
    kept, dropped = learn_module.audit_l1_consistency([principle])

    assert not kept
    assert len(dropped) == 1
    diag = dropped[0]["consistency"]
    assert diag["consistent"] is False
    assert "重叠度" in diag["reason"]
    assert isinstance(diag["score"], float)


def test_opposite_polarity_without_shared_entity_is_filtered(learn_module):
    """原则正向命令、行动却是否定禁止且无共享实体，应判为矛盾。"""
    principle = _make_principle(
        "缓存必须设置过期时间避免雪崩",
        "缓存必须设置过期时间，防止集中失效引发雪崩。",
        "不要直接删除数据库表，避免误删生产数据。",
    )
    kept, dropped = learn_module.audit_l1_consistency([principle])

    assert not kept
    # 低重叠或极性互斥任一分支命中即判为不一致；此处两条路径都指向主题错位。
    assert dropped[0]["consistency"]["consistent"] is False


def test_missing_section_is_conservatively_kept(learn_module):
    """核心小节缺失时无法判定，应保守放行而非误杀。"""
    principle = {
        "title": "缺段原则",
        "content": "### 原则陈述\n\n只含原则陈述，没有行动指引小节。",
        "signal_count": 2,
    }
    result = learn_module.validate_principle_consistency(principle)

    assert result["consistent"] is True
    assert result["score"] is None


def test_audit_returns_kept_and_dropped_separately(learn_module):
    """批量审计应将一致与不一致卡片分别归类，不污染保留列表。"""
    good = _make_principle(
        "API 重试需指数退避",
        "API 请求失败应使用指数退避重试以提升可用性。",
        "实现重试逻辑时应采用指数退避并限制最大尝试次数。",
    )
    bad = _make_principle(
        "索引优化原则",
        "数据库查询必须为高频字段建立索引。",
        "煮咖啡应先研磨豆子再预热萃取头。",
    )
    kept, dropped = learn_module.audit_l1_consistency([good, bad])

    assert [p["title"] for p in kept] == ["API 重试需指数退避"]
    assert [p["title"] for p in dropped] == ["索引优化原则"]


@pytest.mark.parametrize(
    "statement,action,expect_consistent",
    [
        # 共享「校验/来源」实体 → 一致
        ("评分必须校验内容长度与来源独立性。", "计算前应校验内容长度与来源独立性。", True),
        # 完全不相关 → 过滤
        ("数据库需建立复合索引。", "煮咖啡应先研磨豆子。", False),
    ],
)
def test_consistency_parametrized(learn_module, statement, action, expect_consistent):
    principle = _make_principle("参数化用例", statement, action)
    result = learn_module.validate_principle_consistency(principle)
    assert result["consistent"] is expect_consistent
