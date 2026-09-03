"""
    SQLite 查询客户端（通过 Go 后端 SDK 代理）。

    不直接连接 SQLite 数据库，而是通过 Swagger SDK 调用 Go 后端 API，
    由 Go 后端统一执行查询并返回结果。Python 层保留 SQL 安全校验作为客户端双重保险。

    用法:
        import infra.sqlite_client as sqlite_client

        client = sqlite_client.QueryClient("http://localhost:10000")
        result = client.query("SELECT * FROM photos WHERE brand = 'Canon' LIMIT 5")
        print(result.rows)
"""

import re

import swagger_client as sdk
import infra.backend_sdk as bksdk


DEFAULT_TIMEOUT = 30.0


class QueryClient:
    """通过 Go 后端 SDK 执行 SQL 查询的客户端。"""

    def __init__(self, base_url: str, timeout: float = DEFAULT_TIMEOUT):
        """
        初始化查询客户端。

        参数:
            base_url: Go 后端地址，如 "http://localhost:10000"
            timeout:  请求超时时间（秒）
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._api = bksdk.get_query_api(base_url)

    def query(
        self,
        sql: str,
        limit: int = 100,
    ):
        """
        执行 SELECT 查询。

        参数:
            sql:   SQL 查询字符串（SELECT 或 WITH ... SELECT 只读查询）
            limit: 最大返回行数

        返回:
            ApiExecuteSQLResponse（含 columns, rows, count 属性）

        异常:
            ValueError: SQL 安全校验失败
            Exception: SDK 调用失败
        """
        if not validate_select_only(sql):
            raise ValueError(f"SQL 校验失败: 仅允许只读查询（SELECT / WITH ... SELECT）。SQL: {sql[:100]}")

        req = sdk.ApiExecuteSQLRequest(sql=sql, limit=limit)
        return self._api.query_service_execute_sql(req)

    def safe_query(
        self,
        sql: str,
        limit: int = 100,
    ):
        """
        安全执行 SQL（带错误处理）。

        成功时返回 ApiExecuteSQLResponse，失败时返回含 error 字段的 dict。
        """
        try:
            return self.query(sql, limit=limit)
        except Exception as e:
            return {
                "columns": [],
                "rows": [],
                "count": 0,
                "error": str(e),
            }

    def fetch_schema(self):
        """
        从 Go 后端获取 photos 表结构。

        返回:
            ApiGetPhotoSchemaResponse（含 table_name, fields 属性）

        异常:
            Exception: SDK 调用失败
        """
        return self._api.query_service_get_photo_schema()


def validate_select_only(sql: str) -> bool:
    """
    校验 SQL 是否仅为 SELECT 查询。

    检查点:
        1. 去除前后空白后必须以 SELECT 或 WITH 开头（不区分大小写，WITH 承载 CTE 只读查询）
        2. 不包含危险关键字: INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, TRUNCATE, REPLACE, ATTACH, DETACH, PRAGMA
           （WITH 前缀同样可以修饰 DELETE/INSERT 等，由关键字拦截兜住）

    参数:
        sql: SQL 字符串

    返回:
        True 表示安全，False 表示不安全
    """
    if not sql or not sql.strip():
        return False

    # 取第一词，去除可能的注释前缀
    stripped = sql.strip()
    # 去除开头的块注释 /* ... */
    while stripped.startswith("/*"):
        end = stripped.find("*/")
        if end == -1:
            return False
        stripped = stripped[end + 2 :].strip()

    # 去除行注释并找到第一个非空非注释行
    lines = stripped.split("\n")
    first_line = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        comment_dash = line.find("--")
        if comment_dash != -1:
            line = line[:comment_dash].strip()
        if line:
            first_line = line
            break

    # 必须以 SELECT 或 WITH 开头（CTE 只读查询以 WITH 开头）
    upper = first_line.upper()
    if not (upper.startswith("SELECT") or upper.startswith("WITH")):
        return False

    # 禁止危险关键字（全词匹配）
    forbidden = [
        "INSERT",
        "UPDATE",
        "DELETE",
        "DROP",
        "CREATE",
        "ALTER",
        "TRUNCATE",
        "REPLACE",
        "ATTACH",
        "DETACH",
        "PRAGMA",
    ]

    upper_sql = sql.upper()
    for keyword in forbidden:
        pattern = re.compile(rf"\b{keyword}\b")
        if pattern.search(upper_sql):
            return False

    return True


def safe_execute(
    base_url: str,
    sql: str,
    limit: int = 100,
):
    """
    安全执行 SQL：先校验，再调用 Go 后端 API。

    参数:
        base_url: Go 后端地址
        sql:      SQL 查询字符串
        limit:    最大返回行数

    返回:
        ApiExecuteSQLResponse（含 columns, rows, count 属性）

    异常:
        ValueError: SQL 校验失败
        Exception: SDK 调用失败
    """
    if not validate_select_only(sql):
        raise ValueError(f"SQL 校验失败: 仅允许只读查询（SELECT / WITH ... SELECT）。SQL: {sql[:100]}")

    client = QueryClient(base_url)
    return client.query(sql, limit=limit)
