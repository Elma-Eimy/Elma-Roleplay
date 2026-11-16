"""检查群聊包的全部导入方向，包括函数内延迟导入。"""
import ast
from pathlib import Path
import unittest


class GroupServiceDependencyTests(unittest.TestCase):
    def test_group_service_imports_have_no_cycles(self):
        root = Path(__file__).resolve().parents[3] / "services" / "conversation" / "group"
        modules = {path.stem: path for path in root.glob("*.py")}
        graph = {name: set() for name in modules}
        package = "services.conversation.group"
        for name, path in modules.items():
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom):
                    if node.level == 1:
                        dependency = node.module
                    elif node.module == package:
                        dependency = None
                    elif node.module and node.module.startswith(package + "."):
                        dependency = node.module[len(package) + 1:]
                    else:
                        continue
                    targets = [dependency.split(".")[0]] if dependency else [alias.name for alias in node.names]
                    graph[name].update(target for target in targets if target in modules)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith(package + "."):
                            target = alias.name[len(package) + 1:].split(".")[0]
                            if target in modules:
                                graph[name].add(target)

        visited = set()

        def visit(name, chain):
            self.assertNotIn(name, chain, "群聊服务循环依赖：" + " -> ".join((*chain, name)))
            if name in visited:
                return
            for dependency in sorted(graph[name]):
                visit(dependency, (*chain, name))
            visited.add(name)

        for name in sorted(graph):
            visit(name, ())
