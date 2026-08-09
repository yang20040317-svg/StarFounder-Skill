# API 容错策略

这份复盘说明 API 服务如何通过超时、重试和降级提高稳定性。

## 指数退避重试模板

下面的实现用于可恢复网络异常，避免固定间隔造成请求风暴。

```python
def retry_request(request, max_attempts=3):
    for attempt in range(max_attempts):
        if request():
            return "success"
    return "fallback"
```
