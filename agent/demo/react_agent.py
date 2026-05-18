"""
    ReAct Agent：手写思考/行动/观测循环。

    不用 bind_tools，而是通过 prompt 驱动 LLM 按格式输出 Thought + Action，
    由外部解析 Action、执行工具、将 Observation 注入下一轮对话。

    用法：
        cd agent
        venv/bin/python chain/react_agent.py -c ../.local/my-config.yaml
"""

import json
import pathlib
import re
import sys
import typing

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import langchain_openai as lc_openai
import langchain_core.messages as lc_messages

import config
import tools.openapi_client as openapi_client
import utils.streaming_printer as streaming_printer


# ------------------------------------------------------------------ #
# Prompt
# ------------------------------------------------------------------ #

_SYSTEM_PROMPT = (
    "你是一位摄影档案助手，专门帮助用户管理照片库。"
    "你可以使用以下工具来完成用户的请求。"
    "回答简洁，控制在 150 字以内。"
)

_REACT_FORMAT = """
你必须按以下格式严格输出，每一步只输出 Thought + Action 或 Thought + Final Answer：

格式选项 A（需要调用工具时）：
Thought: 你的思考过程，说明为什么需要调用工具
Action: {"tool": "工具名", "args": {"参数名": "参数值", ...}}

格式选项 B（可以直接回答时）：
Thought: 你的思考过程，说明为什么现在可以直接回答
Final Answer: 给用户的最终回答

重要规则：
1. 每一步只输出一个 Thought + 一个 Action/Final Answer
2. Action 必须是可以直接解析的 JSON，不要包含多余文字
3. 如果工具返回错误，尝试其他方式或如实告知用户
4. 不要虚构工具返回的内容，只能基于 Observation 回答
"""


def _build_tool_descriptions(tools: list[dict]) -> str:
    """
    将 OpenAI function 格式的工具定义转为文本描述。
    参考langchain的create_react_agent也是这样处理，
    没有使用OpenAI-API的function参数，直接把工具信息放在系统提示词里了。
    这样能兼容更多模型，不限于OpenAI的API。
    并且这样思考过程才能显式地看到工具描述，方便调试和理解。
    """
    lines: list[str] = []
    for t in tools:
        func = t.get("function", {})
        name = func.get("name", "")
        desc = func.get("description", "")
        params = func.get("parameters", {})
        props = params.get("properties", {})
        required = set(params.get("required", []))

        lines.append(f"- {name}: {desc}")
        if props:
            lines.append("  参数:")
            for pname, pspec in props.items():
                req_mark = " (必填)" if pname in required else ""
                pdesc = pspec.get("description", "")
                ptype = pspec.get("type", "string")
                lines.append(f"    - {pname} ({ptype}){req_mark}: {pdesc}")
        lines.append("")
    return "\n".join(lines)


def _build_react_prompt(tools_text: str) -> str:
    """组装完整的 ReAct 系统提示词。"""
    return (
        f"{_SYSTEM_PROMPT}\n\n"
        f"你可以使用以下工具:\n\n{tools_text}\n"
        f"{_REACT_FORMAT}"
    )


# ------------------------------------------------------------------ #
# 解析器
# ------------------------------------------------------------------ #

_RE_THOUGHT = re.compile(r"Thought:\s*(.+?)(?=\nAction:|\nFinal Answer:|$)", re.DOTALL)
_RE_FINAL = re.compile(r"Final Answer:\s*(.+)", re.DOTALL)


def _extract_json_object(text: str, start_idx: int) -> typing.Optional[dict]:
    """从 start_idx 开始，用括号平衡计数提取第一个完整的 JSON 对象。"""
    if start_idx >= len(text) or text[start_idx] != "{":
        return None

    depth = 0
    in_string = False
    escape = False

    for i in range(start_idx, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start_idx:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _parse_response(text: str) -> typing.Tuple[str, typing.Optional[dict], typing.Optional[str]]:
    """
    解析 LLM 的 ReAct 格式输出。

    返回:
        (thought, action_dict, final_answer)
        action_dict 为 None 表示没有 Action，final_answer 为 None 表示没有最终答案
    """
    thought = ""
    action: typing.Optional[dict] = None
    final: typing.Optional[str] = None

    m_thought = _RE_THOUGHT.search(text)
    if m_thought:
        thought = m_thought.group(1).strip()

    # 先检查 Final Answer（与 Action 互斥，优先）
    m_final = _RE_FINAL.search(text)
    if m_final:
        final = m_final.group(1).strip()
    else:
        # 没有 Final Answer 才解析 Action
        action_start = text.find("Action:")
        if action_start != -1:
            brace_start = text.find("{", action_start)
            if brace_start != -1:
                action = _extract_json_object(text, brace_start)

    return thought, action, final


# ------------------------------------------------------------------ #
# 核心循环
# ------------------------------------------------------------------ #

class ReActError(Exception):
    """ReAct 执行过程中出现意外错误（如 LLM 调用失败、输出格式无法解析）。"""


class ReActMaxStepsError(Exception):
    """达到最大步数限制，LLM 始终未给出 Final Answer。"""


def _run_react_step(
    llm: lc_openai.ChatOpenAI,
    messages: list[lc_messages.BaseMessage],
    tool_client: openapi_client.OpenAPIClient,
) -> typing.Tuple[str, list[lc_messages.BaseMessage]]:
    """
    执行一轮 ReAct：调用 LLM → 解析 → 执行工具（如有）→ 返回结果。

    返回:
        (本轮产生的最终回答或空字符串, 更新后的消息列表)
        返回空字符串表示执行了 Action，需要继续下一步。

    异常:
        ReActError: LLM 调用失败或输出格式无法解析。
    """
    try:
        content_parts: list[str] = []
        with streaming_printer.StreamingPrinter() as printer:
            for chunk in llm.stream(messages):
                text = str(chunk.content)
                if text:
                    printer.feed(text)
                    content_parts.append(text)
        print()
    except Exception as e:
        raise ReActError(f"LLM 调用失败: {e}") from e

    content = "".join(content_parts)
    response = lc_messages.AIMessage(content=content)

    thought, action, final_answer = _parse_response(content)

    if thought:
        print(f"🤔 Thought: {thought[:200]}{'...' if len(thought) > 200 else ''}")

    if final_answer:
        return final_answer, messages + [response]

    if action:
        tool_name = action.get("tool", "")
        tool_args = action.get("args", {})

        print(f"🔧 Action: {tool_name}({json.dumps(tool_args, ensure_ascii=False)})")

        # 执行工具
        result = tool_client.execute(tool_name, tool_args)

        # 截断过长结果
        max_len = 4000
        if len(result) > max_len:
            result = result[:max_len] + f"\n...（结果已截断，原始长度 {len(result)}）"

        print(f"📊 Observation: {result[:200]}{'...' if len(result) > 200 else ''}")

        # 构造观测消息
        observation_msg = lc_messages.HumanMessage(
            content=f"Observation: {result}\n\n请继续思考下一步。"
        )
        return "", messages + [response, observation_msg]

    # 既没 Action 也没 Final Answer，说明输出格式不符合 ReAct 规范
    raise ReActError(f"LLM 输出无法解析为 Action 或 Final Answer。原始输出:\n{content}")

_MAX_STEPS = 5

def chat_loop(cfg: config.Config) -> None:
    """ReAct 多轮对话主循环。"""

    # 初始化工具
    print("🔧 正在加载工具定义...")
    tool_client = openapi_client.OpenAPIClient(cfg.go_backend_url)
    tools = tool_client.get_tools()
    tools_text = _build_tool_descriptions(tools)
    print(f"✅ 已加载 {len(tools)} 个工具")
    print()

    system_prompt = _build_react_prompt(tools_text)

    llm = lc_openai.ChatOpenAI(
        model=cfg.llm_model,
        api_key=cfg.llm_api_key,  # type: ignore[arg-type]
        base_url=cfg.llm_base_url,
        temperature=0.3,
        streaming=True,
    )

    # 聊天历史：保留 HumanMessage + AIMessage，不保留中间 Observation
    history: list[lc_messages.BaseMessage] = []

    print("=" * 50)
    print("🤖 ReAct Agent 已启动")
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

        # 每轮对话的 ReAct 上下文：system + 历史 + 当前问题
        messages: list[lc_messages.BaseMessage] = [
            lc_messages.SystemMessage(content=system_prompt),
        ]
        messages.extend(history)
        messages.append(lc_messages.HumanMessage(content=f"问题: {user_input}"))

        print("⏳ 开始 ReAct 循环...")

        final_reply = ""
        step = 0
        error_info = ""
        try:
            while step < _MAX_STEPS:
                step += 1
                print(f"\n--- Step {step} ---")

                reply, messages = _run_react_step(llm, messages, tool_client)

                if reply:
                    final_reply = reply
                    break

            if not final_reply:
                raise ReActMaxStepsError(
                    f"已达到最大步数限制 ({_MAX_STEPS})，LLM 始终未给出 Final Answer"
                )

        except ReActError as e:
            error_info = str(e)
            print(f"\n❌ ReAct 过程出错: {error_info}")
            final_reply = "抱歉，处理过程中出现了问题，请稍后重试。"

        except ReActMaxStepsError as e:
            error_info = str(e)
            print(f"\n⚠️ {error_info}")
            final_reply = (
                "抱歉，我已经尝试了多种方法，但仍未能找到答案。"
                "请尝试更具体地描述你的问题。"
            )

        if error_info:
            print(f"\n🤖 AI: {final_reply}\n")
        else:
            print()

        # 追加到跨轮历史
        history.append(lc_messages.HumanMessage(content=user_input))
        history.append(lc_messages.AIMessage(content=final_reply))

        # 限制历史长度
        max_history = 20
        if len(history) > max_history:
            history = history[-max_history:]


if __name__ == "__main__":
    cfg = config.load_config()
    chat_loop(cfg)
    print("👋 再见！")
