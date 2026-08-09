"""
StarFounder 经验炼金引擎 — 学习脚本 v2

用途：摄入项目 MD 文件，按六层框架提取可复用知识，入库到 knowledge/ 目录。

用法：
    # 学习单个项目 MD
    python learn.py ingest projects/my-project.md

    # 扫描 projects/ 目录下所有未学习的 MD
    python learn.py scan

    # 查看知识库概览（含空白领域扫描）
    python learn.py overview

    # 查看知识库健康度报告
    python learn.py stats

    # 生命周期维护（持久化到期衰减并列出退役候选）
    python learn.py maintain

    # 仅预览衰减和候选，不修改索引
    python learn.py maintain --dry-run

    # 兼容旧命令，行为与 maintain 相同
    python learn.py retire-scan

    # 退役指定知识（需确认）
    python learn.py retire <knowledge-id> --reason "..."

    # 搜索知识库
    python learn.py search "关键词"
"""

import hashlib
import json
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# ─── 路径常量 ────────────────────────────────────────────

SKILL_DIR = Path(__file__).resolve().parent
KNOWLEDGE_DIR = SKILL_DIR / "knowledge"
PROJECTS_DIR = SKILL_DIR / "projects"
INDEX_PATH = KNOWLEDGE_DIR / "index.json"

# 知识子目录映射
LAYER_DIRS = {
    "L1-principles": KNOWLEDGE_DIR / "L1-principles",
    "L2-assets": KNOWLEDGE_DIR / "L2-assets",
    "L3-classified": KNOWLEDGE_DIR / "L3-classified",
    "L4-iterations": KNOWLEDGE_DIR / "L4-iterations",
    "L5-retired": KNOWLEDGE_DIR / "L5-retired",
}

# NOTE: L2 使用稳定的资产族目录；pattern/decision 都属于可组合框架资产。
L2_TYPE_DIRS = {
    "checklist": "checklists",
    "framework": "frameworks",
    "pattern": "frameworks",
    "decision": "frameworks",
    "pitfall": "pitfalls",
    "template": "templates",
}

# ─── 领域与类型定义 ──────────────────────────────────────

DOMAINS = [
    "frontend", "backend", "devops", "design",
    "business", "ai", "security", "general",
]

KNOWLEDGE_TYPES = [
    "principle", "pattern", "template", "pitfall", "checklist", "decision",
]

# ─── 索引管理 ────────────────────────────────────────────


def load_index() -> dict:
    """加载知识索引，不存在则返回空索引。"""
    if INDEX_PATH.exists():
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return _empty_index()


def save_index(index: dict) -> None:
    """保存知识索引。"""
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def _empty_index() -> dict:
    """创建空索引结构。"""
    return {
        "version": "2.0",
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "totalKnowledge": 0,
        "domains": {d: 0 for d in DOMAINS},
        "types": {t: 0 for t in KNOWLEDGE_TYPES},
        "entries": [],
    }


def _slugify(text: str) -> str:
    """生成 URL 友好的 slug。"""
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[-\s]+", "-", slug).strip("-")
    return slug or "untitled"


def _now_iso() -> str:
    """返回当前 UTC ISO 时间戳。"""
    return datetime.now(timezone.utc).isoformat()


def _short_hash(text: str) -> str:
    """生成 6 位短哈希，用于 slug 去重。"""
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:6]


def _make_unique_slug(base_slug: str, existing_slugs: set) -> str:
    """确保 slug 唯一：如果冲突则追加短哈希。"""
    slug = base_slug
    if slug in existing_slugs:
        # 收集已有 slug 中的候选用途
        hash_suffix = _short_hash(slug + _now_iso())
        slug = f"{base_slug}-{hash_suffix}"
    return slug


def find_entry_by_id(index: dict, knowledge_id: str) -> Optional[dict]:
    """在索引中查找指定 ID 的条目。"""
    for entry in index["entries"]:
        if entry["id"] == knowledge_id:
            return entry
    return None


def find_entry_by_slug(index: dict, slug: str) -> Optional[dict]:
    """在索引中查找指定 slug 的条目。"""
    for entry in index["entries"]:
        if entry.get("slug") == slug:
            return entry
    return None


def update_entry_in_index(index: dict, knowledge_id: str, updates: dict) -> Optional[dict]:
    """更新指定条目的字段并返回更新后的条目。"""
    entry = find_entry_by_id(index, knowledge_id)
    if entry:
        entry.update(updates)
        entry["updatedAt"] = _now_iso()
        index["updatedAt"] = _now_iso()
    return entry


def _base_entry(
    knowledge_id: str,
    title: str,
    domain: str,
    ktype: str,
    layer: str,
    slug: str,
    source_project: str,
    tags: str = "",
    version: int = 1,
    weight: int = 10,
) -> dict:
    """构建基础索引条目。"""
    now = _now_iso()
    return {
        "id": knowledge_id,
        "title": title,
        "domain": domain,
        "type": ktype,
        "layer": layer,
        "slug": slug,
        "sourceProject": source_project,
        "tags": [t.strip() for t in tags.split(",") if t.strip()],
        "version": version,
        "weight": weight,
        "iterationCount": 0,
        "crossRefs": [],
        "createdAt": now,
        "updatedAt": now,
        "lastReferencedAt": now,
        "status": "active",
    }


def add_to_index(
    index: dict,
    *,
    knowledge_id: str,
    title: str,
    domain: str,
    ktype: str,
    layer: str,
    slug: str,
    source_project: str,
    tags: str = "",
) -> None:
    """将新知识条目注册到索引。"""
    entry = _base_entry(
        knowledge_id=knowledge_id,
        title=title,
        domain=domain,
        ktype=ktype,
        layer=layer,
        slug=slug,
        source_project=source_project,
        tags=tags,
    )
    index["entries"].append(entry)
    index["totalKnowledge"] = len(index["entries"])
    index["domains"][domain] = index["domains"].get(domain, 0) + 1
    index["types"][ktype] = index["types"].get(ktype, 0) + 1
    index["updatedAt"] = _now_iso()


# ─── 知识卡片操作 ────────────────────────────────────────


def resolve_knowledge_card_path(layer: str, slug: str, ktype: str) -> Path:
    """
    根据逻辑层和知识类型解析唯一物理路径。
    """
    layer_dir = LAYER_DIRS.get(layer, KNOWLEDGE_DIR)
    if layer == "L2-assets":
        type_dir = L2_TYPE_DIRS.get(ktype)
        if not type_dir:
            raise ValueError(f"不支持的 L2 资产类型: {ktype}")
        layer_dir = layer_dir / type_dir
    return layer_dir / f"{slug}.md"


KNOWLEDGE_CARD_TEMPLATE = """# {title}

- **领域**: {domain}
- **类型**: {type}
- **版本**: v{version}
- **来源项目**: {source_project}
- **创建时间**: {created_at}
- **最后更新**: {updated_at}
- **最后引用**: {last_referenced_at}
- **权重**: {weight}
- **状态**: {status}
- **标签**: {tags}
- **关联知识**: {cross_refs}

---

## 核心内容

{content}

## 使用场景

{usage_scenario}

## 前置条件

{prerequisites}

## 已知局限

{limitations}
"""


def write_knowledge_card(
    *,
    layer: str,
    slug: str,
    title: str,
    domain: str,
    ktype: str,
    source_project: str,
    content: str,
    usage_scenario: str = "通用场景",
    prerequisites: str = "无特殊前置条件",
    limitations: str = "暂无已知局限",
    version: int = 1,
    weight: int = 10,
    tags: str = "",
    cross_refs: str = "",
) -> Path:
    """写入知识卡片到指定 layer/type 目录并返回文件路径。"""
    file_path = resolve_knowledge_card_path(layer, slug, ktype)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    now = _now_iso()

    card_content = KNOWLEDGE_CARD_TEMPLATE.format(
        title=title,
        domain=domain,
        type=ktype,
        version=version,
        source_project=source_project,
        created_at=now,
        updated_at=now,
        last_referenced_at=now,
        weight=weight,
        status="active",
        tags=tags or domain,
        cross_refs=cross_refs or "无",
        content=content,
        usage_scenario=usage_scenario,
        prerequisites=prerequisites,
        limitations=limitations,
    )

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(card_content)

    return file_path


# ─── L1 第一性原理提取器（增强版）──────────────────────────


def _extract_principle_guidance(body: str) -> dict[str, str] | None:
    """
    将原理章节提炼为原则陈述、推导依据和行动指引，拒绝只有标题的空壳内容。
    """
    without_code = re.sub(r"```[\s\S]*?```", " ", body)
    content_lines = [
        line.strip()
        for line in without_code.splitlines()
        if line.strip() and not re.match(r"^#{1,6}\s+", line.strip())
    ]
    plain_body = "\n".join(content_lines).strip()
    plain_body = re.sub(r"\*\*(.+?)\*\*", r"\1", plain_body)
    if len(plain_body) < 50:
        return None

    sentences = [
        sentence.strip(" -\t")
        for sentence in re.split(r"(?<=[。！？])\s*|\n+", plain_body)
        if len(sentence.strip(" -\t")) >= 12
    ]
    if not sentences:
        return None

    statement = sentences[0]
    rationale = next(
        (
            sentence
            for sentence in sentences[1:]
            if any(marker in sentence for marker in ("因为", "本质", "根本", "真正", "不是", "而是", "权衡"))
        ),
        "",
    )
    action = next(
        (
            sentence
            for sentence in reversed(sentences[1:])
            if any(marker in sentence for marker in ("解决", "教训", "应该", "必须", "避免", "优先", "选择", "需要"))
        ),
        "",
    )

    # NOTE: 不凭空补写结论；缺少显式依据或行动句时，使用原文中的其他实质句兜底。
    remaining = [sentence for sentence in sentences[1:] if sentence not in {rationale, action}]
    if not rationale and remaining:
        rationale = remaining.pop(0)
    if not action and remaining:
        action = remaining[-1]
    if not rationale and len(sentences) > 1:
        rationale = sentences[1]
    if not action:
        action = rationale

    unique_parts = {statement, rationale, action}
    if len(unique_parts - {""}) < 2:
        return None

    content = (
        f"### 原则陈述\n\n{statement[:300]}\n\n"
        f"### 推导依据\n\n{rationale[:500]}\n\n"
        f"### 行动指引\n\n{action[:500]}"
    )
    return {"content": content, "plain_body": plain_body[:1000]}


def extract_principles(md_content: str, project_name: str) -> list[dict]:
    """从项目 MD 中提取第一性原理。

    增强策略（v2）：
    - 第一层：标题关键词匹配（"原理/原则/核心/决策"）
    - 第二层：段落模式匹配（"因为...所以..." / "选择A而非B" / "关键洞察"）
    - 第三层：否定式原理提取（"踩坑/不要/避免" → 取反面）
    - 质量阈值：段落 >= 50 字符，至少命中 2 个信号
    """
    principles = []
    sections = re.split(r"(?=^## )", md_content, flags=re.MULTILINE)

    # ── 第一层：标题关键词
    title_keywords = ["原理", "原则", "为什么", "核心", "本质", "底层", "决策", "权衡"]

    # ── 第二层：段落模式
    pattern_signals = [
        r"因为.+所以",
        r"选择.+而非",
        r"关键.+洞察",
        r"底层.+原因",
        r"根本.+在于",
        r"本质.+是",
        r"真正.+问题",
        r"不是.+而是",
        r"设计.+理念",
        r"架构.+考量",
    ]

    # ── 第三层：否定式原理
    negation_keywords = ["教训", "踩坑", "避免", "不要", "别再", "不应该", "反思", "复盘"]

    for section in sections:
        lines = section.strip().split("\n")
        if not lines:
            continue

        # 跳过纯代码块
        if section.strip().startswith("```"):
            continue

        heading = lines[0].lstrip("#").strip()
        raw_body = "\n".join(lines[1:]).strip()
        guidance = _extract_principle_guidance(raw_body)
        if guidance is None:
            continue
        body = guidance["plain_body"]

        if len(body) < 50:
            continue

        # 多信号评分
        signal_count = 0
        signal_sources: list[str] = []

        # 检查标题关键词
        title_hits = [kw for kw in title_keywords if kw in heading]
        signal_count += len(title_hits) * 2  # 标题命中权重更高
        signal_sources.extend(title_hits)

        # 检查段落模式
        for pattern in pattern_signals:
            if re.search(pattern, body):
                signal_count += 1
                signal_sources.append(pattern[:4])

        # 检查否定式原理
        neg_hits = [kw for kw in negation_keywords if kw in body]
        signal_count += len(neg_hits)
        signal_sources.extend(neg_hits)

        # 至少 2 个信号才认定为原理（之前是 1 个关键词就过）
        if signal_count < 2:
            continue

        base_slug = _slugify(f"principle-{heading[:50]}")

        principles.append({
            "title": heading,
            "base_slug": base_slug,  # 让 cmd_ingest 做去重
            "content": guidance["content"],
            "full_body": body[:500],
            "signal_count": signal_count,
            "signal_sources": signal_sources,
            "source_project": project_name,
        })

    # 按信号强度排序，取前 10 条
    principles.sort(key=lambda p: -p["signal_count"])
    return principles[:10]


# ─── L2 资产提取器（增强版）───────────────────────────────


def _extract_template_guidance(title: str, code: str, language: str) -> dict[str, str]:
    """
    为代码模板生成可复用的说明、参数、返回值和使用指导。

    代码仍作为模板的一部分保留，但必须被语义说明包裹，避免知识卡退化成
    无上下文的代码转储。
    """
    function_match = re.search(
        r"(?:def|function)\s+([A-Za-z_]\w*)\s*\(([^)]*)\)", code
    )
    if function_match:
        function_name = function_match.group(1)
        parameter_text = function_match.group(2).strip() or "无参数"
        parameters = (
            "；".join(
                f"`{part.strip().split('=')[0].strip()}`"
                for part in parameter_text.split(",")
                if part.strip()
            )
            or "无参数"
        )
        description_match = re.search(
            r"(?:'''|\"\"\")(.+?)(?:'''|\"\"\")", code, re.DOTALL
        )
        description = (
            re.sub(r"\s+", " ", description_match.group(1)).strip()
            if description_match
            else f"封装 `{function_name}` 的可复用处理逻辑"
        )
        return_value = (
            "返回处理结果；具体值取决于输入和模板分支。"
            if "return" in code
            else "无显式返回值。"
        )
        usage = (
            f"调用 `{function_name}({parameter_text})`，传入符合模板约定的参数，"
            "并根据返回结果继续业务处理。"
        )
        limitations = "使用前应补充业务校验、异常处理和日志策略。"
    else:
        function_name = title or f"{language} 代码模板"
        parameters = "由模板中的变量和配置项决定"
        description = f"提供一段可复用的 {language} 实现，用于：{title or '相关业务处理'}。"
        return_value = "由代码片段实际执行结果决定。"
        usage = "复制模板后，替换示例变量、配置项和业务依赖，再接入调用方。"
        limitations = "使用前应确认依赖版本、输入校验、异常处理和资源边界。"

    content = (
        f"### 模板说明\n\n{description}\n\n"
        f"### 参数\n\n{parameters}\n\n"
        f"### 返回值\n\n{return_value}\n\n"
        f"### 模板代码\n\n```{language}\n{code}\n```\n\n"
        f"### 使用指导\n\n{usage}\n\n"
        f"### 注意事项\n\n{limitations}"
    )
    return {
        "content": content,
        "usage_scenario": f"适用于需要复用“{title or function_name}”逻辑的项目。",
        "prerequisites": "确认运行时版本、依赖包和输入数据结构与模板一致。",
        "limitations": limitations,
    }


def _extract_pitfall_parts(text: str) -> tuple[str, str, str] | None:
    """
    将踩坑描述拆分为标题、陷阱和绕过方案。

    只有同时包含问题与处置建议的内容才值得沉淀为 pitfall，避免生成标题与
    核心内容重复、却没有可执行解决方案的低价值卡片。
    """
    cleaned = re.sub(r"\*{1,2}|`", "", text).strip()
    cleaned = re.sub(r"^\d+[：:.、]\s*", "", cleaned)
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[。！？；])\s*|\n+", cleaned)
        if sentence.strip()
    ]
    if len(sentences) < 2:
        return None

    # NOTE: 优先使用"解决/教训"等强处置标记拆分；弱标记（如"使用"）仅在无强标记时兜底，
    # 避免把问题描述中的普通动词误判为绕过方案起点。
    strong_markers = ("解决", "教训", "绕过", "规避", "修复", "对策")
    weak_markers = (
        "改为", "改用", "使用", "通过", "缓存",
        "降级", "重试", "限制", "应该", "应当", "可以", "而是", "替代",
    )
    solution_index = next(
        (
            index for index, sentence in enumerate(sentences[1:], start=1)
            if any(marker in sentence for marker in strong_markers)
        ),
        None,
    )
    if solution_index is None:
        solution_index = next(
            (
                index for index, sentence in enumerate(sentences[1:], start=1)
                if any(marker in sentence for marker in weak_markers)
            ),
            None,
        )
    if solution_index is None:
        return None

    pitfall = "".join(sentences[:solution_index]).strip()
    workaround = "".join(sentences[solution_index:]).strip()
    # NOTE: 陷阱描述过短（如"被 Google 限流"）无法构成可检索的知识单元，直接丢弃。
    if len(pitfall) < 10 or len(workaround) < 10:
        return None

    title_seed = pitfall.rstrip("。！？；")
    title_seed = re.sub(r"^(?:被|遭遇|出现|发生)\s*", "", title_seed)
    title = title_seed if title_seed.endswith(("陷阱", "风险", "问题")) else f"{title_seed}陷阱"
    return title[:80], pitfall, workaround


def extract_assets(md_content: str, project_name: str) -> list[dict]:
    """从项目 MD 中提取可复用资产。

    增强策略（v2）：
    - 代码块过滤：跳过单行/调试输出/日志片段/错误堆栈
    - Pitfall 正则增强：覆盖更多坑位表述
    - Checklist 检测增强
    """
    assets = []

    # ── 代码块提取（增强过滤）
    code_blocks = re.finditer(
        r"```(\w+)?\n(.*?)```",
        md_content,
        re.DOTALL,
    )

    # 代码块里常见的非资产内容特征
    noise_patterns = [
        r"^\s*(print|console\.log|echo)\s*[\(（]",  # 调试输出
        r"^\s*(error|Error|ERROR)[\s:：]",  # 错误堆栈首行
        r"Traceback\s*\(most recent call last\)",  # Python 堆栈
        r"^\s*(npm\s|yarn\s|pip\s|go\s|git\s)",  # 终端命令
        r"^\s*\d+\s*\|",  # 行号前缀（日志片段）
    ]

    for match in code_blocks:
        lang = match.group(1) or "text"
        code = match.group(2).strip()

        # 过滤：太短
        if len(code) < 50:
            continue

        # 过滤：行数太少（<3 行的单几句不值得存）
        code_lines = [l for l in code.split("\n") if l.strip()]
        if len(code_lines) < 3:
            continue

        # 过滤：噪声内容
        is_noise = False
        for pattern in noise_patterns:
            if re.search(pattern, code, re.MULTILINE):
                is_noise = True
                break
        if is_noise:
            continue

        # NOTE: 仅使用代码块前最近的 Markdown 标题作为描述，避免把代码块内部
        # 的 return、赋值语句或列表内容误识别为知识标题。
        preceding_content = md_content[:match.start()]
        headings = re.findall(r"^#{1,6}\s+(.+?)\s*$", preceding_content, re.MULTILINE)
        desc_line = headings[-1].strip()[:80] if headings else ""

        template_title = desc_line or f"{lang} 代码片段"
        guidance = _extract_template_guidance(template_title, code, lang)
        base_slug = _slugify(f"template-{template_title[:50]}")
        assets.append({
            "type": "template",
            "title": template_title,
            "base_slug": base_slug,
            "content": guidance["content"],
            "language": lang,
            "usage_scenario": guidance["usage_scenario"],
            "prerequisites": guidance["prerequisites"],
            "limitations": guidance["limitations"],
            "source_project": project_name,
        })

    # ── 检查清单提取
    checklist_heading_pattern = re.compile(
        r"(?:^##\s*.*(?:检查|清单|checklist|上线|部署|发布|验证|核对|验收).*$)",
        re.MULTILINE | re.IGNORECASE,
    )
    for match in checklist_heading_pattern.finditer(md_content):
        start = match.start()
        heading_text = match.group()
        next_section = re.search(r"^## ", md_content[start + len(heading_text):], re.MULTILINE)
        end = start + len(heading_text) + (next_section.start() if next_section else len(md_content) - start - len(heading_text))
        body = md_content[start + len(heading_text):end].strip()

        if len(body) > 30:
            heading = heading_text.lstrip("#").strip()
            base_slug = _slugify(f"checklist-{heading[:50]}")
            assets.append({
                "type": "checklist",
                "title": heading,
                "base_slug": base_slug,
                "content": body,
                "source_project": project_name,
            })

    # ── 陷阱/反模式提取（增强版正则）
    pitfall_patterns = [
        # 格式 1：标记型（坑： / 问题： / 错误： / 陷阱： / BUG:）
        r"(?:坑|陷阱|问题|错误|失败|BUG|Bug|bug)[：:\s]+(.+?)(?=\n\n|\n##|\n###|\Z)",
        # 格式 2：踩坑记录
        r"(?:踩坑|踩过.*坑|遇到一个坑)[：:]*\s*(.+?)(?=\n\n|\n##|\n###|\Z)",
        # 格式 3：建议避免
        r"(?:避免|不要|别|不应该|不建议|禁止)\s*(.+?)(?=\n\n|\n##|\n###|\Z)",
        # 格式 4：常见问题
        r"(?:常见问题|注意事项|⚠️|🚨|❗)\s*(.+?)(?=\n\n|\n##|\n###|\Z)",
        # 格式 5：但是 / 然而 / 问题是
        r"(?:但是|然而|问题是|遗憾的是|糟糕的是)\s*(.+?)(?=\n\n|\n##|\n###|\Z)",
    ]

    seen_pitfall_keys = set()

    # ── 踩坑小节提取：`### 踩坑 N：标题` 的标题与正文组成完整知识单元，
    # 使用小节标题作为卡片标题，避免正文首句被误当标题。
    covered_spans: list[tuple[int, int]] = []
    section_matches = list(
        re.finditer(r"^###\s+踩坑[^\n]*\n", md_content, re.MULTILINE)
    )
    for index, section_match in enumerate(section_matches):
        section_end = (
            section_matches[index + 1].start()
            if index + 1 < len(section_matches)
            else len(md_content)
        )
        heading = re.sub(r"^踩坑\s*\d*[：:.、]?\s*", "", section_match.group(0).strip().lstrip("#").strip())
        body = md_content[section_match.end():section_end].strip()[:500]
        parts = _extract_pitfall_parts(body)
        if parts is None or not heading:
            continue

        _, pitfall, workaround = parts
        title = heading[:80]
        dedupe_key = (pitfall.casefold(), workaround.casefold())
        if dedupe_key in seen_pitfall_keys:
            continue

        seen_pitfall_keys.add(dedupe_key)
        covered_spans.append((section_match.start(), section_end))
        base_slug = _slugify(f"pitfall-{title[:50]}")
        assets.append({
            "type": "pitfall",
            "title": title,
            "base_slug": base_slug,
            "content": f"### 陷阱\n\n{pitfall}\n\n### 绕过方案\n\n{workaround}",
            "pitfall": pitfall,
            "workaround": workaround,
            "source_project": project_name,
        })

    for pattern in pitfall_patterns:
        for match in re.finditer(pattern, md_content, re.DOTALL):
            # NOTE: 已被踩坑小节覆盖的文本范围不再参与正则提取，防止同一片段重复成卡。
            if any(start <= match.start() < end for start, end in covered_spans):
                continue
            text = match.group(1).strip()[:500]
            parts = _extract_pitfall_parts(text)
            if parts is None:
                continue

            title, pitfall, workaround = parts
            dedupe_key = (pitfall.casefold(), workaround.casefold())
            if dedupe_key in seen_pitfall_keys:
                continue

            seen_pitfall_keys.add(dedupe_key)
            base_slug = _slugify(f"pitfall-{title[:50]}")
            assets.append({
                "type": "pitfall",
                "title": title,
                "base_slug": base_slug,
                "content": f"### 陷阱\n\n{pitfall}\n\n### 绕过方案\n\n{workaround}",
                "pitfall": pitfall,
                "workaround": workaround,
                "source_project": project_name,
            })

    return assets


# ─── L3 分类器（优先级加权版）─────────────────────────────


def classify_domain(text: str) -> str:
    """基于关键词推断知识所属领域（v2: 优先级加权去重叠）。"""
    # 高优先级关键词（1次命中 ≥ 普通关键词3次）
    high_priority = {
        "frontend": ["react", "vue", "angular", "svelte", "jsx", "hooks", "webpack", "vite", "前端"],
        "backend": ["fastapi", "flask", "django", "orm", "sqlalchemy", "grpc", "rabbitmq", "kafka"],
        "devops": ["docker", "kubernetes", "k8s", "helm", "terraform", "ci/cd", "jenkins", "ansible"],
        "ai": ["llm", "gpt-4", "claude", "rag", "embedding", "langchain", "fine-tun", "transformer"],
        "security": ["xss", "csrf", "cors", "sql injection", "owasp", "漏洞", "注入", "攻击"],
        "design": ["figma", "设计系统", "design system", "prototype", "mockup"],
        "business": ["商业模式", "定价", "获客", "转化率", "留存", "arpu", "ltv"],
    }

    # 普通关键词（可能跨领域重叠）
    normal_keywords = {
        "frontend": ["组件", "css", "html", "浏览器", "dom", "页面", "渲染", "构建", "babel", "typescript", "router", "redux", "zustand", "tailwind", "sass", "less"],
        "backend": ["api", "数据库", "database", "sql", "后端", "服务", "队列", "缓存", "redis", "jwt", "rest", "graphql", "微服务", "rpc"],
        "devops": ["部署", "deploy", "nginx", "服务器", "监控", "日志", "备份", "定时任务", "cron", "负载均衡", "cdn"],
        "ai": ["prompt", "模型", "agent", "向量", "token", "ai", "ml", "训练", "推理", "embedding", "chatgpt"],
        "security": ["安全", "加密", "hash", "权限", "认证", "oauth", "https", "ssl", "tls", "审计"],
        "design": ["ui", "交互", "体验", "视觉", "布局", "色彩", "字体", "图标", "无障碍", "响应式"],
        "business": ["产品", "增长", "运营", "用户", "市场", "商业模式", "ab测试", "指标"],
    }

    text_lower = text.lower()
    scores = {domain: 0 for domain in DOMAINS}

    # 高优先级匹配
    for domain, keywords in high_priority.items():
        for kw in keywords:
            if kw in text_lower:
                scores[domain] += 5  # 高权重

    # 普通匹配
    for domain, keywords in normal_keywords.items():
        for kw in keywords:
            if kw in text_lower:
                scores[domain] += 1

    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general"


def classify_type(text: str) -> str:
    """推断知识卡片类型。"""
    type_indicators = {
        "principle": ["原理", "原则", "第一性", "底层", "本质", "核心"],
        "pattern": ["模式", "方案", "做法", "实践", "方法"],
        "template": ["模板", "脚手架", "配置", "示例代码"],
        "pitfall": ["坑", "陷阱", "错误", "避免", "不要", "别", "问题"],
        "checklist": ["检查", "清单", "核对", "checklist"],
        "decision": ["选型", "对比", "选择", "决策", "权衡", "为什么选"],
    }

    text_lower = text.lower()
    scores = {t: 0 for t in KNOWLEDGE_TYPES}

    for ktype, keywords in type_indicators.items():
        for kw in keywords:
            if kw in text_lower:
                scores[ktype] += 1

    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "pattern"


# ─── L4 迭代检测（新）────────────────────────────────────


# 迭代关系类型
RELATION_NEW = "NEW"        # 完全新知识
RELATION_CONFIRM = "CONFIRM"  # 证实已有经验
RELATION_EXTEND = "EXTEND"    # 补充/扩展已有知识
RELATION_CONFLICT = "CONFLICT"  # 与已有知识矛盾


def _compute_overlap(new_title: str, existing_title: str) -> float:
    """计算两个标题的词汇重叠度。"""
    def tokenize(s: str) -> set:
        # 中英文混合分词
        tokens = set()
        # 中文 2-gram
        chinese_chars = ''.join(re.findall(r'[\u4e00-\u9fff]', s))
        for i in range(len(chinese_chars) - 1):
            tokens.add(chinese_chars[i:i+2])
        # 英文单词
        english_words = re.findall(r'[a-zA-Z]+', s.lower())
        tokens.update(w for w in english_words if len(w) > 2)
        return tokens

    t1 = tokenize(new_title)
    t2 = tokenize(existing_title)
    if not t1 or not t2:
        return 0.0
    return len(t1 & t2) / len(t1 | t2)


def detect_iterations(
    new_items: list[dict],
    index: dict,
) -> dict:
    """
    L4 迭代检测核心引擎。

    对每条新知识，与已有知识库做四种关系检测：
    - CONFIRM：标题重叠 >60%，同领域 → 不新建，已有知识权重+1
    - CONFLICT：同领域同类知识但结论相反 → 标记双方，需人工裁决
    - EXTEND：同领域，标题部分重叠(30-60%) → 追加到已有卡片
    - NEW：无匹配 → 新建

    返回：
        {
            "new_items": [...],       # 确认新建的条目
            "extended": [...],        # 已追加到已有知识的条目
            "confirmed": [...],       # 证实已有经验（不新建）
            "conflicts": [...],       # 冲突待裁决
            "iteration_log": "..."    # 可读日志
        }
    """
    result = {
        "new_items": [],
        "extended": [],
        "confirmed": [],
        "conflicts": [],
        "iteration_log": [],
    }

    active_entries = [e for e in index["entries"] if e["status"] == "active"]

    for item in new_items:
        item_title = item["title"]
        item_domain = item.get("domain") or classify_domain(item.get("content", item_title))

        best_match = None
        best_overlap = 0.0

        for existing in active_entries:
            overlap = _compute_overlap(item_title, existing["title"])
            same_domain = existing["domain"] == item_domain

            # 同领域加分
            if same_domain:
                overlap *= 1.3

            if overlap > best_overlap:
                best_overlap = overlap
                best_match = existing

        if best_match and best_overlap > 0.6:
            # CONFIRM：高重叠 → 证实已有经验
            result["confirmed"].append({
                "item": item,
                "matched_entry": best_match,
                "overlap": round(best_overlap, 2),
            })
            result["iteration_log"].append(
                f"✅ CONFIRM | `{item_title[:40]}` 证实了 `{best_match['title'][:40]}` "
                f"(重叠度 {best_overlap:.0%})，权重由 {best_match['weight']} → {best_match['weight'] + 2}"
            )
        elif best_match and best_overlap > 0.3:
            # EXTEND：中等重叠 → 扩展已有知识
            result["extended"].append({
                "item": item,
                "matched_entry": best_match,
                "overlap": round(best_overlap, 2),
            })
            result["iteration_log"].append(
                f"📝 EXTEND  | `{item_title[:40]}` 扩展了 `{best_match['title'][:40]}` "
                f"(重叠度 {best_overlap:.0%})，版本 {best_match['version']} → {best_match['version'] + 1}"
            )
        elif best_match and best_overlap > 0.15:
            # 低重叠但同领域：检查是否为隐形冲突
            # 通过否定词判断
            item_neg_words = any(kw in item_title + item.get("content", "")
                                for kw in ["不", "避免", "不要", "别", "但", "然而", "反而"])
            if item_neg_words:
                result["conflicts"].append({
                    "item": item,
                    "matched_entry": best_match,
                    "overlap": round(best_overlap, 2),
                })
                result["iteration_log"].append(
                    f"⚠️ CONFLICT| `{item_title[:40]}` 与 `{best_match['title'][:40]}` 可能矛盾 "
                    f"(重叠度 {best_overlap:.0%})，需人工裁决"
                )
            else:
                result["new_items"].append(item)
        else:
            # NEW：无匹配 → 新建
            result["new_items"].append(item)
            result["iteration_log"].append(
                f"🆕 NEW     | `{item_title[:40]}` → 新建卡片"
            )

    return result


def _save_iteration_archive(extended_item: dict, matched_entry: dict, new_content: str) -> Path:
    """将旧版本存档到 L4-iterations/ 目录。"""
    archive_dir = LAYER_DIRS["L4-iterations"]
    archive_dir.mkdir(parents=True, exist_ok=True)

    old_slug = matched_entry.get("slug", "unknown")
    old_version = matched_entry.get("version", 1)
    archive_path = archive_dir / f"{old_slug}_v{old_version}.md"

    timestamp = _now_iso()
    archive_content = f"""# {matched_entry['title']} — v{old_version} 存档

- **存档时间**: {timestamp}
- **被 v{old_version + 1} 替代**
- **原来源项目**: {matched_entry.get('sourceProject', '未知')}
- **原权重**: {matched_entry.get('weight', 'N/A')}

---

{new_content}
"""
    archive_path.write_text(archive_content, encoding="utf-8")
    return archive_path


# ─── L5 退役扫描 ──────────────────────────────────────────


def retire_scan(index: dict, now: Optional[datetime] = None) -> list[dict]:
    """扫描满足退役条件的活动知识条目。"""
    scan_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    candidates = []

    for entry in index["entries"]:
        if entry.get("status") != "active":
            continue

        reasons = []
        updated = _parse_utc(entry.get("updatedAt"), scan_time)
        last_ref = _parse_utc(entry.get("lastReferencedAt", entry["createdAt"]), scan_time)

        # 90 天未更新且权重低
        if (scan_time - updated) > timedelta(days=90) and entry["weight"] <= 5:
            reasons.append("90天未更新且权重≤5")

        # 120 天从未迭代
        created = _parse_utc(entry.get("createdAt"), scan_time)
        if (scan_time - created) > timedelta(days=120) and entry["iterationCount"] == 0:
            reasons.append("120天从未迭代")

        # 180 天未被引用
        if (scan_time - last_ref) > timedelta(days=180):
            reasons.append("180天未被引用")

        if reasons:
            candidates.append({**entry, "retireReasons": reasons})

    return candidates


# ─── L6 权重衰减 & 交叉引用（新）──────────────────────────


def _parse_utc(value: Optional[str], fallback: datetime) -> datetime:
    """
    将索引时间解析为 UTC；无效或未来时间回退到当前维护时间。
    """
    if not value:
        return fallback
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return fallback
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    return min(parsed, fallback)


def apply_weight_decay(index: dict, now: Optional[datetime] = None) -> list[str]:
    """
    对活动知识执行幂等权重衰减，每经过一个新的完整 30 天周期权重减 1。
    """
    maintenance_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    decay_log = []

    for entry in index["entries"]:
        if entry.get("status") != "active":
            continue

        last_ref = _parse_utc(
            entry.get("lastReferencedAt", entry.get("createdAt")), maintenance_time
        )
        decay_watermark = (
            _parse_utc(entry["weightDecayedAt"], maintenance_time)
            if entry.get("weightDecayedAt")
            else last_ref
        )
        decay_start = max(last_ref, decay_watermark)
        elapsed_days = max(0, (maintenance_time - decay_start).days)
        decay_units = elapsed_days // 30
        if decay_units <= 0:
            continue

        old_weight = entry.get("weight", 10)
        new_weight = max(1, old_weight - decay_units)
        entry["weight"] = new_weight
        entry["weightDecayedAt"] = (
            decay_start + timedelta(days=decay_units * 30)
        ).isoformat()
        if new_weight < old_weight:
            decay_log.append(
                f"📉 DECAY  | `{entry['title'][:40]}` 权重 {old_weight} → {new_weight} "
                f"(新增{decay_units}个未引用周期)"
            )

    if decay_log:
        index["updatedAt"] = maintenance_time.isoformat()
    return decay_log


def update_cross_refs(
    index: dict,
    confirmed: list[dict],
    extended: list[dict],
    new_entries: list[dict],
) -> list[str]:
    """
    L6 交叉引用追踪：
    - CONFIRM：被证实的知识权重 +2，lastReferencedAt 刷新
    - EXTEND：被扩展的知识权重 +1，lastReferencedAt 刷新，iterationCount +1
    - NEW：新建卡片，无引用更新
    """
    log = []

    for conf in confirmed:
        eid = conf["matched_entry"]["id"]
        entry = find_entry_by_id(index, eid)
        if entry:
            referenced_at = _now_iso()
            new_item = conf["item"]
            entry["weight"] = entry.get("weight", 10) + 2
            entry["lastReferencedAt"] = referenced_at
            entry.setdefault("crossRefs", []).append({
                "source": new_item.get("source_project", "unknown"),
                "relation": RELATION_CONFIRM,
                "at": referenced_at,
            })
            log.append(f"📈 +2    | `{entry['title'][:40]}` 被新知识证实 → 权重 {entry['weight']}")

    for ext in extended:
        eid = ext["matched_entry"]["id"]
        entry = find_entry_by_id(index, eid)
        if entry:
            referenced_at = _now_iso()
            entry["weight"] = entry.get("weight", 10) + 1
            entry["iterationCount"] = entry.get("iterationCount", 0) + 1
            entry["version"] = entry.get("version", 1) + 1
            entry["lastReferencedAt"] = referenced_at
            new_item = ext["item"]
            entry.setdefault("crossRefs", []).append({
                "source": new_item.get("source_project", "unknown"),
                "relation": RELATION_EXTEND,
                "at": referenced_at,
            })
            log.append(f"📈 +1    | `{entry['title'][:40]}` 被新知识扩展 → 权重 {entry['weight']} v{entry['version']}")

    return log


# ─── 空白领域扫描 ─────────────────────────────────────────


def scan_blank_domains(index: dict) -> list[str]:
    """检查哪些领域还没有知识积累。"""
    blanks = []
    for domain in DOMAINS:
        count = index["domains"].get(domain, 0)
        if count == 0:
            blanks.append(domain)
    return blanks


def scan_domain_imbalance(index: dict) -> dict:
    """检查领域分布是否失衡。"""
    total = index["totalKnowledge"]
    if total == 0:
        return {}

    imbalance = {}
    for domain, count in index["domains"].items():
        pct = count / total * 100
        if pct > 40:  # 超过 40% 视为失衡
            imbalance[domain] = {"count": count, "pct": round(pct, 1), "issue": "占比过高"}
        elif pct == 0:
            imbalance[domain] = {"count": 0, "pct": 0, "issue": "空白领域"}
    return imbalance


# ─── 学习报告输出 ─────────────────────────────────────────


def generate_report(
    project_name: str,
    principles: list[dict],
    assets: list[dict],
    iteration_result: dict,
    decay_log: list[str],
    cross_ref_log: list[str],
    index: dict,
    retired_candidates: list[dict],
) -> str:
    """生成结构化学习报告（v2：完整六层）。"""
    lines = [
        f"## 📊 学习报告：{project_name}",
        "",
    ]

    # L1
    lines.append(f"### 🔬 L1 · 提取原理（{len(principles)} 条）")
    if principles:
        for p in principles:
            signal = p.get("signal_count", "?")
            lines.append(f"- **{p['title']}** (信号强度: {signal}) — {p['content'][:80]}...")
    else:
        lines.append("- 未提取到明确的原理性内容")
    lines.append("")

    # L2
    lines.append(f"### 📦 L2 · 可复用资产（{len(assets)} 件）")
    type_icons = {"template": "📄", "checklist": "✅", "pitfall": "⚠️", "framework": "🔧"}
    if assets:
        for a in assets:
            icon = type_icons.get(a["type"], "📌")
            lines.append(f"- [{icon} {a['type']}] **{a['title'][:60]}**")
    else:
        lines.append("- 未提取到可复用资产")
    lines.append("")

    # L3
    domain_counts: dict[str, int] = {}
    for p in principles:
        d = classify_domain(p["content"])
        domain_counts[d] = domain_counts.get(d, 0) + 1
    for a in assets:
        d = classify_domain(a.get("content", a.get("title", "")))
        domain_counts[d] = domain_counts.get(d, 0) + 1
    domain_str = ", ".join(f"`{d}` ×{c}" for d, c in sorted(domain_counts.items()))
    lines.append(f"### 🏷️ L3 · 分类")
    lines.append(f"- 领域分布：{domain_str or '无'}")
    lines.append(f"- 索引总数：{index['totalKnowledge']} 条")
    lines.append("")

    # L4
    lines.append(f"### 🔄 L4 · 迭代检测")
    ir = iteration_result
    new_count = len(ir["new_items"])
    conf_count = len(ir["confirmed"])
    ext_count = len(ir["extended"])
    conflict_count = len(ir["conflicts"])

    summary_parts = []
    if new_count > 0:
        summary_parts.append(f"🆕 新建 {new_count} 条")
    if conf_count > 0:
        summary_parts.append(f"✅ 证实已有 {conf_count} 条")
    if ext_count > 0:
        summary_parts.append(f"📝 扩展已有 {ext_count} 条")
    if conflict_count > 0:
        summary_parts.append(f"⚠️ 发现冲突 {conflict_count} 处")

    if not summary_parts:
        lines.append("- 本次为初始学习，无迭代事件")
    else:
        lines.append(f"- {', '.join(summary_parts)}")
        for log_line in ir["iteration_log"]:
            lines.append(f"  {log_line}")
    lines.append("")

    # L5
    lines.append("### 🗑️ L5 · 退役建议")
    if retired_candidates:
        for rc in retired_candidates:
            lines.append(f"- ⚠️ `{rc['title']}` — {', '.join(rc['retireReasons'])}")
    else:
        lines.append("- 无退役候选")
    lines.append("")

    # L6
    lines.append("### 📊 L6 · 权重更新")
    if cross_ref_log:
        lines.append("**交叉引用更新：**")
        for log in cross_ref_log:
            lines.append(f"  {log}")
    if decay_log:
        lines.append("**权重衰减：**")
        for log in decay_log:
            lines.append(f"  {log}")
    lines.append(f"- 新增 {new_count} 条知识，初始权重 10")
    lines.append(f"- 知识库总计 {index['totalKnowledge']} 条，活跃 {sum(1 for e in index['entries'] if e['status'] == 'active')} 条")

    # 空白领域提示
    blanks = scan_blank_domains(index)
    if blanks:
        lines.append("")
        lines.append(f"### 🔍 空白领域预警")
        lines.append(f"- 以下领域尚无知识积累：{', '.join(f'`{b}`' for b in blanks)}")

    lines.append("")

    return "\n".join(lines)


# ─── CLI 命令 ─────────────────────────────────────────────


def cmd_ingest(md_path: str, output_report: bool = True) -> str:
    """摄入单个项目 MD，执行完整六层管线。"""
    md_file = Path(md_path)
    if not md_file.exists():
        return f"❌ 文件不存在: {md_path}"

    project_name = md_file.stem
    md_content = md_file.read_text(encoding="utf-8")
    index = load_index()

    # 收集已有 slug（用于去重）
    existing_slugs = {e.get("slug", "") for e in index["entries"]}

    # L1: 提取原理
    raw_principles = extract_principles(md_content, project_name)
    for p in raw_principles:
        p["slug"] = _make_unique_slug(p["base_slug"], existing_slugs)
        existing_slugs.add(p["slug"])

    # L2: 提取资产
    raw_assets = extract_assets(md_content, project_name)
    for a in raw_assets:
        a["slug"] = _make_unique_slug(a["base_slug"], existing_slugs)
        existing_slugs.add(a["slug"])

    # 构建待迭代的新知识清单（L1+L2 合并）
    new_items_for_iteration = []
    for p in raw_principles:
        new_items_for_iteration.append({
            "title": p["title"],
            "content": p["content"],
            "type": "principle",
            "domain": classify_domain(p["content"]),
            "slug": p["slug"],
            "source_project": project_name,
            "_raw": p,
        })
    for a in raw_assets:
        domain = classify_domain(a.get("content", a.get("title", "")))
        new_items_for_iteration.append({
            "title": a["title"],
            "content": a["content"],
            "type": a["type"],
            "domain": domain,
            "slug": a["slug"],
            "source_project": project_name,
            "_raw": a,
        })

    # L4: 迭代检测
    iteration_result = detect_iterations(new_items_for_iteration, index)

    # L6: 权重衰减（摄入时兼容执行，日常维护可单独运行）
    decay_log = apply_weight_decay(index)

    # L6: 交叉引用更新（CONFIRM/EXTEND 更新已有知识权重）
    cross_ref_log = update_cross_refs(
        index,
        iteration_result["confirmed"],
        iteration_result["extended"],
        iteration_result["new_items"],
    )

    # ── 处理 NEW 和 EXTEND，写入文件 ──
    # EXTEND：更新已有卡片，存档旧版本
    for ext in iteration_result["extended"]:
        matched = ext["matched_entry"]
        new_item = ext["item"]["_raw"]
        merged_content = new_item.get("content", "")
        # 读取旧内容做合并
        old_card_path = resolve_knowledge_card_path(
            matched["layer"], matched["slug"], matched["type"]
        )
        old_content = ""
        if old_card_path.exists():
            old_text = old_card_path.read_text(encoding="utf-8")
            # 提取「核心内容」部分
            core_match = re.search(r"## 核心内容\n\n(.*?)(?:\n##|\Z)", old_text, re.DOTALL)
            if core_match:
                old_content = core_match.group(1).strip()

        # 存档旧版本
        _save_iteration_archive(matched, matched, old_content or merged_content)

        # 合并内容写到相同文件
        combined = f"{old_content}\n\n---\n\n## v{matched['version'] + 1} 新增（来自 {project_name}）\n\n{merged_content}"
        write_knowledge_card(
            layer=matched["layer"],
            slug=matched["slug"],
            title=matched["title"],
            domain=matched["domain"],
            ktype=matched["type"],
            source_project=f"{matched.get('sourceProject', '')}, {project_name}",
            content=combined,
            version=matched["version"] + 1,
            weight=matched["weight"],
        )

    # NEW：新建卡片
    for new_item in iteration_result["new_items"]:
        raw = new_item["_raw"]
        domain = new_item["domain"]
        ktype = new_item["type"]
        # 确定 layer
        if ktype == "principle":
            layer = "L1-principles"
        else:
            layer = "L2-assets"

        write_knowledge_card(
            layer=layer,
            slug=new_item["slug"],
            title=new_item["title"],
            domain=domain,
            ktype=ktype,
            source_project=project_name,
            content=raw.get("content", ""),
            usage_scenario=raw.get("usage_scenario", "通用场景"),
            prerequisites=raw.get("prerequisites", "无特殊前置条件"),
            limitations=raw.get("limitations", "暂无已知局限"),
        )
        add_to_index(
            index,
            knowledge_id=str(uuid.uuid4())[:8],
            title=new_item["title"],
            domain=domain,
            ktype=ktype,
            layer=layer,
            slug=new_item["slug"],
            source_project=project_name,
        )

    # L5: 退役扫描
    retired_candidates = retire_scan(index)

    # 最终保存索引
    save_index(index)

    # 生成报告
    report = generate_report(
        project_name,
        raw_principles,
        raw_assets,
        iteration_result,
        decay_log,
        cross_ref_log,
        index,
        retired_candidates,
    )

    if output_report:
        print(report)

    return report


def cmd_scan() -> str:
    """扫描 projects/ 目录下所有未学习的 MD 文件。"""
    projects_dir = PROJECTS_DIR
    if not projects_dir.exists():
        return "⚠️ projects/ 目录不存在，请先创建并放入项目 MD 文件"

    md_files = list(projects_dir.glob("*.md"))
    # 排除 .gitkeep
    md_files = [f for f in md_files if f.name != ".gitkeep"]
    if not md_files:
        return "⚠️ projects/ 目录下没有 .md 文件"

    # 读取已学习的文件记录
    learned_path = KNOWLEDGE_DIR / ".learned.json"
    learned: list[str] = []
    if learned_path.exists():
        learned = json.loads(learned_path.read_text(encoding="utf-8"))

    results = []
    for md_file in md_files:
        if str(md_file) in learned:
            continue
        print(f"\n{'='*60}")
        print(f"🔍 正在学习：{md_file.name}")
        print(f"{'='*60}")
        results.append(cmd_ingest(str(md_file)))
        learned.append(str(md_file))

    # 更新已学习记录
    learned_path.parent.mkdir(parents=True, exist_ok=True)
    learned_path.write_text(json.dumps(learned, ensure_ascii=False, indent=2), encoding="utf-8")

    if not results:
        return "✅ 所有 MD 文件已学习完毕，无新文件"

    return f"✅ 已学习 {len(results)} 个新项目"


def cmd_lifecycle_maintenance(dry_run: bool = False) -> str:
    """
    独立执行 L6 衰减与 L5 候选扫描；默认保存权重，dry-run 仅预览。
    """
    index = load_index()
    if not index["entries"]:
        return "📭 知识库为空"

    maintenance_time = datetime.now(timezone.utc)
    working_index = json.loads(json.dumps(index)) if dry_run else index
    decay_log = apply_weight_decay(working_index, maintenance_time)
    candidates = retire_scan(working_index, maintenance_time)
    if not dry_run and decay_log:
        save_index(working_index)

    mode = "预览" if dry_run else "已执行"
    lines = [f"## 🧹 生命周期维护（{mode}）", ""]
    if decay_log:
        lines.append("### L6 · 权重衰减")
        lines.extend(f"- {log}" for log in decay_log)
    else:
        lines.append("- 本次没有到期的权重衰减")

    lines.extend(["", "### L5 · 退役候选"])
    if candidates:
        for candidate in candidates:
            reasons = ", ".join(candidate["retireReasons"])
            lines.append(f"- `{candidate['id']}` {candidate['title']} — {reasons}")
        lines.append("")
        lines.append("退役仍需人工执行：`python learn.py retire <id> --reason \"退役原因\"`")
    else:
        lines.append("- 无退役候选")

    if dry_run:
        lines.append("")
        lines.append("- dry-run 未修改索引")
    return "\n".join(lines)


def cmd_overview() -> str:
    """输出知识库概览（含空白领域扫描）。"""
    index = load_index()
    if not index["entries"]:
        return "📭 知识库为空，请先运行 `python learn.py ingest <项目.md>`"

    active = [e for e in index["entries"] if e["status"] == "active"]
    retired = [e for e in index["entries"] if e["status"] == "retired"]

    lines = [
        "## 📚 知识库概览",
        f"- 总计：{index['totalKnowledge']} 条",
        f"- 活跃：{len(active)} 条",
        f"- 已退役：{len(retired)} 条",
        "",
        "### 领域分布",
    ]
    for domain, count in sorted(index["domains"].items(), key=lambda x: -x[1]):
        bar = "█" * min(count, 20)
        marker = " ⚠️ 空白" if count == 0 and domain != "general" else ""
        lines.append(f"- `{domain:<12}` {bar} {count}{marker}")

    lines.append("")
    lines.append("### 类型分布")
    for ktype, count in sorted(index["types"].items(), key=lambda x: -x[1]):
        lines.append(f"- `{ktype:<12}` {count} 条")

    lines.append("")
    lines.append("### Top 10 高权重知识")
    top = sorted(active, key=lambda e: -e["weight"])[:10]
    for i, entry in enumerate(top, 1):
        ref_count = len(entry.get("crossRefs", []))
        lines.append(
            f"{i}. [{entry['domain']}] **{entry['title']}** "
            f"(权重: {entry['weight']}, 迭代: {entry['iterationCount']}次, 引用: {ref_count}次)"
        )

    # 空白领域提示
    blanks = [d for d in DOMAINS if index["domains"].get(d, 0) == 0 and d != "general"]
    if blanks:
        lines.append("")
        lines.append("### 🔍 空白领域预警")
        lines.append(f"以下领域尚无知识积累：{', '.join(f'`{b}`' for b in blanks)}")
        lines.append("建议在后续项目中主动关注这些领域。")

    # 失衡检测
    imbalance = scan_domain_imbalance(index)
    if imbalance:
        issues = [f"`{d}`({info['pct']}%, {info['issue']})" for d, info in imbalance.items()]
        lines.append("")
        lines.append("### ⚖️ 领域失衡")
        lines.append(", ".join(issues))

    return "\n".join(lines)


def cmd_stats() -> str:
    """知识库健康度报告。"""
    index = load_index()

    if not index["entries"]:
        return "📭 知识库为空"

    entries = index["entries"]
    active = [e for e in entries if e["status"] == "active"]
    retired = [e for e in entries if e["status"] == "retired"]

    lines = [
        "## 🩺 知识库健康度报告",
        "",
        "### 基本信息",
        f"- 版本: {index.get('version', '1.0')}",
        f"- 最后更新: {index.get('updatedAt', '未知')[:19]}",
        f"- 总数: {len(entries)} | 活跃: {len(active)} | 退役: {len(retired)}",
        "",
        "### 📊 领域覆盖",
    ]

    for domain in DOMAINS:
        count = index["domains"].get(domain, 0)
        active_in_domain = sum(1 for e in active if e["domain"] == domain)
        pct = f"{count/max(1,len(entries))*100:.0f}%"
        bar = "█" * min(count, 15) + "░" * max(0, 15 - min(count, 15))
        status = "⬜ 空白" if count == 0 else "🟢" if count >= 3 else "🟡"
        lines.append(f"- {status} `{domain:<12}` {bar} {count}条 ({pct})")

    lines.append("")
    lines.append("### 📝 类型分布")
    for ktype in KNOWLEDGE_TYPES:
        count = index["types"].get(ktype, 0)
        pct = f"{count/max(1,len(entries))*100:.0f}%"
        lines.append(f"- `{ktype:<12}` {count}条 ({pct})")

    # 类型健康检查
    lines.append("")
    lines.append("### 🔍 诊断建议")
    principle_pct = index["types"].get("principle", 0) / max(1, len(entries)) * 100
    if principle_pct > 60:
        lines.append("- ⚠️ principle 占比过高，建议从项目中多提取 template/checklist/pitfall")
    if index["types"].get("pitfall", 0) == 0 and len(entries) > 5:
        lines.append("- ⚠️ 无 pitfall 类型知识，可能有踩坑经验未被提取")
    blanks = scan_blank_domains(index)
    if blanks:
        lines.append(f"- 🔍 空白领域：{', '.join(blanks)}，关注这些领域")

    # 退役候选
    candidates = retire_scan(index)
    if candidates:
        lines.append(f"- 🗑️ {len(candidates)} 条满足退役条件，运行 `python learn.py retire-scan` 查看")

    # 权重分布
    weights = [e["weight"] for e in active]
    if weights:
        avg_w = sum(weights) / len(weights)
        lines.append(f"- 📊 平均权重: {avg_w:.1f} | 最低: {min(weights)} | 最高: {max(weights)}")

    # 迭代次数
    iters = [e["iterationCount"] for e in active]
    never_iterated = sum(1 for i in iters if i == 0)
    lines.append(f"- 🔄 {never_iterated}/{len(active)} 条从未被迭代")

    return "\n".join(lines)


def cmd_search(query: str) -> str:
    """在知识库中搜索。"""
    index = load_index()
    query_lower = query.lower()

    results = []
    for entry in index["entries"]:
        score = 0
        if query_lower in entry["title"].lower():
            score += 10
        if query_lower in entry["domain"].lower():
            score += 3
        if query_lower in " ".join(entry.get("tags", [])).lower():
            score += 5

        if score > 0:
            results.append((score, entry))

    results.sort(key=lambda x: -x[0])

    if not results:
        return f"🔍 未找到与 '{query}' 相关的知识"

    lines = [f"## 🔍 搜索结果：'{query}'", ""]
    for score, entry in results[:15]:
        status_icon = "🟢" if entry["status"] == "active" else "⚫"
        refs = len(entry.get("crossRefs", []))
        lines.append(
            f"- {status_icon} [{entry['domain']}] **{entry['title']}** "
            f"(`{entry['layer']}`, 权重: {entry['weight']}, 引用: {refs})"
        )
        lines.append(f"  ID: `{entry['id']}` | 来源: {entry['sourceProject']}")

    return "\n".join(lines)


def cmd_retire(knowledge_id: str, reason: str) -> str:
    """退役指定知识条目。"""
    index = load_index()

    target = None
    for entry in index["entries"]:
        if entry["id"] == knowledge_id:
            target = entry
            break

    if not target:
        return f"❌ 未找到知识条目: {knowledge_id}"

    # 移动文件到 L5-retired
    source_layer = target["layer"]
    slug = target["slug"]
    source_path = resolve_knowledge_card_path(source_layer, slug, target["type"])

    if source_path.exists():
        retired_dir = LAYER_DIRS["L5-retired"]
        retired_dir.mkdir(parents=True, exist_ok=True)
        dest_path = retired_dir / f"{slug}.md"
        source_path.rename(dest_path)

        # 在文件头追加退役信息
        old_content = dest_path.read_text(encoding="utf-8")
        retire_note = f"\n> ⚠️ **已退役** ({_now_iso()})：{reason}\n"
        dest_path.write_text(retire_note + old_content, encoding="utf-8")

    # 更新索引状态
    target["status"] = "retired"
    target["retiredAt"] = _now_iso()
    target["retireReason"] = reason
    # 调减领域/类型计数
    target_domain = target["domain"]
    target_type = target["type"]
    if index["domains"].get(target_domain, 0) > 0:
        index["domains"][target_domain] -= 1
    if index["types"].get(target_type, 0) > 0:
        index["types"][target_type] -= 1
    index["updatedAt"] = _now_iso()

    save_index(index)

    return f"✅ 已退役: `{target['title']}`\n   原因: {reason}\n   文件移至: `L5-retired/{slug}.md`"


# ─── 入口 ─────────────────────────────────────────────────


def main():
    # Windows GBK 编码兼容：强制 stdout 使用 UTF-8
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if len(sys.argv) < 2:
        print(__doc__)
        return

    command = sys.argv[1]

    if command == "ingest" and len(sys.argv) >= 3:
        cmd_ingest(sys.argv[2])

    elif command == "scan":
        print(cmd_scan())

    elif command == "overview":
        print(cmd_overview())

    elif command == "stats":
        print(cmd_stats())

    elif command in {"maintain", "retire-scan"}:
        print(cmd_lifecycle_maintenance(dry_run="--dry-run" in sys.argv[2:]))

    elif command == "retire" and len(sys.argv) >= 3:
        knowledge_id = sys.argv[2]
        reason = "手动退役"
        for i, arg in enumerate(sys.argv):
            if arg == "--reason" and i + 1 < len(sys.argv):
                reason = sys.argv[i + 1]
                break
        print(cmd_retire(knowledge_id, reason))

    elif command == "search" and len(sys.argv) >= 3:
        print(cmd_search(sys.argv[2]))

    else:
        print(f"❌ 未知命令: {command}")
        print(__doc__)


if __name__ == "__main__":
    main()
