# strategy-exec delta

## MODIFIED Requirements

### Requirement: iquant 错误处理禁止裸 except

`iquant/*.py` SHALL NOT use bare `except:` clauses that swallow `KeyboardInterrupt` / `SystemExit`. The empty-queue drain pattern

```python
while not Q.empty():
    try:
        Q.get_nowait()
    except:   # ❌ 禁止
        break
```

SHALL be replaced with

```python
import queue
...
while not Q.empty():
    try:
        Q.get_nowait()
    except queue.Empty:
        break
```

#### Scenario: drain queue 时正确捕获 Empty

- **WHEN** a shutdown path drains `GLOBAL_REQ_QUEUE` / `GLOBAL_ANS_QUEUE` in `iquant/runtime_trdapi_rel.py` or `iquant/quota_his.py`
- **THEN** the empty-queue exit catches only `queue.Empty`; `KeyboardInterrupt` / `SystemExit` propagate normally

### Requirement: iquant 行为零变更

The change SHALL NOT modify any of:
- 策略执行热路径（signal 接收 / 下单 / 行情消费）
- RPC 客户端协议（msgpacket / xtconstant）
- MQ 线程生命周期（start / stop / join / daemon flag）
- 沙箱与回测行为

Only the exception narrowing (bare → `queue.Empty`) is applied.