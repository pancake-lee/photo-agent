"""
    Function Calling 单元测试。

    覆盖：
    - OpenAPI 文档解析与工具定义生成
    - HTTP 请求构建（path params, query params, body）
    - 工具执行（模拟 HTTP）
"""

import json
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import tools.openapi_client as openapi_client


# ------------------------------------------------------------------ #
# 模拟 OpenAPI 文档
# ------------------------------------------------------------------ #

MOCK_DOC = {
    "openapi": "3.0.3",
    "info": {"title": "Test", "version": "1.0"},
    "paths": {
        "/photos": {
            "get": {
                "summary": "照片列表",
                "description": "分页查询照片",
                "parameters": [
                    {"name": "keyword", "in": "query", "schema": {"type": "string"}, "description": "关键词"},
                    {"name": "brand", "in": "query", "schema": {"type": "string"}, "description": "品牌"},
                    {"name": "page", "in": "query", "schema": {"type": "integer", "default": 1}, "description": "页码"},
                ],
                "responses": {"200": {"description": "ok"}},
            }
        },
        "/photos/{id}": {
            "get": {
                "summary": "单张照片详情",
                "description": "根据 ID 获取照片",
                "parameters": [
                    {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}, "description": "照片ID"},
                ],
                "responses": {"200": {"description": "ok"}},
            }
        },
        "/photos/{id}/archive": {
            "post": {
                "summary": "归档照片",
                "description": "将照片标记为已归档",
                "parameters": [
                    {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}, "description": "照片ID"},
                ],
                "responses": {"200": {"description": "ok"}},
            }
        },
        "/query/sql": {
            "post": {
                "summary": "SQL查询",
                "description": "执行 SELECT SQL",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "sql": {"type": "string", "description": "SQL语句"},
                                    "limit": {"type": "integer", "description": "限制行数"},
                                },
                                "required": ["sql"],
                            }
                        }
                    }
                },
                "responses": {"200": {"description": "ok"}},
            }
        },
    },
}


def _make_client():
    """创建使用模拟文档的客户端。"""
    client = openapi_client.OpenAPIClient.__new__(openapi_client.OpenAPIClient)
    client.base_url = "http://localhost:10000"
    client.doc = MOCK_DOC
    client._tools = []
    client._tool_map = {}
    client._parse_tools()
    return client


# ------------------------------------------------------------------ #
# 测试
# ------------------------------------------------------------------ #

def test_tool_name_generation():
    assert openapi_client.OpenAPIClient._make_tool_name("get", "/photos") == "get_photos"
    assert openapi_client.OpenAPIClient._make_tool_name("post", "/photos/{id}/archive") == "post_photos_id_archive"
    assert openapi_client.OpenAPIClient._make_tool_name("get", "/timelines/{name}/photos") == "get_timelines_name_photos"


def test_parse_tools_count():
    client = _make_client()
    assert len(client._tools) == 4


def test_list_photos_tool_def():
    client = _make_client()
    tool = next(t for t in client._tools if t["function"]["name"] == "get_photos")
    func = tool["function"]
    assert func["description"] == "分页查询照片"
    props = func["parameters"]["properties"]
    assert "keyword" in props
    assert "brand" in props
    assert "page" in props
    assert func["parameters"]["required"] == []


def test_get_photo_tool_def():
    client = _make_client()
    tool = next(t for t in client._tools if t["function"]["name"] == "get_photos_id")
    func = tool["function"]
    assert "id" in func["parameters"]["properties"]
    assert "id" in func["parameters"]["required"]


def test_archive_tool_def():
    client = _make_client()
    tool = next(t for t in client._tools if t["function"]["name"] == "post_photos_id_archive")
    func = tool["function"]
    assert func["description"] == "将照片标记为已归档"
    assert "id" in func["parameters"]["required"]


def test_sql_tool_def():
    client = _make_client()
    tool = next(t for t in client._tools if t["function"]["name"] == "post_query_sql")
    func = tool["function"]
    props = func["parameters"]["properties"]
    assert "sql" in props
    assert "limit" in props
    assert "sql" in func["parameters"]["required"]
    assert "limit" not in func["parameters"]["required"]


def test_build_request_path_param():
    client = _make_client()
    method, path, spec = client._tool_map["get_photos_id"]
    url, qp, body = client._build_request(path, spec, {"id": "abc-123"})
    assert method == "GET"
    assert url == "http://localhost:10000/api/v1/photos/abc-123"
    assert qp == {}
    assert body is None


def test_build_request_query_params():
    client = _make_client()
    method, path, spec = client._tool_map["get_photos"]
    url, qp, body = client._build_request(path, spec, {"keyword": "风景", "brand": "Nikon"})
    assert url == "http://localhost:10000/api/v1/photos"
    assert qp == {"keyword": "风景", "brand": "Nikon"}
    assert body is None


def test_build_request_body():
    client = _make_client()
    method, path, spec = client._tool_map["post_query_sql"]
    url, qp, body = client._build_request(path, spec, {"sql": "SELECT * FROM photos", "limit": 10})
    assert method == "POST"
    assert url == "http://localhost:10000/api/v1/query/sql"
    assert qp == {}
    assert body == {"sql": "SELECT * FROM photos", "limit": 10}


def test_build_request_body_only_required():
    client = _make_client()
    method, path, spec = client._tool_map["post_query_sql"]
    url, qp, body = client._build_request(path, spec, {"sql": "SELECT 1"})
    assert body == {"sql": "SELECT 1"}


def test_execute_unknown_tool():
    client = _make_client()
    result = client.execute("unknown_tool", {})
    assert "未知工具" in result


def test_get_tools_returns_list():
    client = _make_client()
    tools = client.get_tools()
    assert isinstance(tools, list)
    assert all(t["type"] == "function" for t in tools)


if __name__ == "__main__":
    test_tool_name_generation()
    test_parse_tools_count()
    test_list_photos_tool_def()
    test_get_photo_tool_def()
    test_archive_tool_def()
    test_sql_tool_def()
    test_build_request_path_param()
    test_build_request_query_params()
    test_build_request_body()
    test_build_request_body_only_required()
    test_execute_unknown_tool()
    test_get_tools_returns_list()
    print("✅ 所有测试通过")
