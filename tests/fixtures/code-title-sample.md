# API 容错策略

这份复盘说明 API 服务如何通过超时、重试和降级提高稳定性。

## 指数退避重试模板

下面的实现用于可恢复网络异常，避免固定间隔造成请求风暴。

适用场景：仅当上游返回可恢复异常（如超时、5xx）时调用该模板，固定间隔重试会放大请求风暴。

不要用：遇到 4xx 客户端错误时不要用它，重试对鉴权/参数类错误无意义。

选择指数退避而非固定间隔，因为网络抖动后瞬时重试大概率再次失败，逐步拉长等待能让对端压力自然回落。

```python
def retry_request(request, max_attempts=3):
    for attempt in range(max_attempts):
        if request():
            return "success"
    return "fallback"
```
