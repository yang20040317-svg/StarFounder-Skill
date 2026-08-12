"""存量闸门审计：对当前全部 active 卡按「新 scan gate 标准」复核，列出当年本不该入库的漏网卡。

判定口径（与 learn.py 的 _scan_gate / score_content_fulfillment 完全对齐）：
- 充实度 hollow：score_content_fulfillment 返回 score < HOLLOW_SCORE_THRESHOLD(40) → 内容空洞，新闸门会拦。
- template 决策字段缺失：落盘卡「核心内容」里适用条件/禁忌/决策理由章节为占位腔
  （命中 _PLACEHOLDER_PATTERNS 的「由…决定」「（未提供）」等）→ 等价于源 MD 的 decision_complete=False，gate 会拦。

覆盖两路来源（索引与磁盘可能不完全同步）：
1. 索引中 status=active 的卡（principle/checklist/pitfall 等）
2. 磁盘 knowledge/L2-assets/templates/ 下文件头标记状态=active 的卡（可能不在索引里）
"""

import io
import json
import re
import sys
from pathlib import Path

# Windows 终端常为 GBK，强制 stdout/stderr 为 UTF-8，避免 emoji/中文打印报错
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# 将技能根目录加入 import 路径，复用 learn.py 内部评分与索引逻辑
SKILL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SKILL_DIR))

import learn  # noqa: E402

KNOWLEDGE_DIR = SKILL_DIR / "knowledge"
TEMPLATES_DIR = KNOWLEDGE_DIR / "L2-assets" / "templates"

# template 决策章节的占位腔标记（与落盘卡渲染格式对应）
DECISION_PLACEHOLDER_MARKERS = (
    "由模板中的变量和配置项决定",
    "由代码片段实际执行结果决定",
    "由模板中的变量",
    "由代码片段",
    "（未提供）",
    "(未提供)",
    "未提供",
)


def _read_card_body_from_path(path: Path) -> str:
    """直接从落盘文件读取「## 核心内容」之后的正文。"""
    text = path.read_text(encoding="utf-8")
    match = re.search(r"## 核心内容\s*\n+(.*)", text, re.DOTALL)
    return match.group(1).strip() if match else text.strip()


def _card_status_from_path(path: Path) -> str:
    """从落盘文件头读取状态字段。"""
    text = path.read_text(encoding="utf-8")
    m = re.search(r"-\s*\*\*状态\*\*\s*:\s*(\w+)", text)
    return m.group(1) if m else "unknown"


def _card_has_placeholder_decision(body: str) -> list[str]:
    """检测落盘 template 卡里决策章节是否仍是占位腔。"""
    return [m for m in DECISION_PLACEHOLDER_MARKERS if m in body]


def audit() -> dict:
    index = learn.load_index()
    active_entries = [e for e in index["entries"] if e.get("status") == "active"]

    hollow_cards = []          # 索引 active 卡中充实度空洞
    missing_decision_cards = []  # template 决策字段缺失（磁盘）
    leak_cards = []            # 综合漏网卡

    # ── 1. 索引 active 卡：按充实度 hollow 复核（所有类型）
    for entry in active_entries:
        fulfillment = learn.score_content_fulfillment(entry)
        if fulfillment["hollow"]:
            hollow_cards.append((entry, fulfillment))
            leak_cards.append({
                "source": "index",
                "id": entry.get("id"),
                "title": entry.get("title"),
                "type": entry.get("type"),
                "domain": entry.get("domain"),
                "weight": entry.get("weight"),
                "score": fulfillment["score"],
                "reasons": [f"内容空洞（充实度 {fulfillment['score']}）"],
            })

    # ── 2. 磁盘 templates 目录：状态=active 的卡按决策字段占位腔复核
    if TEMPLATES_DIR.exists():
        for path in TEMPLATES_DIR.glob("*.md"):
            if _card_status_from_path(path) != "active":
                continue
            body = _read_card_body_from_path(path)
            hits = _card_has_placeholder_decision(body)
            if hits:
                title_m = re.search(r"^#\s+(.+?)\s*$", path.read_text(encoding="utf-8"), re.MULTILINE)
                title = title_m.group(1) if title_m else path.stem
                # 尝试在索引中找对应 id
                idx_id = None
                for e in active_entries:
                    if e.get("slug") == path.stem:
                        idx_id = e.get("id")
                        break
                missing_decision_cards.append((path.stem, hits))
                leak_cards.append({
                    "source": "disk-template",
                    "id": idx_id,
                    "title": title,
                    "type": "template",
                    "domain": None,
                    "weight": None,
                    "score": None,
                    "reasons": [f"决策字段占位腔（{'; '.join(hits[:2])}）"],
                })

    return {
        "total_active_index": len(active_entries),
        "hollow_count": len(hollow_cards),
        "missing_decision_count": len(missing_decision_cards),
        "leak_count": len(leak_cards),
        "leaks": leak_cards,
    }


def main() -> None:
    result = audit()
    print("## 🔍 存量闸门审计（按新 scan gate 标准）")
    print(f"- 索引活跃卡总数：{result['total_active_index']}")
    print(f"- 内容空洞（score<40）：{result['hollow_count']} 张")
    print(f"- template 决策字段缺失（磁盘 active）：{result['missing_decision_count']} 张")
    print(f"- **漏网卡合计（当年本不该入库）：{result['leak_count']} 张**")
    print()
    if not result["leaks"]:
        print("✅ 无漏网卡，存量与新闸门标准一致。")
        return

    print("### 漏网卡清单")
    for item in result["leaks"]:
        reason_text = "；".join(item["reasons"])
        loc = "索引" if item["source"] == "index" else "磁盘template"
        print(f"- [{loc}] {item['title']} "
              f"（type={item['type']}, id={item['id']}, 权重={item['weight']}, 充实度={item['score']}）— {reason_text}")

    out_path = SKILL_DIR / "audit-leak-cards.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print(f"📄 详细结果已导出：{out_path}")


if __name__ == "__main__":
    main()
