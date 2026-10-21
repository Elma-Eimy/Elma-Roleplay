"""回复文本契约的容错解析回归测试。"""

import unittest

from services.parse import extract_stream_reply_prefix, extract_xml_block


class ReplyParserTests(unittest.TestCase):
    def test_optional_state_delta_is_validated_and_never_leaks_to_reply(self):
        valid = '{"characters":{"露娜":{"posture":"站着"}}}'
        for data in (valid, '{"scene":null}', '{"unexpected":1}', '{"scene":', '{"scene":"' + '长' * 301 + '"}'):
            with self.subTest(data=data):
                raw = '<reply>正文</reply><status emotion="平静"/><state_update>' + data + '</state_update>'
                result = extract_xml_block(raw)
                self.assertEqual("正文", result["reply"])
                self.assertEqual(data == valid, "role_state_patch" in result)
        self.assertEqual("正文", extract_xml_block('正文<state_update>{"scene":')["reply"])
        self.assertEqual("正文", extract_xml_block('正文<state_update')["reply"])
        self.assertEqual("正文", extract_xml_block('正文<state_update>{"scene":"</state_update>"}</state_update>')["reply"])

    def test_stream_state_delta_without_status_never_leaks(self):
        raw = '一段足够长的正文用于检测流式边界并保证状态协议不进入正文。<state_update>{"scene":"窗边"}</state_update>'
        emitted = ""
        for index in range(1, len(raw) + 1):
            prefix = extract_stream_reply_prefix(raw[:index])
            length = max(0, len(prefix) - 24)
            if prefix.startswith(emitted) and length > len(emitted):
                emitted += prefix[len(emitted):length]
        self.assertTrue(extract_xml_block(raw)["reply"].startswith(emitted))
        self.assertNotIn("state_update", emitted)

    def test_parses_status_attributes_in_any_order(self):
        parsed = extract_xml_block(
            '<reply>你好</reply>'
            '<status affection_change="2" emotion="开心"/>'
        )

        self.assertEqual("你好", parsed["reply"])
        self.assertEqual("开心", parsed["emotion_tag"])
        self.assertEqual(2, parsed["affection_change"])

    def test_flattens_nested_and_malformed_reply_wrappers(self):
        cases = (
            "<reply><reply>正文</reply></reply>",
            "<reply>正文</reply</reply>",
            "正文</reply>",
            "<replay>正文</replay>",
            "正文</replay>",
        )

        for raw in cases:
            with self.subTest(raw=raw):
                self.assertEqual("正文", extract_xml_block(raw)["reply"])

    def test_missing_open_tag_does_not_leak_closing_tag_into_body(self):
        parsed = extract_xml_block(
            '没有开标签的正文</reply>\n'
            '<status emotion="平静" affection_change="0"/>'
        )

        self.assertEqual("没有开标签的正文", parsed["reply"])

    def test_plain_text_remains_supported(self):
        parsed = extract_xml_block("普通纯文本回复")

        self.assertEqual("普通纯文本回复", parsed["reply"])
        self.assertEqual("平静", parsed["emotion_tag"])
        self.assertEqual(0, parsed["affection_change"])

    def test_character_by_character_stream_never_emits_status_markup(self):
        raw = (
            "<reply>这是一段足够长的流式回复正文，用于验证尾部缓冲不会泄漏标签。"
            "</reply><status emotion=\"开心\" affection_change=\"2\"/>"
        )
        emitted = ""
        for index in range(1, len(raw) + 1):
            parsed_prefix = extract_stream_reply_prefix(raw[:index])
            safe_length = max(0, len(parsed_prefix) - 24)
            if (
                parsed_prefix.startswith(emitted)
                and safe_length > len(emitted)
            ):
                emitted += parsed_prefix[len(emitted):safe_length]

        final_reply = extract_xml_block(raw)["reply"]
        self.assertTrue(final_reply.startswith(emitted))
        emitted += final_reply[len(emitted):]
        self.assertEqual(final_reply, emitted)
        self.assertNotIn("<status", emitted)
        self.assertNotIn("</reply", emitted)


if __name__ == "__main__":
    unittest.main()
