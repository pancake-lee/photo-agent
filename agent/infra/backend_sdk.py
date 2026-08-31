"""
    Go Backend SDK 共享工厂。

    统一管理 swagger_client 的 Configuration 和各 API 实例，
    避免各处重复创建。所有模块通过此模块获取 SDK 实例。
"""

from __future__ import absolute_import

import swagger_client as sdk
import requests


# 缓存: base_url -> Configuration
_config_cache: dict[str, sdk.Configuration] = {}


def get_sdk_config(base_url: str) -> sdk.Configuration:
    """获取或创建 SDK Configuration（按 base_url 缓存）。"""
    if base_url not in _config_cache:
        conf = sdk.Configuration()
        conf.host = base_url.rstrip("/")
        _config_cache[base_url] = conf
    return _config_cache[base_url]


def get_api_client(base_url: str) -> sdk.ApiClient:
    """获取带正确 host 的 ApiClient。"""
    return sdk.ApiClient(configuration=get_sdk_config(base_url))


def get_photo_api(base_url: str) -> sdk.PhotoServiceApi:
    return sdk.PhotoServiceApi(api_client=get_api_client(base_url))


def get_curd_api(base_url: str) -> sdk.DefaultCURDApi:
    """通用 CURD API（photo_groups 等表的直接读写）。"""
    return sdk.DefaultCURDApi(api_client=get_api_client(base_url))


def get_query_api(base_url: str) -> sdk.QueryServiceApi:
    return sdk.QueryServiceApi(api_client=get_api_client(base_url))


def get_vlm_api(base_url: str) -> sdk.VlmServiceApi:
    return sdk.VlmServiceApi(api_client=get_api_client(base_url))


def get_tag_api(base_url: str) -> sdk.TagServiceApi:
    return sdk.TagServiceApi(api_client=get_api_client(base_url))


def get_timeline_api(base_url: str) -> sdk.TimelineServiceApi:
    return sdk.TimelineServiceApi(api_client=get_api_client(base_url))


def sdk_to_dict(obj) -> dict:
    """将 SDK 模型对象转为 dict，兼容现有代码。
    如果已是 dict 则直接返回，None 返回空 dict。
    """
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if isinstance(obj, list):
        return [sdk_to_dict(item) for item in obj]
    return obj


def get_photo_health(base_url: str, photo_id: str) -> dict:
    """读取照片 AI 状态，使用原始 JSON 保留新增字段的兼容性。"""
    response = requests.get(
        f"{base_url.rstrip('/')}/api/v1/photos/{photo_id}", timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    photo = payload.get("photo") or {}
    if "descriptionTime" in payload:
        photo["descriptionTime"] = payload["descriptionTime"]
    return photo


def update_photo_health(
    base_url: str,
    photo_id: str,
    status: str,
    reason: str = "",
    description_time: str = "",
) -> None:
    """回写 Embedding 处理结论。"""
    response = requests.post(
        f"{base_url.rstrip('/')}/api/v1/photos/{photo_id}/ai-health",
        json={
            "status": status,
            "reason": reason,
            "description_time": description_time,
        },
        timeout=10,
    )
    response.raise_for_status()
