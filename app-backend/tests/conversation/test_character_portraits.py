"""普通角色、无标签素材、候选与分支边界、资源回收的隔离回归。"""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from application.factory import create_app
from core.database import get_db
from core.models import Base, Character, CharacterPortrait, ChatMessage, MessageRole, OutboxJob
from services.media import character_portraits as portraits
from services.conversation.session_service import create_session_service, save_chat_response
from services.conversation.message_service import switch_candidate, delete_message
from services.character_service import delete_character_service
from services.infrastructure import outbox_worker


class CharacterPortraitTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        @event.listens_for(self.engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, autoflush=False)
        self.db = self.factory()
        self.directory = tempfile.TemporaryDirectory()
        self.config = patch.object(portraits.settings, "STORAGE_UPLOAD_AVATAR_DIR", self.directory.name)
        self.config.start()
        self.character = Character(name="普通卡", description="没有标签或扩展", first_mes="默认开场", avatar_path="avatar.png")
        self.db.add(self.character)
        self.db.commit()
        result = create_session_service(self.character.id, None, "故事", None, None, self.db)
        self.sid, self.pid = result["session_id"], result["persona_id"]
        data = io.BytesIO()
        Image.new("RGB", (4, 6), "green").save(data, format="PNG")
        self.image = data.getvalue()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.config.stop()
        self.directory.cleanup()

    def add(self, name="任意图片.png"):
        return portraits.add_portrait(self.character.id, self.image, name, self.db)["id"]

    def select(self, portrait_id, sid=None):
        sid = sid or self.sid
        current = portraits.get_selection(sid, self.db)
        return portraits.update_selection(sid, portrait_id, current["revision"], self.db)

    def user(self):
        message = ChatMessage(session_id=self.sid, role=MessageRole.user, content="继续", is_active=True)
        self.db.add(message)
        self.db.commit()
        return message.id

    def reply(self, uid, old=None):
        return save_chat_response(self.sid, self.pid, uid, "正文", "", "开心", 0, old is not None, old, self.db)[0]

    def test_plain_card_manual_selection_and_explicit_avatar_fallback(self):
        self.assertEqual([], portraits.list_portraits(self.character.id, self.db)["portraits"])
        self.assertEqual("avatar.png", portraits.get_selection(self.sid, self.db)["image_path"])
        image = self.add()
        chosen = self.select(image)
        self.reply(self.user())
        self.assertEqual(image, portraits.get_selection(self.sid, self.db)["portrait_id"])
        self.assertIsNone(self.select(None)["portrait_id"])
        with self.assertRaises(portraits.PortraitConflict):
            portraits.update_selection(self.sid, image, chosen["revision"], self.db)

    def test_candidates_deletion_and_nonactive_fork_never_inherit_future(self):
        base, alternate = self.add("初始.png"), self.add("另一张.png")
        self.select(base)
        uid = self.user()
        old = self.reply(uid)
        self.select(alternate)
        new = self.reply(uid, old=old)
        self.assertEqual(base, portraits.get_selection(self.sid, self.db)["portrait_id"])
        branch = create_session_service(self.character.id, self.sid, "选旧候选分支", None, old, self.db)
        self.assertEqual(alternate, portraits.get_selection(branch["session_id"], self.db)["portrait_id"])
        switch_candidate(old, self.db)
        self.assertEqual(alternate, portraits.get_selection(self.sid, self.db)["portrait_id"])
        self.select(None)
        self.assertEqual(alternate, portraits.get_selection(branch["session_id"], self.db)["portrait_id"])
        delete_message(old, self.db)
        self.assertEqual(base, portraits.get_selection(self.sid, self.db)["portrait_id"])
        self.assertTrue(self.db.get(ChatMessage, new).is_active)
        copied = self.db.query(ChatMessage).filter_by(session_id=branch["session_id"]).first()
        delete_message(copied.id, self.db)
        self.assertEqual(base, portraits.get_selection(branch["session_id"], self.db)["portrait_id"])

    def test_empty_story_baseline_and_failed_commit(self):
        opening = self.db.query(ChatMessage).filter_by(session_id=self.sid).first()
        delete_message(opening.id, self.db)
        image = self.add()
        self.select(image)
        self.assertEqual(0, self.db.query(ChatMessage).filter_by(session_id=self.sid).count())
        with patch.object(self.db, "commit", side_effect=RuntimeError("failed")):
            with self.assertRaises(RuntimeError):
                self.select(None)
        self.assertEqual(image, portraits.get_selection(self.sid, self.db)["portrait_id"])

    def test_empty_story_fork_snapshots_portrait_baseline_independently(self):
        opening = self.db.query(ChatMessage).filter_by(session_id=self.sid).first()
        delete_message(opening.id, self.db)
        image = self.add()
        self.select(image)
        branch = create_session_service(self.character.id, self.sid, "空故事分支", None, None, self.db)
        child_id = branch["session_id"]
        self.assertEqual(image, portraits.get_selection(child_id, self.db)["portrait_id"])
        self.assertEqual(0, self.db.query(ChatMessage).filter_by(session_id=child_id).count())
        self.select(None)
        self.assertEqual(image, portraits.get_selection(child_id, self.db)["portrait_id"])
        self.select(None, child_id)
        reset_branch = create_session_service(self.character.id, child_id, "沿用头像的空分支", None, None, self.db)
        self.assertIsNone(portraits.get_selection(reset_branch["session_id"], self.db)["portrait_id"])

    def test_truncated_jpeg_is_rejected_without_creating_resource_or_file(self):
        data = io.BytesIO()
        Image.new("RGB", (64, 64), "green").save(data, format="JPEG")
        damaged = data.getvalue()[:-10]
        # 此样本可通过头部校验，但不能完整解码。
        with Image.open(io.BytesIO(damaged)) as image:
            image.verify()
        before_files = set(Path(self.directory.name).iterdir())
        with self.assertRaises(ValueError):
            portraits.add_portrait(self.character.id, damaged, "broken.jpg", self.db)
        self.assertEqual(0, self.db.query(CharacterPortrait).count())
        self.assertEqual(before_files, set(Path(self.directory.name).iterdir()))

    def test_complete_supported_images_remain_uploadable(self):
        for format_name, extension in (("PNG", ".png"), ("JPEG", ".jpg"), ("WEBP", ".webp")):
            with self.subTest(format=format_name):
                data = io.BytesIO()
                Image.new("RGB", (8, 12), "green").save(data, format=format_name)
                result = portraits.add_portrait(self.character.id, data.getvalue(), "valid" + extension, self.db)
                path = Path(result["image_path"])
                self.assertEqual(extension, path.suffix)
                self.assertEqual(data.getvalue(), path.read_bytes())

    def test_resource_deletion_falls_back_and_never_reuses_old_id(self):
        old = self.add()
        selected = self.select(old)
        path = Path(selected["image_path"])
        portraits.delete_portrait(self.character.id, old, self.db)
        self.assertIsNone(portraits.get_selection(self.sid, self.db)["portrait_id"])
        self.assertTrue(path.exists(), "删除仅登记 Outbox")
        self.assertGreater(self.add(), old)
        with patch.object(outbox_worker, "SessionLocal", self.factory):
            outbox_worker.handle_delete_avatar(json.dumps({"file_path": str(path)}))
        self.assertFalse(path.exists())
        delete_character_service(self.character.id, self.db)
        self.assertEqual(0, self.db.query(CharacterPortrait).count())
        self.assertGreaterEqual(self.db.query(OutboxJob).filter_by(task_type="delete_avatar").count(), 3)

    def test_outbox_retains_portrait_reference_and_upload_failure_leaves_no_file(self):
        image = self.add()
        path = self.db.get(CharacterPortrait, image).image_path
        with patch.object(outbox_worker, "SessionLocal", self.factory):
            outbox_worker.handle_delete_avatar(json.dumps({"file_path": path}))
        self.assertTrue(Path(path).exists())
        before = set(Path(self.directory.name).iterdir())
        with patch.object(self.db, "commit", side_effect=RuntimeError("failed")):
            with self.assertRaises(RuntimeError):
                self.add()
        self.assertEqual(before, set(Path(self.directory.name).iterdir()))

    def test_api_validates_images_ownership_revision_and_generation_lock(self):
        app = create_app()
        app.dependency_overrides[get_db] = lambda: self.db
        with TestClient(app) as client:
            url = f"/characters/{self.character.id}/portraits"
            self.assertEqual(422, client.post(url, files={"file": ("fake.png", b"not an image", "image/png")}).status_code)
            saved = client.post(url, files={"file": ("photo.png", self.image, "image/png")})
            self.assertEqual(200, saved.status_code, saved.text)
            image = saved.json()["id"]
            rename = client.put(f"{url}/{image}", json={"name": "便服"})
            self.assertEqual("便服", rename.json()["name"])
            self.assertEqual(422, client.put(f"{url}/{image}", json={"name": "   "}).status_code)
            state_url = f"/sessions/{self.sid}/portrait"
            current = client.get(state_url).json()
            payload = {"portrait_id": image, "expected_revision": current["revision"]}
            self.assertEqual(200, client.put(state_url, json=payload).status_code)
            self.assertEqual(409, client.put(state_url, json=payload).status_code)
            payload["expected_revision"] = client.get(state_url).json()["revision"]
            payload["portrait_id"] = 99999
            self.assertEqual(422, client.put(state_url, json=payload).status_code)
            with patch("routers.sessions.get_session_lock") as lock:
                lock.return_value.locked.return_value = True
                self.assertEqual(409, client.put(state_url, json=payload).status_code)
            other = Character(name="另一个角色", description="", first_mes="")
            self.db.add(other)
            self.db.commit()
            self.assertEqual(404, client.post(f"/characters/{other.id}/portraits/{image}/delete").status_code)
            self.assertEqual(404, client.get("/sessions/999999/portrait").status_code)
