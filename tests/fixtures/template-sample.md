# 指数退避请求模板

该模板用于可恢复网络错误，通过逐步增加等待时间降低请求风暴。

## 指数退避请求模板

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
