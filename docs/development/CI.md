# 持续集成

工作流定义位于 [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml)。使用 GitHub 托管的 Ubuntu 24.04，分别运行文档、后端与前端任务；任一检查失败时，该任务失败。

## 触发方式

- PR 创建、更新或重新打开时执行，检查待合并代码。
- 推送到 `main` 时执行，检查主分支。
- 工作流进入默认分支后，可在 GitHub 的 **Actions → CI → Run workflow** 手动选择分支执行。
- 同一事件下，同一 PR 或分支的新运行会取消尚未结束的旧运行。文档任务限时 5 分钟，后端和前端任务各限时 20 分钟。

首版不按文件路径跳过检查，纯文档 PR 也会运行，保持检查结果一致。

## 检查内容

| 任务 | 环境 | 执行命令 |
| --- | --- | --- |
| Documentation links | Python 3.12，无需安装依赖 | 在仓库根目录执行 `python -m unittest discover -s tools/tests`、`python tools/check_docs.py` |
| Backend tests | Python 3.12 | 在 `app-backend/` 执行 `python -m pip install -r requirements.txt`、`python -m tests` |
| Frontend tests and H5 build | Node.js 24 | 在 `app-frontend/` 执行 `npm ci --no-audit --no-fund`、`npm test`、`npm run type-check`、`npm run build:h5` |

pip 与 npm 下载缓存分别按依赖清单更新；每次仍安装依赖，npm 使用已提交的 `package-lock.json`。缓存不包含数据库、音频或构建产物。

后端沿用[隔离测试入口](../../app-backend/tests/README.md)，在临时工作区生成测试配置和占位凭据，迁移临时 SQLite 数据库并运行自动回归；不运行 `tests/manual/` 中的脚本。前端使用[离线测试](../../app-frontend/tests/README.md)，构建使用仓库默认配置，不复制本地 `.env.production`。

CI 无需配置模型或部署 Secrets，不调用真实模型或 TTS 服务。工作流只申请 `contents: read` 权限。首版不发布构建、不部署应用，也不执行 App Plus 或微信小程序构建；涉及跨端行为时，仍按项目协作约定补充对应构建和真机验收。

## 文档链接检查

[检查脚本](../../tools/check_docs.py) 使用 Python 标准库和 Git，只读取 `git ls-files` 列出的 Markdown。它检查常见行内链接、图片链接与引用式链接的本地目标，要求文件或目录由 Git 跟踪且大小写准确；本地存在但未跟踪的资料不能使检查通过。

代码围栏、缩进代码块与行内代码中的示例链接不参与检查。检查不访问网络，不加载应用配置或数据库；不检查外链可用性、标题锚点、HTML 链接、文风或日志条数，也不替代业务内容审阅。脚本只支持常见 Markdown 链接写法，不作为完整 Markdown 解析器。

在仓库根目录运行 `python tools/check_docs.py`。新增文档及其目标需先由 Git 跟踪，才能纳入检查；结果与干净克隆保持一致。工具自身的临时仓库回归通过 `python -m unittest discover -s tools/tests` 执行，不依赖后端虚拟环境或模型凭据。

## 失败排查

在 PR 的 Checks 或仓库 Actions 页面展开失败步骤，先区分依赖下载、测试、类型检查和构建错误，再使用表中相同命令复现。Windows 未激活后端虚拟环境时，用 `.\venv\Scripts\python.exe` 替换 `python`。

Linux 文件路径区分大小写，导入必须与文件名一致。依赖安装失败时，检查包源访问和锁文件同步；当前 npm 锁文件保留已有镜像地址，`npm ci` 会按锁文件下载。不要用跳过失败检查代替修复。

工作流文件不会自动启用分支保护。若后续需要合并前强制通过 CI，可在仓库规则中选择上述检查配置为必需检查。
