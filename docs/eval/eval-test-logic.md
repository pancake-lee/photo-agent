# 评估测试用例逻辑

> 本文档记录当前评估基建的单元测试与三层回归 CLI 用例逻辑。
> 指标基线见 [baseline.md](baseline.md)。
> 实现入口：[agent/internal/evals/evaluation.py](../../agent/internal/evals/evaluation.py)、
> [agent/scripts/regression/standard.py](../../agent/scripts/regression/standard.py)。

## 1. 用例与评估

- 黄金用例的期望统一按单张照片读取和评估。旧文件中的粒度字段按兼容逻辑处理。
- 评估使用全量照片集合，产出 Precision、Recall、MRR 及资产健康快照。开发期回归从黄金用例取问题和关联照片，从配置取层级和粒度断言。
- 离线用例验证单张语义、写入去重、健康证据与配置组合。 [评估单测](../../agent/tests/test_evaluation.py) · [回归配置单测](../../agent/tests/test_eval_regression.py)

## 2. 三层回归 CLI

在 `agent/` 运行：

```bash
.venv/bin/python scripts/regression/standard.py \
  -c ../.local/my-config.yaml \
  --level L0
```

- L0 检查目标照片、连拍封面与三个集合的数据。L1 直接执行检索，核对配置中要求的照片和组 ID。L1 会生成查询向量。
- L2 核对健康和黄金用例列表接口。配置含 `expected_chat_filenames` 时，创建临时会话，按指定粒度发送真实消息，核对召回并清理会话。当前配置包含这类断言，运行 L2 或 all 需当轮授权。
- `--level` 可选 `all`、`L0`、`L1`、`L2`。用 `--golden-id` 限定标记用例，用 `--agent-url` 指定 L2 地址。失败输出层级、用例、断言和实际结果，并返回非零状态。

问题和期望照片从本地黄金用例文件读取。开发期标记、连拍档位及对话断言在[评估配置](../../configs/evaluation.yaml)维护。图库重建后先核对 L0，再判断 L1 变化。
