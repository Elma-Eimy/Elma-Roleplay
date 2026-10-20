import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from application.factory import create_app
from routers import characters
from core.database import SessionLocal
from core.models import Character


class CharacterImportApiTests(unittest.TestCase):
    def test_json_import_has_persistable_metadata_without_creating_avatar_or_character(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(characters, 'UPLOAD_DIR', temporary):
            client = TestClient(create_app())
            self.addCleanup(client.close)
            with SessionLocal() as db:
                count_before = db.query(Character).count()
            response = client.post('/characters/parse', files={'file': ('card.json', json.dumps({
                'spec': 'chara_card_v2', 'data': {'name': 'Import draft', 'creator': 'Author',
                'character_version': 'main', 'alternate_greetings': ['Second start'], 'extensions': {'vendor': 1}},
            }).encode(), 'application/json')})
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()['data']
            with SessionLocal() as db:
                self.assertEqual(db.query(Character).count(), count_before)
            self.assertEqual(data['avatar_path'], '')
            self.assertEqual(data['extensions']['ai_roleplay_card']['creator'], 'Author')
            self.assertEqual(data['extensions']['alternate_greetings'], ['Second start'])
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_invalid_and_oversized_files_leave_no_avatar(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(characters, 'UPLOAD_DIR', temporary), patch.object(characters, 'MAX_CARD_SIZE_BYTES', 32):
            client = TestClient(create_app())
            self.addCleanup(client.close)
            bad = client.post('/characters/parse', files={'file': ('photo.png', b'not a card', 'image/png')})
            large = client.post('/characters/parse', files={'file': ('large.json', b'x' * 33, 'application/json')})
            self.assertEqual(bad.status_code, 400)
            self.assertEqual(large.status_code, 413)
            self.assertEqual(list(Path(temporary).iterdir()), [])
