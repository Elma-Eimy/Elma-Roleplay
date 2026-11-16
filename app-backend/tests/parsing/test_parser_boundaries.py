"""解析领域可独立导入，旧路径继续指向同一实现。"""
import subprocess
import sys
import textwrap
import unittest

from services import parse as compatibility
from services.conversation import reply_parser
from services.media import character_card_parser


class ParserBoundaryTests(unittest.TestCase):
    def test_legacy_exports_preserve_function_and_pattern_identity(self):
        card_names = (
            "parse_character_card", "_parse_json_card", "read_png_card_payloads",
            "write_png_card_payloads", "_decompress_card_text", "_validate_card_object",
            "_parse_png_card", "_html_to_markdown", "_normalize_prompt_text", "_extract_v2_data",
        )
        reply_names = (
            "extract_xml_block", "extract_stream_reply_prefix", "_extract_xml_block",
            "_REPLY_TAG_RE", "_MALFORMED_REPLY_CLOSE_RE", "_STATUS_TAG_RE",
            "_STATUS_CLOSE_RE", "_STATUS_ATTRIBUTE_RE", "_STREAM_REPLY_END_RE",
        )
        for module, names in ((character_card_parser, card_names), (reply_parser, reply_names)):
            for name in names:
                with self.subTest(name=name):
                    self.assertIs(getattr(module, name), getattr(compatibility, name))
        self.assertIs(reply_parser.extract_xml_block, compatibility._extract_xml_block)

    def test_each_parser_imports_without_the_other_domain_or_runtime_initialization(self):
        modules = ("services.media.character_card_parser", "services.conversation.reply_parser")
        script = textwrap.dedent("""
            import importlib
            import sys
            target, other = sys.argv[1:]
            importlib.import_module(target)
            forbidden = (other, 'services.parse', 'core.config', 'core.database')
            loaded = [name for name in forbidden if name in sys.modules]
            assert not loaded, loaded
        """)
        for target, other in (modules, modules[::-1]):
            with self.subTest(module=target):
                result = subprocess.run(
                    [sys.executable, "-c", script, target, other],
                    capture_output=True, text=True, encoding="utf-8", timeout=30,
                )
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
