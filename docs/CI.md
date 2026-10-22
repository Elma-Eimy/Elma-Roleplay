# 持续集成

工作流定义位于 [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)。首版使用 GitHub 托管的 Ubuntu 24.04，运行两个独立任务；任一检查失败时，该任务失败。

## 触发方式

- PR 创建、更新或重新打开时执行，检查待合并代码。
- 推送到 `main` 时执行，检查主分支。
- 工作流进入默认分支后，可在 GitHub 的 **Actions → CI → Run workflow** 手动选择分支执行。
- 同一事件下，同一 PR 或分支的新运行会取消尚未结束的旧运行。两个任务各限时 20 分钟。

首版不按文件路径跳过检查，纯文档 PR 也会运行，保持检查结果一致。

## 检查内容

| 任务 | 环境 | 执行命令 |
| --- | --- | --- |
| Backend tests | Python 3.12 | 在 `app-backend/` 执行 `python -m pip install -r requirements.txt`、`python -m tests` |
| Frontend tests and H5 build | Node.js 24 | 在 `app-frontend/` 执行 `npm ci --no-audit --no-fund`、`npm test`、`npm run type-check`、`npm run build:h5` |

pip 与 npm 下载缓存分别按依赖清单更新；每次仍安装依赖，npm 使用已提交的 `package-lock.json`。缓存不包含数据库、音频或构建产物。

后端沿用[隔离测试入口](../app-backend/tests/README.md)，在临时工作区生成测试配置和占位凭据，迁移临时 SQLite 数据库并运行自动回归；不运行 `tests/manual/` 中的脚本。前端使用[离线测试](../app-frontend/tests/README.md)，构建使用仓库默认配置，不复制本地 `.env.production`。

CI 无需配置模型或部署 Secrets，不调用真实模型或 TTS 服务。工作流只申请 `contents: read` 权限。首版不发布构建、不部署应用，也不执行 App Plus 或微信小程序构建；涉及跨端行为时，仍按项目协作约定补充对应构建和真机验收。

## 失败排查

在 PR 的 Checks 或仓库 Actions 页面展开失败步骤，先区分依赖下载、测试、类型检查和构建错误，再使用表中相同命令复现。Windows 未激活后端虚拟环境时，用 `.\venv\Scripts\python.exe` 替换 `python`。

Linux 文件路径区分大小写，导入必须与文件名一致。依赖安装失败时，检查包源访问和锁文件同步；当前 npm 锁文件保留已有镜像地址，`npm ci` 会按锁文件下载。不要用跳过失败检查代替修复。

工作流文件不会自动启用分支保护。若后续需要合并前强制通过 CI，可在仓库规则中将上述两个检查配置为必需检查。
