"""默认单聊的 HTTP 边界，使用 FastAPI 校验后的参数检查资源归属。"""
import inspect
from functools import wraps

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from fastapi.routing import APIRoute
from pydantic import BaseModel

from services.conversation.session_access import check_single_chat_arguments


class SingleChatRoute(APIRoute):
    def __init__(self, path, endpoint, **kwargs):
        if not getattr(endpoint, "__single_chat_boundary__", False):
            signature = inspect.signature(endpoint)
            original_endpoint = endpoint

            def check(arguments):
                check_single_chat_arguments(arguments, arguments.get("db"))
                def check_model(value):
                    if isinstance(value, BaseModel):
                        fields = {name: getattr(value, name) for name in type(value).model_fields}
                        check_single_chat_arguments(fields, arguments.get("db"))
                        for field in fields.values():
                            check_model(field)
                    elif isinstance(value, (list, tuple)):
                        for item in value:
                            check_model(item)
                for value in arguments.values():
                    check_model(value)

            if inspect.iscoroutinefunction(endpoint):
                @wraps(endpoint)
                async def guarded(**arguments):
                    await run_in_threadpool(check, arguments)
                    return await original_endpoint(**arguments)
            else:
                @wraps(endpoint)
                def guarded(**arguments):
                    check(arguments)
                    return original_endpoint(**arguments)

            # FastAPI 需要原函数的参数类型；注解可能来自延迟求值。
            annotations = inspect.get_annotations(endpoint, eval_str=True)
            guarded.__signature__ = signature.replace(parameters=[
                parameter.replace(annotation=annotations.get(
                    name, parameter.annotation))
                for name, parameter in signature.parameters.items()
            ], return_annotation=annotations.get("return", signature.return_annotation))
            guarded.__single_chat_boundary__ = True
            endpoint = guarded
        super().__init__(path, endpoint, **kwargs)


class SessionAPIRouter(APIRouter):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("route_class", SingleChatRoute)
        super().__init__(*args, **kwargs)


def validate_session_routes(app):
    """装配时阻止普通 APIRouter 绕过默认边界，不依赖手写路由名单。"""
    for route in app.routes:
        if isinstance(route, APIRoute) and not isinstance(route, SingleChatRoute):
            raise RuntimeError(f"接口 {route.path} 未经过会话访问边界，请使用 SessionAPIRouter")
