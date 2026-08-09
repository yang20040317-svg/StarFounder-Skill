# Ribbit Scanner — 多源需求信号扫描器

> 一个零依赖的多源 Web 采集管线，从 Reddit、Hacker News、V2EX、Amazon、Product Hunt、Dev.to、Indie Hackers 七大平台中智能探测需求信号，并通过 Google Trends 进行交叉验证。纯 Python 后端 + Vanilla JS 前端，无需 OAuth，无需数据库。

---

## 项目概况

- **技术栈**: Python 3.10+（核心管线）+ Vanilla JS + HTML5 + CSS3
- **架构模式**: 多阶段管线（Phased Pipeline）+ 三层数据降级（Graceful Degradation）
- **数据源**: Reddit, Hacker News, V2EX, Amazon, Product Hunt, Dev.to, Indie Hackers, Google Trends
- **核心能力**: 需求信号分类（7 类）、情感分析、场景识别、热度评分、趋势交叉验证

---

## 架构设计 —— 为什么这样设计

### 核心设计决策：零 OAuth 的 HTML 解析策略

这个系统最根本的设计考量是：**全程不依赖任何 OAuth 流程或 API Key**。

选择通过 old.reddit.com 的 `data-*` HTML 属性解析帖子，而非使用 Reddit 的官方 API。同样，Amazon 评论爬取走的是公开的 HTML 页面，Product Hunt 和 Indie Hackers 也通过 HTML 解析实现。

因为需求信号扫描是一个低频的分析任务，不是高频的实时数据流。零认证的设计使得系统可以在任何环境（包括 CI/CD、一次性容器）中运行，无需配置密钥管理。**真正的问题不是"怎么获取数据"，而是"怎么在不引入认证复杂度的前提下获取足够好的信号"。**

### 三层数据降级模式

前端采用三层数据加载策略，本质上是一个容错设计：

```
Layer 1: insights.json → 本地缓存（首次加载最快）
Layer 2: Backend API  → 实时数据（通过 fetch 调用）
Layer 3: data.js mock → 兜底数据（确保界面永不白屏）
```

选择这种降级链而不是单一数据源，因为信号扫描的产出是分析型数据——它对"最新"的敏感度远低于交易型数据。与其在 API 不可用时向用户展示错误，不如优雅地展示上一次的成功结果。**关键洞察：对于分析类产品，可用性优先于实时性。**

### 需求信号的分类体系设计

7 类需求类型采用**有序关键词匹配**：`产品机会 > 替代方案 > 功能需求 > 营销话题 > 内容选题 > SEO词根 > 短期热闹`。

这个排序不是随机的。因为用户在 Reddit 上说"有什么替代 Notion 的？"同时提到了"产品"和"替代"，按优先级匹配确保它被归类为更有商业价值的"替代方案"而非通用的"产品机会"。**本质是对商业信号做了隐式权重建模，用排序规则代替了复杂的 NLP 模型。**

---

## 管线详解 —— 从信号采集到行动建议

### Phase 1：社区讨论信号

```
scanner.py → Reddit (old.reddit.com HTML) + Hacker News (Firebase API) + V2EX (v2ex.com API)
```

Reddit 解析策略的关键：通过 `data-*` 属性（`data-author`、`data-subreddit`、`data-timestamp`）直接提取结构化数据，完全避免 JSON API 的限流问题。不是调用 API，而是从 HTML 中"偷"数据——因为 old.reddit.com 的 DOM 结构比 JSON API 更稳定。

HN 选择 Firebase API 而非官方的 Algolia Search API：Firebase `/v0/item/` 端点运行在 Google 基础设施上，延迟极低且无频率限制。而 Algolia 的搜索 API 有隐性速率限制，在高频批量拉取场景下不可靠。

### Phase 2：电商评价信号

```
reviews_scraper.py → Amazon HTML + Product Hunt Review
```

Amazon 评论爬取使用 HTML 选择器（`[data-hook="review-body"]`、`[data-hook="review-title"]`）配合 User-Agent 伪装，而非社区维护的爬虫框架。**选择原生 requests + BeautifulSoup 而非 Scrapy 框架，是因为本系统的爬取规模不需要调度器、中间件链和去重逻辑——过度设计反而增加维护负担。**

Product Hunt 的 API 虽然公开，但需要注册应用。HTML 解析避免了这一步骤，同时 Product Hunt 的页面结构变化频率极低（每年 1-2 次），维护成本可控。

### Phase 3：内容平台信号

```
content_scraper.py → Dev.to API (公开 RSS) + Indie Hackers HTML
```

Dev.to 的 RSS API 零配置，直接返回 Markdown 格式的正文，无需任何认证。Indie Hackers 的 HTML 结构简单稳定，CSS 选择器抽取即可。

### Phase 4：趋势交叉验证

```
trends.py → Google Trends (文件缓存 + 72h TTL)
```

Google Trends 没有公开 API，通过 `pytrends` 库调用，使用 72 小时文件缓存避免被 Google 限流。缓存策略不是基于数据库，而是基于本地 JSON 文件——因为信号扫描场景下不需要多进程共享缓存，文件系统已经足够。

---

## 设计原理 —— 可复用的核心经验

### 原理 1：信号评分需要"反虚高"机制

热潮评分公式包含了 Google Trends 验证分、来源平台权威分、情感强度分。但核心的保护机制是：**短文本（<30 字）的原始热度分量会被乘以 0.5 的衰减系数**。

因为 Reddit 上大量热帖其实是 meme 或灌水（如几十字的吐槽），但 UGC 平台对这些内容也有极高的点赞量。不是因为内容有价值，而是因为容易消费。衰减系数本质上是在对抗"低信息密度内容"——这类内容在点赞/评论指标上虚高，但不具备任何商业信号价值。

### 原理 2：全量重跑优于增量更新

系统每次扫描都会重新拉取全部数据并完整覆盖 `insights.json`，不做增量更新。这不是效率妥协，而是刻意选择。

因为需求信号的判断依赖全局上下文——当某种声音从 5 条变为 50 条时，信号性质会从"短期热闹"升级为"产品机会"。增量更新的 delta 模式无法感知这种质变，因为它只看新增/变化的部分。**本质是：信号检测是时间窗内的全局排序问题，不是流式计算问题。**

### 原理 3：前端状态管理的最小可行性方案

没有使用 React/Vue，而是用原生 DOM 操作 + 事件委托。因为：
- 状态只有两个：信号列表 + 筛选状态
- 交互只有四种：筛选、排序、查看详情、标记状态
- 数据流是单向的：数据源 → 渲染 → 用户操作 → 重新渲染

对于这种复杂度，引入框架的模板编译和虚拟 DOM diff 反而增加性能开销。**选择工具前先问：你的状态形态是什么？不是"我该用哪个框架"，而是"我的状态图能有多复杂"。**

---

## 信号识别引擎 —— 核心算法细节

### 有序关键词匹配的实现

```python
NEED_TYPES = [
    ("产品机会", ["想找", "有没有", "求推荐", "哪里能买到", "怎么实现"]),
    ("替代方案", ["替代", "竞品", "除了", "有没有类似", "换成"]),
    ("功能需求", ["希望", "如果能", "能不能", "加个功能", "想要"]),
    ("营销话题", ["爆火", "大家都在", "火了", "趋势", "风口"]),
    ("内容选题", ["怎么学", "教程", "入门", "新手", "经验分享"]),
    ("SEO词根", ["最好用的", "免费的", "在线", "工具", "网站"]),
    ("短期热闹", ["震惊", "太牛了", "笑死", "无语", "离谱"]),
]

def classify_need_type(text):
    """按优先级匹配，第一个命中即返回"""
    for need_type, keywords in NEED_TYPES:
        if any(kw in text for kw in keywords):
            return need_type
    return "其他"
```

### 痛感描述生成

```python
def generate_pain_desc(post, need_type):
    """根据需求类型生成结构化的痛感描述"""
    templates = {
        "产品机会": f"用户正在寻找{post.get('topic', '某类产品')}，当前市场存在空白",
        "替代方案": f"用户对{post.get('current_tool', '现有方案')}不满意，寻求替代品",
        "功能需求": f"用户希望{post.get('platform', '某产品')}能支持{post.get('feature', '某项功能')}",
        "营销话题": f"'{post['title']}'话题正在快速升温，存在流量红利",
        "内容选题": f"大量用户在搜索'{post.get('topic', '某主题')}'的入门教程",
        "SEO词根": f"'{post['title']}'这类长尾词有搜索量但竞争低",
        "短期热闹": f"'{post['title']}'短期内关注度高但持续性存疑",
    }
    return templates.get(need_type, f"需要进一步分析: {post['title']}")
```

### 热度综合评分

```python
def compute_heat_score(signal):
    """综合多维度指标计算热度评分 (0-100)"""
    raw_heat = signal.get("upvotes", 0) * 0.3 + signal.get("comments", 0) * 0.4
    # 短文本衰减：低于30字的帖子热度减半
    if len(signal.get("content", "")) < 30:
        raw_heat *= 0.5
    # 趋势修正
    trend_score = signal.get("searchTrend", {}).get("score", 0)
    return min(100, round(raw_heat * 0.6 + trend_score * 0.4))
```

---

## 踩坑记录与经验教训

### 踩坑 1：Reddit JSON API 的 429 限流陷阱

最初尝试用 Reddit 的 `.json` 后缀（如 `reddit.com/r/SideProject.json`）直接获取 JSON 数据，但 Reddit 对无 User-Agent 的请求会返回 429 Too Many Requests，即使加了 UA 也有模糊的速率限制。

解决：切换到 `old.reddit.com` 的 HTML 解析。老版页面的 `data-*` 属性是服务器端渲染的，不经过 API 网关，完全不受频率限制。**避免直接使用未认证的 JSON API——HTML 页面往往是更稳定的数据源。**

### 踩坑 2：Google Trends 的瞬时封禁

使用 `pytrends` 短时间连续请求超过 5 次会触发 Google 的临时封禁（返回 429 或空数据）。而且被封后至少需要等待 2-4 小时才能解封。

解决：实现 72 小时文件缓存（`trends_cache.json`），并在两次请求之间增加 5-10 秒的随机等待。每次扫描最多请求 20 个关键词的 Trends 数据，超出的使用模拟数据填充。**外部数据源都有隐性频率围墙，缓存策略不应该在"被限流后"才加，而是在设计阶段就要内置。**

### 踩坑 3：Amazon 的 HTML 结构漂移

Amazon 的商品页面在不同品类下使用了不同的 DOM 结构。电子产品页面的 review section 在 `#cm_cr-review_list` 下，而图书页面在 `#reviews-medley-footer` 下，服装页面又不一样。

解决：多层回退选择器策略——先用精确选择器，失败后用语义选择器，再失败用 mock 数据保证流程不中断。`data-hook` 属性比 CSS class 更稳定，优先使用。**不是所有的"数据获取"都需要成功——对于分析型系统，优雅降级比完整性更重要。**

### 踩坑 4：前端 Mock 数据与真实数据脱节

开发阶段的 `data.js` 里手动构造了 20 条模拟信号，但真实数据到达后，mock 数据中的字段结构和真实 API 返回不完全一致（如 `searchTrend` 字段在 mock 中是 string 而在真实数据中是 object）。

教训：Mock 数据必须和真实 API 的 Schema 同步。**不是"开发时随便写写 mock，上线后自然就对了"——mock 数据是一种隐性契约，应该在数据层的类型定义中明确声明，最好用 JSON Schema 或 TypeScript 类型统一约束。**

---

## 上线检查清单

- [ ] 确认 Google Trends 缓存目录的写入权限
- [ ] 验证各数据源选择器的可用性（尤其是 Amazon 品类变化）
- [ ] 检查 `insights.json` 的 Schema 版本与前端 `app.js` 的兼容性
- [ ] 确认 User-Agent 头已伪装（Reddit 和 Amazon 对 default UA 敏感）
- [ ] 验证三层数据降级链路：删除 insights.json → 测试 API 降级 → 测试 mock 兜底
- [ ] 检查 `data.js` 的 mock 数据字段与真实 Schema 对齐
- [ ] 确认各平台请求间隔已设置（Reddit 2s, HN 无限制, Amazon 3s, Trends 10s）
- [ ] 运行一次完整扫描并对比历史结果，检查信号数量是否异常波动

---

## 关键决策记录

### 决策 1：为什么选择 Vanilla JS 而不是 React？

信号扫描器是典型的"仪表盘"型应用，数据流极简单：加载数据 → 渲染表格 → 筛选/排序/标记。这种场景下，React 的组件化、状态管理、虚拟 DOM 全部是过度设计。

**权衡**：牺牲了可扩展性（未来加复杂交互需要重构），换来零依赖、零构建步骤、可单文件部署。对于一个分析工具而言，部署简洁性的价值远大于前端架构的灵活性。

### 决策 2：为什么用文件缓存而不是 SQLite？

项目没有使用任何数据库，数据全部存储在 JSON 文件（`insights.json`、`trends_cache.json`）中。因为总数据量在 1000 条信号以内，单文件 JSON 的读写性能完全够用。

**权衡**：放弃了多进程并发写的安全性，但换来了零运维成本。对于单机、单用户的扫描工具，文件系统就是最好的数据库。

### 决策 3：为什么不使用异步爬虫（asyncio/aiohttp）？

所有爬取都是同步 `requests.get()`，没有任何异步。因为总数据量不超过 200 条帖子，同步请求的总耗时在 30 秒以内。引入 asyncio 会显著增加代码复杂度（错误处理、连接池管理、超时重试），收益却微乎其微。

**本质上是在选择"工程复杂度"的投放位置——把复杂度放在业务规则（信号分类、热度评分）上，而不是基础设施（并发、队列、重试）上。**
