# StarFounder 经验炼金引擎 v2

> 把每次项目的 Markdown 文档，转化为**可复用、可迭代、可退役**的结构化经验资产。

---

## 这是什么

StarFounder 是一个面向独立开发者与小团队的**经验沉淀引擎**。它不是笔记软件，也不是文档站点，而是一条从「项目复盘 MD」到「可检索知识库」的自动化管线。

每次写完一份项目总结、踩坑记录或架构复盘，把它丢进 `projects/` 目录，引擎会自动完成：

1. **拆解第一性原理** —— 从段落中识别「因为…所以…」「选择 A 而非 B」等推理结构，提炼出可迁移的底层规律，而不是表面总结。
2. **提取可复用资产** —— 代码模板、检查清单、决策框架、踩坑日志，按类型分门别类落盘，下次直接拿来用。
3. **自动分类入库** —— 按 8 个领域 × 6 种类型二维打标，写入全局索引。
4. **迭代而非覆盖** —— 新知识会与已有知识做四关系检测（NEW / CONFIRM / EXTEND / CONFLICT），证实则加权，补充则版本升级，冲突则标记待裁决，绝不静默覆盖。
5. **生命周期维护** —— 权重随时间衰减，长期未引用的知识进入退役候选，退役不删除、可恢复。

核心理念只有一句话：**版本历史比当前版本更有价值，追加比覆盖更有价值。**

---

## 核心特性

| 能力 | 说明 |
|------|------|
| **六层学习框架** | L1 原理 → L2 资产 → L3 分类 → L4 迭代 → L5 退役 → L6 维护，每层职责清晰 |
| **多信号原理提取** | 标题信号（×2）+ 段落模式 + 否定式原理，≥2 信号才入库，过滤噪声 |
| **四关系迭代检测** | 基于标题词汇重叠度 + 领域匹配，自动判定 NEW/CONFIRM/EXTEND/CONFLICT |
| **幂等摄入** | 相同内容二次学习识别为 CONFIRM，不重复创建卡片 |
| **权重衰减与退役** | 每 30 天未引用权重 −1，满足条件进入退役候选，退役可恢复 |
| **空白领域预警** | 自动扫描哪些领域尚无积累，提示补全方向 |
| **领域失衡检测** | 单领域占比 >40% 触发预警，避免知识结构偏科 |
| **纯 Markdown 存储** | 知识卡片即 `.md` 文件，索引即 `index.json`，零依赖、可读、可迁移 |

---

## 快速开始

### 环境要求

- Python 3.10+（使用了 `dict[str, str]` 等新语法）

### 安装

```bash
git clone https://github.com/yang20040317-svg/StarFounder-Skill.git
cd StarFounder-Skill
```

无需安装第三方依赖，核心引擎仅使用 Python 标准库。运行测试可选装 pytest：

```bash
pip install -r requirements-dev.txt
pytest
```

### 三步上手

**1. 放入项目 MD**

把项目复盘 / 总结的 Markdown 文件放到 `projects/` 目录：

```
projects/
├── ribbit-scanner-v1.md
├── my-saas-backend.md
└── react-dashboard-optimization.md
```

**2. 运行学习引擎**

```bash
# 学习单个项目（完整六层管线）
python learn.py ingest projects/my-saas-backend.md

# 批量扫描 projects/ 下所有新 MD（幂等安全）
python learn.py scan
```

**3. 查看与维护知识库**

```bash
python learn.py overview          # 概览 + 空白领域预警 + 失衡检测
python learn.py stats             # 健康度诊断报告
python learn.py search "React"    # 关键词搜索
python learn.py maintain          # 生命周期维护（衰减 + 退役候选）
python learn.py maintain --dry-run  # 仅预览，不落盘
python learn.py retire <知识ID> --reason "AI 已覆盖此能力"
```

---

## 六层学习框架

| 层级 | 名称 | 核心动作 |
|------|------|---------|
| **L1** | 第一性原理拆解 | 三信号评分 → 标题/模式/否定式，≥2 信号入库 |
| **L2** | 可复用资产提取 | 提取模板/清单/陷阱 → 过滤噪声，只存高价值 |
| **L3** | 分类 | 优先级加权关键词 → 8 领域 × 6 类型分类 |
| **L4** | 迭代（自动） | NEW/CONFIRM/EXTEND/CONFLICT 四关系检测 |
| **L5** | 退役 | 7 条退役条件 → 移入 retired，可恢复 |
| **L6** | 继续学习（自动） | 权重衰减 / 交叉引用 / 空白扫描 / 失衡检测 |

详细方法论见 [SKILL.md](SKILL.md)。

---

## 与 AI 协作

本仓库同时是一份可被 AI 加载的技能定义。在对话中说以下任意触发词，AI 将按 `SKILL.md` 中定义的六层框架执行完整知识提取流程：

- "学习这个项目" / "从项目里提取经验"
- "沉淀知识" / "更新知识库"
- "退役过时知识" / "清理知识库"

---

## 知识卡片结构

每条知识被存储为标准 Markdown 卡片：

```markdown
# 标题

- 领域 / 类型 / 版本 / 来源项目 / 权重 / 状态 / 标签
- 创建时间 / 最后更新 / 最后引用 / 关联知识

---

## 核心内容
## 使用场景
## 前置条件
## 已知局限
```

存储路径：

- `L1-principles/` — 第一性原理
- `L2-assets/` — 可复用资产根目录；按 `checklists/`、`frameworks/`、`pitfalls/`、`templates/` 分类落盘
- `L4-iterations/` — 版本迭代存档（v1→v2 旧版留痕）
- `L5-retired/` — 退役知识（标记但不丢弃）

---

## 设计原则

1. **来源可追溯** — 每条知识标注来源项目
2. **只从 MD 提取** — 不凭空补充未经验证的知识
3. **索引即真相** — `index.json` v2（含 crossRefs / lastReferencedAt）
4. **退役可恢复** — 不移除，只是标记为 retired
5. **生命周期可维护** — `maintain` 独立执行衰减与退役扫描，`--dry-run` 不落盘
6. **版本即历史** — 覆盖比删除更危险，追加比覆盖更有价值
7. **幂等摄入** — 相同内容二次学习自动识别为 CONFIRM，不重复创建

---

## 目录结构

```
StarFounder-Skill/
├── SKILL.md              ← 技能入口与六层流程定义
├── learn.py              ← 学习引擎 CLI
├── README.md             ← 本文件
├── pytest.ini            ← 测试配置
├── requirements-dev.txt  ← 开发依赖（仅 pytest）
├── knowledge/            ← 可复用知识资产
│   ├── index.json        ← v2 全局索引（含 L3 分类元数据）
│   ├── L1-principles/    ← 第一性原理
│   ├── L2-assets/        ← 资产根目录，按类型分目录
│   │   ├── checklists/   ← 检查清单
│   │   ├── frameworks/   ← 模式、框架与决策
│   │   ├── pitfalls/     ← 陷阱与绕过方案
│   │   └── templates/    ← 可复用模板
│   ├── L3-classified/    ← 分类体系说明
│   ├── L4-iterations/    ← 版本迭代存档
│   └── L5-retired/       ← 退役知识
├── projects/             ← 待学习的项目 MD
└── tests/                ← 引擎测试
```

---

## License

MIT
