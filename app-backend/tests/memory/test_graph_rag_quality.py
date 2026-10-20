r"""Offline quality regressions for branch-aware Graph RAG."""

from __future__ import annotations

import json
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.config import settings
from core.models import (
    Base,
    Character,
    GraphEntity,
    Session,
    SessionPersona,
)
from services.memory.graph_service import (
    normalize_entity_name,
    retrieve_graph_context,
    sanitize_entity_aliases,
    upsert_graph_data,
)


class GraphRagQualityTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.old_min_importance = settings.APP_GRAPH_MIN_IMPORTANCE
        self.old_max_relations = settings.APP_GRAPH_MAX_RELATIONS
        settings.APP_GRAPH_MIN_IMPORTANCE = 0.0
        settings.APP_GRAPH_MAX_RELATIONS = 12

        self.character = Character(
            name="林墨",
            description="测试角色",
            personality="冷静",
            scenario="办公室",
            first_mes="你好",
        )
        self.parent_session = Session(title="parent")
        self.db.add_all([self.character, self.parent_session])
        self.db.flush()
        self.parent_persona = SessionPersona(
            session_id=self.parent_session.id,
            character_id=self.character.id,
        )
        self.db.add(self.parent_persona)
        self.db.flush()
        self.child_session = Session(
            title="child",
            parent_session_id=self.parent_session.id,
        )
        self.db.add(self.child_session)
        self.db.flush()
        self.child_persona = SessionPersona(
            session_id=self.child_session.id,
            character_id=self.character.id,
            parent_persona_id=self.parent_persona.id,
        )
        self.db.add(self.child_persona)
        self.db.commit()

    def tearDown(self):
        settings.APP_GRAPH_MIN_IMPORTANCE = self.old_min_importance
        settings.APP_GRAPH_MAX_RELATIONS = self.old_max_relations
        self.db.close()
        self.engine.dispose()

    def _upsert(self, persona, entities, relations):
        upsert_graph_data(persona.id, entities, relations, self.db)
        self.db.commit()

    def test_aliases_match_and_generic_pronouns_are_discarded(self):
        self._upsert(
            self.parent_persona,
            [{
                "name": "林墨",
                "aliases": ["阿墨", "墨哥", "她", "那个", "ＡＬＩＣＥ", "alice"],
                "entity_type": "person",
                "description": "一名调查员。",
            }, {
                "name": "旧城区",
                "entity_type": "place",
                "description": "案件发生地。",
            }],
            [{
                "source": "林墨",
                "relation_type": "visited",
                "target": "旧城区",
                "description": "林墨去过旧城区。",
                "importance": 0.8,
            }],
        )

        entity = self.db.query(GraphEntity).filter(GraphEntity.name == "林墨").one()
        aliases = json.loads(entity.aliases)
        self.assertIn("阿墨", aliases)
        self.assertIn("墨哥", aliases)
        self.assertNotIn("她", aliases)
        self.assertNotIn("那个", aliases)
        # NFKC + casefold duplicate aliases collapse to one spelling.
        self.assertEqual(
            1,
            len([alias for alias in aliases if normalize_entity_name(alias) == "alice"]),
        )

        context = retrieve_graph_context(
            self.parent_persona.id,
            "墨哥最近去过哪里？",
            self.db,
        )
        self.assertIn("林墨去过旧城区", context)

    def test_true_two_hop_includes_chain_edge_but_not_third_hop(self):
        self._upsert(
            self.parent_persona,
            [
                {"name": "A", "entity_type": "person", "description": "节点 A"},
                {"name": "B", "entity_type": "person", "description": "节点 B"},
                {"name": "C", "entity_type": "place", "description": "节点 C"},
                {"name": "D", "entity_type": "place", "description": "节点 D"},
            ],
            [
                {"source": "A", "relation_type": "knows", "target": "B", "description": "A 认识 B。", "importance": 0.9},
                {"source": "B", "relation_type": "visits", "target": "C", "description": "B 经常去 C。", "importance": 0.8},
                {"source": "C", "relation_type": "near", "target": "D", "description": "C 靠近 D。", "importance": 0.7},
            ],
        )

        context = retrieve_graph_context(self.parent_persona.id, "A 怎么样？", self.db)
        self.assertIn("A 认识 B", context)
        self.assertIn("B 经常去 C", context)
        self.assertNotIn("C 靠近 D", context)

    def test_hub_seed_does_not_expand_every_neighbor_to_second_hop(self):
        self._upsert(
            self.parent_persona,
            [
                {"name": "用户", "entity_type": "person", "description": "用户"},
                {"name": "小红", "entity_type": "person", "description": "朋友"},
                {"name": "Alice", "entity_type": "person", "description": "朋友"},
                {"name": "学校", "entity_type": "place", "description": "地点"},
                {"name": "医院", "entity_type": "place", "description": "地点"},
            ],
            [
                {"source": "用户", "relation_type": "friend", "target": "小红", "description": "用户认识小红。", "importance": 0.9},
                {"source": "用户", "relation_type": "friend", "target": "Alice", "description": "用户认识 Alice。", "importance": 0.9},
                {"source": "小红", "relation_type": "studies_at", "target": "学校", "description": "小红在学校读书。", "importance": 0.8},
                {"source": "Alice", "relation_type": "works_at", "target": "医院", "description": "Alice 在医院工作。", "importance": 0.8},
            ],
        )

        context = retrieve_graph_context(self.parent_persona.id, "用户有哪些朋友？", self.db)
        self.assertIn("用户认识小红", context)
        self.assertIn("用户认识 Alice", context)
        self.assertNotIn("小红在学校读书", context)
        self.assertNotIn("Alice 在医院工作", context)

    def test_child_description_and_relation_shadow_parent_without_concatenation(self):
        self._upsert(
            self.parent_persona,
            [
                {"name": "小红", "entity_type": "person", "description": "用户的初中同学。"},
                {"name": "蛋糕", "entity_type": "object", "description": "甜品。"},
            ],
            [{
                "source": "小红",
                "relation_type": "likes",
                "target": "蛋糕",
                "description": "小红过去喜欢蛋糕。",
                "importance": 0.8,
            }],
        )
        self._upsert(
            self.child_persona,
            [{"name": "小红", "entity_type": "person", "description": "用户现在最信任的朋友。"}],
            [{
                "source": "小红",
                "relation_type": "likes",
                "target": "蛋糕",
                "description": "小红现在只偶尔吃蛋糕。",
                "importance": 0.9,
            }],
        )

        context = retrieve_graph_context(self.child_persona.id, "小红喜欢什么？", self.db)
        child_cake = self.db.query(GraphEntity).filter(
            GraphEntity.persona_id == self.child_persona.id,
            GraphEntity.name == "蛋糕",
        ).one()
        self.assertEqual("object", child_cake.entity_type)
        self.assertIn("用户现在最信任的朋友", context)
        self.assertIn("小红现在只偶尔吃蛋糕", context)
        self.assertNotIn("用户的初中同学", context)
        self.assertNotIn("小红过去喜欢蛋糕", context)
        self.assertNotIn("；", context)

    def test_same_persona_update_replaces_description_and_output_is_stable(self):
        self._upsert(
            self.parent_persona,
            [
                {"name": "小红", "entity_type": "person", "description": "旧描述"},
                {"name": "公园", "entity_type": "place", "description": "地点"},
            ],
            [{
                "source": "小红",
                "relation_type": "visited",
                "target": "公园",
                "description": "旧关系描述",
                "importance": 0.7,
            }],
        )
        self._upsert(
            self.parent_persona,
            [{"name": "小红", "entity_type": "person", "description": "新描述"}],
            [{
                "source": "小红",
                "relation_type": "visited",
                "target": "公园",
                "description": "新关系描述",
                "importance": 0.8,
            }],
        )

        first = retrieve_graph_context(self.parent_persona.id, "小红", self.db)
        second = retrieve_graph_context(self.parent_persona.id, "小红", self.db)
        self.assertEqual(first, second)
        self.assertIn("新描述", first)
        self.assertIn("新关系描述", first)
        self.assertNotIn("旧描述", first)
        self.assertNotIn("旧关系描述", first)

    def test_relation_limit_is_deterministic(self):
        settings.APP_GRAPH_MAX_RELATIONS = 2
        self._upsert(
            self.parent_persona,
            [
                {"name": "中心", "entity_type": "concept", "description": "中心"},
                {"name": "高", "entity_type": "concept", "description": "高"},
                {"name": "中", "entity_type": "concept", "description": "中"},
                {"name": "低", "entity_type": "concept", "description": "低"},
            ],
            [
                {"source": "中心", "relation_type": "high", "target": "高", "description": "高优先关系", "importance": 0.9},
                {"source": "中心", "relation_type": "medium", "target": "中", "description": "中优先关系", "importance": 0.7},
                {"source": "中心", "relation_type": "low", "target": "低", "description": "低优先关系", "importance": 0.5},
            ],
        )

        context = retrieve_graph_context(self.parent_persona.id, "中心", self.db)
        self.assertIn("高优先关系", context)
        self.assertIn("中优先关系", context)
        self.assertNotIn("低优先关系", context)

    def test_alias_sanitizer_is_backward_compatible_with_null(self):
        self.assertEqual([], sanitize_entity_aliases(None, "小红"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
