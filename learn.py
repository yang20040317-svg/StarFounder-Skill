"""
StarFounder 经验炼金引擎 — 学习脚本 v2

用途：摄入项目 MD 文件，按六层框架提取可复用知识，入库到 knowledge/ 目录。

用法：
    # 学习单个项目 MD
    python learn.py ingest projects/my-project.md

    # 扫描配置的所有目录（config.json 的 scan_roots）+ 当前工作区
    python learn.py scan
    python learn.py scan --workspace "D:\当前项目"   # 自动识别你正在编程的位置

    # 管理扫描源（替代手动改 junction）
    python learn.py config --list
    python learn.py config --add-root "D:\另一个项目"
    python learn.py config --remove-root "D:\旧项目"
    python learn.py config --auto-workspace on|off

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

import json
import os
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
CONFIG_PATH = SKILL_DIR / "config.json"
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


def _make_unique_slug(base_slug: str, existing_slugs: set) -> str:
    """
    确保 slug 唯一，但**不再用随机哈希生成孤儿卡**。

    撞名时保留原标题字面、追加确定性序号（如 `门控函数-2`）——可读、可关联，
    区别于旧版的随机 6 位哈希（如 `门控函数-c2f4fd`）。同名卡是否「真重复」或
    「同标题不同义」由入库流程的相似度决策（见 ingest 主流程 new_items 写盘阶段）
    判定：真重复走归因/跳过，不同义则在 crossRefs 建 RELATION_SAME_TITLE 互链。
    """
    if base_slug not in existing_slugs:
        return base_slug
    # NOTE: 撞名不哈希，改用确定性序号后缀，避免炸成互不关联的哈希孤儿卡。
    suffix = 2
    while f"{base_slug}-{suffix}" in existing_slugs:
        suffix += 1
    return f"{base_slug}-{suffix}"


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


# ─── L1 事后校验：语义一致性检测 ─────────────────────────
# 目的：L1 抽取可能把不相关的「行动指引」塞进一条「原则陈述」，
# 形成主题错位的卡片。写入库前必须过滤「行动指引/场景」与「原则陈述」脱节的卡片。

# 一致性阈值：原则陈述与行动指引的实词重叠度低于此值判为脱节。
# 数值偏小是因为采用「实词召回」口径（共享实词数 / 较少方实词数），
# 同义改写会共享核心单字，故无需高阈值即可放行。
CONSISTENCY_OVERLAP_THRESHOLD = 0.12

# 中文停用字：无独立语义或跨主题高频出现，参与重叠会制造噪声，需剔除。
_STOP_CHARS = set(
    "的了个是在应要不对我你他这那也就都也还先再上下中内后前给对把被让使将从到与和或但却而因所以如果因为行动必须需要应该避免选择优先解决处理"
)

# 互斥语义标记：原则陈述与行动指引若分属对立极性，且无共享实体，则判为矛盾。
_NEGATION_MARKERS = ("不要", "避免", "禁止", "拒绝", "别", "切勿")


def _parse_principle_parts(content: str) -> dict[str, str]:
    """
    从 L1 卡片 content 中拆出「原则陈述」与「行动指引」两段正文。

    解析失败时返回空串，交由调用方按缺段处理。
    """
    def _section(name: str) -> str:
        match = re.search(rf"### {name}\s*\n+(.*?)(?=\n### |\Z)", content, re.DOTALL)
        return match.group(1).strip() if match else ""

    return {
        "statement": _section("原则陈述"),
        "rationale": _section("推导依据"),
        "action": _section("行动指引"),
    }


def _content_tokens(text: str) -> set[str]:
    """
    抽取有信息量的实词 token：中文单字（去停用字）+ 长度>2 的英文词。

    用单字而非 2-gram：同义改写常保留核心单字（如「热度评分」与「综合热度」共享「热/度」），
    2-gram 对措辞差异过于敏感，会把合理的同义重述误判为错位。
    """
    tokens: set[str] = set()
    for ch in re.findall(r'[\u4e00-\u9fff]', text):
        if ch not in _STOP_CHARS:
            tokens.add(ch)
    tokens.update(w for w in re.findall(r'[a-zA-Z]+', text.lower()) if len(w) > 2)
    return tokens


def _clean_summary(body: str, limit: int = 400) -> str:
    """生成注入用干净摘要：跳过 fenced 代码块、表格行、分隔符与迭代残片，取前 limit 字。

    召回时直接 body[:400] 会把代码块/表格碎片原样 dump 进上下文，可读性差。
    这里逐行过滤：代码块（``` 围栏内）整段跳过，孤立的 Markdown 表格行（以 | 起止
    或全是 |---）也跳过，仅作版式装饰的 `---` 分隔符与 `## vN 新增（来自...）` 这类
    迭代残片同样剔除，只保留叙述性内容，再按字符上限裁剪。
    """
    lines = body.splitlines()
    keep: list[str] = []
    in_code = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            # 进入/离开代码块围栏，整段不计
            in_code = not in_code
            continue
        if in_code:
            continue
        # 跳过表格行：以 | 开头或纯分隔行（|---|---|）
        if stripped.startswith("|") or re.match(r'^\s*\|?[-:\s|]+\|?\s*$', stripped):
            if "|" in stripped:
                continue
        # NOTE: 清理版式装饰与迭代残片，避免无语义噪声污染召回上下文。
        # 1) 纯 `---` / `***` / `___` 分隔符（水平线），无叙述价值；
        # 2) `## vN 新增（来自...）` 类迭代元数据标题，是 L4 版本演进残片，非知识正文。
        if stripped in ("---", "***", "___"):
            continue
        if re.match(r'^#{1,6}\s*v\d+\s*新增', stripped):
            continue
        if not stripped:
            continue
        keep.append(stripped)

    cleaned = " ".join(keep)
    return cleaned[:limit] + ("…" if len(cleaned) > limit else "")


# 业务标签词表（domain 无关）：覆盖常见技术栈 / 设计模式 / 典型问题类。
# 用于 backfill 自动补 tag，让 recall 从「正文子串碰巧命中」升级为「业务标签语义命中」。
TAG_VOCAB_EN = {
    # 基础设施 / 部署
    "docker", "dockerfile", "kubernetes", "k8s", "nginx", "proxy", "ssl", "tls",
    "ci", "cd", "deploy", "docker-compose", "cron", "systemd", "supervisor",
    # 并发 / 分布式
    "multithread", "thread", "async", "await", "coroutine", "lock", "deadlock",
    "mutex", "queue", "channel", "race", "atomic", "idempotent", "幂等",
    # 网络 / 协议
    "grpc", "graphql", "websocket", "oauth", "jwt", "cors", "http", "https",
    "rest", "rpc", "tcp", "udp", "dns", "cdn",
    # 数据 / 存储
    "redis", "cache", "sql", "mysql", "postgres", "index", "sqlite", "mongodb",
    "orm", "migration", "pagination", "分页", "分库", "分表", "replication",
    # 可靠性模式
    "retry", "重试", "rate-limit", "限流", "circuit-breaker", "熔断", "fallback",
    "降级", "timeout", "超时", "backoff", "幂等",
    # 抓取 / 解析
    "scrapy", "selenium", "playwright", "puppeteer", "xpath", "css-selector",
    "dom", "html-parsing", "反爬", "爬虫", "render", "渲染", "headless",
    # 前端 / 框架
    "react", "vue", "svelte", "fastapi", "flask", "django", "express", "spring",
    "pytest", "mock", "jest", "typescript", "webpack", "vite",
    # 质量 / 运维
    "logging", "日志", "monitor", "监控", "trace", "灰度", "canary", "dedup",
    "去重", "compress", "压缩", "encrypt", "加密", "validate", "校验", "auth", "鉴权",
}
# 中文业务短语（2-4 字，作为整词标签，避免单字碎片）
TAG_VOCAB_CN = {
    # 原技术栈术语
    "限流", "重试", "缓存", "并发", "死锁", "分页", "鉴权", "反爬", "爬虫", "解析",
    "渲染", "降级", "熔断", "幂等", "去重", "压缩", "加密", "日志", "监控", "灰度",
    "超时", "兜底", "隔离", "限频", "热更新", "懒加载", "预加载", "增量",
    # NOTE: 以下为存量碎卡正文高频业务词（原词表缺失，导致 backfill 对中文卡推导为 0）。
    # 覆盖验证/依赖/部署/调试等通用工程主题，让 _auto_tag 能命中正文中文业务词。
    "验证", "依赖", "安装", "部署", "调试", "性能", "异常", "协议", "接口", "权限",
    "配置", "环境", "构建", "发布", "回滚", "迁移", "同步", "异步", "锁", "事务",
    "索引", "查询", "路由", "组件", "模块", "封装", "抽象", "继承", "多态", "泛型",
    "类型", "泛型", "内存", "泄漏", "溢出", "注入", "跨域", "编码", "解码", "序列化",
    "反序列化", "状态", "生命周期", "副作用", "纯函数", "递归", "迭代", "算法", "复杂度",
    "决策", "复盘", "协作", "对齐", "评审", "架构", "设计", "方案", "机制", "流程",
    "策略", "模型", "抽象", "边界", "契约", "规范", "约束", "权衡", "取舍", "演进",
}


def _auto_tag(entry: dict, max_tags: int = 6) -> list[str]:
    """从标题 + 正文推导 domain 无关的业务标签（供 backfill 批量补 tag）。

    标签来源：
    1. 英文/中文业务词表精确匹配（TAG_VOCAB_EN / TAG_VOCAB_CN），避免无意义的碎词；
    2. 标题里连续的中文技术名词短语（2 字以上）作为候选，但过滤纯停用语。

    产出标签刻意与 domain 解耦——domain 表示「领域归属」，tag 表示「用了什么技术 /
    踩了什么坑」，recall 按 tag 召回即「语义命中」而非「碰巧子串命中」。
    """
    title = entry.get("title", "")
    body = _load_card_body(entry)
    haystack = f"{title}\n{body}".lower()

    found: list[str] = []
    seen = set()

    # 1) 业务词表匹配
    for vocab in TAG_VOCAB_EN:
        if vocab in haystack and vocab not in seen:
            found.append(vocab)
            seen.add(vocab)
    for vocab in TAG_VOCAB_CN:
        if vocab in haystack and vocab not in seen:
            found.append(vocab)
            seen.add(vocab)

    # 2) 中文业务词：从「标题+正文」提取，命中 TAG_VOCAB_CN 即作为 tag。
    # NOTE: 原实现仅扫标题 3-5 字技术短语，导致正文有料但标题碎的卡（如「阶段5: 协程编排」）
    # 推导为 0。改为对 haystack 整体扫描 2-4 字中文短语，命中词表即采纳，不再苛求技术后缀。
    # 同时过滤含指代/虚字的碎片（样/这/那/其/该/如何/为什么/怎么），避免纯描述词混入。
    _cn_stop = ("样", "这", "那", "其", "该", "如何", "为什么", "怎么", "我们", "你们", "他们")
    for phrase in re.findall(r'[\u4e00-\u9fff]{2,4}', haystack):
        if phrase in seen:
            continue
        if any(stop in phrase for stop in _cn_stop):
            continue
        if phrase in TAG_VOCAB_CN:
            found.append(phrase)
            seen.add(phrase)

    return found[:max_tags]


def validate_principle_consistency(principle: dict) -> dict[str, object]:
    """
    单条 L1 卡片的语义一致性校验。

    返回 {consistent, score, reason}：
    - consistent: 行动指引/场景是否与原则陈述主题一致
    - score:      两者实词重叠度（0.0~1.0），缺段时记为 None
    - reason:     人类可读的判定依据，用于报告与人工复核
    """
    content = principle.get("content", "")
    parts = _parse_principle_parts(content)
    statement = parts["statement"]
    action = parts["action"]

    # 缺失核心小节无法判定，保守放行（缺段本身已由 _extract_principle_guidance 过滤）。
    if not statement or not action:
        return {"consistent": True, "score": None, "reason": "核心小节缺失，跳过一致性判定"}

    # 仅比对「原则陈述」与「行动指引」两段正文，标题不作为重叠来源，
    # 否则原则的高层锚点会系统性抬高重叠度、掩盖行动指引的真实错位。
    statement_tokens = _content_tokens(statement)
    action_tokens = _content_tokens(action)

    if not statement_tokens or not action_tokens:
        return {"consistent": True, "score": None, "reason": "可分词信息不足，跳过一致性判定"}

    # 实词召回口径：共享实词数 / 较少一方的实词数，对同义改写更宽容。
    shared = len(statement_tokens & action_tokens)
    overlap = shared / min(len(statement_tokens), len(action_tokens))

    # 重叠度过低 → 行动指引与原则陈述主题脱节
    if overlap < CONSISTENCY_OVERLAP_THRESHOLD:
        return {
            "consistent": False,
            "score": round(overlap, 3),
            "reason": f"行动指引与原则陈述重叠度过低（{overlap:.2f}），疑似主题错位",
        }

    # 互斥极性检测：原则正向命令、行动却是否定禁止，且二者核心实体无交集 → 矛盾。
    statement_neg = any(m in statement for m in _NEGATION_MARKERS)
    action_neg = any(m in action for m in _NEGATION_MARKERS)
    if statement_neg != action_neg and not (statement_tokens & action_tokens):
        return {
            "consistent": False,
            "score": round(overlap, 3),
            "reason": "原则陈述与行动指引极性互斥且无共享实体",
        }

    return {"consistent": True, "score": round(overlap, 3), "reason": "主题一致"}


def audit_l1_consistency(principles: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    批量审计 L1 卡片，返回 (保留列表, 被过滤列表)。

    被过滤列表中的每条附加 `consistency` 诊断字段，供报告展示。
    """
    kept: list[dict] = []
    dropped: list[dict] = []
    for p in principles:
        diagnosis = validate_principle_consistency(p)
        if diagnosis["consistent"]:
            kept.append(p)
        else:
            dropped.append({**p, "consistency": diagnosis})
    return kept, dropped


# ─── L2 资产提取器（增强版）───────────────────────────────


def _extract_decision_context(surrounding_text: str) -> dict[str, str]:
    """
    从代码块前后的文本中抽取模板卡的三个决策字段。

    决策字段必须来自源 MD 里真实存在的标记句，绝不能用模板腔兜底：
    - 适用条件（when）：`适用`/`用在`/`用于`/`适合`/`当……时`/`场景` 等标记句
    - 禁忌（avoid）：`不要`/`别`/`禁止`/`避免`/`不要用`/`切忌`/`禁忌` 等否定标记句
    - 决策理由（why）：`因为`/`所以`/`选择…而非`/`而非`/`相比`/`注意`/`理由` 等因果/取舍句

    任一字段抽不到则返回空字符串，调用方据此判定该模板卡无决策上下文、
    不值得入库（避免退化成「代码快照」）。
    """
    # NOTE: 剥离代码围栏与 Markdown 噪声，只保留自然语言句子用于语义抽取。
    cleaned = re.sub(r"```.*?```", " ", surrounding_text, flags=re.DOTALL)
    cleaned = re.sub(r"^#{1,6}\s+.*$", " ", cleaned, flags=re.MULTILINE)
    sentences = [
        s.strip() for s in re.split(r"(?<=[。！？；])\s*|\n+", cleaned) if s.strip()
    ]

    when_markers = ("适用", "用在", "用于", "适合", "当", "场景", "仅在", "前提")
    avoid_markers = ("不要", "别", "禁止", "避免", "不要用", "切忌", "禁忌", "不应", "不应该", "慎用")
    why_markers = ("因为", "所以", "而非", "相比", "相比", "注意", "理由", "选择", "取舍", "权衡", "出于")

    when_sentences: list[str] = []
    avoid_sentences: list[str] = []
    why_sentences: list[str] = []
    for sentence in sentences:
        if any(marker in sentence for marker in when_markers) and sentence not in when_sentences:
            when_sentences.append(sentence)
        if any(marker in sentence for marker in avoid_markers) and sentence not in avoid_sentences:
            avoid_sentences.append(sentence)
        if any(marker in sentence for marker in why_markers) and sentence not in why_sentences:
            why_sentences.append(sentence)

    return {
        "when": "；".join(when_sentences).strip(),
        "avoid": "；".join(avoid_sentences).strip(),
        "why": "；".join(why_sentences).strip(),
    }


def _extract_template_guidance(
    title: str,
    code: str,
    language: str,
    decision: dict[str, str] | None = None,
) -> dict[str, str]:
    """
    为代码模板生成可复用的说明、参数、返回值和使用指导。

    代码仍作为模板的一部分保留，但必须被语义说明包裹。三个决策字段
    （适用条件 / 禁忌 / 决策理由）只能来自 `_extract_decision_context` 的真实抽取，
    绝不允许用「由模板中的变量决定」等占位腔填充。若 decision 为 None 或任一字段
    为空，则返回的 `decision_complete` 为 False，调用方据此丢弃该模板卡。
    """
    decision = decision or {"when": "", "avoid": "", "why": ""}
    decision_complete = all(decision.get(field) for field in ("when", "avoid", "why"))

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
    else:
        function_name = title or f"{language} 代码模板"
        parameters = "无显式参数（见代码中的变量与配置项）"
        description = f"提供一段可复用的 {language} 实现，用于：{title or '相关业务处理'}。"
        return_value = "由代码片段实际执行结果决定。"

    # NOTE: 使用指导与注意事项优先采用真实决策字段；仅在字段缺失（不入库路径）
    # 时回退为中性描述，绝不用模板腔伪装成「使用指导」。
    usage = decision.get("why") or (
        f"调用 `{function_name}` 前先确认上文中「适用条件」是否满足。"
        if function_match else
        "复制模板后，替换示例变量与业务依赖，再接入调用方。"
    )
    limitations = decision.get("avoid") or "见上方「禁忌」字段，无则需在引入前自行评估风险。"

    content = (
        f"### 模板说明\n\n{description}\n\n"
        f"### 参数\n\n{parameters}\n\n"
        f"### 返回值\n\n{return_value}\n\n"
        f"### 模板代码\n\n```{language}\n{code}\n```\n\n"
        f"### 适用条件（何时该用）\n\n{decision.get('when') or '（未提供）'}\n\n"
        f"### 禁忌（何时别用）\n\n{decision.get('avoid') or '（未提供）'}\n\n"
        f"### 决策理由（为何这样写）\n\n{decision.get('why') or '（未提供）'}\n\n"
        f"### 使用指导\n\n{usage}\n\n"
        f"### 注意事项\n\n{limitations}"
    )
    return {
        "content": content,
        "usage_scenario": decision.get("when") or f"适用于需要复用“{title or function_name}”逻辑的项目（决策上下文缺失）。",
        "prerequisites": "确认运行时版本、依赖包和输入数据结构与模板一致。",
        "limitations": limitations,
        "decision_complete": decision_complete,
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
    # NOTE: Windows 下文件常为 CRLF，正则按 LF 编写；统一标准化避免匹配失败。
    md_content = md_content.replace("\r\n", "\n")
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

        # NOTE: 决策上下文来自代码块「前后」的自然语言，而非代码本身。
        # 取代码块前 600 字 + 后 400 字作为语义窗口，避免跨章节串味。
        ctx_start = max(0, match.start() - 600)
        ctx_end = min(len(md_content), match.end() + 400)
        surrounding = md_content[ctx_start:ctx_end]
        decision = _extract_decision_context(surrounding)
        guidance = _extract_template_guidance(template_title, code, lang, decision)

        # NOTE: 模板卡必须带「适用条件 / 禁忌 / 决策理由」三项决策上下文，
        # 否则只是代码快照，降级为不入库（仅记录来源项目，见下方 source_project 跳过）。
        if not guidance["decision_complete"]:
            continue

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
            "decision_complete": guidance["decision_complete"],
            "decision_when": decision["when"],
            "decision_avoid": decision["avoid"],
            "decision_why": decision["why"],
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
    # 同源去重召回阈值：正则卡的陷阱实词被小节卡「标题+陷阱」覆盖比例 ≥ 此值即判同源丢弃。
    SECTION_PITFALL_RECALL_THRESHOLD = 0.5
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
    # 小节卡的「标题 + 陷阱」联合实词，用于同源正则碎片的语义去重（见下方正则循环）。
    section_pitfall_tokens: list[set[str]] = []
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
        # NOTE: 同源去重基于「标题 + 陷阱」联合信号，比单看正文更能捕获同主题重述。
        section_pitfall_tokens.append(_content_tokens(f"{title} {pitfall}"))
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

            # NOTE: 同源去重——正则片段若与小节卡「标题+陷阱」语义高度重叠（同主题重述），
            # 视为已被更完整的小节卡覆盖，丢弃此碎片，避免同源陷阱重复成卡。
            if section_pitfall_tokens:
                reg_tokens = _content_tokens(pitfall)
                if reg_tokens:
                    recall = max(
                        len(reg_tokens & sec_tokens) / len(reg_tokens)
                        for sec_tokens in section_pitfall_tokens
                    )
                    if recall >= SECTION_PITFALL_RECALL_THRESHOLD:
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
RELATION_SAME_TITLE = "SAME_TITLE"  # 同标题不同义：需人工归并的同源卡家族


def _tokenize(s: str) -> set[str]:
    """中英文混合分词：中文 2-gram + 长度>2 的英文词。供重叠度与一致性检测复用。"""
    tokens: set[str] = set()
    chinese_chars = ''.join(re.findall(r'[\u4e00-\u9fff]', s))
    for i in range(len(chinese_chars) - 1):
        tokens.add(chinese_chars[i:i + 2])
    english_words = re.findall(r'[a-zA-Z]+', s.lower())
    tokens.update(w for w in english_words if len(w) > 2)
    return tokens


def _compute_overlap(new_title: str, existing_title: str) -> float:
    """计算两个标题的词汇重叠度。"""
    t1 = _tokenize(new_title)
    t2 = _tokenize(existing_title)
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
    """扫描满足退役条件的活动知识条目。

    退役原因分两类，便于人工裁决：
    - 老化退役（aging）：90 天未更新且权重≤5 / 120 天从未迭代 / 180 天未被引用
    - 空洞退役（hollow）：内容充实度 < HOLLOW_SCORE_THRESHOLD 且未被人工标记核心，
      不必等 180 天窗口，直接进候选。覆盖所有类型（含 template）——
      template 虽本就是「给他人填的壳」，但在充实度口径下大量 score=0 的空壳
      正是需要清理的噪声，故不再豁免。
    """
    scan_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    candidates = []
    # NOTE: 同一张卡可能被两条分支重复打分；批处理时缓存充实度结果避免重复读盘 IO。
    fulfillment_cache: dict[str, dict] = {}

    for entry in index["entries"]:
        if entry.get("status") != "active":
            continue

        # NOTE: 人工标记核心（index.json 中 entry 设 "core": true）免于任何自动退役，
        # 包括下方的空洞判定与时间窗口判定，避免误杀经人确认的关键知识。
        if entry.get("core") is True:
            continue

        reasons: list[str] = []
        categories: list[str] = []
        updated = _parse_utc(entry.get("updatedAt"), scan_time)
        last_ref = _parse_utc(entry.get("lastReferencedAt", entry["createdAt"]), scan_time)

        # 90 天未更新且权重低
        if (scan_time - updated) > timedelta(days=90) and entry["weight"] <= 5:
            reasons.append("90天未更新且权重≤5")
            categories.append("aging")

        # 120 天从未迭代
        created = _parse_utc(entry.get("createdAt"), scan_time)
        if (scan_time - created) > timedelta(days=120) and entry["iterationCount"] == 0:
            reasons.append("120天从未迭代")
            categories.append("aging")

        # 180 天未被引用
        if (scan_time - last_ref) > timedelta(days=180):
            reasons.append("180天未被引用")
            categories.append("aging")

        # NOTE: 空洞卡片——内容充实度低于阈值即为「装饰性空壳」，不必等 180 天时间窗口，
        # 直接进退役候选。充实度口径复用 score_content_fulfillment（< HOLLOW_SCORE_THRESHOLD）。
        # 命中后缓存到 fulfillment_cache，避免同一张卡在老化分支二次打分时重复读盘。
        if entry["id"] not in fulfillment_cache:
            fulfillment_cache[entry["id"]] = score_content_fulfillment(entry)
        fulfillment = fulfillment_cache[entry["id"]]
        if fulfillment["score"] < HOLLOW_SCORE_THRESHOLD:
            reasons.append(f"内容空洞（充实度{fulfillment['score']}）")
            categories.append("hollow")

        if reasons:
            candidates.append({**entry, "retireReasons": reasons, "retireCategory": categories})

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
    dropped_principles: list[dict] | None = None,
    ingest_skipped: list[dict] | None = None,
) -> str:
    """生成结构化学习报告（v2：完整六层）。"""
    dropped_principles = dropped_principles or []
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

    # L1 语义一致性校验（事后过滤）
    lines.append(f"### 🧪 L1 · 语义一致性校验（过滤 {len(dropped_principles)} 条）")
    if dropped_principles:
        for p in dropped_principles:
            diag = p.get("consistency", {})
            reason = diag.get("reason", "未知原因")
            score = diag.get("score")
            score_str = f"{score:.2f}" if isinstance(score, (int, float)) else "N/A"
            lines.append(f"- ⚠️ **{p['title']}** (重叠度 {score_str}) — {reason}")
    else:
        lines.append("- 全部保留，未发现主题错位")
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

    # 摄入前查重（治本方案）：跳过的高相似重复项
    ingest_skipped = ingest_skipped or []
    lines.append("")
    lines.append(f"### 🚫 摄入前查重（跳过 {len(ingest_skipped)} 条）")
    if ingest_skipped:
        lines.append("- 以下待入库知识与已有卡片正文高度相似，已跳过新建并归因到已有卡片：")
        for s in ingest_skipped:
            lines.append(
                f"  - **{s['item']['title'][:50]}** → 命中 `{s['matched_title'][:40]}` "
                f"(相似度 {s['score']:.0%})"
            )
    else:
        lines.append("- 无重复，本次摄入全部新建")

    # 空白领域提示
    blanks = scan_blank_domains(index)
    if blanks:
        lines.append("")
        lines.append(f"### 🔍 空白领域预警")
        lines.append(f"- 以下领域尚无知识积累：{', '.join(f'`{b}`' for b in blanks)}")

    lines.append("")

    return "\n".join(lines)


# ─── CLI 命令 ─────────────────────────────────────────────


def _resolve_same_title_collision(
    index: dict,
    new_item: dict,
    new_id: str,
    source_project: str = "unknown",
) -> tuple[str, list[dict]]:
    """
    处理新卡与同名已有卡的碰撞，消除「哈希孤儿」。

    返回 (action, targets)：
    - ("unique", [])：无同名卡，正常新建；
    - ("skip", [matched_entry])：与同名卡相似度 ≥ 阈值（真重复），已归因到已有卡
      （刷新 lastReferencedAt + 追加 PREINGEST_DEDUP crossRef），调用方不写盘、不建 entry；
    - ("linked", same_title_entries)：同标题不同义，调用方建卡后需在双方 crossRefs
      建双向 RELATION_SAME_TITLE，让同源卡家族互相可见、可被 dupcheck 识别为需人工归并。

    注意：真重复的主路径由 check_ingest_duplicates 在 L4 之后统一移除 new_item，
    此处为入库写盘阶段的兜底，确保同名真重复绝不新建孤儿卡。
    """
    raw = new_item.get("_raw", new_item)
    base_slug = raw.get("base_slug", new_item.get("slug", ""))
    ktype = new_item.get("type", raw.get("type", ""))

    same_title_entries = [
        e for e in index["entries"]
        if e.get("status") == "active" and (
            e.get("slug") == base_slug
            or e.get("slug", "").startswith(f"{base_slug}-")
        )
    ]
    if not same_title_entries:
        return "unique", []

    item_tokens = _similarity_tokens_from_content(raw.get("content", ""), ktype)
    best_id = None
    best_score = 0.0
    if item_tokens:
        for st in same_title_entries:
            st_tokens = _similarity_tokens_from_entry(st)
            if not st_tokens:
                continue
            union = item_tokens | st_tokens
            if not union:
                continue
            score = len(item_tokens & st_tokens) / len(union)
            if score > best_score:
                best_score = score
                best_id = st["id"]

    # 真重复：归因跳过（兜底；主路径已由 check_ingest_duplicates 处理）。
    if best_id and best_score >= INGEST_DEDUP_THRESHOLD:
        matched = find_entry_by_id(index, best_id)
        if matched:
            referenced_at = _now_iso()
            matched["lastReferencedAt"] = referenced_at
            matched.setdefault("crossRefs", []).append({
                "source": source_project,
                "relation": "PREINGEST_DEDUP",
                "at": referenced_at,
            })
        return "skip", [matched]

    # 同标题不同义：返回同源卡列表，由调用方建双向 RELATION_SAME_TITLE。
    return "linked", same_title_entries


def _link_same_title(index: dict, new_id: str, same_title_entries: list[dict]) -> None:
    """
    为新卡与同源卡家族建双向 RELATION_SAME_TITLE 关联（调用方已 add_to_index(new_id) 后使用）。
    让同一概念家族的卡互相可见、可被 dupcheck 识别为「需人工归并」而非「已去重」。
    """
    referenced_at = _now_iso()
    new_entry = find_entry_by_id(index, new_id)
    for st in same_title_entries:
        if new_entry:
            new_entry.setdefault("crossRefs", []).append({
                "source": st.get("id", "unknown"),
                "relation": RELATION_SAME_TITLE,
                "at": referenced_at,
            })
        st.setdefault("crossRefs", []).append({
            "source": new_id,
            "relation": RELATION_SAME_TITLE,
            "at": referenced_at,
        })


def _ensure_same_title_link(entry_a: dict, entry_b: dict) -> bool:
    """
    在两卡间补建双向 RELATION_SAME_TITLE 关联（去重，不覆盖已有）。

    用于存量回填：把 base slug 相同的存活卡两两互链，让同名概念家族互相可见。
    若任一方向已存在同源 SAME_TITLE 关联则跳过，返回 False 表示无新增。
    """
    referenced_at = _now_iso()
    a_refs = entry_a.setdefault("crossRefs", [])
    b_refs = entry_b.setdefault("crossRefs", [])

    a_has = any(
        r.get("source") == entry_b["id"] and r.get("relation") == RELATION_SAME_TITLE
        for r in a_refs
    )
    b_has = any(
        r.get("source") == entry_a["id"] and r.get("relation") == RELATION_SAME_TITLE
        for r in b_refs
    )
    if a_has and b_has:
        return False

    if not a_has:
        a_refs.append({
            "source": entry_b["id"],
            "relation": RELATION_SAME_TITLE,
            "at": referenced_at,
        })
    if not b_has:
        b_refs.append({
            "source": entry_a["id"],
            "relation": RELATION_SAME_TITLE,
            "at": referenced_at,
        })
    return True


def cmd_ingest(md_path: str, output_report: bool = True) -> str:
    """摄入单个项目 MD，执行完整六层管线。"""
    md_file = Path(md_path)
    if not md_file.exists():
        return f"❌ 文件不存在: {md_path}"

    project_name = md_file.stem
    md_content = _read_text_robust(md_file)
    index = load_index()

    # 收集已有 slug（用于去重）
    existing_slugs = {e.get("slug", "") for e in index["entries"]}

    # L1: 提取原理
    raw_principles = extract_principles(md_content, project_name)
    for p in raw_principles:
        p["slug"] = _make_unique_slug(p["base_slug"], existing_slugs)
        existing_slugs.add(p["slug"])

    # L1 事后校验：过滤「行动指引/场景」与「原则陈述」脱节的卡片
    raw_principles, dropped_principles = audit_l1_consistency(raw_principles)

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

    # ── 摄入前查重（治本）：NEW 类知识再做一次正文相似度检测，
    # 命中高相似则跳过新建、仅归因到已有卡片，从源头阻止近似模板重复入库。
    dedup_result = check_ingest_duplicates(iteration_result["new_items"], index)
    ingest_skipped = dedup_result["skipped"]
    iteration_result["new_items"] = dedup_result["kept"]

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
        base_slug = raw.get("base_slug", new_item["slug"])
        # 确定 layer
        if ktype == "principle":
            layer = "L1-principles"
        else:
            layer = "L2-assets"

        # ── 同标题相似度决策（消除哈希孤儿的核心）──
        # _resolve_same_title_collision：真重复（≥阈值）归因跳过，不同义返回同源卡列表。
        new_id = str(uuid.uuid4())[:8]
        action, targets = _resolve_same_title_collision(
            index, new_item, new_id, source_project=project_name
        )
        if action == "skip":
            # 真重复已归因到已有卡，不新建、不建 entry。
            continue

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
            knowledge_id=new_id,
            title=new_item["title"],
            domain=domain,
            ktype=ktype,
            layer=layer,
            slug=new_item["slug"],
            source_project=project_name,
        )

        # NOTE: 同标题不同义（linked）→ 双向建 RELATION_SAME_TITLE，让同源卡家族互相可见、
        # 可被 dupcheck 识别为需人工归并。slug 保留标题字面（确定性序号而非哈希）。
        if action == "linked":
            _link_same_title(index, new_id, targets)

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
        dropped_principles,
        ingest_skipped,
    )

    if output_report:
        print(report)

    return report


# scan 时跳过的目录：第三方依赖、版本控制、其他 Agent 数据、构建产物、缓存等
SCAN_EXCLUDE_DIRS = {
    "node_modules", ".git", ".codebuddy", ".backup", ".venv", "venv",
    "dist", "build", "__pycache__", ".next", "out", "target", "bin", "obj",
    ".idea", ".vscode", ".pytest_cache", "node_modules.lock", ".antigravity",
    ".workbuddy", ".agent", ".claude", ".cursor",
}


def _scan_md_files(roots) -> list:
    """递归收集多个根目录下所有 .md，跳过依赖/缓存/其他 Agent 数据目录与 .gitkeep。"""
    results = []
    for root in roots:
        root = Path(root).resolve()  # 解析 junction，确保 ** 递归稳定、顺序可追溯
        if not root.exists():
            continue
        for f in root.glob("**/*.md"):
            if f.name == ".gitkeep":
                continue
            if any(part in SCAN_EXCLUDE_DIRS for part in f.parts):
                continue
            results.append(f)
    results.sort(key=lambda p: str(p))
    return results


# ─── 扫描根配置：替代硬编码 projects/，支持多目录 + 自动识别当前工作区 ───

def _load_config() -> dict:
    """读取技能配置 config.json；缺失或损坏时返回默认值。"""
    default = {"scan_roots": [], "auto_include_workspace": True}
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                default.update({k: data[k] for k in default if k in data})
                return default
        except Exception:
            pass
    return default


def _save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_scan_roots(workspace: str = None) -> list:
    """返回所有扫描根目录（已去重、已存在性过滤）。

    - config.json 的 scan_roots
    - 旧版兼容：若 projects/ 自身是 junction（非技能目录本身），纳入
    - 工作区自动识别：传入的 workspace 参数，或环境变量 STARFOUNDER_WORKSPACE
      （auto_include_workspace 为 true 时启用；每日自动化通常不传，仅用固定 roots）
    """
    cfg = _load_config()
    roots = list(cfg.get("scan_roots", []))

    # 旧 junction 兼容：仅当 projects/ 本身是 junction（重解析点）时，纳入其目标目录
    try:
        if PROJECTS_DIR.exists() and getattr(os.stat(PROJECTS_DIR), "st_reparse_point", 0):
            roots.append(str(PROJECTS_DIR.resolve()))
    except Exception:
        pass

    # 工作区自动识别
    ws = workspace or (os.environ.get("STARFOUNDER_WORKSPACE") if cfg.get("auto_include_workspace", True) else None)
    if ws:
        roots.append(ws)

    seen, out = set(), []
    for r in roots:
        try:
            p = Path(r)
        except Exception:
            continue
        if not p.exists():
            continue
        rp = str(p.resolve())
        if rp in seen:
            continue
        seen.add(rp)
        out.append(p.resolve())
    return out


def _read_text_robust(path: Path) -> str:
    """读取文本：优先 utf-8，失败回退 gbk，再回退 latin-1。

    兼容中文 Windows 下常见的 GBK 编码 Markdown，避免扫描时因编码崩溃。
    读取后将 CRLF 统一为 LF，避免后续正则把 \r 当作普通字符处理。
    """
    raw = path.read_bytes()
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            return raw.decode(enc).replace("\r\n", "\n")
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace").replace("\r\n", "\n")


def _scan_gate(md_file: Path, md_content: str, project_name: str) -> tuple[list[dict], list[str]]:
    """
    scan 前置闸门：对单个 MD 文件做决策字段 / 充实度复核。

    只有能产出高质量资产的文件才应进入 ingest；纯占位腔 / 裸代码快照 /
    无决策上下文的模板会被过滤，避免把旧 projects/ 里的垃圾重新灌回知识库。

    返回 (passed_assets, reject_reasons)。passed_assets 非空表示该文件可通过闸门。
    """
    assets = extract_assets(md_content, project_name)
    passed: list[dict] = []
    reasons: list[str] = []

    # 预检：文件里是否存在「看起来能当模板的代码块」但 extract_assets 没产出 template。
    # 这种情况通常是因为决策字段缺失被内部过滤，需要给出明确原因。
    has_qualified_code = False
    for match in re.finditer(r"```(\w+)?\n(.*?)```", md_content, re.DOTALL):
        code = match.group(2).strip()
        code_lines = [l for l in code.split("\n") if l.strip()]
        if len(code) >= 50 and len(code_lines) >= 3:
            has_qualified_code = True
            break
    has_template_asset = any(a.get("type") == "template" for a in assets)

    for asset in assets:
        title = asset.get("title", "")[:30]
        # 模板必须带完整决策上下文，否则只是代码快照
        if asset.get("type") == "template" and not asset.get("decision_complete"):
            reasons.append(f"模板「{title}」缺少决策字段（适用条件/禁忌/决策理由）")
            continue
        score_info = _score_asset_fulfillment(asset)
        if score_info["hollow"]:
            reasons.append(f"资产「{title}」内容空洞（充实度 {score_info['score']}）")
            continue
        passed.append(asset)

    if not passed:
        if has_qualified_code and not has_template_asset:
            reasons.append("模板代码块缺少决策字段（适用条件/禁忌/决策理由）")

        # 若文件明确写了某种资产的小节标题，却未产出任何对应 asset，
        # 说明该小节内容被原始提取规则过滤，通常是空洞占位腔或信号不足。
        if re.search(r"原理|原则|为什么|核心|本质|底层|决策|权衡", md_content) and not any(
            a.get("type") == "principle" for a in assets
        ):
            reasons.append("原理/原则段落内容未达门槛（可能为空洞占位腔）")
        if re.search(r"检查|清单|checklist|上线|部署|发布|验证|核对|验收", md_content, re.IGNORECASE) and not any(
            a.get("type") == "checklist" for a in assets
        ):
            reasons.append("检查清单段落内容未达门槛（可能为空洞占位腔）")
        if re.search(r"坑|陷阱|风险|问题|错误|失败", md_content) and not any(
            a.get("type") == "pitfall" for a in assets
        ):
            reasons.append("陷阱/风险段落内容未达门槛（可能为空洞占位腔）")

        if not reasons:
            reasons.append("未检测到可入库资产（内容可能被原始提取规则过滤或为空洞占位腔）")

    return passed, reasons


def cmd_scan(workspace: str = None) -> str:
    """扫描 config.json 配置的所有扫描根 + 可选工作区：新增或内容有改动（mtime 变化）的文件都会重新摄入；未改动的文件跳过，避免重复。"""
    roots = _get_scan_roots(workspace)
    if not roots:
        return ("⚠️ 没有可扫描的目录。请在 config.json 的 scan_roots 中添加目录，"
                "或运行 `python learn.py config --add-root <路径>`。")

    md_files = _scan_md_files(roots)
    if not md_files:
        return "⚠️ 所有扫描根目录下都没有可学习的 .md 文件"

    # 读取已学习记录。新格式：{ "绝对路径": mtime_float }
    # 兼容旧版 list[str]：迁移为 dict 并记录当前 mtime（此后的修改才会触发重学，旧文件本次不重扫）。
    learned_path = KNOWLEDGE_DIR / ".learned.json"
    learned: dict[str, float] = {}
    if learned_path.exists():
        raw = json.loads(learned_path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            for p in raw:
                try:
                    learned[p] = Path(p).stat().st_mtime
                except Exception:
                    learned[p] = 0.0
        else:
            learned = {str(k): float(v) for k, v in raw.items()}

    new_count = 0
    updated_count = 0
    gate_skipped = 0
    failed = []
    for md_file in md_files:
        key = str(md_file)
        try:
            cur_mtime = md_file.stat().st_mtime
        except Exception:
            cur_mtime = 0.0
        # 未改动（路径已记录且 mtime 一致）-> 跳过
        if key in learned and learned[key] == cur_mtime:
            continue
        is_update = key in learned

        # NOTE: scan gate 在真正 ingest 之前复核决策字段与充实度，
        # 避免旧 projects/ 里的占位腔/裸代码快照被重新灌入知识库。
        try:
            md_content = _read_text_robust(md_file)
            passed_assets, gate_reasons = _scan_gate(md_file, md_content, md_file.stem)
        except Exception as e:
            failed.append((key, f"gate 复核失败：{e}"))
            print(f"⚠️ gate 复核失败（已跳过）：{md_file.name} — {e}")
            continue

        if not passed_assets:
            gate_skipped += 1
            print(f"\n🚫 闸门拦截：{md_file.name}")
            for reason in gate_reasons[:3]:
                print(f"   - {reason}")
            if len(gate_reasons) > 3:
                print(f"   ... 等 {len(gate_reasons)} 条原因")
            # 被 gate 拦截的文件不写入 learned，下次修改后仍有机会被重新评估
            continue

        print(f"\n{'='*60}")
        print(f"🔍 正在学习：{md_file.name}" + ("（已修改，重新摄入）" if is_update else ""))
        print(f"{'='*60}")
        try:
            cmd_ingest(key)
            learned[key] = cur_mtime
            if is_update:
                updated_count += 1
            else:
                new_count += 1
            # 增量写入，避免中途崩溃丢失进度
            learned_path.parent.mkdir(parents=True, exist_ok=True)
            learned_path.write_text(json.dumps(learned, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            failed.append((key, str(e)))
            print(f"⚠️ 学习失败（已跳过）：{e}")

    # 持久化：确保 dict 格式与最新 mtime 落盘（即使本轮全部跳过也要写，
    # 否则跨 run 无法检测文件修改——每次都从旧 list 重新迁移成当前 mtime 会漏掉改动）。
    learned_path.parent.mkdir(parents=True, exist_ok=True)
    learned_path.write_text(json.dumps(learned, ensure_ascii=False, indent=2), encoding="utf-8")

    if new_count == 0 and updated_count == 0 and gate_skipped == 0 and not failed:
        return "✅ 所有 MD 文件已是最新，无新增/无修改"

    parts = []
    if new_count:
        parts.append(f"新增 {new_count} 个")
    if updated_count:
        parts.append(f"更新 {updated_count} 个（已有文件被修改）")
    if gate_skipped:
        parts.append(f"闸门拦截 {gate_skipped} 个（低质量占位/裸代码）")
    msg = "✅ 已处理 " + "、".join(parts) + " 项目"
    if failed:
        names = "、".join(Path(f).name for f, _ in failed[:5])
        msg += f"；{len(failed)} 个文件学习失败（已跳过）：{names}"
    return msg


def cmd_precheck(workspace: str = None) -> str:
    """
    对扫描根下所有 MD 做 scan gate 预览，不写入知识库。

    输出每份 MD 的复核结果：
    - ✅ 通过：会产出几张高质量资产
    - 🚫 拦截：因缺少决策字段或充实度不足被 gate 挡住
    用于在真正跑 scan 之前发现 projects/ 里的占位腔/裸代码快照。
    """
    roots = _get_scan_roots(workspace)
    if not roots:
        return ("⚠️ 没有可扫描的目录。请在 config.json 的 scan_roots 中添加目录，"
                "或运行 `python learn.py config --add-root <路径>`。")

    md_files = _scan_md_files(roots)
    if not md_files:
        return "⚠️ 所有扫描根目录下都没有可学习的 .md 文件"

    passed_files: list[tuple[Path, list[dict]]] = []
    blocked_files: list[tuple[Path, list[str]]] = []

    for md_file in md_files:
        try:
            md_content = _read_text_robust(md_file)
            passed_assets, reasons = _scan_gate(md_file, md_content, md_file.stem)
        except Exception as e:
            blocked_files.append((md_file, [f"复核异常：{e}"]))
            continue

        if passed_assets:
            passed_files.append((md_file, passed_assets))
        else:
            blocked_files.append((md_file, reasons))

    lines = [f"📋 scan gate 预览（共 {len(md_files)} 个 MD 文件）"]
    lines.append("")
    lines.append(f"✅ 会通过：{len(passed_files)} 个")
    for md_file, assets in passed_files:
        type_counts = {}
        for a in assets:
            type_counts[a["type"]] = type_counts.get(a["type"], 0) + 1
        summary = ", ".join(f"{cnt} 张 {t}" for t, cnt in type_counts.items())
        lines.append(f"   - {md_file.name} → {summary}")

    lines.append("")
    lines.append(f"🚫 会被拦截：{len(blocked_files)} 个")
    for md_file, reasons in blocked_files:
        lines.append(f"   - {md_file.name}")
        for r in reasons[:2]:
            lines.append(f"       {r}")
        if len(reasons) > 2:
            lines.append(f"       ... 等 {len(reasons)} 条原因")

    return "\n".join(lines)


def cmd_config(args: list) -> str:
    """管理扫描根配置：list / --add-root <路径> / --remove-root <路径> / --auto-workspace on|off"""
    cfg = _load_config()
    if not args or "--list" in args:
        roots = cfg.get("scan_roots", [])
        auto = cfg.get("auto_include_workspace", True)
        lines = [f"📂 扫描根目录（{len(roots)} 个）："]
        for r in roots:
            lines.append(f"   - {r}")
        lines.append(f"🔧 自动包含工作区：{auto}")
        return "\n".join(lines)

    if "--add-root" in args:
        i = args.index("--add-root")
        val = args[i + 1] if i + 1 < len(args) else None
        if not val:
            return "❌ 请提供路径：learn.py config --add-root <路径>"
        roots = cfg.setdefault("scan_roots", [])
        rp = str(Path(val).resolve())
        if rp not in [str(Path(r).resolve()) for r in roots]:
            roots.append(val)
            _save_config(cfg)
            return f"✅ 已添加扫描根：{val}"
        return f"ℹ️ 已存在：{val}"

    if "--remove-root" in args:
        i = args.index("--remove-root")
        val = args[i + 1] if i + 1 < len(args) else None
        if not val:
            return "❌ 请提供路径：learn.py config --remove-root <路径>"
        roots = cfg.get("scan_roots", [])
        rp = str(Path(val).resolve())
        new = [r for r in roots if str(Path(r).resolve()) != rp]
        cfg["scan_roots"] = new
        _save_config(cfg)
        return f"✅ 已移除扫描根：{val}（剩余 {len(new)} 个）"

    if "--auto-workspace" in args:
        i = args.index("--auto-workspace")
        val = args[i + 1] if i + 1 < len(args) else None
        if val is None:
            return "❌ 请提供 on/off：learn.py config --auto-workspace on|off"
        cfg["auto_include_workspace"] = val.lower() in ("on", "true", "1", "yes")
        _save_config(cfg)
        return f"✅ 自动包含工作区：{cfg['auto_include_workspace']}"

    return "用法：learn.py config [--list] | --add-root <路径> | --remove-root <路径> | --auto-workspace on|off"


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
        hollow = [c for c in candidates if "hollow" in c.get("retireCategory", [])]
        aging = [c for c in candidates if "aging" in c.get("retireCategory", [])]

        def _render(group: list[dict], tag: str) -> None:
            for candidate in group:
                reasons = ", ".join(candidate["retireReasons"])
                lines.append(f"- 🕳️ [{tag}] `{candidate['id']}` {candidate['title']} — {reasons}")

        if hollow:
            lines.append(f"**空洞退役（{len(hollow)} 张，内容空洞不必等老化窗口）**")
            _render(hollow, "空洞")
        if aging:
            lines.append(f"**老化退役（{len(aging)} 张，时间窗口到期）**")
            _render(aging, "老化")
        lines.append("")
        lines.append("退役仍需人工执行：`python learn.py retire <id> --reason \"退役原因\"`")
    else:
        lines.append("- 无退役候选")

    if dry_run:
        lines.append("")
        lines.append("- dry-run 未修改索引")
    return "\n".join(lines)


# ─── L6 活体演进扫描（iterate-scan）──────────────────────

# NOTE: 矛盾检测信号词——与 ingest 的 CONFLICT 判定共用同一组否定/反向词，
# 保证「摄入时矛盾」与「存量互比矛盾」判定口径一致。
_CONFLICT_SIGNALS = ("不要", "避免", "禁止", "不应该", "不能", "反对", "弃用",
                     "过时", "错误", "缺陷", "反面", "相反", "not", "never",
                     "avoid", "deprecated", "wrong", "切忌", "慎用")


def _entry_overlap(a: dict, b: dict) -> float:
    """计算两张卡的综合重叠度（0~1），取标题/标签/正文三者中最强信号。

    复用 ingest 已有的重叠口径：标题词汇重叠权重最高（同名不同义由 SAME_TITLE
    关联处理），标签重叠代表同领域同坑，正文 Jaccard 取半权重（抗长文噪声）。
    """
    # NOTE: 标题含代码/路径/emoji 等「非字母字符」占比 >30% 时，英文 token 不可靠
    # （如「Video Workflow」vs「Video Ag…」会虚高），此时对标题 Jaccard 降权，
    # 改以 tag 重叠为主信号，避免碎片标题被误判为「互相印证」。
    title_raw_a = a.get("title", "")
    title_raw_b = b.get("title", "")
    title_a = _content_tokens(title_raw_a)
    title_b = _content_tokens(title_raw_b)
    title_j = 0.0
    if title_a and title_b:
        inter = len(title_a & title_b)
        union = len(title_a | title_b)
        base_title_j = inter / union if union else 0.0
        non_alpha_a = len(re.findall(r"[^a-zA-Z\u4e00-\u9fff\s]", title_raw_a))
        non_alpha_b = len(re.findall(r"[^a-zA-Z\u4e00-\u9fff\s]", title_raw_b))
        len_a, len_b = max(len(title_raw_a), 1), max(len(title_raw_b), 1)
        noise_a = non_alpha_a / len_a
        noise_b = non_alpha_b / len_b
        # 标题噪声高时仅保留 30% 权重，把主导权交还给 tag 重叠
        title_j = base_title_j * 0.3 if (noise_a > 0.3 or noise_b > 0.3) else base_title_j

    tags_a = set(t.lower() for t in a.get("tags", []))
    tags_b = set(t.lower() for t in b.get("tags", []))
    # 未补 tag 的卡用实时 _auto_tag 推导，保证「无存盘 tag 也能被语义比对命中」
    if not tags_a:
        tags_a = set(t.lower() for t in _auto_tag(a))
    if not tags_b:
        tags_b = set(t.lower() for t in _auto_tag(b))
    if tags_a and tags_b:
        inter = len(tags_a & tags_b)
        union = len(tags_a | tags_b)
        tag_j = inter / union if union else 0.0
    else:
        tag_j = 0.0

    body_a = _content_tokens(_load_card_body(a))
    body_b = _content_tokens(_load_card_body(b))
    if body_a and body_b:
        inter = len(body_a & body_b)
        union = len(body_a | body_b)
        body_j = inter / union if union else 0.0
    else:
        body_j = 0.0

    return max(title_j, tag_j, 0.5 * body_j)


def _has_conflict_signal(entry: dict) -> bool:
    """判断某卡正文是否含矛盾/否定信号（用于 CONFLICT 关系判定）。

    NOTE: 单向含否定词不够——「验证红灯」与「验证绿灯」互补而非冲突，二者
    都含「避免」也会被误判。故改为双向：A、B 双方正文都含冲突信号词，才
    视为真正冲突（红/绿这类仅一方含词的自然被豁免）。
    """
    body = _load_card_body(entry).lower()
    return any(sig in body for sig in _CONFLICT_SIGNALS)


def _both_have_conflict(a: dict, b: dict) -> bool:
    """双向冲突：A、B 都含否定/矛盾信号才判冲突，避免互补表述被误标。"""
    return _has_conflict_signal(a) and _has_conflict_signal(b)


def cmd_iterate_scan(apply: bool = False, min_overlap: float = 0.3) -> str:
    """L6 活体演进：对 active 卡两两互比，发现重叠/矛盾并给出演进建议。

    与 maintain（只衰减+列退役候选）互补——maintain 是「被动衰老」，本命令是
    「主动演进」：让已有卡之间互相印证（CONFIRM/EXTEND）或暴露矛盾（CONFLICT），
    把静态精炼的知识推向活体迭代。

    默认 dry-run（只读审计、不落盘）；--apply 才写索引——沿用「退役审计需人工确认」
    的治理哲学，避免自动改写污染知识。

    关系判定（复用 ingest 重叠口径）：
    - CONFIRM：重叠 ≥ 0.6 且同向 → 权重+2、刷新引用、建 crossRef（CONFIRM）
    - EXTEND ：0.3 ≤ 重叠 < 0.6 → 权重+1、iterationCount+1、建 crossRef（EXTEND）
    - CONFLICT：重叠 ≥ 0.5 且 A、B 双向都含矛盾信号 → 仅告警，不自动改（需人工裁决）
    - 孤立热卡：weight≥12 且从未迭代且充实度高 → 建议沉淀为方法论/checklist
    """
    index = load_index()
    active = [e for e in index["entries"] if e.get("status") == "active"]
    if not active:
        return "📭 知识库无 active 卡片，无需演进扫描"

    working = json.loads(json.dumps(index)) if not apply else index
    working_active = [e for e in working["entries"] if e.get("status") == "active"]

    confirm_log, extend_log, conflict_log, isolate_log = [], [], [], []
    seen_pairs = set()

    # NOTE: O(n^2) 两两比对，n=143 约 1 万对，单次扫描可接受；用 seen_pairs 去对称重复。
    for i in range(len(active)):
        for j in range(i + 1, len(active)):
            a, b = active[i], active[j]
            pair_key = tuple(sorted((a["id"], b["id"])))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            # NOTE: 同源豁免——同一 sourceProject 的卡来自同一次摄入切分，正文 token
            # 天然高度重叠是切分伪影（非知识演进），互判 CONFIRM/EXTEND 会污染索引。
            # 同源对强制压到 0.15，远低于 min_overlap（默认 0.3），直接跳过。
            if a.get("sourceProject") == b.get("sourceProject") and a.get("sourceProject"):
                continue
            overlap = _entry_overlap(a, b)
            if overlap < min_overlap:
                continue

            # 在 working 副本中找到对应条目（apply 时即本体）
            wa = next((x for x in working_active if x["id"] == a["id"]), None)
            wb = next((x for x in working_active if x["id"] == b["id"]), None)

            # CONFLICT：重叠 ≥0.5 且 A、B 双向都含矛盾信号 → 仅告警（不自动改）。
            # 阈值抬到 0.5 + 双向，避免「验证红灯↔绿灯」这类互补表述被误标。
            if overlap >= 0.5 and _both_have_conflict(a, b):
                conflict_log.append(
                    f"⚠️ CONFLICT | `{a['title'][:30]}` ↔ `{b['title'][:30]}` "
                    f"(重叠 {overlap:.0%}) — 双向观点冲突，需人工裁决"
                )
                continue

            if overlap >= 0.6:
                # CONFIRM：互相印证，权重+2、刷新引用、建 crossRef
                if wa and wb:
                    referenced_at = _now_iso()
                    wa["weight"] = wa.get("weight", 10) + 2
                    wa["lastReferencedAt"] = referenced_at
                    wa.setdefault("crossRefs", []).append({
                        "source": b.get("sourceProject", "unknown"),
                        "relation": RELATION_CONFIRM,
                        "at": referenced_at,
                    })
                    wb["weight"] = wb.get("weight", 10) + 2
                    wb["lastReferencedAt"] = referenced_at
                    wb.setdefault("crossRefs", []).append({
                        "source": a.get("sourceProject", "unknown"),
                        "relation": RELATION_CONFIRM,
                        "at": referenced_at,
                    })
                confirm_log.append(
                    f"✅ CONFIRM | `{a['title'][:30]}` ↔ `{b['title'][:30]}` "
                    f"(重叠 {overlap:.0%}) — 互相印证，权重各 +2"
                )
            else:
                # EXTEND：部分重叠，权重+1、iterationCount+1、建 crossRef
                if wa and wb:
                    referenced_at = _now_iso()
                    wa["weight"] = wa.get("weight", 10) + 1
                    wa["iterationCount"] = wa.get("iterationCount", 0) + 1
                    wa["version"] = wa.get("version", 1) + 1
                    wa["lastReferencedAt"] = referenced_at
                    wa.setdefault("crossRefs", []).append({
                        "source": b.get("sourceProject", "unknown"),
                        "relation": RELATION_EXTEND,
                        "at": referenced_at,
                    })
                    wb["weight"] = wb.get("weight", 10) + 1
                    wb["iterationCount"] = wb.get("iterationCount", 0) + 1
                    wb["version"] = wb.get("version", 1) + 1
                    wb["lastReferencedAt"] = referenced_at
                    wb.setdefault("crossRefs", []).append({
                        "source": a.get("sourceProject", "unknown"),
                        "relation": RELATION_EXTEND,
                        "at": referenced_at,
                    })
                extend_log.append(
                    f"🔗 EXTEND  | `{a['title'][:30]}` ↔ `{b['title'][:30]}` "
                    f"(重叠 {overlap:.0%}) — 部分重叠，互相扩展，权重各 +1"
                )

    # 孤立热卡检测：高权重但从未迭代、且内容充实 → 建议沉淀
    # NOTE: 排除本就是方法论/清单/陷阱类的卡（type 已标注则无需再建议沉淀），
    # 只针对「高权重、未迭代、但内容属通用经验」的卡提示，降低噪声。
    methodology_types = {"methodology", "checklist", "pitfall", "template"}
    for e in active:
        if e.get("weight", 0) >= 12 and e.get("iterationCount", 0) == 0:
            if e.get("type") in methodology_types:
                continue
            fulfillment = score_content_fulfillment(e)
            if fulfillment["score"] >= 60:
                isolate_log.append(
                    f"🌟 孤立热卡 | `{e['title'][:30]}` "
                    f"(权重 {e['weight']}，迭代 0 次，充实度 {fulfillment['score']}) "
                    f"— 高价值未沉淀，建议提炼为方法论/checklist"
                )

    if apply and (confirm_log or extend_log):
        working["updatedAt"] = _now_iso()
        save_index(working)

    mode = "已应用" if apply else "预览（dry-run）"
    lines = [f"## 🔄 活体演进扫描（{mode}）", ""]
    lines.append(f"扫描 {len(active)} 张 active 卡，最小重叠阈值 {min_overlap:.0%}")
    lines.append("")

    if confirm_log:
        lines.append(f"### ✅ CONFIRM 互相印证（{len(confirm_log)} 对）")
        lines.extend(f"- {log}" for log in confirm_log)
        lines.append("")
    if extend_log:
        lines.append(f"### 🔗 EXTEND 互相扩展（{len(extend_log)} 对）")
        lines.extend(f"- {log}" for log in extend_log)
        lines.append("")
    if conflict_log:
        lines.append(f"### ⚠️ CONFLICT 疑似冲突（{len(conflict_log)} 对，需人工裁决）")
        lines.extend(f"- {log}" for log in conflict_log)
        lines.append("")
    if isolate_log:
        lines.append(f"### 🌟 孤立热卡（{len(isolate_log)} 张，建议沉淀）")
        lines.extend(f"- {log}" for log in isolate_log)
        lines.append("")

    if not (confirm_log or extend_log or conflict_log or isolate_log):
        lines.append("- 未发现需演进的关系（卡片间重叠度均低于阈值，或已是稳态）")

    if not apply and (confirm_log or extend_log):
        lines.append("")
        lines.append("- 以上权重/版本变更为预览；加 `--apply` 才真正写入索引")

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


# ─── 内容充实度评分（知识库「质」的度量）──────────────────────
# 解决 stats 只报数量/权重、缺失「质」度量的问题。
# 充实度从「实质内容量」与「占位填充」两个正交维度刻画一张卡片的完成度。

# 实质实词数达到该值即视为「充实」，对应基础分 100。
# 校准依据：一段含 3 句完整工程原则的卡片约 39 实词，应得满分；
# 仅含模板腔占位的空壳卡片约 10~15 实词，应落入空洞区间。
FULFILLMENT_FULL_MARK = 35
# 充实度低于该值判为「空洞卡片」。
HOLLOW_SCORE_THRESHOLD = 40
# 每命中一个占位模式扣减的分数（封顶扣至 0）。
PLACEHOLDER_PENALTY = 25

# 典型占位/机械填充短语：L2 template 抽取等流程未填充参数时留下的模板腔。
_PLACEHOLDER_PATTERNS = (
    "由模板中的变量和配置项决定",
    "由代码片段实际执行结果决定",
    "由模板中的变量",
    "由代码片段",
    "待补充",
    "待实现",
    "示例待填",
    "此处留空",
    "TODO:",
    "FIXME:",
    "XXX",
)


def _load_card_body(entry: dict) -> str:
    """读取卡片正文（仅 `## 核心内容` 之后的实质内容，排除 frontmatter）。"""
    path = resolve_knowledge_card_path(entry["layer"], entry["slug"], entry["type"])
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    match = re.search(r"## 核心内容\s*\n+(.*)", text, re.DOTALL)
    return match.group(1).strip() if match else text.strip()


def score_content_fulfillment(entry: dict) -> dict[str, object]:
    """
    单张卡片的内容充实度评分（0~100）。

    返回 {score, substance_tokens, placeholder_hits, hollow}：
    - score:            0~100 综合充实度
    - substance_tokens: 实质实词数（去停用字、去 markdown 噪声）
    - placeholder_hits: 命中的占位短语列表
    - hollow:           是否判为「空洞卡片」（score < 阈值）
    """
    body = _load_card_body(entry)

    # 去除代码块（保留其外实质文本即可，模板代码本身有内容但属「给他人填的壳」，
    # 不计入本卡片的自有实质量；避免把「含一段代码的空壳」误判充实）。
    body_no_code = re.sub(r"```.*?```", "", body, flags=re.DOTALL)

    substance = _content_tokens(body_no_code)
    base = min(100, len(substance) / FULFILLMENT_FULL_MARK * 100)

    hits = [p for p in _PLACEHOLDER_PATTERNS if p in body]
    penalty = min(100, len(hits) * PLACEHOLDER_PENALTY)

    score = max(0, round(base - penalty))
    return {
        "score": score,
        "substance_tokens": len(substance),
        "placeholder_hits": hits,
        "hollow": score < HOLLOW_SCORE_THRESHOLD,
    }


def _score_asset_fulfillment(asset: dict) -> dict[str, object]:
    """
    对尚未写入磁盘的待摄入资产做充实度预检。

    scan/precheck 阶段调用，避免把占位腔资产灌入知识库。
    口径与 score_content_fulfillment 保持一致：去掉代码块后统计实词，
    再按占位短语扣减。返回结构与 score_content_fulfillment 相同。
    """
    body = asset.get("content", "")
    body_no_code = re.sub(r"```.*?```", "", body, flags=re.DOTALL)
    substance = _content_tokens(body_no_code)
    base = min(100, len(substance) / FULFILLMENT_FULL_MARK * 100)

    hits = [p for p in _PLACEHOLDER_PATTERNS if p in body]
    penalty = min(100, len(hits) * PLACEHOLDER_PENALTY)

    score = max(0, round(base - penalty))
    return {
        "score": score,
        "substance_tokens": len(substance),
        "placeholder_hits": hits,
        "hollow": score < HOLLOW_SCORE_THRESHOLD,
    }


def audit_content_fulfillment(entries: list[dict]) -> dict[str, object]:
    """
    批量审计知识库内容充实度，产出「质」的健康指标。

    返回库级聚合指标，供 cmd_stats 渲染。
    """
    scored = [(e, score_content_fulfillment(e)) for e in entries]
    active_scored = [(e, s) for e, s in scored if e["status"] == "active"]

    if not active_scored:
        return {"count": 0, "avg_score": 0, "hollow_rate": 0.0,
                "placeholder_rate": 0.0, "worst": []}

    total = len(active_scored)
    scores = [s["score"] for _, s in active_scored]
    hollow = sum(1 for s in scores if s < HOLLOW_SCORE_THRESHOLD)
    with_placeholder = sum(1 for _, s in active_scored if s["placeholder_hits"])

    # 充实度最低的 5 张，供人工补强。
    worst = sorted(active_scored, key=lambda x: x[1]["score"])[:5]

    return {
        "count": total,
        "avg_score": round(sum(scores) / total, 1),
        "hollow_rate": round(hollow / total * 100, 1),
        "placeholder_rate": round(with_placeholder / total * 100, 1),
        "worst": [
            {"title": e["title"], "score": s["score"], "hits": s["placeholder_hits"]}
            for e, s in worst
        ],
    }


# ─── L2 模板相似度去重检测 ─────────────────────────────────
# 现有 slug 去重只防「字面冲突」，不同项目摄入同一模板（如 Dockerfile 模板）
# 会带着不同 slug 并存。此处基于正文实词 Jaccard 检测高度相似的疑似重复。

# Jaccard 重叠度达到该值即判为疑似重复。探针校准：去除模板框架套话后，
# 同模板多次摄入的 Jaccard 落在 0.55~0.72，不同主题模板通常 <0.3，
# 故 0.5 可捕获重复且不会把不同主题误判。
TEMPLATE_DUP_THRESHOLD = 0.5

# 模板框架套话：不同模板间高度共享的固定生成文本（与具体业务无关），
# 若不剔除会系统性抬高两两重叠、制造海量假阳性重复。比对前整体移除。
_TEMPLATE_BOILERPLATE_PATTERNS = (
    "使用前应确认依赖版本、输入校验、异常处理和资源边界",
    "确认运行时版本、依赖包和输入数据结构与模板一致",
    "复制模板后，替换示例变量、配置项和业务依赖，再接入调用方",
    "使用前应补充业务校验、异常处理和日志策略",
    "返回处理结果；具体值取决于输入和模板分支",
) + _PLACEHOLDER_PATTERNS


def _template_similarity_tokens(entry: dict) -> set[str]:
    """
    抽取模板卡片用于相似度比对的实词集合。

    先剥离框架套话与占位腔（这些与业务无关、跨模板共享），
    再取全量实词（含代码块）——同主题模板的「用途描述 + 代码」才是独特指纹。
    """
    body = _load_card_body(entry)
    for pattern in _TEMPLATE_BOILERPLATE_PATTERNS:
        body = body.replace(pattern, "")
    return _content_tokens(body)


def detect_template_duplicates(entries: list[dict], threshold: float = TEMPLATE_DUP_THRESHOLD) -> list[dict]:
    """
    检测 L2 template 卡片间的高相似度疑似重复。

    返回按相似度降序排列的重复对列表，每项 {a_id, a_title, b_id, b_title, score}。
    仅比较 active 的 template 类型条目；比对前剔除模板框架套话与占位腔，
    避免「通用模板框架」被误判为重复内容。
    """
    candidates = [
        e for e in entries
        if e.get("type") == "template" and e.get("status") == "active"
    ]
    if len(candidates) < 2:
        return []

    # 预计算每张卡片的实词集合，避免重复分词。
    tokens_cache: dict[str, set[str]] = {}
    for e in candidates:
        tokens_cache[e["id"]] = _template_similarity_tokens(e)

    duplicates: list[dict] = []
    n = len(candidates)
    for i in range(n):
        ei = candidates[i]
        ti = tokens_cache[ei["id"]]
        if not ti:
            continue
        for j in range(i + 1, n):
            ej = candidates[j]
            tj = tokens_cache[ej["id"]]
            if not tj:
                continue
            union = ti | tj
            if not union:
                continue
            score = len(ti & tj) / len(union)
            if score >= threshold:
                duplicates.append({
                    "a_id": ei["id"],
                    "a_title": ei["title"],
                    "b_id": ej["id"],
                    "b_title": ej["title"],
                    "score": round(score, 3),
                })

    duplicates.sort(key=lambda d: -d["score"])
    return duplicates


# 高置信重复阈值：达到该值判为「强重复」，应优先人工去重。
TEMPLATE_DUP_HIGH_CONFIDENCE = 0.6


def cluster_template_duplicates(entries: list[dict], threshold: float = TEMPLATE_DUP_HIGH_CONFIDENCE) -> list[dict]:
    """
    将高相似模板聚合成重复簇（并查集），降低两两对的噪音。

    返回按簇规模降序的簇列表，每项 {representative, size, max_score, members}；
    members 为簇内所有模板的 {id, title}。仅含 size≥2 的簇。
    """
    pairs = detect_template_duplicates(entries, threshold)
    if not pairs:
        return []

    # 并查集：把相似度达标的卡片连通成簇。
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    title_by_id: dict[str, str] = {e["id"]: e["title"] for e in entries}
    # 记录每簇内的最高相似度（取该簇涉及边的最大值）。
    cluster_max: dict[str, float] = {}
    for p in pairs:
        union(p["a_id"], p["b_id"])
        root = find(p["a_id"])
        cluster_max[root] = max(cluster_max.get(root, 0.0), p["score"])

    groups: dict[str, list[str]] = {}
    for e in entries:
        if e.get("type") == "template" and e.get("status") == "active":
            root = find(e["id"])
            groups.setdefault(root, []).append(e["id"])

    clusters = []
    for root, members in groups.items():
        if len(members) < 2:
            continue
        clusters.append({
            "representative": title_by_id.get(members[0], members[0]),
            "size": len(members),
            "max_score": round(cluster_max.get(root, 0.0), 3),
            "members": [{"id": mid, "title": title_by_id.get(mid, mid)} for mid in members],
        })

    clusters.sort(key=lambda c: -c["size"])
    return clusters


def cmd_dupcheck() -> str:
    """检测 L2 模板间的高度相似重复，按重复簇输出。"""
    index = load_index()
    entries = index["entries"]
    template_count = sum(
        1 for e in entries if e.get("type") == "template" and e.get("status") == "active"
    )

    lines = [
        "## 🔁 L2 模板相似度去重检测",
        "",
        f"- 参与比对：{template_count} 张 active 模板",
        f"- 高置信阈值：Jaccard ≥ {TEMPLATE_DUP_HIGH_CONFIDENCE}（灰区 {TEMPLATE_DUP_THRESHOLD}~{TEMPLATE_DUP_HIGH_CONFIDENCE} 需人工审视）",
        "",
    ]

    # 灰区（低阈值）规模，用于提示近似模板泛滥程度。
    gray_pairs = detect_template_duplicates(entries, TEMPLATE_DUP_THRESHOLD)
    gray_count = sum(1 for d in gray_pairs if d["score"] < TEMPLATE_DUP_HIGH_CONFIDENCE)
    lines.append(f"- 灰区近似对（{TEMPLATE_DUP_THRESHOLD}~{TEMPLATE_DUP_HIGH_CONFIDENCE}）：{gray_count} 对")

    clusters = cluster_template_duplicates(entries)
    if not clusters:
        lines.append("✅ 未发现高置信的重复模板簇")
        return "\n".join(lines)

    involved = sum(c["size"] for c in clusters)
    lines.append(f"⚠️ 发现 {len(clusters)} 个高置信重复簇，涉及 {involved} 张模板")
    lines.append("")
    lines.append("| 簇规模 | 最高相似度 | 代表模板 |")
    lines.append("|--------|-----------|----------|")
    for c in clusters[:30]:  # 控量，避免报告爆炸
        lines.append(
            f"| {c['size']} | {c['max_score']:.2f} | {c['representative'][:30]} |"
        )
    lines.append("")
    lines.append("建议：逐簇保留代表性一张，其余走 "
                 "`python learn.py retire <id> --reason \"重复模板\"`")
    if len(clusters) > 30:
        lines.append(f"（仅展示前 30 个簇，共 {len(clusters)} 个）")

    # ── 同标题不同义的同源卡家族（RELATION_SAME_TITLE）──
    # 这些卡已由入库流程互链，但正文相似度 < 阈值、dupcheck 正文比对捞不到，
    # 此处按 SAME_TITLE 关联聚合成簇，明确提示「需人工归并」，而非当成已去重。
    same_title_clusters = _cluster_same_title_families(entries)
    if same_title_clusters:
        lines.append("")
        lines.append(f"## 🔗 同标题不同义家族（需人工归并）：{len(same_title_clusters)} 簇")
        lines.append("")
        lines.append("| 簇规模 | 成员标题 |")
        lines.append("|--------|----------|")
        for fam in same_title_clusters[:30]:
            titles = " / ".join(t[:24] for t in fam["titles"])
            lines.append(f"| {fam['size']} | {titles} |")
        lines.append("")
        lines.append("建议：同标题但内容不同义，人工确认后保留其一、归并其余，"
                     "或拆分为更精确的标题避免歧义。")
        if len(same_title_clusters) > 30:
            lines.append(f"（仅展示前 30 个簇，共 {len(same_title_clusters)} 个）")

    return "\n".join(lines)


def _cluster_same_title_families(entries: list[dict]) -> list[dict]:
    """
    按 RELATION_SAME_TITLE 关联把 active 卡聚合成同源家族。
    返回按簇规模降序的列表，每项为 {"size", "ids", "titles"}。
    """
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    active = [e for e in entries if e.get("status") == "active"]
    id_set = {e["id"] for e in active}
    for e in active:
        eid = e["id"]
        for ref in e.get("crossRefs", []):
            if ref.get("relation") == RELATION_SAME_TITLE:
                other = ref.get("source")
                if other in id_set:
                    union(eid, other)

    groups: dict[str, list[str]] = {}
    for eid in id_set:
        groups.setdefault(find(eid), []).append(eid)

    families = []
    for ids in groups.values():
        if len(ids) >= 2:
            titles = [
                next((e["title"] for e in active if e["id"] == i), i)
                for i in ids
            ]
            families.append({"size": len(ids), "ids": ids, "titles": titles})
    families.sort(key=lambda f: f["size"], reverse=True)
    return families


# ─── 摄入前查重（治本方案）─────────────────────────────────
# 事后 dupcheck 只能发现重复、无法阻止存储膨胀。更根治的做法是在 ingest 时
# 对每条待新建知识做正文相似度查重：命中高相似则跳过新建（不占存储），
# 仅把来源项目归因到已有卡片（刷新引用时间，等效一次轻量旁证）。
# 这样从源头堵住「多项目反复生成近似模板」的漏水口，比事后清理更省空间。

# 摄入侧硬跳过阈值：达到该正文 Jaccard 即判为「同一知识的不同表述/副本」，
# 直接跳过新建。沿用 dupcheck 校准基线（0.6）——同模板多次摄入落在 0.55~0.72，
# 此处取高置信上沿，宁可少跳过也不误杀不同主题。
INGEST_DEDUP_THRESHOLD = 0.6


def _similarity_tokens_from_content(content: str, ktype: str) -> set[str]:
    """
    从内存中的卡片正文计算相似度 token。

    模板类型先剥离框架套话（跨模板共享、与业务无关），其余类型直接取实词；
    与 `_similarity_tokens_from_entry` 保持同一口径，保证内存侧与盘上侧可比。
    """
    body = content
    if ktype == "template":
        for pattern in _TEMPLATE_BOILERPLATE_PATTERNS:
            body = body.replace(pattern, "")
    return _content_tokens(body)


def _similarity_tokens_from_entry(entry: dict) -> set[str]:
    """已有库卡片的相似度 token（复用现有剥离/读盘逻辑，与内存侧口径一致）。"""
    if entry.get("type") == "template":
        return _template_similarity_tokens(entry)
    # 内存侧已带 content（如测试或运行时未落盘的 entry）优先用内存值，避免重复读盘。
    body = entry.get("content") or _load_card_body(entry)
    return _content_tokens(body)


def check_ingest_duplicates(new_items: list[dict], index: dict) -> dict:
    """
    摄入前查重：对每条待新建知识，与已有 active 卡片做正文相似度检测。

    命中高相似（≥INGEST_DEDUP_THRESHOLD）的待入库项将被「跳过 + 归因」：
    - 不新建文件、不写新索引条目（省存储）
    - 把来源项目追加到已有卡片 crossRefs 并刷新 lastReferencedAt（轻量旁证）

    返回 {kept, skipped, log}：
    - kept:    真正需要写盘新建的 new_items（已剔除被跳过的）
    - skipped: 被查重拦截的待入库项，每项含匹配卡片信息
    - log:     人类可读的拦截日志
    """
    active_entries = [
        e for e in index["entries"] if e.get("status") == "active"
    ]
    # 预计算已有卡片 token，避免重复分词。
    existing_tokens: dict[str, set[str]] = {
        e["id"]: _similarity_tokens_from_entry(e) for e in active_entries
    }

    kept: list[dict] = []
    skipped: list[dict] = []
    log: list[str] = []

    for item in new_items:
        raw = item.get("_raw", item)
        content = raw.get("content", "")
        ktype = item.get("type", raw.get("type", ""))
        if not content:
            kept.append(item)
            continue

        item_tokens = _similarity_tokens_from_content(content, ktype)
        if not item_tokens:
            kept.append(item)
            continue

        best_id = None
        best_score = 0.0
        for eid, toks in existing_tokens.items():
            if not toks:
                continue
            union = item_tokens | toks
            if not union:
                continue
            score = len(item_tokens & toks) / len(union)
            if score > best_score:
                best_score = score
                best_id = eid

        if best_id and best_score >= INGEST_DEDUP_THRESHOLD:
            matched = find_entry_by_id(index, best_id)
            source = item.get("source_project", "unknown")
            # 归因：刷新引用时间 + 追加来源旁证，等效一次轻量 CONFIRM。
            referenced_at = _now_iso()
            matched["lastReferencedAt"] = referenced_at
            matched.setdefault("crossRefs", []).append({
                "source": source,
                "relation": "PREINGEST_DEDUP",
                "at": referenced_at,
            })
            skipped.append({
                "item": item,
                "matched_id": best_id,
                "matched_title": matched.get("title", best_id),
                "score": round(best_score, 3),
            })
            log.append(
                f"🚫 SKIP    | `{item['title'][:40]}` 与 `{matched['title'][:40]}` "
                f"正文相似度 {best_score:.0%} ≥ 阈值，跳过新建，归因到已有卡片"
            )
        else:
            kept.append(item)

    return {"kept": kept, "skipped": skipped, "log": log}


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

    # 退役候选（分别标注空洞退役与老化退役，便于人工裁决）
    candidates = retire_scan(index)
    if candidates:
        hollow = sum(1 for c in candidates if "hollow" in c.get("retireCategory", []))
        aging = sum(1 for c in candidates if "aging" in c.get("retireCategory", []))
        lines.append(
            f"- 🗑️ {len(candidates)} 条满足退役条件"
            f"（空洞 {hollow} / 老化 {aging}），运行 `python learn.py retire-scan` 查看"
        )

    # 权重分布
    weights = [e["weight"] for e in active]
    if weights:
        avg_w = sum(weights) / len(weights)
        lines.append(f"- 📊 平均权重: {avg_w:.1f} | 最低: {min(weights)} | 最高: {max(weights)}")

    # 迭代次数
    iters = [e["iterationCount"] for e in active]
    never_iterated = sum(1 for i in iters if i == 0)
    lines.append(f"- 🔄 {never_iterated}/{len(active)} 条从未被迭代")

    # 内容充实度（质的度量）
    lines.append("")
    lines.append("### 📏 内容充实度（质的度量）")
    fulfillment = audit_content_fulfillment(entries)
    if fulfillment["count"] == 0:
        lines.append("- 无活跃卡片可评估")
    else:
        avg = fulfillment["avg_score"]
        grade = "🟢 充实" if avg >= 70 else "🟡 一般" if avg >= 50 else "🔴 偏空洞"
        lines.append(f"- 平均充实度: **{avg}/100** {grade}")
        lines.append(f"- 🕳️ 空洞卡片率: {fulfillment['hollow_rate']}% （充实度 < {HOLLOW_SCORE_THRESHOLD}）")
        lines.append(f"- 🧩 占位填充率: {fulfillment['placeholder_rate']}% （仍含模板腔/待补充等占位文本）")
        if fulfillment["worst"]:
            lines.append("- 充实度最低的卡片（建议补强）：")
            for w in fulfillment["worst"]:
                hits = "、".join(w["hits"][:2]) if w["hits"] else "内容偏薄"
                lines.append(f"  - `{w['title'][:24]}` ({w['score']}/100) — {hits}")

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


def _recall_keywords_from_workspace(workspace: str = None) -> str:
    """从工作区推导召回意图词：聚合目录名 + 近期 MD 标题/首段关键词。"""
    if not workspace:
        return ""
    root = Path(workspace)
    if not root.exists():
        return ""
    cues = [root.name]  # 目录名本身就是强意图信号（如 my-saas-backend）
    md_files = sorted(root.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:10]
    for md in md_files:
        cues.append(md.stem)
        # 取首段非标题文本作为意图补充
        try:
            text = md.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        paras = [p.strip() for p in text.split("\n\n") if p.strip() and not p.strip().startswith("#")]
        if paras:
            cues.append(paras[0][:120])
    return " ".join(cues)


def _recall_score(entry: dict, query_tokens: set[str]) -> int:
    """对单张 active 卡按意图词做加权召回评分。

    权重：标题命中 > domain 命中 > tag 命中 > 正文实词命中；高权重卡额外加权，
    确保「高权重 + 相关」的卡优先浮现（对齐 L6 权重语义）。
    """
    if not query_tokens:
        return 0
    score = 0
    title = entry.get("title", "").lower()
    domain = entry.get("domain", "").lower()
    # 存盘 tag + 实时推导 tag 合并：部分卡未走 backfill 补 tag，实时 _auto_tag 复用
    # 同一套业务词表，让"限流/429"这类意图词即便卡无存盘 tag 也能语义命中（治本复用）。
    stored_tags = [t.lower() for t in entry.get("tags", [])]
    inferred_tags = [t.lower() for t in _auto_tag(entry)]
    tags = " ".join(stored_tags + inferred_tags)
    body = _load_card_body(entry).lower()

    for tok in query_tokens:
        if not tok:
            continue
        if tok in title:
            score += 10
        if tok in domain:
            score += 4
        if tok in tags:
            # tag 是 backfill 推导的「业务标签」，与 domain 解耦——tag 命中即语义命中，
            # 权重最高（超过标题），让 recall 从"正文子串碰巧命中"升级为"标签语义命中"。
            score += 14
        # 正文实词命中（实词已在 _content_tokens 里去噪，这里直接子串足够轻量）
        if tok in body:
            score += 2

    # 防噪声（关键）：仅 domain 弱命中或"正文只蹭到一个词"的卡视为弱相关，压到 0。
    # 要求：至少一次标题/tag 强命中，或正文命中 >= 2 个不同意图词，否则不召回。
    # 避免「devops 域 + 正文里恰好出现 docker 一词」的发布卡被误召。
    title_tag_hits = sum(
        1 for tok in query_tokens
        if tok and (tok in title or tok in tags)
    )
    body_hit_tokens = {tok for tok in query_tokens if tok and tok in body}
    if title_tag_hits == 0 and len(body_hit_tokens) < 2:
        return 0

    # 高权重卡加权：权重 >= 权重中位数的卡额外 +30%，强化"经验优先"
    if entry.get("weight", 1) >= 5:
        score = int(score * 1.3)
    return score


def cmd_recall(intent: str = None, workspace: str = None, top_k: int = 8,
               as_json: bool = False) -> str:
    """主动召回引擎：按当前项目/意图从库里捞出相关卡片，并产出决策建议。

    三层反哺：
    1. 主动召回——不等人手搜，依据 workspace 目录名/近期 MD 或给定 intent 推导意图词，
       对 active 卡做加权匹配，返回 Top-N 相关卡。
    2. 上下文注入——每张命中卡输出「核心内容」摘要，便于塞进系统提示/任务上下文。
    3. 决策建议——从命中卡筛 pitfall/checklist，按 domain 聚类产出「注意 X / 按 Y 核对」。
    """
    index = load_index()
    active = [e for e in index["entries"] if e.get("status") == "active"]

    # 推导意图词：workspace 优先，否则用 intent 文本
    query_text = intent or _recall_keywords_from_workspace(workspace)
    if not query_text:
        return ("⚠️ 缺少召回意图。请传入 --intent \"描述\" 或 --workspace \"项目路径\"，"
                "例如：`python learn.py recall --workspace \"D:\\my-saas-backend\"`")
    query_tokens = {t for t in _content_tokens(query_text) if len(t) >= 2}

    ranked = [(s, e) for e in active if (s := _recall_score(e, query_tokens)) > 0]
    ranked.sort(key=lambda x: -x[0])
    hits = ranked[:top_k]

    if not hits:
        return (f"🤷 未从知识库召回与「{query_text[:40]}」相关的卡片。"
                f"可先 `learn.py scan` 摄入相关经验，或用更宽泛的意图词。")

    # ── 组装召回结果 + 决策建议 ──
    lines = [f"## 🧠 主动召回（意图：{query_text[:50]}）", ""]
    lines.append(f"命中 {len(hits)} 张相关卡片（按相关性 + 权重排序）：")
    lines.append("")

    pitfalls, checklists = [], []
    for score, entry in hits:
        body = _load_card_body(entry)
        card_tags = entry.get("tags", [])
        # 注入用摘要：跳过 fenced 代码块与表格行，取前 400 字干净内容，
        # 避免把代码/表格碎片原样 dump 进上下文（出库实用性：可读性）。
        summary = _clean_summary(body, limit=400)
        lines.append(f"### [{entry['type']}/{entry['domain']}] {entry['title']} "
                     f"(权重 {entry['weight']}, 相关度 {score})")
        lines.append(f"> ID: `{entry['id']}` | 来源: {entry.get('sourceProject', '未知')}"
                     + (f" | 命中标签: {', '.join(card_tags)}" if card_tags else ""))
        lines.append("")
        lines.append(summary)
        lines.append("")

        if entry["type"] == "pitfall":
            pitfalls.append(entry)
        elif entry["type"] == "checklist":
            checklists.append(entry)

    # ── 决策建议（第三层）──
    if pitfalls or checklists:
        lines.append("---")
        lines.append("### 💡 决策建议（基于命中经验）")
        if pitfalls:
            lines.append(f"**⚠️ 这个项目要当心（{len(pitfalls)} 条已知陷阱）：**")
            for p in pitfalls:
                # pitfall 卡正文首句通常即风险点，取第一段作为建议
                body = _load_card_body(p)
                first_line = next((l.strip("-* ").strip() for l in body.splitlines()
                                   if l.strip() and not l.strip().startswith("#")), "")
                lines.append(f"- 注意「{p['title']}」：{first_line[:80]}")
        if checklists:
            lines.append(f"**✅ 上线前请按这些清单核对（{len(checklists)} 张）：**")
            for c in checklists:
                lines.append(f"- 核对「{c['title']}」（domain: {c['domain']}, ID: `{c['id']}`）")
        lines.append("")

    result = "\n".join(lines)
    if as_json:
        payload = {
            "intent": query_text,
            "hits": [
                {"id": e["id"], "title": e["title"], "type": e["type"],
                 "domain": e["domain"], "weight": e["weight"], "score": s,
                 "body": _load_card_body(e)}
                for s, e in hits
            ],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)
    return result


def _retire_entry_in_place(index: dict, entry: dict, reason: str) -> bool:
    """
    就地退役单张卡：移动 Markdown 文件到 L5-retired 并更新索引状态/计数。

    抽出于 cmd_retire（单张）与 cmd_backfill（批量）共用，避免批量场景
    重复 load/save 索引。调用方负责最终 save_index。返回是否真的移动了文件。
    """
    # 移动文件到 L5-retired
    source_layer = entry["layer"]
    slug = entry["slug"]
    source_path = resolve_knowledge_card_path(source_layer, slug, entry["type"])

    moved = False
    if source_path.exists():
        retired_dir = LAYER_DIRS["L5-retired"]
        retired_dir.mkdir(parents=True, exist_ok=True)
        dest_path = retired_dir / f"{slug}.md"
        source_path.rename(dest_path)

        # 在文件头追加退役信息
        old_content = dest_path.read_text(encoding="utf-8")
        retire_note = f"\n> ⚠️ **已退役** ({_now_iso()})：{reason}\n"
        dest_path.write_text(retire_note + old_content, encoding="utf-8")
        moved = True

    # 更新索引状态
    entry["status"] = "retired"
    entry["retiredAt"] = _now_iso()
    entry["retireReason"] = reason
    # 调减领域/类型计数
    target_domain = entry["domain"]
    target_type = entry["type"]
    if index["domains"].get(target_domain, 0) > 0:
        index["domains"][target_domain] -= 1
    if index["types"].get(target_type, 0) > 0:
        index["types"][target_type] -= 1

    return moved


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

    _retire_entry_in_place(index, target, reason)
    index["updatedAt"] = _now_iso()
    save_index(index)

    return f"✅ 已退役: `{target['title']}`\n   原因: {reason}\n   文件移至: `L5-retired/{target['slug']}.md`"


def cmd_backfill(dry_run: bool = False) -> str:
    """
    存量回填：对历史知识库执行两类补救动作。

    1. 空洞批量退役：用 retire_scan 的 hollow 候选，将全部内容空洞卡批量退到 L5-retired。
       在 retire-scan 中已排除 core:true 的核心卡，本命令不二次过滤。
    2. 孤儿 crossRef 重算：对「不会退役」的存活 active 卡，按 base slug（去 -数字 后缀）
       归组，组内 >1 张则两两补建 RELATION_SAME_TITLE 双向关联，让同名概念家族互见、
       可被 dupcheck 识别为「需人工归并」而非「已去重」。被纳入退役候选的卡不参与，
       避免为即将退掉的卡浪费关联。

    全程仅 load/save 索引一次（批量场景），文件移动复用 _retire_entry_in_place。
    """
    import re as _re

    index = load_index()
    entries = index["entries"]

    # NOTE: 先算退役候选 id 集合，孤儿重算需排除这些即将退掉的卡。
    candidates = retire_scan(index)
    to_retire_ids = {c["id"] for c in candidates if "hollow" in c.get("retireCategory", [])}
    retire_reason = "存量回填：内容空洞（批量退役）"

    # ── 步骤 1：孤儿 crossRef 重算（仅存活且非候选的 active 卡）──
    same_title_added = 0
    survivor_active = [
        e for e in entries
        if e.get("status") == "active" and e["id"] not in to_retire_ids
    ]
    base_groups: dict[str, list[dict]] = {}
    for e in survivor_active:
        base = _re.sub(r"-(\d+)$", "", e.get("slug", ""))
        base_groups.setdefault(base, []).append(e)

    for base, group in base_groups.items():
        if len(group) < 2:
            continue
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                if _ensure_same_title_link(a, b):
                    same_title_added += 1

    # ── 步骤 2：空洞批量退役 ──
    # NOTE: 以「进入退役处理的卡数」为计数依据，而非文件是否发生物理移动——
    # 部分卡的文件此前已落在 L5-retired（路径偏差或历史操作），status 标记即视为退役完成。
    retired_count = 0
    retired_titles: list[str] = []
    for entry in entries:
        if entry["id"] in to_retire_ids and entry.get("status") == "active":
            _retire_entry_in_place(index, entry, retire_reason)
            retired_count += 1
            retired_titles.append(entry["title"])

    # ── 步骤 3：自动补 tag（仅非候选 active 卡）──
    # 从标题 + 正文推导 domain 无关的业务标签，写回索引 + 落盘文件头「标签:」字段。
    # 目的：让 recall 从「正文子串碰巧命中」升级为「业务标签语义命中」。
    # 仅对 tag 为空（或仅含 domain 退化值）的卡补，已带人工 tag 的尊重不覆盖。
    tag_added = 0
    tag_examples: list[str] = []
    for entry in survivor_active:
        existing = entry.get("tags", [])
        # 退化判定：tag 为空，或仅含等于 domain 的占位值（write_card 默认 tags or domain）
        degenerate = (not existing) or (len(existing) == 1 and existing[0] == entry.get("domain"))
        if not degenerate:
            continue
        new_tags = _auto_tag(entry)
        if not new_tags:
            continue
        entry["tags"] = new_tags
        # 写回落盘文件头「- **标签**: ...」
        try:
            path = resolve_knowledge_card_path(
                entry["layer"], entry["slug"], entry["type"]
            )
            if path.exists():
                text = path.read_text(encoding="utf-8")
                text = re.sub(
                    r"(-\s*\*\*标签\*\*\s*:\s*).*",
                    rf"\1{', '.join(new_tags)}",
                    text,
                    count=1,
                )
                path.write_text(text, encoding="utf-8")
        except Exception:
            pass
        tag_added += 1
        if len(tag_examples) < 5:
            tag_examples.append(f"{entry['title']}→{', '.join(new_tags)}")

    index["updatedAt"] = _now_iso()

    if dry_run:
        return (
            f"🔍 回填预演（不落盘）\n"
            f"- 孤儿 SAME_TITLE 关联将新增: {same_title_added} 条\n"
            f"- 空洞卡将退役: {len(to_retire_ids)} 张\n"
            f"  示例: {', '.join(list(retired_titles[:5]) + ['…'] if retired_titles else [])}\n"
            f"- 自动补 tag 将覆盖: {tag_added} 张\n"
            f"  示例: {'; '.join(tag_examples + ['…'])}"
        )

    save_index(index)
    return (
        f"✅ 回填完成\n"
        f"- 补建孤儿 SAME_TITLE 关联: {same_title_added} 条\n"
        f"- 批量退役空洞卡: {retired_count} 张（移入 L5-retired/）\n"
        f"  示例: {', '.join(retired_titles[:5])}\n"
        f"- 自动补 tag: {tag_added} 张\n"
        f"  示例: {'; '.join(tag_examples)}"
    )


def cmd_audit_l1_consistency(dry_run: bool = True) -> str:
    """
    存量 L1 语义一致性审计。

    仅对 active 原则卡跑「原则陈述↔行动指引」主题一致性检测（复用
    validate_principle_consistency）。错位的存量卡即为历史上被「文档碎片误抽」
    的产物——它们逃过了 ingest 时的闸门，是 backfill 未覆盖的存量债。

    dry_run=True（默认）：只列出候选，不落盘。
    dry_run=False（需带 --retire 标志）：批量执行一致性退役。
    """
    index = load_index()
    principles = [
        e
        for e in index["entries"]
        if e.get("type") == "principle" and e.get("status") == "active"
    ]

    dropped: list[tuple[dict, dict]] = []
    for e in principles:
        path = f"knowledge/L1-principles/{e['slug']}.md"
        try:
            content = open(path, encoding="utf-8").read()
        except FileNotFoundError:
            continue
        diagnosis = validate_principle_consistency({"content": content})
        if not diagnosis["consistent"]:
            dropped.append((e, diagnosis))

    if not dropped:
        return "✅ L1 一致性审计：无错位卡，存量原则卡全部通过闸门。"

    lines = [
        f"{'🔍 预览（不落盘）' if dry_run else '🗑 执行一致性退役'}",
        f"错位候选: {len(dropped)} / {len(principles)} 张 active 原则卡",
        "",
    ]
    for e, diag in dropped:
        lines.append(
            f"- {e['slug']} | score={diag['score']} | {diag['reason']}"
        )

    if dry_run:
        lines.append("")
        lines.append("（加 --retire 执行退役）")
        return "\n".join(lines)

    # 批量退役：复用原地退役逻辑，最后统一 save 一次索引
    retired_count = 0
    for e, diag in dropped:
        _retire_entry_in_place(
            index,
            e,
            reason=f"存量 L1 语义不一致（score={diag['score']}）：{diag['reason']}",
        )
        retired_count += 1
    save_index(index)

    return (
        f"✅ 一致性退役完成: {retired_count} 张原则卡移入 L5-retired/\n"
        f"剩余 active 原则卡: {len(principles) - retired_count} 张"
    )


def cmd_protect(knowledge_id: str, mark: bool = True) -> str:
    """
    人工标记/取消标记核心知识（index.json 中 entry 的 "core" 字段）。

    被标记核心的卡在 retire-scan 中免于任何自动退役（含空洞判定与时间窗口），
    是「空洞卡片直接退役」规则的白名单逃生阀。
    """
    index = load_index()

    target = None
    for entry in index["entries"]:
        if entry["id"] == knowledge_id:
            target = entry
            break

    if not target:
        return f"❌ 未找到知识条目: {knowledge_id}"

    target["core"] = mark
    index["updatedAt"] = _now_iso()
    save_index(index)

    action = "标记为核心（免于自动退役）" if mark else "取消核心标记"
    return f"✅ 已{action}: `{target['title']}`"


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
        workspace = None
        if "--workspace" in sys.argv[2:]:
            i = sys.argv.index("--workspace")
            workspace = sys.argv[i + 1] if i + 1 < len(sys.argv) else None
        print(cmd_scan(workspace))

    elif command == "precheck":
        workspace = None
        if "--workspace" in sys.argv[2:]:
            i = sys.argv.index("--workspace")
            workspace = sys.argv[i + 1] if i + 1 < len(sys.argv) else None
        print(cmd_precheck(workspace))

    elif command == "config":
        print(cmd_config(sys.argv[2:]))

    elif command == "overview":
        print(cmd_overview())

    elif command == "stats":
        print(cmd_stats())

    elif command in {"maintain", "retire-scan"}:
        print(cmd_lifecycle_maintenance(dry_run="--dry-run" in sys.argv[2:]))

    elif command == "iterate-scan":
        # 活体演进扫描：默认 dry-run 只读审计；--apply 才写盘；--min-overlap 调阈值
        apply = "--apply" in sys.argv[2:]
        min_overlap = 0.3
        for i, arg in enumerate(sys.argv[2:], start=2):
            if arg == "--min-overlap" and i + 1 < len(sys.argv):
                try:
                    min_overlap = float(sys.argv[i + 1])
                except ValueError:
                    pass
        print(cmd_iterate_scan(apply=apply, min_overlap=min_overlap))

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

    elif command == "recall":
        # 主动召回：--workspace 项目路径 | --intent 意图文本 | --json 结构化 | --top N
        workspace = None
        intent = None
        as_json = "--json" in sys.argv[2:]
        top_k = 8
        for i, arg in enumerate(sys.argv[2:], start=2):
            if arg == "--workspace" and i + 1 < len(sys.argv):
                workspace = sys.argv[i + 1]
            elif arg == "--intent" and i + 1 < len(sys.argv):
                intent = sys.argv[i + 1]
            elif arg == "--top" and i + 1 < len(sys.argv):
                try:
                    top_k = int(sys.argv[i + 1])
                except ValueError:
                    pass
        print(cmd_recall(intent=intent, workspace=workspace, top_k=top_k, as_json=as_json))

    elif command == "protect" and len(sys.argv) >= 3:
        unprotect = "--unprotect" in sys.argv[2:]
        # NOTE: 仅取首个非选项参数作为知识条目 ID，--unprotect 视为开关而非 ID。
        knowledge_id = next(
            (a for a in sys.argv[2:] if not a.startswith("--")), None
        )
        if knowledge_id:
            print(cmd_protect(knowledge_id, mark=not unprotect))

    elif command == "dupcheck":
        print(cmd_dupcheck())

    elif command == "backfill":
        print(cmd_backfill(dry_run="--dry-run" in sys.argv[2:]))

    elif command == "audit-l1-consistency":
        # 存量 L1 语义一致性审计：对 active 原则卡跑「原则陈述↔行动指引」错位检测，
        # 错位卡默认预览，加 --retire 才执行一致性退役（不写 --dry-run 也只预览）。
        dry_run = "--dry-run" in sys.argv[2:] or "--retire" not in sys.argv[2:]
        print(cmd_audit_l1_consistency(dry_run=dry_run))

    else:
        print(f"❌ 未知命令: {command}")
        print(__doc__)


if __name__ == "__main__":
    main()
