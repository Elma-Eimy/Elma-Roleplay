import base64
from copy import deepcopy
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from services.media.character_card_import import import_character_card
from services.parse import _extract_v2_data, parse_character_card, read_png_card_payloads


def chunk(kind, content):
    return struct.pack('>I', len(content)) + kind + content + struct.pack('>I', zlib.crc32(kind + content))


def png(*texts):
    return b'\x89PNG\r\n\x1a\n' + b''.join(texts) + chunk(b'IEND', b'')


def card(**fields):
    return {'spec': 'chara_card_v2', 'spec_version': '2.0', 'data': {'name': '测试角色', **fields}}


def encoded(raw):
    return base64.b64encode(json.dumps(raw, ensure_ascii=False).encode())


class CharacterCardImportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_all_metadata_exported_and_first_worldbook_is_imported(self):
        first = card(character_book={'entries': [{'content': '<fact>原文</fact>', 'extensions': {'vendor': 1}}]})
        second = card()
        source = self.root / 'card.png'
        source.write_bytes(png(chunk(b'tEXt', b'chara\0' + encoded(first)), chunk(b'tEXt', b'chara\0' + encoded(second))))
        self.assertEqual(read_png_card_payloads(str(source)), [first, second])
        self.assertEqual(parse_character_card(str(source))['extensions']['character_book'], first['data']['character_book'])

    def test_compressed_and_international_metadata(self):
        raw = card(first_mes='你好🌸')
        text = encoded(raw)
        for kind, content in [(b'zTXt', b'chara\0\0' + zlib.compress(text)), (b'iTXt', b'chara\0\0\0\0\0' + text), (b'iTXt', b'chara\0\1\0\0\0' + zlib.compress(text))]:
            with self.subTest(kind=kind, content=content[:10]):
                source = self.root / 'card.png'
                source.write_bytes(png(chunk(kind, content)))
                self.assertEqual(read_png_card_payloads(str(source)), [raw])

    def test_bad_metadata_does_not_hide_later_valid_card(self):
        source = self.root / 'card.png'
        source.write_bytes(png(chunk(b'tEXt', b'chara\0[]'), chunk(b'tEXt', b'chara\0' + encoded(card()))))
        self.assertEqual(parse_character_card(str(source))['name'], '测试角色')

    def test_truncated_png_has_readable_error(self):
        source = self.root / 'card.png'
        source.write_bytes(b'\x89PNG\r\n\x1a\n' + struct.pack('>I', 999999999) + b'tEXt')
        with self.assertRaisesRegex(ValueError, '不完整'):
            parse_character_card(str(source))

    def test_normalization_does_not_mutate_source_extensions(self):
        raw = card(alternate_greetings=['<b>你好</b>'], extensions={'vendor': {'unknown': True}}, character_book={'entries': [{'content': ' <fact>原文</fact> '}]})
        before = deepcopy(raw)
        result = _extract_v2_data(raw)
        self.assertEqual(raw, before)
        self.assertTrue(result['extensions']['vendor']['unknown'])
        self.assertEqual(result['alternate_greetings'], ['**你好**'])

    def test_null_optional_arrays_and_bom_json(self):
        content = ('\ufeff' + json.dumps(card(tags=None, alternate_greetings=None))).encode()
        result = import_character_card(content, '.json', str(self.root / 'avatars'))
        self.assertEqual(result['tags'], [])
        self.assertEqual(result['avatar_path'], '')
        self.assertFalse((self.root / 'avatars').exists())

    def test_invalid_json_leaves_no_avatar(self):
        for raw in ([], {}, {'data': None}, card(tags='tag'), card(alternate_greetings=[12])):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                import_character_card(json.dumps(raw).encode(), '.json', str(self.root / 'avatars'))
        self.assertFalse((self.root / 'avatars').exists())

    def test_repeat_png_import_reuses_avatar(self):
        content = png(chunk(b'tEXt', b'chara\0' + encoded(card())))
        directory = self.root / 'avatars'
        first = import_character_card(content, '.png', str(directory))
        second = import_character_card(content, '.png', str(directory))
        self.assertEqual(first['avatar_path'], second['avatar_path'])
        self.assertEqual(list(directory.iterdir()), [Path(first['avatar_path'])])
        self.assertEqual(Path(first['avatar_path']).read_bytes(), content)

    def test_creator_metadata_and_saved_greetings_survive_import(self):
        raw = card(creator='Author', character_version='main', extensions={'vendor': {'unknown': True}, 'alternate_greetings': ['Saved start']})
        parsed = _extract_v2_data(raw)
        metadata = parsed['extensions']['ai_roleplay_card']
        self.assertEqual(metadata['creator'], 'Author')
        self.assertEqual(metadata['character_version'], 'main')
        self.assertEqual(metadata['spec'], 'chara_card_v2')
        self.assertEqual(parsed['extensions']['alternate_greetings'], ['Saved start'])
        self.assertTrue(parsed['extensions']['vendor']['unknown'])

    def test_null_text_fields_become_editable_empty_strings(self):
        parsed = _extract_v2_data(card(description=None, first_mes=None, personality=None, creator_notes=None))
        for key in ('description', 'first_mes', 'personality', 'creator_notes'):
            self.assertEqual(parsed[key], '')
        with self.assertRaisesRegex(ValueError, 'description'):
            _extract_v2_data(card(description={'not': 'text'}))
