"""读取 API 文档中的路由索引和显式请求示例，不导入应用或访问数据。"""

import json
import re
from typing import get_args, get_origin


DOMAIN_DOCUMENTS = ("GENERAL.md", "CHARACTERS.md", "SESSIONS.md", "LOREBOOKS.md", "CHAT.md")
ROUTE_ROW = re.compile(r'^\|\s*\*\*([A-Z /]+)\*\*\s*\|\s*`([^`]+)`', re.MULTILINE)
REQUEST_EXAMPLE = re.compile(
    r'<!-- request-example:\s*([^\n]+?)\s*-->\s*```json\s*\n(.*?)^\s*```',
    re.MULTILINE | re.DOTALL,
)


def documented_routes(content):
    routes = []
    for match in ROUTE_ROW.finditer(content):
        for method in match[1].split("/"):
            routes.append((method.strip(), match[2]))
    return routes


def request_examples(content):
    """返回带源行号的请求样本，JSON 解析错误保留给调用方报告。"""
    for match in REQUEST_EXAMPLE.finditer(content):
        line = content.count("\n", 0, match.start()) + 1
        routes = []
        for label in match[1].split(";"):
            method, path = label.strip().split(" ", 1)
            routes.append((method, path))
        yield line, routes, json.loads(match[2])


def unknown_model_fields(value, model, location="body"):
    """即使请求模型忽略额外字段，文档也不允许悄悄拼错字段名。"""
    args = get_args(model)
    if type(None) in args and len(args) == 2:
        return unknown_model_fields(value, next(arg for arg in args if arg is not type(None)), location)
    if get_origin(model) is list and isinstance(value, list) and args:
        return [
            error for index, item in enumerate(value)
            for error in unknown_model_fields(item, args[0], f"{location}[{index}]")
        ]
    if not isinstance(value, dict) or not hasattr(model, "model_fields"):
        return []
    errors = [f"{location}.{name}" for name in value if name not in model.model_fields]
    for name, field in model.model_fields.items():
        if name not in value:
            continue
        errors.extend(unknown_model_fields(value[name], field.annotation, f"{location}.{name}"))
    return errors
