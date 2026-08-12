---
name: starfounder-experience-alchemy
description: 将项目 Markdown 文档转化为可复用、可迭代、可退役的结构化知识资产；适用于学习项目、提取经验、更新知识库和扫描退役候选。
---

# StarFounder 经验炼金引擎 — 技能定义 v2

> **使命**：把每次项目的 MD 文档转化为可复用、可迭代、可退役的结构化经验资产。

---

## 六层学习框架（核心方法论）

### L1 · 第一性原理进拆解

拿到项目 MD 后，不做表面总结。多维度信号评分：

1. **标题信号**：含"原理/原则/核心/决策/权衡"等关键词（权重 ×2）
2. **模式信号**：段落含"因为...所以"/"选择...而非"/"本质是"等推理结构
3. **否定信号**：从"踩坑/避免/不要/反思"中提取反面原理

**质量阈值**：至少命中 2 个信号才认定为原理，按信号强度排序取 Top 10。

**事后校验（语义一致性）**：抽取出的卡片需通过「原则陈述 ↔ 行动指引」主题一致性检测，过滤两者脱节的错位卡片（实词重叠度低于阈值、或极性互斥且无共享实体）。被过滤的卡片不入库，仅在报告中列出供人工复核。详见 `learn.py` 的 `audit_l1_consistency`。

输出产物：`knowledge/L1-principles/{slug}.md`，每个文件一条原理。

---

### L2 · 每次投入留下可复用资产

从项目 MD 中提取**下次能直接用的东西**：

| 资产类型 | 示例 | 输出路径 |
|---------|------|---------|
| 代码模板 | 脚手架、配置文件、脚本骨架（≥3行，排除调试输出） | `L2-assets/templates/{slug}.md` |
| 检查清单 | 上线前 checklist、安全审计清单 | `L2-assets/checklists/{slug}.md` |
| 决策框架 | 可复用模式、方案与技术决策 | `L2-assets/frameworks/{slug}.md` |
| 踩坑日志 | 已知陷阱 + 绕过方案（5 种正则模式） | `L2-assets/pitfalls/{slug}.md` |

**原则**：如果不提取成资产，这个项目的经验就浪费了 70%。

---

### L3 · 分类

所有知识卡片按**领域 × 类型**二维分类，使用优先级加权关键词匹配：

**领域分类**（高优关键词权重 ×5，普通 ×1）：
- `frontend` — React/Vue/HTML/CSS/组件/渲染/构建
- `backend` — API/数据库/认证/队列/架构
- `devops` — 部署/Docker/CI-CD/监控
- `design` — UI/UX/设计系统/交互
- `business` — 产品/增长/运营/商业模式
- `ai` — LLM/Prompt/Agent/RAG/模型部署
- `security` — 安全审计/漏洞/合规
- `general` — 通用工程实践

**类型标签**：
- `principle` / `pattern` / `template` / `pitfall` / `checklist` / `decision`

---

### L4 · 迭代（自动检测）

每次 ingest 自动执行四关系检测（基于标题词汇重叠度 + 领域匹配）：

| 关系 | 触发条件 | 处理方式 |
|------|---------|---------|
| **CONFIRM** | 标题重叠 >60%，同领域 | 已有知识权重 +2，不新建卡片 |
| **EXTEND** | 标题重叠 30-60%，同领域 | 追加内容，版本号 +1，旧版存档到 L4-iterations/ |
| **CONFLICT** | 标题重叠 15-30%，含否定词 | 标记冲突双方，输出警告等待人工裁决 |
| **NEW** | 无匹配 | 新建卡片 |

**原则**：不覆盖，只追加。版本历史是比当前版本更有价值的信息。

### L4.5 · 摄入前查重（治本方案）

标题重叠判定只能捕获"标题相似"的重复；但多项目反复生成**内容高度相似、标题却不同**的近似模板（如不同项目都产出的 Dockerfile 模板），会漏过 L4 落为 NEW，最终在库内堆积成重复资产（`dupcheck` 的灰区即此类下游症状）。

因此在 L4 之后、写盘之前，对每条 NEW 知识再做一次**正文相似度查重**：

- 算法：复用 L2 去重的实词 Jaccard 口径（模板先剥离框架套话）
- 阈值：`INGEST_DEDUP_THRESHOLD = 0.6`（沿用 dupcheck 高置信基线上沿）
- 命中高相似（≥0.6）：**跳过新建**（不占存储），仅把来源项目追加到已有卡片 `crossRefs`，关系标记为 `PREINGEST_DEDUP`，并刷新 `lastReferencedAt`（等效一次轻量旁证 CONFIRM）
- 未命中：正常新建

> 事后 `dupcheck` 只能发现重复、无法阻止存储膨胀；摄入前查重从源头堵住漏水口，比事后清理更省空间。二者互补：`dupcheck` 用于治理历史债，`ingest` 查重防止新债产生。

---

### L5 · 删除（退役机制）

生命周期维护命令会先执行 L6 权重衰减，再扫描退役候选：

```bash
python learn.py maintain
python learn.py maintain --dry-run
```

`maintain` 只自动更新权重并列出候选，不自动退役；退役仍需人工执行 `retire <id> --reason "..."`。

触发退役的条件（满足任一）：

- AI 能力已经覆盖此经验
- 工具/框架升级后不再适用
- 经验被证明错误或有更好替代
- 90 天未更新且权重 ≤5
- 120 天从未迭代
- 180 天未被引用

**退役不等于删除**：移入 `L5-retired/`，索引中标记 `status: retired`，保留可检索。

---

### L6 · 继续学习（自动执行）

每摄入一个新项目 MD 时执行；也可通过 `maintain` 独立执行生命周期维护：

1. **L4 迭代检测** — 四关系检测（CONFIRM/EXTEND/CONFLICT/NEW）
2. **交叉引用追踪** — 更新 `crossRefs` 字段，追踪知识之间的引用关系
3. **权重衰减** — 每 30 天未被引用，权重自动 -1（最低 1），按 `weightDecayedAt` 水位幂等执行
4. **空白扫描** — 报告哪些领域尚无知识积累
5. **退役候选** — 扫描满足 L5 条件的老知识；`maintain --dry-run` 可只预览不落盘

---

## 处理流程（完整管线）

```
用户提供 project.md
        │
        ▼
┌─────────────────────────────────┐
│ Step 1: 结构解析                │
│ 提取标题/章节/技术栈/关键决策    │
│ 提取代码块（语言/路径标注）      │
│ 提取错误信息与修复日志           │
└──────────────┬──────────────────┘
               ▼
┌─────────────────────────────────┐
│ Step 2: L1 第一性原理拆解        │
│ 追问三问 → 提炼底层原理          │
│ → 写入 L1-principles/           │
└──────────────┬──────────────────┘
               ▼
┌─────────────────────────────────┐
│ Step 3: L2 资产提取              │
│ 代码模板/检查清单/决策框架/陷阱   │
│ → 按类型写入 L2-assets 子目录    │
└──────────────┬──────────────────┘
               ▼
┌─────────────────────────────────┐
│ Step 4: L3 分类入库              │
│ 领域分类 + 类型标签 + 关键词      │
│ → 只写入 index.json 元数据       │
└──────────────┬──────────────────┘
               ▼
┌─────────────────────────────────┐
│ Step 5: L4 迭代检测              │
│ 检查是否与已有知识冲突/补充       │
│ → 更新版本记录                   │
└──────────────┬──────────────────┘
               ▼
┌─────────────────────────────────┐
│ Step 6: L5 退役扫描 + L6 权重     │
│ 建议退役清单 + 更新索引权重       │
│ → 输出学习报告                   │
└─────────────────────────────────┘
```

---

## 输出格式

处理完一个项目 MD 后，输出结构化学习报告：

```markdown
## 📊 学习报告：{项目名称}

### L1 · 提取原理（{N} 条）
- **{原理标题}** — {一句话摘要} → `L1-principles/{slug}.md`

### L1 · 语义一致性校验（过滤 {M} 条）
- ⚠️ **{被过滤原理标题}** (重叠度 {score}) — {错位原因}

### L2 · 可复用资产（{N} 件）
- **[模板]** {描述} → `L2-assets/templates/{slug}.md`
- **[清单]** {描述} → `L2-assets/checklists/{slug}.md`
- **[框架]** {描述} → `L2-assets/frameworks/{slug}.md`
- **[陷阱]** {描述} → `L2-assets/pitfalls/{slug}.md`

### L3 · 分类入库
- 分类元数据写入 `index.json`：`frontend` ×2, `backend` ×1, `devops` ×1

### L4 · 迭代
- 补充了 `xxx` 的 v2（新增场景：...）
- 无冲突

### L5 · 退役建议
- `xxx` — 90天未引用，建议退役

### L6 · 权重更新
- {被引用知识} +1, {衰减知识} 权重降低 → 当前索引概览
```

---

## 知识卡片模板

每张知识卡片统一用以下 Markdown 模板：

```markdown
# {标题}

- **领域**: {frontend/backend/devops/design/business/ai/security/general}
- **类型**: {principle/pattern/template/pitfall/checklist/decision}
- **版本**: v{1}
- **来源项目**: {项目名}
- **创建时间**: {ISO 8601}
- **权重**: {0-100}
- **状态**: {active/deprecated/retired}
- **标签**: {tag1, tag2}

---

## 核心内容

{具体知识内容}

## 使用场景

{什么情况下可以使用/参考此知识}

## 前置条件

{使用此知识需要的环境/依赖/技能}

## 已知局限

{此知识不适用的情况}
```

---

## 触发词

当用户说以下内容时，自动激活此技能：
- "学习这个项目" / "从项目里提取经验"
- "总结可复用经验" / "沉淀知识"
- "更新知识库" / "迭代经验"
- "退役过时知识" / "清理知识库"

---

## 会话启动钩子（激活时执行）

> **主动反哺回路**：知识库不能只单向写入 `knowledge/`。AI 在对话开头必须主动把库里相关经验「捞出来、塞进上下文、给建议」，带着经验干活，而不是等用户手动 `search`。本钩子实现三层反哺：①主动召回 ②上下文注入 ③决策建议。

当用户命中上方「触发词」或语义与本技能相关时，**在动手前先执行主动召回**：

```bash
# 方式一：传入当前项目路径，引擎自动从目录名 + 近期 MD 推导意图词并召回
python learn.py recall --workspace "D:\当前项目"

# 方式二：直接描述意图（无项目路径时）
python learn.py recall --intent "Docker 容器构建镜像体积优化"

# 结构化输出（便于脚本/自动化二次处理）
python learn.py recall --workspace "D:\当前项目" --json
```

`recall` 输出包含三层内容，请**全部纳入本次对话的系统提示/任务上下文**：
1. **主动召回**：按意图词加权匹配（标题 > tag > 正文实词，高权重卡优先），返回 Top-N 相关卡片；
2. **上下文注入**：每张命中卡附「核心内容」摘要，直接作为你思考该问题的背景经验；
3. **决策建议**：自动从命中卡筛出 `pitfall` / `checklist`，聚类产出「⚠️ 这个项目要当心 X」「✅ 上线前按 Y 清单核对」的主动提醒。

**补充基线（领域级）**：若要判断"该学什么/哪些领域空白"，再跑：

```bash
python learn.py overview   # 领域分布 / 空白领域 / Top 高权重知识
```

将 `overview` 的「空白领域 / 已饱和领域」作为摄入去重基线——用户要"学新项目"时先看哪些领域已饱和、哪些是空白，避免重复摄入近似模板。

**条件触发，非每次会话**：仅在技能被激活时执行，纯闲聊或与知识库无关的任务不触发，避免无谓的索引读取开销。`recall` 默认只读索引 + 命中卡正文，开销可控。

---

## CLI 命令

```bash
python learn.py ingest <file>     # 学习单个项目 MD（含 L4.5 摄入前查重：高度相似则跳过新建）
python learn.py scan              # 扫描 config.json 的 scan_roots（多目录）+ 当前工作区：新增或「内容有改动(mtime 变化)」的 MD 会重新摄入；未改动则跳过（不重复）
python learn.py scan --workspace "D:\当前项目"   # 额外扫描你正在编程的位置（自动识别，不写入 config）
python learn.py config --list               # 查看当前扫描源
python learn.py config --add-root "D:\新项目"   # 新增扫描源（无需手动建软链）
python learn.py config --remove-root "D:\旧项目" # 移除扫描源
python learn.py config --auto-workspace on|off  # 是否自动包含工作区
python learn.py overview          # 知识库概览 + 空白扫描 + 失衡检测
python learn.py stats             # 健康度诊断报告（含内容充实度：平均充实度/空洞卡片率/占位填充率）
python learn.py search "关键词"    # 搜索知识库
python learn.py recall --workspace "D:\项目" # 主动召回：按项目/意图捞相关卡 + 注入摘要 + 决策建议（三层反哺，按业务 tag 语义命中）
python learn.py recall --intent "描述" --json  # 按意图召回（结构化输出）
python learn.py backfill          # 存量回填：补建孤儿关联 + 批量退役空洞卡 + 自动补业务 tag（从标题+正文推导，供 recall 语义召回）
python learn.py backfill --dry-run # 预演（不落盘）
python learn.py retire-scan       # 列出退役候选
python learn.py dupcheck          # L2 模板相似度去重检测（疑似重复对）
python learn.py retire <id> --reason "原因"  # 退役
python learn.py protect <id>       # 人工标记核心（免于 retire-scan 自动退役，含空洞规则）
python learn.py protect <id> --unprotect  # 取消核心标记
python learn.py iterate-scan       # L6 活体演进：active 卡两两互比，发现 CONFIRM/EXTEND/CONFLICT 并给退役外建议（默认 dry-run 只读）
python learn.py iterate-scan --apply     # 真正写入索引（权重/版本/crossRefs）；CONFLICT 仅告警不自动改
python learn.py iterate-scan --min-overlap 0.4  # 调整最小重叠阈值（默认 0.3）
```

> **退役候选判定（retire-scan）**：满足以下任一即进候选——
> - 90 天未更新且权重 ≤ 5；或 120 天从未迭代；或 **180 天未被引用**；
> - **空洞卡片**：内容充实度 < 40（`score_content_fulfillment` 口径），直接进候选，**不必等 180 天时间窗口**（装饰性空壳应尽早清理）；`template` 类型本就是「给他人填的壳」，此规则不适用，避免误杀可复用骨架。
>
> **人工白名单**：经 `protect <id>` 标记 `core: true` 的卡，免于一切自动退役（含空洞规则）；`protect <id> --unprotect` 取消。

## 治理规则

1. **来源必须可追溯**：每条知识必须标注来源项目和原文引用
2. **不添加未经项目验证的知识**：只从 MD 中提取，不凭空补充
3. **退役审计永不自动执行**：退役建议需要用户确认
4. **索引即真相**：`knowledge/index.json` v2 格式，含 crossRefs、lastReferencedAt、weight 等治理字段
5. **Slug 唯一性**：自动追加短哈希防止文件名冲突
6. **幂等保护**：`.learned.json` 记录已学习文件，避免重复摄入

## 部署说明（本机）

- **扫描源由 `config.json` 驱动**（不再写死 junction）：`scan_roots` 是字符串数组，列出要扫描的目录；`auto_include_workspace` 控制是否自动纳入当前工作区。
- 当前配置：`scan_roots = ["D:\\shujuchucun"]`，即用户的项目资料库。因此 `scan` 与每日自动化直接读取 D 盘项目，无需手动搬运文件。
- `scan` 为**递归**扫描，并跳过 `node_modules` / `.git` / `.codebuddy` / `.backup` / `dist` / `build` / `.workbuddy` 等噪声目录，避免把第三方依赖或 Agent 内部文档吃进知识库。
- **自己改扫描源（无需找助手）**：
  - 直接编辑 `config.json` 的 `scan_roots` 数组；或
  - 运行 `python learn.py config --add-root "D:\新项目"` / `--remove-root "D:\旧项目"`；或
  - 对话里说「学一下 D:\xxx」「把 D:\yyy 加进经验库」等，由助手写入 config。
- **自动识别当前编程位置**：在对话里触发扫描时，可传入 `--workspace <当前项目路径>`，该目录会临时加入本次扫描（不写入 config，下次需重传）；也可保持 `auto_include_workspace: true`，由助手在对话时自动把当前工作区传入。
- `C:\Users\27513\WorkBuddy`（WorkBuddy 内部数据目录）**未**纳入固定扫描源，避免把内部会话/记忆 .md 当作项目知识摄入（`.workbuddy` 目录已被排除规则覆盖）。
