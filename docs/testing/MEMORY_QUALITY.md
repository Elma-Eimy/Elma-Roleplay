# 记忆整理质量验收

工具使用固定虚构样本调用实际的记忆整理服务，在临时 SQLite 中执行预览、应用、撤销和分支检查，并生成可离线打开的 HTML 对照报告。默认不调用外部模型，不读取开发 `.env`、`config.yaml` 或数据库，不启动 Outbox Worker，不修改正常聊天流程。

## 快速开始

在 `app-backend/` 执行；已激活虚拟环境时可以将下面的解释器替换为 `python`。

```powershell
.\venv\Scripts\python.exe -m scripts.memory_quality
```

每次在 Git 忽略的 `docs/local/memory-quality/<时间-随机编号>/` 新建 `index.html` 和 `report.json`，不覆盖旧结果。默认 12 个场景各运行一次。终端的“自动检查通过”只表示规则检查通过；语义结论全部待人工审阅。离线建议来自样本中的固定响应，不能据此认定模型质量。

混合类型场景沿用生产流程，按记忆类型分别调用，整批最多 12 组。报告的 `generation_calls` 保存每次响应、来源 ID、实际参数与 Prompt 哈希，涵盖纠正重试；单次调用保留原 `raw_response` 格式，多次调用时该字段为所有响应字符串组成的 JSON 数组，`system_prompt_sha256` 为各次哈希序列的汇总哈希。离线回放按分组首张来源路由完整建议，跨类型错误引用仍交给真实服务拒绝，不裁剪分组掩盖错误。

```powershell
# 只检查两个场景，重复两次
.\venv\Scripts\python.exe -m scripts.memory_quality --case station_event --case negation --repeat 2

# 对比旧报告；将路径替换为实际文件
.\venv\Scripts\python.exe -m scripts.memory_quality --repeat 2 --baseline ..\docs\local\memory-quality\<旧目录>\report.json

# 指定报告父目录，每次仍新建运行子目录
.\venv\Scripts\python.exe -m scripts.memory_quality --output ..\docs\local\my-memory-checks
```

退出码：`0` 表示自动检查全部通过；`1` 表示有场景检查或执行失败，但已生成报告；`2` 表示参数、输入或环境有误。未知场景 ID 会报错，不以零场景通过结束。

## 在线模型验收

只有显式使用 `--online` 才调用模型。先在当前进程环境设置 `MEMORY_QUALITY_API_KEY`，或用 `--api-key-env` 指定已经设置的变量名称。工具不从 `.env` 读取密钥，也不接受命令行密钥正文。必须提供模型和兼容 API 地址，地址不能包含凭据、查询参数或片段。

```powershell
.\venv\Scripts\python.exe -m scripts.memory_quality --online --base-url https://example.invalid/v1 --model your-memory-model --case station_event
```

把地址和模型替换为实际值，建议先运行一个场景。在线模式会向该端点发送所选样本并产生服务费用；不要加入未经脱敏的真实对话。线上仍使用临时业务库与固定本地检索基线，不操作生产记忆。

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--adapter` | `auto` | `auto/compatible/deepseek/reasoning`，沿用现有能力适配 |
| `--thinking-mode` | `disabled` | `enabled/disabled`；固定思考模型按现有规则启用思考 |
| `--reasoning-effort` | `high` | `low/medium/high/max`，须与模型能力相容 |
| `--repeat` | `1` | `1–5`；每个场景每次预览至多一次模型调用，SDK 连接失败可能重试 |
| `--cases` | 仓库虚构样本 | 自定义版本化 JSON 文件 |

失败场景记录阶段与异常类型，不保存可能含服务凭据的原始异常。原始模型正文只保存 `content`，不保存思考链。

## 审阅报告

1. 确认运行模式、模型、样本 SHA-256、Git 版本/脏状态和执行源码指纹。场景还记录实际生成参数及 System Prompt 指纹。
2. 对照原卡、整理建议及有效卡，核对主体、否定、时间、地点、因果、承诺与取消条件。
3. 查看固定问题的召回顺序、正文和排序分，不仅看卡数变化。
4. 标记人工通过、遗漏、失真/编造、误合并或其他问题，并填写笔记。
5. 导出审阅 JSON 留档。浏览器会尝试自动保存；本地文件存储受限时仍可导出。可导入同次运行的记录恢复，不允许将上次人工通过结论直接灌入新运行。

自动检查覆盖：预览不改变原卡、单批覆盖全部输入、没有跨越允许分组、来源与原卡保留、父故事应用不影响已有分支、撤销恢复原卡和保留子故事快照。允许组未被合并只提示，不自动判错；保守保留可能是正确选择。

执行源码指纹涵盖整理、可见性、检索、ORM、验收 Worker 和样本规则，不包含报告排版。模型字段记录请求的模型 ID，不能保证服务端别名背后的模型版本不变。

整理服务还会过滤来源发生日期明确冲突的事件组；应用旧预览时也会再次检查。报告的“原始模型正文”可能包含被后端跳过的组，“整理建议”才是实际可应用部分。跳过整组时原卡不丢失，`unmerged_opportunities` 可能增加；这是保守保留，不应为了提高归并率放宽日期边界。预约目标日期不作为本次发生日，未注明/相对日期仍不在该规则的可靠识别范围内。

重复组也会筛去明确否定标记不同的来源，避免“喜欢某种称呼”与“不喜欢另一种称呼”被当作同一事实；筛查没有匹配到冲突不等于证明语义等价。

字面线索只检查同一张卡中是否出现预设词组，不能判断否定、时态、人物归属或因果是否正确，未命中也可能是同义改写。全部线索命中仍不代表语义通过。

尤其要人工核对条件语气：例如“如果加班就改到周六”被改成“因为加班已经改到周六”，即使“加班”“周六”仍全部命中，也属于语义失真。

### 召回与指标的边界

第一版不调用 Embedding，用中文双字词项/英文词余弦基线替代 Chroma 查询，同时调用真实 `retrieve_memories` 执行 SQLite 过滤和精排。固定 `top_k=3`、最低权重 `0`、最大距离 `0.95`；其他实际排序参数记录在报告，样本初始权重统一为 `0.7`。

它能反复检查整理后可供检索的内容及固定基线下的前后差异，**不能证明生产语义向量检索质量改善**。索引替身即时同步临时 SQLite，不检验 Outbox 延迟/重试及真实向量服务；这些仍由现有隔离回归覆盖。

重复运行展示正文/分组变体数与执行失败次数，不判断变体是否语义等价。离线回放稳定也不代表在线模型稳定。

`--baseline` 比较同一场景的自动失败次数、平均有效卡数和平均缺失字面线索数；样本文件、模式、场景范围及检索参数相同才标记为可直接比较。不同重复次数需结合失败比例/完成次数阅读。失败轮次不计入卡数和线索均值，避免把失败当成更好的压缩。上述统计不是语义质量分数。

## 增加样本

跨批提取与事件阶段另有固定虚构对话 [event_retention_cases.json](../../app-backend/tests/fixtures/event_retention_cases.json)，运行 `python -m tests --group memory --pattern test_event_retention.py`。它用预录的新进展响应检查已提取内容在后续批次、阶段保存和重启后的字面事实线索保留，不调用真实模型，也不使用本页的卡片整理输入格式。指标与局限见[事件生命周期](../features/MEMORY_EVENTS.md#日志与验证)。

默认夹具：[memory_quality_cases.json](../../app-backend/tests/fixtures/memory_quality_cases.json)。覆盖重复偏好、事件碎片、否定、计划与已发生、两次生日、关系变化、独立事实、人物归属、精确承诺、情绪上下文、地点变化和混合分组。

格式为 `version=1`，每个文件 1–50 个场景，每个场景 2–100 张卡，保证由当前整理接口单次完整检查。

另有聚焦百张以内碎片整理的 [混合故事夹具](../../app-backend/tests/fixtures/memory_fragment_cases.json)：48 张和 96 张两个场景，每个包含 8 组可归并碎片，交错混入应独立保留的事实、身份、否定和时间变化。猫名重复卡固定放在首尾，覆盖原来 80 张分批会隔开的来源。96 张场景在 48 张基础上增加 48 条独立事实，便于观察干扰增加后的整理表现。

```powershell
# 离线检查夹具与执行链路；不代表模型质量
.\venv\Scripts\python.exe -m scripts.memory_quality --cases tests/fixtures/memory_fragment_cases.json

# 使用真实模型时，另加 --online、--base-url、--model 并设置密钥环境变量
```

审阅这组场景时，优先逐组核对来源完整度，以及时间、人物、金额、物品归属、承诺和取消条件；同时看 `unmerged_opportunities`，避免把“完全不整理”误当作质量优秀。8 组是本夹具的机会数，当前生产协议单次最多建议 12 组；单批覆盖 100 张不等于一次一定完成所有可整理项。

```json
{
  "version": 1,
  "cases": [{
    "id": "book_gift",
    "title": "同一次赠书的互补细节",
    "cards": [
      {"key":"a","type":"event","content":"周日用户送给林墨一本诗集。"},
      {"key":"b","type":"event","content":"周日用户送给林墨的那本诗集是蓝色封面。"}
    ],
    "allowed_groups": [["a","b"]],
    "replay_groups": [{"kind":"event","source_keys":["a","b"],"content":"周日用户送给林墨一本蓝色封面的诗集。","reason":"同一次赠书的互补细节。"}],
    "facts": [{"description":"周日赠送蓝色诗集","anchors":[["周日"],["蓝色"],["诗集"]]}],
    "questions": [{"text":"用户送给林墨的诗集是什么颜色？","fact_indices":[0]}]
  }]
}
```

- `key` 是场景内唯一卡片标识，`type` 为现有四种记忆类型之一。
- `allowed_groups` 是允许合并的来源集合；每条建议必须完全落在其中一组内。空数组表示不允许合并。这些预期不发送给在线模型。
- `replay_groups` 独立维护预录响应，不从评价预期自动生成；在线时不用于代替模型结果。
- `facts.anchors` 外层须同时命中，内层任选同义表达；`questions.fact_indices` 引用从零开始的保真要点。

发现真实问题后，先改写成脱敏虚构场景，补上禁止的误合并与必须保留的细节。不要将真实数据库、头像、音频、密钥或个人配置加入夹具。

## 实现与测试

入口在 `scripts/memory_quality/`：`cli.py` 建立临时源码/配置，`worker.py` 调用实际业务服务，`cases.py` 校验样本，`report.py` 生成无 CDN 的 HTML 和本地审阅交互。不要直接执行内部 Worker；它会校验临时工作区标记并拒绝直接在当前项目运行。

```powershell
.\venv\Scripts\python.exe -m tests --group memory --pattern test_memory_quality_tool.py
```

[回归用例](../../app-backend/tests/memory/test_memory_quality_tool.py) 覆盖重复性、隔离启动、在线凭据替身、错误记录、误合并、保守不合并、HTML 转义与指标边界，不调用真实模型。
