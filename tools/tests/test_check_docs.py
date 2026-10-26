"""文档检查只依赖仓库内已跟踪路径，不受本地私有文件影响。"""

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest


spec = importlib.util.spec_from_file_location(
    "check_docs", Path(__file__).resolve().parents[1] / "check_docs.py"
)
check_docs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_docs)


class DocumentationLinkTests(unittest.TestCase):
    def test_inline_reference_and_encoded_paths(self):
        content = """
[普通](guide.md#标题) [带空格](<my guide.md>) [编码](my%20guide.md)
![图片](images/a(1).png "说明") [引用][guide] [guide][] [guide]
[guide]: guide.md "指南"
"""
        targets = [target for _, target in check_docs.link_targets(content)]
        self.assertEqual(
            ["guide.md#标题", "my guide.md", "my%20guide.md", "images/a(1).png",
             "guide.md", "guide.md", "guide.md"], targets,
        )

    def test_inline_link_does_not_use_same_named_reference(self):
        content = "[guide](real.md)\n[guide]: unused.md\n"
        self.assertEqual([(1, "real.md")], list(check_docs.link_targets(content)))

    def test_code_examples_are_ignored(self):
        content = """
`[例子](missing.md)`
```markdown
[例子](missing.md)
````
~~~~
[例子](missing.md)
~~~~
    [例子](missing.md)
[真实](real.md)
"""
        self.assertEqual([(10, "real.md")], list(check_docs.link_targets(content)))

    def test_tracked_paths_case_private_files_and_deleted_targets(self):
        with tempfile.TemporaryDirectory(prefix="docs-links-") as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            (root / "docs").mkdir()
            (root / "docs" / "Guide.md").write_text("# 指南\n", encoding="utf-8")
            (root / "README.md").write_text(
                "[正确](docs/Guide.md#不检查锚点) [目录](docs/)\n"
                "[大小写](docs/guide.md) [私有](private.md) [不存在](missing.md)\n"
                "[外链](https://example.invalid/page) [页内](#标题)\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "README.md", "docs/Guide.md"], cwd=root, check=True)
            (root / "private.md").write_text("[本地坏链接](also-missing.md)", encoding="utf-8")
            count, errors = check_docs.check_repository(root)
            self.assertEqual(2, count)
            self.assertEqual(3, len(errors), errors)
            self.assertIn("大小写", errors[0])
            self.assertIn("private.md", errors[1])
            self.assertIn("missing.md", errors[2])
            (root / "docs" / "Guide.md").unlink()
            _, errors = check_docs.check_repository(root)
            self.assertTrue(any("目标已从工作区删除" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
