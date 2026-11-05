# 群聊 M3 联通验收与交接

[文档导航](../README.md) · [M3 设计与记录](../plans/group-chat/M3_DIRECTOR.md) · [群聊接口](../api/GROUP_SESSIONS.md)

M3 的内部执行、可见单元和只读展示已接通。以下入口只使用虚构临时数据，不开放正式发送、确认、候选切换或失败恢复。离线程序检查、H5 浏览器检查、真实模型质量和真机验收分别记录。

## 重现只读预览

先在 `app-frontend/` 用 PowerShell 构建专用 H5：

```powershell
$env:VITE_GROUP_PREVIEW = 'true'
npm run build:h5 -- --base=/preview/
Remove-Item Env:VITE_GROUP_PREVIEW
```

然后在 `app-backend/` 执行：

```powershell
.\venv\Scripts\python.exe -m scripts.group_chat_prototype --serve --frontend-dist ..\app-frontend\dist\build\h5
```

回放完成后打开 `http://127.0.0.1:8767/`，选择场景进入现有群聊详情页。默认运行 9 个离线场景，包含一个预期失败场景；已保存前缀、成员身份、状态与停止提示应与报告一致。`--case` 可重复指定；例如只检查失败前缀：`--case failed-prefix`。

预览固定监听本机，默认最多 600 秒，`--port` 可更换端口，`--preview-seconds` 可设为 1–3600 秒。预览进程结束后临时源码、SQLite 与 H5 副本清理，报告保留在启动器输出目录；可用 `--output` 更换报告父目录。退出后页面不会继续取得数据，需要重新启动预览。

专用 H5 忽略已保存的服务器地址和访问密钥，固定请求当前页面来源，发送写请求前即报只读错误。启动器拒绝没有预览标记的普通 H5 构建，防止误连原服务器；恢复普通 H5 时不设置该环境变量，重新执行常规构建。预览后端仅开放群聊 GET、静态资源与预览首页，数据库以 mode=ro/query_only 打开，不运行应用 lifespan、迁移或后台 Worker。现有页面的删除按钮在此预览中不能删除数据。

## 检查内容

| 场景 | 自动检查 | 页面检查 |
| --- | --- | --- |
| private-retelling-aba | A→B→A；B 的完整调用输入不含原始秘密 | 三条发言顺序与成员编号正确，正常结束提示可见 |
| silent-listener / third-member-absent | 旁听依据保留；缺席成员不取得秘密 | 没有强制人人发言，成员与实际发言分别展示 |
| same-name-forged-label | 作者取服务端 Persona ID，正文伪造标签不改身份 | 两个“无名”仍以成员编号区分 |
| mixed-private-thought | 公开线索保留，B 输入不含私密心理 | 操作者仍能读完整正文；此页面不是 B 的个人视角 |
| no-visible-basis / director-immediate-end | 零角色调用，有正常终态 | 有用户项与结束原因，没有虚构角色发言 |
| hard-step-limit / failed-prefix | 上限停止；第二次角色生成无效时保留第一条发言 | 停止原因与失败提示不同，失败内容不出现，已保存正文仍可读 |

`report.json` 的 checks 是程序断言；故障注入的 invalid_output 是预期结果，expected_outcome 通过才算此场景成功。失败场景不伪造最终个人输入诊断。报告的 candidate_state 和 director_steps 供内部核对，普通 rounds API 不暴露审计 JSON 或模型 reasoning。

2026-11-05 已在 H5 浏览器中核对 A→B→A、同名成员、失败前缀、步数停止和零发言；补充专用构建保护后再次检查失败前缀与刷新。程序回放不评价语言自然度，H5 检查也不替代 App/微信真机。构建产物仅用于本机预览，没有部署。

## 独立验收仍待补齐

| 证据 | 状态 | 通过条件 |
| --- | --- | --- |
| 离线程序与 H5 联通 | 已验证 | 严格协议、过滤、顺序、终态与失败前缀一致 |
| 真实模型语义 | 待授权后验证 | 至少覆盖私聊、旁听、冲突、公开转述、同名和混合内容；逐例审阅知情与单元分类，定位任何泄漏 |
| App Plus 真机 | 待验证 | 身份、长文阅读、刷新、切服及失败前缀可用 |
| 微信真机 | 待验证 | 同上，并核对网络配置及安全区 |

在线模式沿用启动器显式 `--online`、独立地址/模型和进程外密钥，不读取开发配置。授权需明确测试模型、场景与费用边界；当前 M3-D 实现及离线执行不代表已经授权或通过在线验收。故障注入场景只供离线，默认在线样本仍为 8 个。

## 给后续模块的交接

M4 应沿用 Round/Candidate ID 与 revision，读取已保存前缀和 finish_reason/error_code，不建立另一套轮次身份。整轮失败只返回本次实际提交或最后接受的版本，发生外部版本竞争时不冒认对方版本；只读 API 则返回数据库当前候选版本。仍只允许一个未确认轮次，失败不能通过新建下一轮绕过恢复。

v1 全文与 v2 单元由候选 protocol_version 区分。M4 切换候选必须同时保持单元、知情和父发言状态归属；M5 检索/提纯应复用个人可见单元，不能拿操作者 rounds 全文或导演全局快照作为成员输入。父项状态每次角色调用只应用一次。M3 没有接入继承记忆检索、持续提纯或完整成长面板。
