"""进程配置兼容入口；读取环境与 YAML，不在导入时保存配置。"""

import os
import yaml
from dotenv import load_dotenv

from core.config_schema import CONFIG_SCHEMA
from core.config_settings import Settings

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
load_dotenv(os.path.join(parent_dir, ".env"))

settings = Settings()
