# 前端回归检查

在 `app-frontend/` 中执行：

```bash
npm test
npm run type-check
```

测试使用 Node.js 内置测试器和项目已有的 TypeScript 转译器，不新增测试框架依赖，也不会连接真实后端。

- `character-card.test.cjs`：导入关闭/换卡后的旧响应隔离、字段替换与空项补充、第三方扩展保留、开场原始索引及三端文件选择。
- `character-translation.test.cjs`：中英文阅读切换、原卡及隐藏 Prompt 隔离、手动翻译、缓存与生成竞态、换卡失效、失败保留译文和在线 API / 离线 Mock 边界。

- `stream.test.cjs`：跨字节 UTF-8、SSE 帧边界、错误与截断响应、H5 取消、小程序分块与整包接收、取消请求及禁止重复 POST。
- `app-stream.test.cjs`：App XHR 分块与收尾、HTTP/协议/网络错误、取消与旧连接回调隔离、桥接实例隔离，以及逻辑层同步失效和终态去重。
- `entry-case.test.cjs`：入口文件与导入的精确大小写。
- `session-lifecycle.test.cjs`：历史请求乱序、分页失效、切换会话后的旧回调，以及人物详情的异步隔离。
- `session-api.test.cjs`：领域拆分后的请求方法、路径、参数与兼容导出；完整会话分页、错误传递，以及离线分支继承、消息候选和记忆筛选/修改。
- `helpers/load-ts.cjs`：内存加载实际 TypeScript 源码，以替身注入网络和平台接口。Store 使用实际 Vue/Pinia；测试加载器只筛选本次涉及的条件编译块。

这些测试不模拟完整的 uni-app 编译器或手机运行环境。修改跨端网络逻辑后，还需要执行：

```bash
npm run build:h5
npx --no-install uni build -p app-plus
npm run build:mp-weixin
```

三个平台共用 `utils/chatStreamProtocol.ts` 解析 SSE 消息和终态。App 的 `ChatStreamBridge.vue` 通过 renderjs/XHR 接收字符文本，由 `ownerInstance.callMethod` 回传逻辑层；字节解码器用于 H5 和 uni 请求任务。真机上的分块回调、页面退出和网络中断仍需按目标平台验收。
