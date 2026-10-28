# API 阅读与维护

[HTTP API 总表](../../API_TABLE.md) 是统一导航与路由清单，具体契约按领域维护，每项行为只保留一份正文。

| 领域 | 请求、响应与兼容规则 |
| --- | --- |
| 通用、配置与音频 | [GENERAL.md](GENERAL.md) |
| 角色、翻译、CHARX 与立绘 | [CHARACTERS.md](CHARACTERS.md) |
| 会话、分支、消息、状态与记忆 | [SESSIONS.md](SESSIONS.md) |
| 世界书、词条与角色绑定 | [LOREBOOKS.md](LOREBOOKS.md) |
| 聊天、SSE 与候选切换 | [CHAT.md](CHAT.md) |
| 记忆筛选、继承与整理的补充规则 | [MEMORY_API.md](MEMORY_API.md) |

接入功能时先从总表选择领域，再对照后端路由、`schemas.py` 与前端领域 API 和类型。运行中的 `/docs`、`/openapi.json` 提供框架声明的信息；未声明响应模型的接口、SSE、分叉与事务规则需查领域契约及测试，不能只靠 OpenAPI 推断。

## 自动校验范围

在 `app-backend/` 使用已有虚拟环境执行：

```powershell
.\venv\Scripts\python.exe -m tests --group api --pattern test_api_documentation.py
```

已激活环境时可以使用 `python`。该检查包含在完整后端回归和现有 Backend tests CI 中，不增加真实服务调用。

检查在临时源码副本中创建应用，比较总表中的方法和路径是否完整、重复或多余。每个 JSON 请求接口必须至少绑定一个文档示例；示例经真实请求模型验证必填项、类型和模型约束，并额外检查常见嵌套模型中的未知字段，避免默认忽略额外字段掩盖拼写错误。创建应用不会进入 lifespan，不执行接口业务或调用模型。

这项校验不覆盖查询参数说明、未出现在样本中的可选字段和默认值，也不证明动态响应、错误码、数据库约束或 SSE 顺序正确。示例中的资源 ID 和版本号仅用于结构验证，不代表请求在某个真实故事中一定成功。相应语义仍由领域测试和人工审阅负责。

## 请求示例写法

成功请求示例必须是合法 JSON，不使用注释、尾随逗号或省略号。示例前添加路由标记；相同请求结构可以关联多个接口，用分号分隔。

````markdown
<!-- request-example: POST /chat; POST /chat/stream -->
```json
{"session_id": 1, "user_message": "你好"}
```
````

标记后紧接 JSON 围栏，解释文字写在标记之前或围栏之后。只有标记的请求样本参与模型校验；响应示例和内部模型输出协议不能加该标记。一个接口可以保留多个有效样本，以覆盖关键可选字段或不同操作；非法请求的测试留在测试代码中。

修改接口时同时更新根总表、领域详情和前端调用方。新增 JSON 请求接口必须补充标记样本；新增领域文档时同步维护 `scripts/api_documentation.py` 的固定清单，测试入口只复制总表和清单中的文档，不复制 `docs/local/`。修改测试隔离复制范围后运行完整后端回归。

本地链接与精确大小写由根目录 `python tools/check_docs.py` 单独检查。接口校验不扫描开发配置、不连接开发数据库，也不会通过重复发送聊天请求检查 SSE。
