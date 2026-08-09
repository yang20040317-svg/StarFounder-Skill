# Reddit JSON API 的 429 限流陷阱

- **领域**: frontend
- **类型**: pitfall
- **版本**: v3
- **来源项目**: ribbit-scanner
- **创建时间**: 2026-08-05T02:12:47.704809+00:00
- **最后更新**: 2026-08-05T02:12:47.704809+00:00
- **最后引用**: 2026-08-05T02:12:47.704809+00:00
- **权重**: 13
- **状态**: active
- **标签**: frontend, reddit, rate-limit, html-parsing
- **关联知识**: pitfall-google-trends-的瞬时封禁

---

## 核心内容

### 陷阱

最初尝试用 Reddit 的 `.json` 后缀（如 `reddit.com/r/SideProject.json`）直接获取 JSON 数据，但 Reddit 对无 User-Agent 的请求会返回 429 Too Many Requests，即使加了 UA 也有模糊的速率限制。

### 绕过方案

切换到 `old.reddit.com` 的 HTML 解析。老版页面的 `data-*` 属性是服务器端渲染的，不经过 API 网关，完全不受频率限制。**避免直接使用未认证的 JSON API——HTML 页面往往是更稳定的数据源。**

## 使用场景

通过 old.reddit.com 采集 Reddit 社区讨论信号，且希望避免 OAuth/API Key 接入的扫描任务。

## 前置条件

调用方需实现基于 `data-*` 属性的 HTML 解析器，并伪装 User-Agent 头。

## 已知局限

依赖 old.reddit.com 的 DOM 结构稳定性；若 Reddit 下线旧版页面，需回退到其他数据源。
