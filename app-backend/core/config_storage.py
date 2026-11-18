"""配置 YAML 的读取和原子保存；仅在调用函数时访问文件。"""

import os
from pathlib import Path
import tempfile

import yaml


def read_yaml_config(filepath):
    path = Path(filepath)
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = yaml.safe_load(handle)
    except FileNotFoundError:
        return {}
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("配置文件根节点必须是对象。")
    return value


def write_yaml_config(filepath, config):
    path = Path(filepath)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
            prefix=path.name + ".", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            yaml.safe_dump(config, handle, allow_unicode=True, sort_keys=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
