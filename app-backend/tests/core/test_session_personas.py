"""单聊兼容访问和多成员数据库约束。"""
import unittest

from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from core.models import Base, Character, Session, SessionPersona


class SessionPersonasTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)

        @event.listens_for(self.engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.addCleanup(self.db.close)
        self.db.add_all([Character(id=i, name=str(i), description="test", first_mes="hello") for i in range(1, 5)])
        self.db.commit()

    def test_single_compatibility_is_read_only_and_group_has_no_default_persona(self):
        single = Session(personas=[SessionPersona(character_id=1)])
        group = Session(kind="group", personas=[SessionPersona(character_id=2, member_slot=2),
                                               SessionPersona(character_id=1, member_slot=1)])
        self.db.add_all([single, group])
        self.db.commit()
        self.assertEqual(1, single.persona.character_id)
        self.assertEqual(0, single.persona.member_slot)
        self.assertIsNone(group.persona)
        self.assertEqual([1, 2], [member.member_slot for member in group.personas])
        with self.assertRaises(AttributeError):
            single.persona = SessionPersona(character_id=4)
        self.db.delete(group)
        self.db.commit()
        self.assertEqual(1, self.db.query(SessionPersona).count())
        self.assertEqual(4, self.db.query(Character).count())

    def test_unique_slots_unique_characters_and_slot_range(self):
        group = Session(kind="group", personas=[SessionPersona(character_id=1, member_slot=1)])
        self.db.add(group)
        self.db.commit()
        for character_id, slot in ((2, 1), (1, 2), (2, -1), (2, 4)):
            with self.subTest(character_id=character_id, slot=slot):
                self.db.add(SessionPersona(session_id=group.id, character_id=character_id, member_slot=slot))
                with self.assertRaises(IntegrityError):
                    self.db.flush()
                self.db.rollback()
        self.assertEqual(1, self.db.query(SessionPersona).count())
        self.db.add(Session(kind="unsupported"))
        with self.assertRaises(IntegrityError):
            self.db.flush()
        self.db.rollback()
