# 指数退避请求模板

该模板用于可恢复网络错误，通过逐步增加等待时间降低请求风暴。

## 指数退避请求模板

适用场景：仅在遇到超时等可恢复异常时使用，瞬断后立刻重试会加剧对端负载。

不要用：对业务逻辑错误（如参数校验失败）切勿套用，重试无法修复根因。

选择指数退避而非固定间隔，因为逐步拉长等待能让上游压力自然回落，而固定间隔会制造请求风暴。

```python
def retry_request(request, max_attempts=3, base_delay=1):
    """执行带指数退避的可恢复请求。"""
    for attempt in range(max_attempts):
        try:
            return request()
        except TimeoutError:
            if attempt == max_attempts - 1:
                raise
            time.sleep(base_delay * (2 ** attempt))
```
