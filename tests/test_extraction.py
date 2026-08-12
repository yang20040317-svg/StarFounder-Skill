from pathlib import Path


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_principle_extracts_reusable_guidance_instead_of_heading(learn_module):
    """
    原理卡片必须组织原则、依据和行动，而不能把三级标题当作摘要。
    """
    content = (FIXTURE_DIR / "principle-sample.md").read_text(encoding="utf-8")

    principles = learn_module.extract_principles(content, "principle-sample")

    assert len(principles) == 1
    principle = principles[0]
    assert principle["title"] == "设计原理 —— 可复用的核心经验"
    assert principle["content"].startswith("### 原则陈述")
    assert "### 推导依据" in principle["content"]
    assert "### 行动指引" in principle["content"]
    assert "低信息密度内容" in principle["content"]
    assert "校验内容长度与来源独立性" in principle["content"]
    assert "### 原理 1" not in principle["content"]
    assert principle["content"] != principle["title"]


def test_principle_without_substantive_body_is_not_persisted(learn_module):
    """
    只有原理小节标题、没有可推导正文时，不应生成空壳 L1 卡片。
    """
    content = "## 设计原理\n\n### 原理 1：信号评分需要反虚高机制"

    assert not learn_module.extract_principles(content, "empty-principle")


def test_code_asset_uses_nearest_markdown_heading(learn_module):
    """
    代码资产必须使用最近的 Markdown 标题，不能使用 return 等代码行。
    """
    content = (FIXTURE_DIR / "code-title-sample.md").read_text(encoding="utf-8")

    assets = learn_module.extract_assets(content, "code-title-sample")
    templates = [asset for asset in assets if asset["type"] == "template"]

    assert len(templates) == 1
    assert templates[0]["title"] == "指数退避重试模板"
    assert not templates[0]["title"].startswith("return")
    assert templates[0]["base_slug"] == "template-指数退避重试模板"
    assert "### 模板说明" in templates[0]["content"]
    assert "### 参数" in templates[0]["content"]
    assert "### 模板代码" in templates[0]["content"]
    assert "### 使用指导" in templates[0]["content"]
    assert templates[0]["content"] != templates[0]["title"]


def test_template_contains_parameters_guidance_and_limits(learn_module):
    """
    函数模板必须说明用途、参数、返回值、调用方式和接入限制。
    """
    content = (FIXTURE_DIR / "template-sample.md").read_text(encoding="utf-8")

    assets = learn_module.extract_assets(content, "template-sample")
    templates = [asset for asset in assets if asset["type"] == "template"]

    assert len(templates) == 1
    template = templates[0]
    assert "执行带指数退避的可恢复请求" in template["content"]
    assert "`request`" in template["content"]
    assert "`max_attempts`" in template["content"]
    assert "`base_delay`" in template["content"]
    assert "### 返回值" in template["content"]
    assert "retry_request(request, max_attempts=3, base_delay=1)" in template["content"]
    assert "### 适用条件（何时该用）" in template["content"]
    assert "### 禁忌（何时别用）" in template["content"]
    assert "### 决策理由（为何这样写）" in template["content"]
    assert "运行时版本" in template["prerequisites"]
    # 决策字段必须来自源 MD 真实标记句，而非「使用前应确认依赖版本」这类占位腔。
    assert "对业务逻辑错误" in template["decision_avoid"]
    assert "指数退避而非固定间隔" in template["decision_why"]
    assert "超时等可恢复异常" in template["decision_when"]


def test_template_requires_decision_fields(learn_module):
    """
    模板卡必须带「适用条件 / 禁忌 / 决策理由」三项决策上下文。

    只有裸函数 + 标题、源 MD 里没有任何适用/禁忌/取舍标记句的代码块，
    属于「代码快照」而非经验，不应入库为 template。
    """
    # NOTE: 仅含标题与一段无上下文的多行函数，无「适用/不要/因为」等语义标记。
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

    assets = learn_module.extract_assets(content, "bare-function")
    templates = [asset for asset in assets if asset["type"] == "template"]

    assert not templates, "无决策上下文的裸代码块不应产出 template 卡"


def test_pitfall_separates_problem_from_workaround(learn_module):
    """
    Pitfall 卡片必须包含独立的陷阱与绕过方案，且标题不能复制整段正文。

    注意：同文档内更完整的「踩坑小节」卡会覆盖同源的通用正则碎片
    （见 extract_pitfalls 的同源去重），因此本 fixture 最终只保留小节卡，
    而非来自正文 `问题：` 行的简短正则卡。
    """
    content = (FIXTURE_DIR / "pitfall-sample.md").read_text(encoding="utf-8")

    assets = learn_module.extract_assets(content, "pitfall-sample")
    pitfalls = [asset for asset in assets if asset["type"] == "pitfall"]

    assert len(pitfalls) == 1
    # 同源正则碎片（「频繁请求 Google Trends 会被限流」）已被小节卡覆盖剔除，
    # 保留更完整的小节卡。
    assert pitfalls[0]["title"] == "Google Trends 的瞬时封禁"
    assert "临时封禁" in pitfalls[0]["pitfall"]
    assert "72 小时" in pitfalls[0]["workaround"]
    assert pitfalls[0]["content"].startswith("### 陷阱")
    assert "### 绕过方案" in pitfalls[0]["content"]
    assert pitfalls[0]["title"] != pitfalls[0]["content"]


def test_pitfall_without_workaround_is_not_persisted(learn_module):
    """
    只有问题标题、没有处置建议的片段不应沉淀为低价值 pitfall。
    """
    content = "问题：Reddit JSON API 出现 429 限流陷阱"

    assets = learn_module.extract_assets(content, "incomplete-pitfall")

    assert not [asset for asset in assets if asset["type"] == "pitfall"]


def test_pitfall_section_uses_heading_and_full_body(learn_module):
    """
    踩坑小节必须用小节标题作为卡片标题，并从正文拆分陷阱与绕过方案。
    """
    content = (FIXTURE_DIR / "pitfall-sample.md").read_text(encoding="utf-8")

    assets = learn_module.extract_assets(content, "pitfall-sample")
    pitfalls = [asset for asset in assets if asset["type"] == "pitfall"]

    section_card = next(
        (p for p in pitfalls if p["title"] == "Google Trends 的瞬时封禁"), None
    )
    assert section_card is not None, "踩坑小节应生成独立卡片"
    assert "临时封禁" in section_card["pitfall"]
    assert "72 小时文件缓存" in section_card["workaround"]
    assert "随机等待" in section_card["workaround"]
    assert section_card["base_slug"].startswith("pitfall-google-trends")


def test_pitfall_section_suppresses_fragment_duplicates(learn_module):
    """
    踩坑小节覆盖的文本不再被通用正则重复提取，弱陷阱碎片直接丢弃。

    同源覆盖：正文中 `问题：频繁请求 Google Trends 会被 Google 限流` 与小节卡
    「Google Trends 的瞬时封禁」同主题，应被小节卡覆盖剔除，不另成卡。
    """
    content = (FIXTURE_DIR / "pitfall-sample.md").read_text(encoding="utf-8")

    assets = learn_module.extract_assets(content, "pitfall-sample")
    pitfalls = [asset for asset in assets if asset["type"] == "pitfall"]

    titles = [p["title"] for p in pitfalls]
    assert len(titles) == len(set(titles)), "同一来源不应产出重复陷阱卡"
    assert not any("只有" in title for title in titles)
    # 同源正则碎片应被小节卡覆盖，不再单独成卡。
    assert not any("频繁请求 Google Trends" in title for title in titles)
