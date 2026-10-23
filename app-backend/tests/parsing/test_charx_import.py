"""使用自制最小 CHARX 校验限制、预览生命周期与事务边界。"""
import base64
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image, ImageOps
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from application.factory import create_app
from core.database import get_db
from core.models import Base, Character, CharacterPortrait, CharacterPackageImport, OutboxJob
from services.media import charx_import as service
from services.media.character_portraits import list_portraits


def package(extra=None, card=None, compression=zipfile.ZIP_DEFLATED):
    image = io.BytesIO()
    Image.new("RGB", (12, 18), "green").save(image, format="PNG")
    raw = card or {"spec": "chara_card_v3", "spec_version": "3.0", "data": {
        "name": "测试角色包", "description": "角色设定", "first_mes": '你好<img="happy">',
        "extensions": {"risuai": {"triggerscript": ["never execute"]}},
        "assets": [{"type": "icon", "name": "main", "uri": "embeded://assets/avatar.png", "ext": "png"},
                   {"type": "x-risu-asset", "name": "角色.happy.png", "uri": "embeded://assets/happy.png.png", "ext": "png"}]}}
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as archive:
        archive.writestr("card.json", json.dumps(raw, ensure_ascii=False))
        archive.writestr("assets/avatar.png", image.getvalue())
        archive.writestr("assets/happy.png.png", image.getvalue())
        for name, content in (extra or {}).items():
            archive.writestr(name, content)
    return output.getvalue()


class CharxImportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.patches = [patch.object(service, "ROOT", self.root / "previews"),
                        patch.object(service.settings, "STORAGE_UPLOAD_AVATAR_DIR", str(self.root / "images"))]
        for item in self.patches:
            item.start()
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        @event.listens_for(self.engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, autoflush=False)()
        self.app = create_app()
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.db.close()
        self.engine.dispose()
        for item in reversed(self.patches):
            item.stop()
        self.directory.cleanup()

    def request(self, **changes):
        return {"character_id": None, "name": None, "portrait_indices": [1], "avatar_index": 0, **changes}

    def test_preview_is_not_persistence_and_preserves_source_names(self):
        result = service.preview_package(package({"module.risum": b"must never execute", "assets/font.woff2": b"font"}))
        self.assertEqual(0, self.db.query(Character).count())
        self.assertFalse((self.root / "images").exists())
        self.assertEqual(["main", "角色.happy.png"], [a["name"] for a in result["assets"]])
        self.assertNotIn("risuai", result["card"]["extensions"])
        self.assertTrue(any("模块" in notice for notice in result["warnings"]))
        self.assertTrue(any("内嵌图片" in notice for notice in result["warnings"]))
        images = service.preview_images(result["token"], 1, 1)
        self.assertEqual(1, images["images"][0]["index"])
        self.assertTrue(images["images"][0]["thumbnail"].startswith("data:image/png;base64,"))
        service.cancel_preview(result["token"])
        self.assertFalse((service.ROOT / result['token']).exists())
        self.assertEqual('cancelled', service.preview_status(result['token'], self.db)['status'])
        with self.assertRaises(LookupError):
            service.preview_images(result["token"])

    def test_import_new_character_is_atomic_idempotent_and_keeps_resource_metadata(self):
        preview = service.preview_package(package())
        result = service.import_package(preview["token"], self.request(), self.db)
        self.assertTrue(result["created"])
        character = self.db.get(Character, result["character_id"])
        self.assertTrue(Path(character.avatar_path).exists())
        portrait = self.db.query(CharacterPortrait).one()
        self.assertEqual("角色.happy.png", portrait.source_name)
        self.assertEqual("x-risu-asset", portrait.source_type)
        self.assertEqual("embeded://assets/happy.png.png", portrait.source_uri)
        self.assertEqual(result, service.import_package(preview["token"], self.request(), self.db))
        self.assertEqual(1, self.db.query(CharacterPortrait).count())
        with self.assertRaises(service.CharxConflict):
            service.import_package(preview["token"], self.request(portrait_indices=[]), self.db)

    def test_bad_png_checksum_is_skipped_without_losing_valid_images(self):
        image = io.BytesIO()
        Image.new("RGB", (12, 18), "green").save(image, format="PNG")
        damaged = bytearray(image.getvalue())
        damaged[damaged.index(b"IDAT") + 4] ^= 1
        raw = {"spec": "chara_card_v3", "spec_version": "3.0", "data": {"name": "部分坏图", "assets": [
            {"type": "icon", "name": "main", "uri": "embeded://assets/avatar.png", "ext": "png"},
            {"type": "emotion", "name": "broken", "uri": "embeded://assets/broken.png", "ext": "png"}]}}
        response = self.client.post("/characters/charx/preview", files={"file": (
            "broken.charx", package({"assets/broken.png": damaged}, card=raw))})
        self.assertEqual(200, response.status_code, response.text)
        preview = response.json()
        self.assertEqual([0], [asset["index"] for asset in preview["assets"]])
        self.assertEqual(1, preview["skipped_count"])
        self.assertTrue(any("损坏图片" in notice for notice in preview["warnings"]))
        self.assertEqual(1, len(service.preview_images(preview["token"])["images"]))
        result = service.import_package(preview["token"], self.request(portrait_indices=[0]), self.db)
        self.assertEqual(1, result["portraits_added"])

    def test_failed_jpeg_decodes_still_consume_the_total_pixel_budget(self):
        image = io.BytesIO()
        Image.new("RGB", (12, 18), "green").save(image, format="JPEG")
        damaged = image.getvalue()[:-2]
        # 头部校验能通过，但像素解码失败，不能因跳过而退还预算。
        with Image.open(io.BytesIO(damaged)) as source:
            source.verify()
        with Image.open(io.BytesIO(damaged)) as source, self.assertRaises(OSError):
            source.load()
        raw = {"spec": "chara_card_v3", "spec_version": "3.0", "data": {"name": "重复坏图", "assets": [
            {"type": "emotion", "name": str(index), "uri": f"embeded://assets/broken{index}.jpg", "ext": "jpg"}
            for index in range(3)]}}
        content = package({f"assets/broken{index}.jpg": damaged for index in range(3)}, card=raw)
        with patch.object(service, "MAX_TOTAL_PIXELS", 12 * 18 * 2):
            response = self.client.post("/characters/charx/preview", files={"file": ("budget.charx", content)})
        self.assertEqual(422, response.status_code, response.text)
        self.assertIn("总像素", response.json()["detail"])
        self.assertEqual([], list(service.ROOT.iterdir()))
        # 预算足够时，仍按无效素材跳过，允许保留角色设定。
        with patch.object(service, "MAX_TOTAL_PIXELS", 12 * 18 * 3):
            preview = service.preview_package(content)
        self.assertEqual(3, preview["skipped_count"])
        self.assertEqual([], preview["assets"])

    def test_jpeg_thumbnails_apply_exif_rotation_and_mirroring(self):
        for orientation in (6, 2):
            with self.subTest(orientation=orientation):
                image = Image.new("RGB", (120, 180), "red")
                image.paste("blue", (0, 0, 60, 180))
                exif = Image.Exif()
                exif[274] = orientation
                content = io.BytesIO()
                image.save(content, format="JPEG", exif=exif)
                raw = {"spec": "chara_card_v3", "spec_version": "3.0", "data": {"name": "方向", "assets": [
                    {"type": "icon", "name": "main", "uri": "embeded://assets/rotated.jpg", "ext": "jpg"}]}}
                preview = service.preview_package(package({"assets/rotated.jpg": content.getvalue()}, card=raw))
                thumbnail = service.preview_images(preview["token"])["images"][0]["thumbnail"]
                with Image.open(io.BytesIO(content.getvalue())) as original:
                    expected = ImageOps.exif_transpose(original)
                    expected.thumbnail((128, 160))
                    with Image.open(io.BytesIO(base64.b64decode(thumbnail.split(",", 1)[1]))) as actual:
                        self.assertEqual((128, 85) if orientation == 6 else (107, 160), actual.size)
                        self.assertEqual(expected.convert("RGBA").tobytes(), actual.convert("RGBA").tobytes())
                    expected.close()
                self.assertEqual(content.getvalue(), (service.ROOT / preview["token"] / "0.jpg").read_bytes())
                service.cancel_preview(preview["token"])

    def test_existing_character_only_appends_selected_images_unless_avatar_explicit(self):
        character = Character(name="原角色", description="必须保留", first_mes="原开场", avatar_path="original.png")
        self.db.add(character)
        self.db.commit()
        preview = service.preview_package(package())
        result = service.import_package(preview["token"], self.request(character_id=character.id, avatar_index=None), self.db)
        self.assertFalse(result["created"])
        self.assertEqual("必须保留", character.description)
        self.assertEqual("原开场", character.first_mes)
        self.assertEqual("original.png", character.avatar_path)
        next_preview = service.preview_package(package())
        service.import_package(next_preview["token"], self.request(character_id=character.id, avatar_index=0, portrait_indices=[]), self.db)
        self.assertNotEqual("original.png", character.avatar_path)
        self.assertEqual(1, self.db.query(OutboxJob).filter_by(task_type="delete_avatar").count())

    def test_deleted_import_target_cannot_be_confused_with_a_reused_character_id(self):
        preview = service.preview_package(package())
        result = service.import_package(preview["token"], self.request(), self.db)
        character = self.db.get(Character, result["character_id"])
        self.db.delete(character)
        self.db.commit()
        replacement = Character(name="替代角色", description="", first_mes="")
        self.db.add(replacement)
        self.db.commit()
        self.assertEqual(result["character_id"], replacement.id)
        self.assertIsNone(self.db.get(CharacterPackageImport, preview["token"]).character_id)
        with self.assertRaises(service.CharxConflict):
            service.import_package(preview["token"], self.request(), self.db)

    def test_failed_commit_cleans_copied_images_and_can_be_retried(self):
        preview = service.preview_package(package())
        with patch.object(self.db, "commit", side_effect=RuntimeError("commit failed")):
            with self.assertRaises(RuntimeError):
                service.import_package(preview["token"], self.request(), self.db)
        self.assertEqual([], list((self.root / "images").iterdir()))
        self.assertEqual(0, self.db.query(Character).count())
        self.assertEqual(0, self.db.query(CharacterPackageImport).count())
        self.assertTrue(service.import_package(preview["token"], self.request(), self.db)["created"])

    def test_duplicate_names_and_nonexistent_selection_cannot_modify_characters(self):
        first = service.preview_package(package())
        service.import_package(first["token"], self.request(), self.db)
        second = service.preview_package(package())
        with self.assertRaises(service.CharxConflict):
            service.import_package(second["token"], self.request(), self.db)
        with self.assertRaises(ValueError):
            service.import_package(second["token"], self.request(name="新角色", portrait_indices=[999]), self.db)
        with self.assertRaises(LookupError):
            service.import_package(second["token"], self.request(character_id=999), self.db)
        self.assertEqual(1, self.db.query(Character).count())

    def test_unsafe_paths_duplicate_names_symlinks_and_compression_are_rejected(self):
        link = zipfile.ZipInfo("assets/link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        backslash = zipfile.ZipInfo("assets/bad.png")
        backslash.filename = "assets\\bad.png"
        cases = [package({"../escape": b"x"}), package({"C:/escape": b"x"}),
                 package({backslash: b"x"}), package({"CARD.JSON": b"{}"}),
                 package({link: b"outside"}), package({"nested.zip": b"nested"}), package(compression=zipfile.ZIP_BZIP2), b"not a zip"]
        for content in cases:
            with self.subTest(length=len(content)):
                with self.assertRaises(ValueError):
                    service.preview_package(content)
        self.assertEqual([], list(service.ROOT.iterdir()))

    def test_limits_apply_to_upload_card_entries_expansion_and_image_count(self):
        for attribute, value in (("MAX_CARD", 4), ("MAX_FILES", 2), ("MAX_EXPANDED", 100), ("MAX_IMAGES", 1), ("MAX_STAGED_BYTES", 100), ("MAX_TOTAL_PIXELS", 10)):
            with self.subTest(attribute=attribute), patch.object(service, attribute, value):
                with self.assertRaises(ValueError):
                    service.preview_package(package())
        with patch.object(service, "upload_limit", return_value=10):
            response = self.client.post("/characters/charx/preview", files={"file": ("test.charx", b"x" * 11)})
            self.assertEqual(413, response.status_code)
        self.assertEqual(422, self.client.post("/characters/charx/preview", files={"file": ("test.png", package())}).status_code)

    def test_missing_remote_and_unsupported_resources_are_reported_without_network_access(self):
        raw = {"spec": "chara_card_v3", "spec_version": "3.0", "data": {"name": "缺图", "assets": [
            {"type": "icon", "name": "missing", "uri": "embeded://missing.png", "ext": "png"},
            {"type": "emotion", "name": "remote", "uri": "https://example.invalid/p.png", "ext": "png"}]}}
        preview = service.preview_package(package(card=raw))
        self.assertEqual([], preview["assets"])
        self.assertEqual(2, preview["skipped_count"])
        self.assertTrue(service.import_package(preview["token"], self.request(portrait_indices=[], avatar_index=None), self.db)["created"])

    def test_invalid_card_structures_return_validation_errors_and_remove_previews(self):
        for fields in ({"extensions": [1]}, {"character_book": []}, {"character_book": {"entries": [1]}}, {"assets": [None]}):
            raw = {"spec": "chara_card_v3", "spec_version": "3.0", "data": {"name": "invalid", **fields}}
            response = self.client.post("/characters/charx/preview", files={"file": ("test.charx", package(card=raw))})
            self.assertEqual(422, response.status_code, response.text)
        self.assertEqual([], list(service.ROOT.iterdir()))

    def test_nonfinite_numbers_and_invalid_unicode_are_rejected_before_staging(self):
        for value in ('NaN', 'Infinity', '-Infinity', '1e999', '"\\ud800"'):
            with self.subTest(value=value):
                payload = ('{"spec":"chara_card_v3","spec_version":"3.0",'
                           '"data":{"name":"invalid","extensions":{"custom":' + value + '}}}')
                output = io.BytesIO()
                with zipfile.ZipFile(output, 'w') as archive:
                    archive.writestr('card.json', payload)
                client = TestClient(self.app, raise_server_exceptions=False)
                try:
                    response = client.post('/characters/charx/preview', files={'file': ('invalid.charx', output.getvalue())})
                finally:
                    client.close()
                self.assertEqual(422, response.status_code, response.text)
                self.assertEqual([], list(service.ROOT.iterdir()))
                self.assertEqual(0, self.db.query(Character).count())

    def test_expiry_preview_capacity_and_token_validation(self):
        previews = [service.preview_package(package()) for _ in range(service.MAX_PREVIEWS)]
        with self.assertRaises(service.CharxConflict):
            service.preview_package(package())
        with patch.object(service.time, "time", return_value=previews[0]["expires_at"] + 1):
            with self.assertRaises(LookupError):
                service.preview_images(previews[0]["token"])
            service.preview_package(package())
        for token in ("../outside", "A" * 32):
            with self.assertRaises(LookupError):
                service.cancel_preview(token)

    def test_api_preview_confirm_and_cancel_follow_contract(self):
        response = self.client.post("/characters/charx/preview", files={"file": ("test.zip", package())})
        self.assertEqual(200, response.status_code, response.text)
        token = response.json()["token"]
        base = f"/characters/charx/previews/{token}"
        self.assertEqual(200, self.client.get(base + "/images").status_code)
        self.assertEqual(422, self.client.get(base + "/images?limit=13").status_code)
        saved = self.client.post(base + "/import", json=self.request())
        self.assertEqual(200, saved.status_code, saved.text)
        self.assertEqual(saved.json(), self.client.post(base + "/import", json=self.request()).json())
        self.assertEqual(200, self.client.post(base + "/cancel").status_code)
        self.assertEqual(404, self.client.get(base + "/images").status_code)

    def test_portrait_pagination_keeps_imported_resources_bounded(self):
        preview = service.preview_package(package())
        result = service.import_package(preview["token"], self.request(), self.db)
        for index in range(30):
            self.db.add(CharacterPortrait(character_id=result["character_id"], name=str(index), image_path="test.png"))
        self.db.commit()
        first = list_portraits(result["character_id"], self.db)
        second = list_portraits(result["character_id"], self.db, offset=24)
        self.assertEqual(24, len(first["portraits"]))
        self.assertEqual(7, len(second["portraits"]))
        self.assertTrue(first["has_more"])
        self.assertFalse(second["has_more"])
        self.assertEqual(31, first["total"])

    def test_repeated_bad_images_are_read_once_and_distinct_failures_consume_bytes(self):
        raw = {'spec': 'chara_card_v3', 'spec_version': '3.0', 'data': {'name': 'budget', 'assets': [
            {'type': 'icon', 'name': str(i), 'uri': 'embeded://bad.png', 'ext': 'png'} for i in range(20)]}}
        with patch.object(service, '_read', wraps=service._read) as read:
            preview = service.preview_package(package({'bad.png': b'x' * service.MB}, card=raw))
        self.assertEqual(2, read.call_count)  # card + unique bad image
        self.assertEqual(20, preview['skipped_count'])
        service.cancel_preview(preview['token'])
        raw['data']['assets'] = [{'type': 'icon', 'name': str(i), 'uri': f'embeded://bad{i}.png', 'ext': 'png'} for i in range(3)]
        with patch.object(service, 'MAX_STAGED_BYTES', 2 * service.MB):
            with self.assertRaises(service.CharxLimit):
                service.preview_package(package({f'bad{i}.png': b'x' * service.MB for i in range(3)}, card=raw))

    def test_same_content_is_skipped_across_tokens_and_can_be_explicitly_kept(self):
        first = service.preview_package(package())
        result = service.import_package(first['token'], self.request(portrait_indices=[0, 1]), self.db)
        self.assertEqual(1, result['portraits_added'])
        self.assertEqual(1, result['duplicates_skipped'])
        second = service.preview_package(package())
        again = service.import_package(second['token'], self.request(character_id=result['character_id']), self.db)
        self.assertEqual(0, again['portraits_added'])
        self.assertEqual(1, again['duplicates_skipped'])
        third = service.preview_package(package())
        kept = service.import_package(third['token'], self.request(character_id=result['character_id'], skip_duplicates=False), self.db)
        self.assertEqual(1, kept['portraits_added'])
        self.assertEqual(1, len(list((self.root / 'images').iterdir())))
        self.assertEqual(2, self.db.query(CharacterPortrait).count())

    def test_status_recovers_committed_result_independently_of_request_changes(self):
        preview = service.preview_package(package())
        base = f"/characters/charx/previews/{preview['token']}"
        self.assertEqual('ready', self.client.get(base + '/status').json()['status'])
        result = service.import_package(preview['token'], self.request(), self.db)
        status = self.client.get(base + '/status').json()
        self.assertEqual('imported', status['status'])
        self.assertEqual(result, status['result'])
        service.cancel_preview(preview['token'])
        self.assertEqual('imported', self.client.get(base + '/status').json()['status'])

    def test_shared_file_survives_portrait_deletion_until_avatar_is_released(self):
        from services.media.character_portraits import delete_portrait
        from services.infrastructure import outbox_worker
        preview = service.preview_package(package())
        result = service.import_package(preview['token'], self.request(portrait_indices=[0, 1], skip_duplicates=False), self.db)
        character = self.db.get(Character, result['character_id'])
        path = Path(character.avatar_path)
        portraits = self.db.query(CharacterPortrait).all()
        with patch.object(outbox_worker, 'SessionLocal', sessionmaker(bind=self.engine)):
            for portrait in portraits:
                delete_portrait(character.id, portrait.id, self.db)
                outbox_worker.handle_delete_avatar(json.dumps({'file_path': str(path)}))
                self.assertTrue(path.exists())
            character.avatar_path = ''
            self.db.commit()
            outbox_worker.handle_delete_avatar(json.dumps({'file_path': str(path)}))
            self.assertFalse(path.exists())

    def test_legacy_portrait_without_hash_is_deduplicated_and_backfilled(self):
        first = service.preview_package(package())
        result = service.import_package(first['token'], self.request(), self.db)
        portrait = self.db.query(CharacterPortrait).one()
        portrait.content_sha256 = None
        self.db.commit()
        second = service.preview_package(package())
        result = service.import_package(second['token'], self.request(character_id=result['character_id']), self.db)
        self.assertEqual(0, result['portraits_added'])
        self.assertEqual(64, len(portrait.content_sha256))

    def test_old_preview_format_expires_instead_of_failing_during_import(self):
        preview = service.preview_package(package())
        manifest = service.ROOT / preview['token'] / 'manifest.json'
        data = json.loads(manifest.read_text(encoding='utf-8'))
        data.pop('plan_version')
        manifest.write_text(json.dumps(data), encoding='utf-8')
        self.assertEqual('expired', service.preview_status(preview['token'], self.db)['status'])

    def test_cleanup_reclaims_abandoned_images_and_preserves_expired_status(self):
        preview = service.preview_package(package())
        with patch.object(service.time, 'time', return_value=preview['expires_at'] + 1):
            service.cleanup_previews()
            self.assertFalse((service.ROOT / preview['token']).exists())
            self.assertEqual('expired', service.preview_status(preview['token'], self.db)['status'])

    def test_compatibility_plan_reports_loss_and_unknown_extensions(self):
        raw = {'spec': 'chara_card_v3', 'spec_version': '3.0', 'data': {'name': 'plan',
               'nickname': 'nick', 'future_field': 'value', 'extensions': {'unknown': {'x': 1}},
               'character_book': {'entries': [{'content': 'lore'}]},
               'assets': [{'type': 'audio', 'name': 'voice', 'uri': 'https://example.invalid/a.mp3', 'ext': 'mp3'}]}}
        preview = service.preview_package(package(card=raw))
        report = preview['compatibility']
        self.assertTrue(any(row['status'] == 'unknown' and 'future_field' in row['label'] for row in report))
        self.assertTrue(any(row['status'] == 'skipped' and 'nickname' in row['label'] for row in report))
        self.assertTrue(any(row['count'] == 1 and '世界书条目' in row['label'] for row in report))
        self.assertEqual('voice', preview['skipped_assets'][0]['name'])

    def test_operation_contract_and_extra_multipart_files_are_rejected(self):
        preview = service.preview_package(package())
        url = f"/characters/charx/previews/{preview['token']}/import"
        response = self.client.post(url, json=self.request(operation='append_assets'))
        self.assertEqual(422, response.status_code)
        response = self.client.post('/characters/charx/preview', files=[('file', ('a.charx', package())), ('extra', ('b', b'x'))])
        self.assertEqual(400, response.status_code)

    def test_parsing_does_not_block_other_preview_lifecycle_operations(self):
        import threading
        preview = service.preview_package(package())
        started, resume = threading.Event(), threading.Event()
        original = service._parse_archive
        def blocked(*args):
            started.set()
            if not resume.wait(5):
                raise RuntimeError('test timed out')
            return original(*args)
        with patch.object(service, '_parse_archive', side_effect=blocked):
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor() as pool:
                pending = pool.submit(service.preview_package, package())
                self.assertTrue(started.wait(2))
                try:
                    cancel = pool.submit(service.cancel_preview, preview['token'])
                    cancel.result(timeout=2)
                finally:
                    resume.set()
                pending.result(timeout=5)
