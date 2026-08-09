import importlib.util
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).resolve().parents[1]
LEARN_PATH = SKILL_ROOT / "learn.py"


@pytest.fixture(scope="session")
def learn_module():
    """
    加载学习引擎模块，避免目录名称中的空格影响常规 import。
    """
    spec = importlib.util.spec_from_file_location("starfounder_learn", LEARN_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载学习引擎: {LEARN_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def base_entry(learn_module):
    """
    提供固定时间字段齐全的活动知识条目。
    """
    return learn_module._base_entry(
        knowledge_id="entry-001",
        title="API 服务容错重试策略",
        domain="backend",
        ktype="pattern",
        layer="L2-assets",
        slug="api-retry-strategy",
        source_project="baseline",
    )


@pytest.fixture
def empty_index(learn_module):
    """
    提供不依赖真实知识库文件的空索引。
    """
    return learn_module._empty_index()
