# 角色卡导入与参考规范

## 社区规范

- [Character Card V2 原始规范](https://github.com/malfoyslastname/character-card-spec-v2/blob/main/spec_v2.md)：V2 使用 `spec`、`spec_version` 与 `data` 封装，包含备用开场白、作者信息、扩展和可选世界书。第三方扩展应保留。
- [Character Card V3 原始规范](https://github.com/kwaroran/character-card-spec-v3/blob/main/SPEC_V3.md)：PNG/APNG 的 V3 数据使用 `ccv3` 文本块；同时存在 `ccv3` 与 `chara` 时，V3 实现应优先采用 `ccv3`。

本项目目前支持 PNG 的 `chara` 元数据与 V1/V2 风格 JSON。读取 `tEXt`、`zTXt`、`iTXt`，兼容 Base64 JSON 与原始 JSON 文本。尚未完整支持 CCv3、CHARX 及其资源、昵称和群聊开场白语义，不应把读取部分共有字段视为完整 V3 支持。

## 导入与持久化

1. `/characters/parse` 在临时目录校验、解析 PNG 或 JSON，不创建角色记录。
2. 有效 PNG 使用完整文件 SHA-256 命名并复用头像；失败文件和 JSON 不写入头像目录。调用方应复用返回的 `avatar_path`。
3. 作者、角色版本及来源格式写入 `extensions.ai_roleplay_card`；备用开场和内嵌世界书沿用现有扩展字段持久化，无需数据库迁移。
4. 创建接口用 `created: true/false` 区分新角色和同名已有角色；同名请求返回已有 ID，不覆盖设定，调用方应提示用户决定后续操作。

成功解析但未保存的 PNG 仍可能成为未引用资源，本次不增加自动清理此类文件的策略。

同一 PNG 的多个有效 `chara` 块按文件顺序保留；产品导入沿用首个有效块，后续副本不覆盖它。此选择是项目兼容策略，并非社区规范定义的重复块优先级。不要拼接不同块的字段，以免混用不同角色版本。

解析会校验角色对象、非空名称和字符串数组，支持带 UTF-8 BOM 的 JSON。归一化在副本上执行，不修改原始对象。展示字段仍沿用 HTML 转 Markdown；Prompt、示例和世界书正文保持现有 DSL 处理规则。归一化响应并非原始卡的无损备份。

## 无损 JSON 导出

在 `app-backend/` 执行：

```powershell
.\venv\Scripts\python.exe -m scripts.export_character_card <原始PNG路径> <输出文件夹>
```

命令不连接数据库，为每个有效 `chara` 块生成独立的 `.chara-1.json`、`.chara-2.json` 等文件，不清洗字段或覆盖已有输出。它保存 JSON 数据的原始结构和值，不保留 JSON 空白排版或 PNG 二进制块。

本次用户提供的本地参考卡有两份有效 `chara` 数据；第一份含内嵌世界书，第二份不含。两份均包含 39 条备用开场白和较长的作者说明。原卡、导出 JSON 及资源清理备份仅保留在本地，不作为自动测试夹具提交。

## 历史重复资源清理

仅按完整文件 SHA-256 判定相同内容，不按文件名或视觉相似度删除。保留当前 SQLite 文本字段中引用的文件及用户指定的参考原图；删除前逐个备份并校验副本，清单保存在 `docs/local/avatar-cleanup-2026-10-20/manifest.json`。本次未修改角色记录或会话数据，也未删除无重复副本的其他文件。
