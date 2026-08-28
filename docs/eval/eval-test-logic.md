# 评估测试用例逻辑

> 本文档记录当前评估基建的单元测试与三层回归 CLI 用例逻辑。
> 指标基线见 [baseline.md](baseline.md)。
> 实现入口：[agent/chain/evaluation.py](../../agent/chain/evaluation.py)、
> [agent/scripts/eval_regression.py](../../agent/scripts/eval_regression.py)。

## 0. 称呼约定

- **「回归测试」**（regression）：指这套三层 CLI，即 `agent/scripts/eval_regression.py`。用 L0 数据态、L1 函数级检索、L2 HTTP 契约三层断言定位失败层级，无 LLM、无浏览器。对话中说「跑回归测试」即在本目录执行：
  ```bash
  cd agent
  .venv/bin/python scripts/eval_regression.py -c ../.local/my-config.yaml --level all
  ```
- **「评估」**：指黄金用例打分链路（`agent/chain/evaluation.py` + `eval_engine.py`），产出维度评分与报告。
- 两者共用 `data/eval_seed_cases.json` 与同一套检索模块，但评估评效果、回归验闭环；回归失败会直接指向 L0/L1/L2 中的具体层级。

## 1. 测试范围

当前测试分为两组：

- 单元测试：隔离评估模块、粒度模型和 Collection 路由，不访问真实服务。
- 三层回归：使用当前图库中的真实照片，按 L0、L1、L2 定位数据态、检索函数和 HTTP 契约问题。

两组测试都不验证 LLM 的回答文案。评估对象是照片检索结果及其粒度语义。

## 2. 单元测试逻辑

实现文件：

- `agent/tests/test_evaluation.py`
- `agent/tests/test_eval_regression.py`

### 2.1 黄金用例粒度兼容

测试输入同时包含旧格式和新格式：

- 旧格式照片引用没有 `granularity`。
- 新格式分别声明 `fine` 和 `coarse`。

断言：

- 缺少粒度时默认使用 `photo`。
- `fine`、`coarse` 能被原样读取。
- 未知粒度会抛出包含“未知检索粒度”的错误。

这组测试保证旧黄金 JSON 不需要手工迁移，新 JSON 也不会静默接受拼写错误。

### 2.2 三 Collection 路由

测试使用假的 Embedder、Chroma Store 和 UUID→文件名映射：

- `photo` Store 返回 `photo-uuid`。
- `fine` Store 返回 `fine-uuid`。
- `coarse` Store 返回 `coarse-uuid`。

输入用例同时标注三种粒度，断言：

- 三个 Collection 都被实例化并查询。
- 每个 Collection 的结果都进入同一份评估结果。
- 三个目标都被判定为命中。
- 没有遗留未命中目标。

该测试不访问 embedding 服务和 Chroma 实例，专门验证评估模块的分流逻辑。

### 2.3 Pydantic 粒度模型

测试 `GoldenPhotoRef`：

- 未指定粒度时为 `photo`。
- 指定 `fine` 时保持为 `fine`。
- 指定非法值时校验失败。

### 2.4 种子文件结构

`test_eval_regression.py` 不执行真实检索，只检查种子契约：

- 必须存在检索闭环和连拍粒度闭环两条用例。
- 连拍用例必须同时覆盖 `photo`、`fine`、`coarse`。
- JSON 可以正常读取。
- `.jpg` 和 `.nef` 文件名归一化为相同的无扩展名 ID。

## 3. 三层回归 CLI 逻辑

入口：

```bash
cd agent
.venv/bin/python scripts/eval_regression.py \
  -c ../.local/my-config.yaml \
  --level all
```

参数：

- `--level all|L0|L1|L2`：运行全部层级或指定层级。
- `--case all|retrieval|burst`：运行全部种子、检索种子或连拍种子。
- `--agent-url`：L2 Python Agent 地址，默认 `http://127.0.0.1:10005`。

成功输出每层一行结论；失败输出层级、用例名、断言和实际错误，并以非零状态码结束。

### 3.1 L0：数据态

目的：回答“目标照片和向量集合的数据是否存在”。

检查内容：

- Go 后端照片列表中存在 `DSC_2215`。
- 精细和模糊连拍档位都能找到 `DSC_2167`。
- 封面照片确实标记为连拍组封面，并带有组 ID。
- `photos`、`photos_burst_fine`、`photos_burst_coarse` Collection 非空。

L0 不生成 embedding，也不执行语义查询。Go 服务不可访问、目标照片不存在或组 Collection 为空时，错误会停留在 L0。

### 3.2 L1：函数级检索

目的：回答“检索函数和粒度切换是否正确”。

检索闭环：

- 问题：`找找佛像和人的合照`。
- 粒度：`photo`。
- 预期排序首位：`DSC_2215`。

连拍粒度闭环：

- 问题：`佛堂里佛像和人的合照`。
- `photo` 首位预期为 `DSC_2215`。
- `fine` 首位预期为 `DSC_2167`，组 ID 为 `burst_fine_2cfd1ebd`。
- `coarse` 首位预期为 `DSC_2167`，组 ID 为 `burst_coarse_2cfd1ebd`。

L1 直接调用 `_retrieve`，不经过 HTTP，不调用 LLM；检索结果中的 UUID 通过 Go 照片列表转换为文件名后再断言。

### 3.3 L2：HTTP 契约

目的：回答“Python Agent 服务是否启动且基础接口契约可用”。

检查内容：

- `GET /api/chat/health` 返回 HTTP 2xx，且 `status` 为 `ok`。
- `GET /api/golden-queries` 返回 JSON 数组。

L2 不发送聊天消息，因此不会触发 LLM。服务未启动、地址错误、健康状态异常或返回结构错误时，报告为 L2 失败。

## 4. 种子数据来源

种子文件为 [data/eval_seed_cases.json](../../data/eval_seed_cases.json)。照片 ID 来自当前 SQLite 图库，不是临时生成数据：

- `DSC_2215.jpg`：佛像旁有两名女性合影。
- `DSC_2167.jpg`：同一连拍组的封面照片。
- 精细组：`burst_fine_2cfd1ebd`。
- 模糊组：`burst_coarse_2cfd1ebd`。

如果图库重建导致文件名或连拍组封面变化，应同步更新种子文件，并先运行 L0 确认数据态，再判断 L1 检索是否回归。

## 5. 当前验证状态

最近一次离线单元测试结果：

- `tests.test_evaluation`：3/3 通过。
- `tests.test_eval_regression`：3/3 通过。
- 合计：6/6 通过。

真实三层回归需要 Go 后端、Python Agent 和已同步的三个 Chroma Collection。当前若组 Collection 为空，预期由 L0 报告数据态失败，而不是将问题误判为检索算法失败。
