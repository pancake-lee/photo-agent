<!-- harness:begin -->
# Python 代码规范

修改 Python 代码时，与[通用代码规范](code.md)一起读取。

1. 沿用项目 Python 版本、虚拟环境、依赖管理和格式化配置；需要依赖时先确认既有能力与引入成本。
2. 项目内导入优先保留模块限定名，如 `import package.module as module`，调用时显式使用 `module.name`；标准库、第三方库及项目既有公开接口沿用相应惯例。
3. 对公开边界与复杂数据增加有用的类型标注；已有明确结构时避免用无约束字典层层传递，不为简单局部变量堆叠类型包装。
4. 只捕获当前层能够处理的异常，保留必要异常链；异步调用、阻塞操作和资源生命周期应清楚可见。
5. 测试按项目既有工具组织；外部服务使用受控替身，验证关键输出与副作用，清理临时文件和连接。

模块限定导入是本 Harness 的偏好，不表述为 Python 社区的统一强制要求。
<!-- harness:end -->

## Python（agent/）

### 导入规范

- 使用**显式包名导入**（Go 风格限定调用）：`import langchain_openai as lc_openai`，调用时 `lc_openai.ChatOpenAI(...)`；项目内模块同样如此，`import chat.photo_rag as photo_rag`，调用点 `photo_rag.answer_question(...)`
- **禁止** `from xxx import <符号>` 导入项目内模块的类或函数（如 `from chat.session_store import SessionStore`），符号来源必须在调用点可见
- 例外：标准库与第三方包按 Python 惯例允许 `from` 导入，如 `from typing import Literal`、`from dataclasses import dataclass`、fastapi 的路由与模型导入、`from __future__ import annotations`
- 包名过长时允许简写别名，但至少保留一个单词方便阅读，如 `import langchain.schema as lc_schema`、`import langchain_core.prompts as lc_prompts`
- 别名与原名一致时写裸导入（`import photo_agent`），不要写 `import photo_agent as photo_agent` 式冗余别名
- 存量 `from import` 已于 2026-08-31（TIDY6）全部转换为限定调用，新增代码不得回退

### 环境管理（uv）

```
curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.12.4
uv python pin 3.12
uv venv
source .venv/bin/activate
uv init
uv sync
deactivate
```

---
