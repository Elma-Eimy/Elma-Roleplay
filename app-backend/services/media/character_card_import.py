"""先验证角色卡，再保留可复用的 PNG 头像；JSON 与失败文件不留在资源目录。"""

import hashlib
from pathlib import Path
import tempfile

from services.parse import parse_character_card


def import_character_card(content: bytes, extension: str, upload_dir: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="character-card-") as temporary:
        source = Path(temporary) / ("card" + extension)
        source.write_bytes(content)
        data = parse_character_card(str(source))

    data["avatar_path"] = ""
    if extension == ".png":
        root = Path(upload_dir)
        root.mkdir(parents=True, exist_ok=True)
        target = root / ("card_" + hashlib.sha256(content).hexdigest() + ".png")
        # 同一内容重复解析复用文件；exclusive create 避免并发覆盖。
        try:
            with target.open("xb") as destination:
                destination.write(content)
        except FileExistsError:
            if target.read_bytes() != content:
                raise ValueError("已有头像内容不匹配，请检查资源文件。")
        data["avatar_path"] = str(target).replace("\\", "/")
    return data
