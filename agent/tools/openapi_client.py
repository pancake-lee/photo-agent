"""
    OpenAPI 工具客户端。

    从 Go 后端 /v1/openapi.json 自动解析接口定义，
    转换为 LLM Function Calling 可用的工具格式，
    并在 LLM 决定调用时执行对应的 HTTP 请求。
"""

import json
import re
import typing

import httpx


class OpenAPIClient:
    """OpenAPI 文档客户端：解析 + 执行工具。"""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.doc: dict = {}
        self._tools: list[dict] = []
        self._tool_map: dict[str, tuple[str, str, dict]] = {}

        self._fetch_doc()
        self._parse_tools()

    def _fetch_doc(self) -> None:
        """从 Go 后端获取 OpenAPI JSON。"""
        url = f"{self.base_url}/v1/openapi.json"
        with httpx.Client() as client:
            resp = client.get(url, timeout=10.0)
            resp.raise_for_status()
            self.doc = resp.json()

    # ------------------------------------------------------------------ #
    # 解析：OpenAPI → OpenAI function definitions
    # ------------------------------------------------------------------ #

    def _parse_tools(self) -> None:
        """解析 OpenAPI paths，生成工具定义映射。"""
        paths = self.doc.get("paths", {})
        for path, methods in paths.items():
            for method, spec in methods.items():
                tool_name = self._make_tool_name(method, path)
                func_def = self._build_function_def(tool_name, path, spec)
                self._tools.append(func_def)
                self._tool_map[tool_name] = (method.upper(), path, spec)

    @staticmethod
    def _make_tool_name(method: str, path: str) -> str:
        """将 HTTP method + path 转换为 snake_case 工具名。"""
        parts = [method.lower()]
        for seg in path.strip("/").split("/"):
            seg = re.sub(r"[{}]", "", seg)
            if seg:
                parts.append(seg)
        return "_".join(parts)

    def _build_function_def(self, name: str, path: str, spec: dict) -> dict:
        """将单个 OpenAPI operation 转换为 function definition。"""
        desc = spec.get("description") or spec.get("summary") or ""

        props: dict[str, dict] = {}
        required: list[str] = []

        # 路径参数
        for param in spec.get("parameters", []):
            if param.get("in") in ("path", "query"):
                pname = param["name"]
                schema = param.get("schema", {"type": "string"})
                props[pname] = {
                    "type": schema.get("type", "string"),
                    "description": param.get("description", ""),
                }
                if param.get("required") or param.get("in") == "path":
                    required.append(pname)

        # requestBody JSON 参数（平铺到顶层）
        body = spec.get("requestBody", {})
        if body:
            content = body.get("content", {})
            json_schema = content.get("application/json", {}).get("schema", {})
            for k, v in json_schema.get("properties", {}).items():
                props[k] = {
                    "type": v.get("type", "string"),
                    "description": v.get("description", ""),
                }
            for k in json_schema.get("required", []):
                if k not in required:
                    required.append(k)

        return {
            "type": "function",
            "function": {
                "name": name,
                "description": desc,
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": required,
                },
            },
        }

    # ------------------------------------------------------------------ #
    # 对外接口
    # ------------------------------------------------------------------ #

    def get_tools(self) -> list[dict]:
        """返回 OpenAI function calling 格式的工具定义列表。"""
        return self._tools

    def execute(self, tool_name: str, arguments: dict) -> str:
        """
        执行指定工具的 HTTP 请求。

        参数:
            tool_name: 工具名（如 list_photos）
            arguments: 参数字典

        返回:
            HTTP 响应体文本
        """
        if tool_name not in self._tool_map:
            return f"未知工具: {tool_name}"

        method, path, spec = self._tool_map[tool_name]
        url, query_params, body = self._build_request(path, spec, arguments)

        try:
            with httpx.Client() as client:
                if method == "GET":
                    resp = client.get(url, params=query_params, timeout=15.0)
                else:
                    resp = client.request(method, url, params=query_params, json=body, timeout=15.0)
                resp.raise_for_status()
                return resp.text
        except httpx.HTTPStatusError as e:
            return f"HTTP 错误 {e.response.status_code}: {e.response.text}"
        except Exception as e:
            return f"请求失败: {e}"

    def _build_request(
        self, path: str, spec: dict, arguments: dict
    ) -> typing.Tuple[str, dict, typing.Optional[dict]]:
        """
        根据参数构建请求 URL、query 参数和 body。

        返回:
            (完整 URL, query 参数字典, body 字典或 None)
        """
        url = self.base_url + "/api/v1" + path
        query_params: dict = {}
        body: dict | None = None

        path_params = set()
        for param in spec.get("parameters", []):
            pname = param["name"]
            if pname not in arguments:
                continue
            val = arguments[pname]
            if param.get("in") == "path":
                url = url.replace(f"{{{pname}}}", str(val))
                path_params.add(pname)
            elif param.get("in") == "query":
                query_params[pname] = val

        # requestBody 中的参数
        body_spec = spec.get("requestBody", {})
        if body_spec:
            body = {}
            content = body_spec.get("content", {})
            json_schema = content.get("application/json", {}).get("schema", {})
            for k in json_schema.get("properties", {}).keys():
                if k in arguments and k not in path_params:
                    body[k] = arguments[k]

        return url, query_params, body if body else None


# ------------------------------------------------------------------ #
# 便捷函数
# ------------------------------------------------------------------ #

def build_tools_from_openapi(base_url: str) -> list[dict]:
    """快捷方法：直接返回工具定义列表。"""
    client = OpenAPIClient(base_url)
    return client.get_tools()
