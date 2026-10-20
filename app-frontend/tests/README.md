# 前端回归检查

在 `app-frontend/` 中执行：

```bash
npm test
npm run type-check
```

测试使用 Node.js 内置测试器和项目已有的 TypeScript 转译器，不新增测试框架依赖，也不会连接真实后端。

- `stream.test.cjs`：跨字节 UTF-8、SSE 帧边界、错误与截断响应、H5 取消、小程序分块与整包接收、取消请求及禁止重复 POST。
- `entry-case.test.cjs`：入口文件与导入的精确大小写。
- `helpers/load-ts.cjs`：内存加载实际 TypeScript 源码，以替身注入网络和平台接口。Store 使用实际 Vue/Pinia；测试加载器只筛选本次涉及的条件编译块。

这些测试不模拟完整的 uni-app 编译器或手机运行环境。修改跨端网络逻辑后，还需要执行：

```bash
npm run build:h5
npx --no-install uni build -p app-plus
npm run build:mp-weixin
```

App 的 renderjs 桥仍通过浏览器 XHR 接收字符文本；本次共享的字节解码器用于 H5 和 uni 请求任务。真机上的分块回调、页面退出和网络中断仍需按目标平台验收。
