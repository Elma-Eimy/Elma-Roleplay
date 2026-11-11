"""导演仅生成调度决定；旧知情与审查阶段不能重新启用。"""
import json
import unittest
from services.conversation import group_director_service as director


class DirectorPromptTests(unittest.TestCase):
    def context(self, max_chars=24000):
        sources = {'7': {'item:1': {'source': 'user', 'turn': 'current'}},
                   '9': {'item:1': {'source': 'user', 'turn': 'current'}}}
        payload = {'history': [{'kind': 'user', 'reference': 'item:1', 'content': '用户原文'}],
                   'eligible_persona_ids': [7, 9], 'response_sources': sources}
        return director.DirectorContext(json.dumps(payload, ensure_ascii=False), (7, 9), (7, 9), max_chars, 1, sources)

    def test_director_only_selects_speaker_target_or_end(self):
        messages = director.build_director_messages(self.context())
        system = messages[0]['content']
        for field in ('"action"', '"speaker_persona_id"', '"basis"'):
            self.assertIn(field, system)
        for field in ('"recipients"', '"units"', '"claims"', '"review"', '"request_result"'):
            self.assertNotIn(field, system)
        self.assertEqual('next_action', json.loads(messages[1]['content'])['stage'])

    def test_removed_stages_are_rejected_before_building_a_request(self):
        for stage in ('user_visibility', 'utterance_visibility', 'role_experience_review'):
            with self.subTest(stage=stage), self.assertRaisesRegex(director.GroupDirectorError, 'invalid_stage'):
                director.build_director_messages(self.context(), stage)

    def test_current_prefix_cannot_be_trimmed_to_fit_budget(self):
        full = director.build_director_messages(self.context())
        size = len(full[1]['content'])
        director.build_director_messages(self.context(size))
        with self.assertRaisesRegex(director.GroupDirectorError, 'context_budget'):
            director.build_director_messages(self.context(size-1))
