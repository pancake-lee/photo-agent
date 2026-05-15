"""
    最简单的多轮对话 Agent。

    用法：
        venv/bin/python chain/chat_agent.py -c ../.local/my-config.yaml
"""

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import langchain.prompts as lc_prompts
import langchain.schema as lc_schema
import langchain_openai as lc_openai

import config
import utils.streaming_printer as streaming_printer


SYSTEM_PROMPT = (
    "你是一位经验丰富的摄影专家，擅长用通俗易懂的语言解释摄影知识，"
    "回答简洁，控制在 100 字以内。"
)


def chat_loop(cfg: config.Config) -> None:
    """多轮对话主循环。"""

    llm = lc_openai.ChatOpenAI(
        model=cfg.llm_model,
        api_key=cfg.llm_api_key,  # type: ignore[arg-type]
        base_url=cfg.llm_base_url,
        temperature=0.7,
        streaming=True,
    )

    # Prompt 模板：system 指令 + 动态历史 + 当前用户输入
    prompt = lc_prompts.ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        lc_prompts.MessagesPlaceholder(variable_name="history"),
        ("human", "{input}"),
    ])

    # 管道：prompt 处理输入 → llm 生成回复
    chain = prompt | llm

    # 聊天历史：只存 HumanMessage 和 AIMessage
    history: list[lc_schema.BaseMessage] = []

    print("=" * 50)
    print("🤖 摄影专家 Agent 已启动")
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

        if not user_input.strip():  # 去掉两端空格
            continue

        print(f"AI: ", end="")

        reply_parts: list[str] = []
        with streaming_printer.StreamingPrinter() as printer:
            for chunk in chain.stream({"history": history, "input": user_input}):
                text = str(chunk.content)
                if text:
                    printer.feed(text)
                    reply_parts.append(text)
        reply = "".join(reply_parts)
        print()
        print()

        # 追加到历史
        history.append(lc_schema.HumanMessage(content=user_input))
        history.append(lc_schema.AIMessage(content=reply))


if __name__ == "__main__":
    cfg = config.load_config()
    chat_loop(cfg)
    print("👋 再见！")
