import os
import sys
import unittest
import yaml

# 将当前目录的父目录加入 python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import Settings, CONFIG_SCHEMA

class TestConfigSystem(unittest.TestCase):
    def setUp(self):
        self.test_yaml_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "test_config_temp.yaml")
        # Ensure clean state
        if os.path.exists(self.test_yaml_path):
            os.remove(self.test_yaml_path)

    def tearDown(self):
        if os.path.exists(self.test_yaml_path):
            os.remove(self.test_yaml_path)

    def test_auto_merge_missing_keys(self):
        # 1. 创建一个缺少部分字段的旧版 yaml 配置
        incomplete_config = {
            "llm": {
                "chat_model": "gpt-custom-model",
                "temperature": 0.5
                # 缺少 max_tokens, reasoning_mode 等
            },
            "app": {
                "context_history_limit": 5
                # 缺少 sqlite_db_path 等
            }
        }
        
        with open(self.test_yaml_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(incomplete_config, f)

        # 2. 模拟使用自定义测试配置初始化 Settings
        settings = Settings()
        # 覆写加载与保存路径
        settings._load_yaml_config = lambda filepath=None: yaml.safe_load(open(self.test_yaml_path, "r", encoding="utf-8")) or {}
        
        def save_mock(filepath=None):
            with open(self.test_yaml_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(settings.config, f, allow_unicode=True, sort_keys=False)
        settings._save_yaml_config = save_mock
        
        # 3. 重新加载并触发 migrate_and_bind_config
        settings.config = settings._load_yaml_config()
        settings.migrate_and_bind_config()

        # 4. 验证缺失字段是否已被 Schema 默认值补齐
        self.assertEqual(settings.CHAT_MODEL_REASONING, "gpt-custom-model")  # 保留原有
        self.assertEqual(settings.LLM_TEMPERATURE, 0.5)  # 保留原有
        self.assertEqual(settings.LLM_MAX_TOKENS, 4096)  # 补全默认值
        self.assertEqual(settings.LLM_REASONING_MODE, False)  # 补全默认值
        
        # 5. 验证是否已将更新回写持久化到文件
        with open(self.test_yaml_path, "r", encoding="utf-8") as f:
            saved_data = yaml.safe_load(f)
        
        self.assertIn("max_tokens", saved_data["llm"])
        self.assertEqual(saved_data["llm"]["max_tokens"], 4096)
        self.assertIn("sqlite_db_path", saved_data["app"])

    def test_update_and_persist(self):
        # 1. 写入最小配置
        initial_config = {
            "llm": {"temperature": 0.7},
            "app": {"context_history_limit": 10}
        }
        with open(self.test_yaml_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(initial_config, f)

        # 2. 初始化 Settings 并绑定 Mock 存储
        settings = Settings()
        settings._load_yaml_config = lambda filepath=None: yaml.safe_load(open(self.test_yaml_path, "r", encoding="utf-8")) or {}
        def save_mock(filepath=None):
            with open(self.test_yaml_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(settings.config, f, allow_unicode=True, sort_keys=False)
        settings._save_yaml_config = save_mock

        settings.config = settings._load_yaml_config()
        settings.migrate_and_bind_config()

        # 3. 执行动态热更新
        updates = {
            "temperature": 0.95,
            "context_history_limit": "25",  # 测试字符串形式的 int 是否强转成功
            "reasoning_mode": True,
            "chat_model": "hacky-model",  # chat_model is dynamic=False, 应该被忽略
            "reasoning_effort": "none"    # 测试空值字符串归一化为 None
        }
        settings.update_and_persist(updates)

        # 4. 验证内存属性已更新且强转类型成功
        self.assertEqual(settings.LLM_TEMPERATURE, 0.95)
        self.assertEqual(settings.APP_CONTEXT_HISTORY_LIMIT, 25)
        self.assertEqual(settings.LLM_REASONING_MODE, True)
        self.assertEqual(settings.CHAT_MODEL_REASONING, "gpt-3.5-turbo")  # chat_model is not dynamic, kept default/original
        self.assertIsNone(settings.LLM_REASONING_EFFORT)  # "none" 应该被成功归一化为 None

        # 5. 验证是否持久化写回文件
        with open(self.test_yaml_path, "r", encoding="utf-8") as f:
            saved_data = yaml.safe_load(f)
        self.assertEqual(saved_data["llm"]["temperature"], 0.95)
        self.assertEqual(saved_data["app"]["context_history_limit"], 25)
        self.assertEqual(saved_data["llm"]["reasoning_mode"], True)
        self.assertIsNone(saved_data["llm"]["reasoning_effort"])

if __name__ == "__main__":
    unittest.main()
