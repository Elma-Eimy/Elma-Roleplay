# 后端维护工具

在 `app-backend/` 目录、已安装依赖的 Python 环境中使用模块命令：

| 命令 | 用途 |
| --- | --- |
| `python -m scripts.query_db` | 查看当前配置的 SQLite 和 ChromaDB 数据概览 |
| `python -m scripts.export_character_card <PNG路径> <输出文件夹>` | 无损导出 PNG 内每个有效 chara JSON，不连接数据库、不覆盖已有输出 |
| `python -m scripts.query_session_messages 12 15` | 查看会话 12 的最近 15 条消息 |
| `python -m scripts.clear_db` | 清空当前配置的 SQLite/ChromaDB 数据，并用 Alembic 重建 SQLite |

查询工具会读取实际消息和角色内容。清库工具保留原有终端确认步骤；它会永久删除数据，执行前应停止服务并备份。工具均使用 `core.config` 和 `core.database`，没有独立的配置来源。

这些命令只在显式执行时运行，不由 HTTP 服务启动过程或自动测试调用。
