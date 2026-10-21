"""Cached downloads and legacy audio recovery must survive service extraction."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from services.media import audio_service


class AudioFileTests(unittest.IsolatedAsyncioTestCase):
    async def test_cached_file_does_not_open_database_or_call_tts(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            audio_service.settings, "TTS_CACHE_DIR", temporary
        ), patch.object(audio_service, "SessionLocal") as session:
            path = Path(temporary) / "cached.mp3"
            path.write_bytes(b"audio")
            self.assertEqual(path, Path(await audio_service.resolve_audio_file(path.name)))
            session.assert_not_called()

    async def test_missing_unbound_file_does_not_open_database(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            audio_service.settings, "TTS_CACHE_DIR", temporary
        ), patch.object(audio_service, "SessionLocal") as session:
            with self.assertRaises(FileNotFoundError):
                await audio_service.resolve_audio_file("missing.mp3")
            session.assert_not_called()

    async def test_legacy_recovery_returns_file_and_closes_database(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            audio_service.settings, "TTS_CACHE_DIR", temporary
        ), patch.object(audio_service, "SessionLocal") as session, patch.object(
            audio_service.TTSService, "get_instance"
        ) as service:
            path = Path(temporary) / "msg_7_voice_1.00.mp3"

            async def synthesize(**kwargs):
                path.write_bytes(b"recovered")

            service.return_value.generate_speech_async = AsyncMock(side_effect=synthesize)
            self.assertEqual(path, Path(await audio_service.resolve_audio_file(path.name)))
            service.return_value.generate_speech_async.assert_awaited_once_with(
                text="", voice="voice", speed=1.0, message_id=7, db=session.return_value
            )
            session.return_value.close.assert_called_once()
