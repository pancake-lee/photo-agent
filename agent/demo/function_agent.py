"""
    Function Calling Agent：LLM 自主调用照片工具。

    用法：
        cd agent
        venv/bin/python chain/function_agent.py -c ../.local/my-config.yaml

    流程：
        1. 从 Go 后端 /v1/openapi.json 自动解析可用工具
        2. 用户输入 → LLM（带工具定义）→ 可能触发工具调用
        3. 执行工具 → 结果返回 LLM → 生成最终回答
        4. 最终回答支持 Streaming，控制台实时输出
"""

import pathlib
import sys


import langchain_core.prompts as lc_prompts
import langchain_core.messages as lc_messages
import langchain_openai as lc_openai
from langchain_core.messages import ToolMessage

import config
import tools.openapi_client as openapi_client
import utils.streaming_printer as streaming_printer


SYSTEM_PROMPT = (
    "你是一位摄影档案助手，专门帮助用户管理照片库。\n"
    "你可以使用以下工具来完成用户的请求：\n"
    "- 搜索照片（按关键词、品牌、镜头、时间线、标签等过滤）\n"
    "- 查看照片详情和统计信息\n"
    "- 执行 SQL 查询获取精确统计\n"
    "- 查询用户时间线，获取照片拍摄时用户对应的活动（去哪里？做什么？）\n\n"
    "当用户请求不明确时，先搜索相关信息再回答。"
    "回答简洁，控制在 150 字以内。"
)


def _print_stream(stream) -> str:
    """消费流式输出，用 StreamingPrinter 平滑打印，返回完整文本。"""
    reply_parts: list[str] = []
    print("AI: ", end="")
    with streaming_printer.StreamingPrinter() as printer:
        for chunk in stream:
            text = str(chunk.content)
            if text:
                printer.feed(text)
                reply_parts.append(text)
    print()
    return "".join(reply_parts)


def chat_loop(cfg: config.Config) -> None:
    """Function Calling 多轮对话主循环。"""

    # 初始化 OpenAPI 工具客户端
    print("🔧 正在加载工具定义...")
    tool_client = openapi_client.OpenAPIClient(cfg.go_backend_url)
    tools = tool_client.get_tools()
    print(f"✅ 已加载 {len(tools)} 个工具")
    print()

    # 提取 function definitions 用于 bind_tools
    function_defs = [t["function"] for t in tools]

    llm = lc_openai.ChatOpenAI(
        model=cfg.llm_model,
        api_key=cfg.llm_api_key,  # type: ignore[arg-type]
        base_url=cfg.llm_base_url,
        temperature=0.3,
    )
    llm_with_tools = llm.bind_tools(function_defs)

    prompt = lc_prompts.ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        lc_prompts.MessagesPlaceholder(variable_name="history"),
        ("human", "{input}"),
    ])

    # 聊天历史
    history: list[lc_messages.BaseMessage] = []

    print("=" * 50)
    print("🤖 Function Calling Agent 已启动")
    print("   输入 exit 或按 Ctrl+C 退出")
    print("=" * 50)
    print()

    while True:
        try:
            user_input = input("你: ")
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if user_input.lower() == "exit":
            break

        if not user_input.strip():
            continue

        # 构建当前轮次的消息列表
        messages = prompt.format_messages(history=history, input=user_input)

        # 第一轮：LLM 决定是否调用工具（非流式，需要完整 tool_calls）
        print("⏳ 思考中...")
        response = llm_with_tools.invoke(messages)

        # 处理工具调用
        tool_calls = getattr(response, "tool_calls", None) or []
        if tool_calls:
            print(f"🔧 调用工具: {', '.join(t['name'] for t in tool_calls)}")

            # 将 LLM 的 tool_calls 请求加入历史
            messages.append(response)

            for tc in tool_calls:
                tool_name = tc["name"]
                tool_args = tc.get("args", {})

                # 执行工具
                result = tool_client.execute(tool_name, tool_args)
                print(f"   [{tool_name}] 返回 {len(result)} 字符")

                # 截断过长的结果，避免超出 token 限制
                max_len = 4000
                if len(result) > max_len:
                    result = result[:max_len] + f"\n...（结果已截断，原始长度 {len(result)}）"

                # 将工具结果加入消息历史
                messages.append(ToolMessage(content=result, tool_call_id=tc["id"]))

            # 第二轮：LLM 基于工具结果生成最终回答（流式输出）
            # 注意：仍需用 llm_with_tools，否则 LLM 无法正确理解 ToolMessage 上下文
            print("⏳ 生成回答...")
            reply = _print_stream(llm_with_tools.stream(messages))

        else:
            # 无工具调用，直接输出（流式）
            reply = _print_stream(llm.stream(messages))

        print()

        # 追加到历史（只保留 HumanMessage 和 AIMessage，不保留 ToolMessage）
        history.append(lc_messages.HumanMessage(content=user_input))
        history.append(lc_messages.AIMessage(content=reply))

        # 限制历史长度，防止上下文过长
        max_history = 20
        if len(history) > max_history:
            history = history[-max_history:]


if __name__ == "__main__":
    cfg = config.load_config()
    chat_loop(cfg)
    print("👋 再见！")
