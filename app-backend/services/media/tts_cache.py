"""TTS 缓存命名与文件操作；配置和日志器由调用方传入。"""

from dataclasses import dataclass
import hashlib
import logging
import os
import tempfile

from services.infrastructure.logging_context import log_event


@dataclass(frozen=True)
class TTSAudioCache:
    directory: str
    filename: str

    @classmethod
    def for_message(cls, directory, message_id, version, voice, speed):
        return cls(directory, f"msg_{message_id}_p{version}_{voice}_{speed:.2f}.mp3")

    @classmethod
    def for_text(cls, directory, text, version, voice, speed):
        # 用原文生成缓存键，命中时无需再次调用预处理模型。
        hash_input = f"p{version}_{text.strip()}_{voice}_{speed:.2f}"
        digest = hashlib.md5(hash_input.encode("utf-8")).hexdigest()
        return cls(directory, f"{digest}.mp3")

    @property
    def filepath(self):
        return os.path.join(self.directory, self.filename)

    @property
    def audio_url(self):
        return f"/audio/{self.filename}"

    def is_ready(self):
        return os.path.exists(self.filepath) and os.path.getsize(self.filepath) > 0

    def write(self, audio_bytes):
        # 临时文件与目标同目录，关闭后替换，避免读者命中尚未写完的 MP3。
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=self.directory,
                prefix=".tts-", suffix=".tmp", delete=False) as file:
                temporary = file.name
                file.write(audio_bytes)
            os.replace(temporary, self.filepath)
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    # 清理失败不能覆盖写入或替换异常；临时文件不会参与缓存命中。
                    pass


def prune_cache(cache_dir, max_files, *, logger):
    """按修改时间淘汰最旧 MP3；读取缓存不更新文件时间。"""
    try:
        if not os.path.exists(cache_dir):
            return

        files = []
        for filename in os.listdir(cache_dir):
            if filename.endswith(".mp3"):
                path = os.path.join(cache_dir, filename)
                try:
                    files.append((path, os.path.getmtime(path)))
                except OSError:
                    continue

        if len(files) <= max_files:
            return

        log_event(logger, logging.INFO, "tts_cache_prune_started", count=len(files), max_files=max_files)
        files.sort(key=lambda item: item[1])
        files_to_delete = files[:len(files) - max_files]
        deleted_count = 0
        for path, _ in files_to_delete:
            try:
                os.remove(path)
                deleted_count += 1
            except OSError as exc:
                log_event(logger, logging.WARNING, "tts_cache_delete_failed", error_type=type(exc).__name__)

        log_event(logger, logging.INFO, "tts_cache_prune_completed", count=deleted_count)
    except Exception as exc:
        log_event(logger, logging.ERROR, "tts_cache_prune_failed", error_type=type(exc).__name__)
