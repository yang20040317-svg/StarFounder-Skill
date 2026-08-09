# StarFounder Skill 项目记忆

## 项目定位
经验炼金引擎 v2 — 将项目 MD 文档转化为可复用、可迭代、可退役的结构化知识资产。

## 技术栈
- 核心指令：`skill.md`（AI 上下文加载）
- 学习引擎：`learn.py`（Python CLI，~950 行，v2 完整六层管线）
- 知识存储：`knowledge/` 目录下的 Markdown 卡片 + `index.json` v2 索引

## 六层框架（v2 已全部实现）
1. L1 第一性原理进拆解 — 三信号评分（标题/段落模式/否定式），≥2 信号才入库
2. L2 每次投入留下可复用资产 — 模板/清单/陷阱提取，代码块 ≥50 字符 + ≥3 行 + 噪声过滤
3. L3 分类 — 优先级加权关键词（高优 ×5，普通 ×1），解决领域重叠
4. L4 迭代 — 四关系自动检测（NEW/CONFIRM/EXTEND/CONFLICT），基于标题词汇重叠度
5. L5 删除（退役） — 过时知识 → L5-retired/，新增 180 天未引用 + 权重归零条件
6. L6 继续学习 — 交叉引用追踪、每 30 天自动权重衰减、空白领域扫描、失衡检测

## CLI 命令（v2 新增 stats）
- `python learn.py ingest <项目.md>` — 单文件摄入（完整六层管线）
- `python learn.py scan` — 批量扫描 projects/ 目录（含 .learned.json 幂等控制）
- `python learn.py overview` — 知识库概览（含空白扫描 + 失衡检测）
- `python learn.py stats` — 健康度诊断报告（领域覆盖/类型分布/权重分布/诊断建议）
- `python learn.py search <关键词>` — 搜索
- `python learn.py retire-scan` — 退役候选扫描
- `python learn.py retire <id> --reason "..."` — 执行退役

## 关键设计决策
1. 知识以 Markdown 卡片存储，index.json v2（含 crossRefs、lastReferencedAt）
2. 退役不移除，标记并移入 L5-retired
3. 版本以追加方式迭代，旧版存档到 L4-iterations/
4. L4 迭代检测：CONFIRM(>60%重叠) / EXTEND(30-60%) / CONFLICT(15-30%+否定词) / NEW(无匹配)
5. Slug 唯一性：冲突时追加 6 位 MD5 短哈希
6. L6 权重衰减：每 30 天未引用 -1（最低 1）
7. 分类器使用优先级加权（高优关键词解决 frontend/design、backend/security 重叠）
8. Windows 下 stdout 强制 UTF-8 编码
