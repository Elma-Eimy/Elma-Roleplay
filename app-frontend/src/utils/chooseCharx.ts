export interface CharxFile { path: string; name: string; size?: number }
export const MAX_CHARX_BYTES = 20 * 1024 * 1024;

export function chooseCharx(): Promise<CharxFile | null> {
  return new Promise((resolve, reject) => {
    const accept = (file: CharxFile) => {
      if (!/\.(charx|zip)$/i.test(file.name)) { reject(new Error("请选择 .charx 或符合角色包结构的 .zip 文件")); return; }
      if (file.size !== undefined && file.size > MAX_CHARX_BYTES) { reject(new Error("角色包超过 20 MB，请选择较小的包")); return; }
      resolve(file);
    };
    const fail = (error: { errMsg?: string }) => /cancel/i.test(error.errMsg || "") ? resolve(null) : reject(new Error("无法选择文件，请检查文件权限"));
    // #ifdef APP-PLUS
    if (typeof uni !== "undefined" && typeof uni.chooseFile === "function") {
      uni.chooseFile({ count: 1, type: "all", extension: [".charx", ".zip"],
        success: result => {
          const file = (result.tempFiles as { name?: string; size?: number }[] | undefined)?.[0];
          const path = result.tempFilePaths[0];
          if (path) accept({ path, name: file?.name || path.split("/").pop() || "", size: file?.size }); else resolve(null);
        }, fail });
    } else {
      reject(new Error("App 首版暂不支持角色包文件选择。请在 H5 网页导入，之后可在 App 使用角色和立绘。"));
    }
    // #endif
    // #ifdef MP-WEIXIN
    uni.chooseMessageFile({ count: 1, type: "file", extension: ["charx", "zip"],
      success: result => { const file = result.tempFiles[0]; if (file) accept({ path: file.path, name: file.name, size: file.size }); else resolve(null); }, fail });
    // #endif
    // #ifndef APP-PLUS || MP-WEIXIN
    uni.chooseFile({ count: 1, type: "all", extension: [".charx", ".zip"],
      success: result => {
        const file = (result.tempFiles as { name?: string; size?: number }[] | undefined)?.[0];
        const path = result.tempFilePaths[0];
        if (path) accept({ path, name: file?.name || path.split("/").pop() || "", size: file?.size }); else resolve(null);
      }, fail });
    // #endif
  });
}
