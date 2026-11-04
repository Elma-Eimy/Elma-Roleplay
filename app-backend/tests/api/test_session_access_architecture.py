"""自动发现入口；新增操作遗漏单聊边界时，隔离回归必须失败。"""
import ast
import asyncio
import importlib
import inspect
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi import APIRouter, Depends, FastAPI
from fastapi.routing import APIRoute
from pydantic import BaseModel

from application.session_routes import SessionAPIRouter, SessionAccessRoute, validate_session_routes
from core.database import get_db
from services.conversation.session_access import RESOURCE_ARGUMENTS, SessionKindConflict
from tests.api import test_group_session_boundary as fixtures


def discover_operations(root):
    """扫描全部服务源码，不维护函数或模块白名单。"""
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        nodes = [(node, "") for node in tree.body]
        for node, prefix in nodes:
            if isinstance(node, ast.ClassDef):
                nodes.extend((child, prefix + node.name + ".") for child in node.body)
                continue
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name.startswith("_"):
                continue
            names = {arg.arg for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs}
            if "db" in names and names.intersection(RESOURCE_ARGUMENTS):
                yield path, prefix + node.name


class SessionAccessArchitectureTests(unittest.TestCase):
    setUp = fixtures.GroupSessionBoundaryTests.setUp
    snapshot = fixtures.GroupSessionBoundaryTests.snapshot

    def test_every_registered_api_route_uses_the_default_boundary(self):
        routes = [route for route in self.app.routes if isinstance(route, APIRoute)]
        self.assertTrue(routes)
        for route in routes:
            with self.subTest(path=route.path):
                self.assertIsInstance(route, SessionAccessRoute)
                self.assertEqual(route.session_kind, getattr(route.endpoint, "__session_access_policy__", None))

    def test_new_endpoints_are_guarded_without_business_checks(self):
        router = SessionAPIRouter()
        called = []

        @router.get("/new/{session_id}")
        def new_read(session_id: int, db=Depends(get_db)):
            called.append(session_id)
            return {"id": session_id}

        class Payload(BaseModel):
            message_id: int

        @router.post("/new")
        async def new_write(request: Payload, db=Depends(get_db)):
            called.append(request.message_id)
            return {"id": request.message_id}

        self.app.include_router(router)
        self.assertEqual(409, self.client.get("/new/20").status_code)
        self.assertEqual(409, self.client.post("/new", json={"message_id": 2}).status_code)
        self.assertEqual([], called)
        self.assertEqual(200, self.client.get("/new/10").status_code)
        self.assertEqual([10], called)
        self.assertEqual(422, self.client.get("/new/invalid").status_code)

    def test_plain_router_is_rejected_during_application_assembly(self):
        app = FastAPI()
        router = APIRouter()

        @router.get("/forgotten/{session_id}")
        def forgotten(session_id: int):
            return session_id

        app.include_router(router)
        with self.assertRaisesRegex(RuntimeError, "未经过会话访问边界"):
            validate_session_routes(app)

    def test_nested_models_are_checked_but_freeform_metadata_is_not_a_resource(self):
        class Member(BaseModel):
            persona_id: int

        class Payload(BaseModel):
            members: list[Member]
            metadata: dict = {}

        router = SessionAPIRouter()
        called = []

        @router.post("/nested")
        def nested(request: Payload, db=Depends(get_db)):
            called.append(True)
            return {}

        self.app.include_router(router)
        self.assertEqual(409, self.client.post("/nested", json={"members": [{"persona_id": 200}]}).status_code)
        self.assertEqual([], called)
        self.assertEqual(200, self.client.post("/nested", json={
            "members": [{"persona_id": 100}], "metadata": {"session_id": "a label"},
        }).status_code)

    def test_missing_database_dependency_cannot_silently_skip_the_check(self):
        router = SessionAPIRouter()
        called = []

        @router.get("/missing-db/{session_id}")
        def missing_db(session_id: int):
            called.append(True)
            return {}

        self.app.include_router(router)
        with self.assertRaisesRegex(RuntimeError, "未声明 db 依赖"):
            self.client.get("/missing-db/20")
        self.assertEqual([], called)

    def test_all_public_resource_services_reject_group_or_declare_shared_semantics(self):
        backend = Path(__file__).resolve().parents[2]
        original = self.snapshot()
        discovered = list(discover_operations(backend / "services"))
        self.assertTrue(discovered)
        with patch("services.infrastructure.llm_provider.get_llm_provider",
                   side_effect=AssertionError("入口校验前不得调用模型")):
            for path, name in discovered:
                module_name = ".".join(path.relative_to(backend).with_suffix("").parts)
                operation = importlib.import_module(module_name)
                for part in name.split("."):
                    operation = getattr(operation, part)
                if getattr(operation, "__session_kind_agnostic__", None):
                    continue
                parameters = inspect.signature(operation).parameters
                arguments = {key: 1 for key, value in parameters.items()
                             if value.default is inspect.Parameter.empty}
                wrong_kind = ({"session": 10, "persona": 100, "message": 999, "source_session": 20}
                              if getattr(operation, "__session_kind__", None) == "group"
                              else {"session": 20, "persona": 200, "message": 2, "source_session": 20})
                arguments.update({key: wrong_kind[kind]
                                  for key, kind in RESOURCE_ARGUMENTS.items() if key in parameters})
                arguments["db"] = self.db
                with self.subTest(operation=f"{module_name}.{name}"):
                    with self.assertRaises(SessionKindConflict):
                        result = operation(**arguments)
                        if inspect.isawaitable(result):
                            asyncio.run(result)
                    self.assertEqual(original, self.snapshot())
                    self.assertFalse(self.db.new or self.db.dirty or self.db.deleted)
                self.db.rollback()

    def test_discovery_includes_a_new_module_and_operation(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "new_service.py"
            path.write_text("def forgotten_operation(session_id, db):\n    return db.get(object, session_id)\n")
            self.assertEqual([(path, "forgotten_operation")], list(discover_operations(root)))
