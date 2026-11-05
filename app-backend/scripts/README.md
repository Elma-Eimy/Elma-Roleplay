# 后端维护工具

在 `app-backend/` 目录、已安装依赖的 Python 环境中使用模块命令：

| 命令 | 用途 |
| --- | --- |
| `python -m scripts.query_db` | 查看当前配置的 SQLite 和 ChromaDB 数据概览 |
| `python -m scripts.export_character_card <PNG路径> <输出文件夹>` | 无损导出 PNG 内每个有效 chara JSON，不连接数据库、不覆盖已有输出 |
| `python -m scripts.memory_quality` | 在临时副本中运行固定虚构记忆样本，生成整理前后与召回对照报告；默认离线 |
| `python -m scripts.group_chat_prototype` | 在临时源码和虚构库中回放导演选人、个人生成、知情后判与只读 HTTP，默认离线 |
| `python -m scripts.query_session_messages 12 15` | 查看会话 12 的最近 15 条消息 |
| `python -m scripts.clear_db` | 清空当前配置的 SQLite/ChromaDB 数据，并用 Alembic 重建 SQLite |

查询工具会读取实际消息和角色内容。清库工具保留原有终端确认步骤；它会永久删除数据，执行前应停止服务并备份。上述查询/清库工具使用当前 `core.config` 和 `core.database`。

`memory_quality` 是独立隔离入口，不读取开发配置和数据库。默认固定响应回放不评价模型质量；仅 `--online` 加显式模型、地址和环境变量密钥才会发送样本。报告默认写入 Git 忽略的 `docs/local/memory-quality/`。用法与样本格式见 [记忆整理质量验收](../../docs/testing/MEMORY_QUALITY.md)。

查询与清库命令只在显式执行时运行，不由 HTTP 服务启动过程或自动测试调用。隔离验收入口可以由离线回归调用。

## 群聊导演原型

在后端目录运行 `python -m scripts.group_chat_prototype`，默认执行 8 个固定虚构场景。可用 `--case private-retelling-aba` 选择场景，`--case` 可重复；`--output <目录>` 指定报告父目录，每次创建独立子目录。默认结果位于 Git 忽略的 `docs/local/group-chat-prototype/`，临时源码、数据库和媒体目录在结束后清理，不复制 `.env`、开发配置或数据。

`report.json` 记录实际发送的导演/角色 messages、调用次数、成员 ID、只读 rounds 响应和自动检查。报告只含虚构样本；`mode=offline` 是固定响应回放，`semantic_review=pending` 表示未进行真实语义验收。混合内容场景的 `granularity_review=requires_split...` 是已知的公开信息损失，自动检查通过不表示全文粒度适合正式产品。

真实模型模式必须显式使用 `--online --base-url <兼容API地址> --model <模型ID>`，密钥通过 `GROUP_PROTOTYPE_API_KEY` 或 `--api-key-env <变量名>` 指定，不接受密钥正文。它会发送选定虚构场景并产生费用，只有明确授权时执行；不会读取开发连接配置。在线原型与 M3-B 内部服务使用同一轮次专用客户端，关闭自动重试，角色与导演使用同一模型；服务冻结调用参数并管理任务执行权。在线场景的正向自然表述需人工审阅，不要求命中预录台词标记。

当前原型在独占临时库内复用 group_round_service 的整轮执行权、参数快照与预算，以及 M2 的上下文、输出解析和原子写入；内部任务已登记到运行权拥有者，应用关闭会等待清理。它不提供普通生成 API、持久导演审计、细分可见单元、候选确认或恢复。自动回归会调用离线启动器验证隔离与报告，不会执行在线模式。设计与限制见 [M3 记录](../../docs/plans/group-chat/M3_DIRECTOR.md)。

原型最终候选终态提交若已明确成功，即使等待期间收到取消也返回已完成结果，保持调用结果与数据库一致；最终提交失败时仍传播取消并保留失败前缀。导演输入预算包含阶段字段与待判正文，先省略旧历史，当前前缀和待判正文超限时才失败。

最终个人输入诊断读取失败时，report.json 单独记录 diagnostic_error_code、清空不完整 personal_inputs，并将 input_collection 检查标为未通过；候选仍依据实际执行结果结束。程序在每次模型返回后复核单次绝对期限，已触发超时的迟到结果按失败处理，等待清理结束后停止推进。
