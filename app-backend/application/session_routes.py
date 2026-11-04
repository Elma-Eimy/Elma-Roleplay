"""使用 FastAPI 校验后的参数执行显式的单聊或群聊访问策略。"""
import inspect
from functools import wraps

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from fastapi.routing import APIRoute
from pydantic import BaseModel

from services.conversation.session_access import check_chat_arguments


class SessionAccessRoute(APIRoute):
    session_kind = "single"

    def __init__(self, path, endpoint, **kwargs):
        policy = getattr(endpoint, "__session_access_policy__", None)
        if policy is not None and policy != self.session_kind:
            raise RuntimeError("同一业务入口不能同时使用单聊与群聊访问策略")
        if policy is None:
            signature = inspect.signature(endpoint)
            original_endpoint = endpoint

            def check(arguments):
                check_chat_arguments(arguments, arguments.get("db"), self.session_kind)
                def check_model(value):
                    if isinstance(value, BaseModel):
                        fields = {name: getattr(value, name) for name in type(value).model_fields}
                        check_chat_arguments(fields, arguments.get("db"), self.session_kind)
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
            guarded.__session_access_policy__ = self.session_kind
            guarded.__single_chat_boundary__ = self.session_kind == "single"
            endpoint = guarded
        super().__init__(path, endpoint, **kwargs)


class SingleChatRoute(SessionAccessRoute):
    session_kind = "single"


class GroupChatRoute(SessionAccessRoute):
    session_kind = "group"


class SessionAPIRouter(APIRouter):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("route_class", SingleChatRoute)
        super().__init__(*args, **kwargs)


class GroupSessionAPIRouter(SessionAPIRouter):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("route_class", GroupChatRoute)
        super().__init__(*args, **kwargs)


def validate_session_routes(app):
    """装配时阻止普通 APIRouter 绕过默认边界，不依赖手写路由名单。"""
    for route in app.routes:
        if isinstance(route, APIRoute) and not isinstance(route, (SingleChatRoute, GroupChatRoute)):
            raise RuntimeError(f"接口 {route.path} 未经过会话访问边界，请使用 SessionAPIRouter")
