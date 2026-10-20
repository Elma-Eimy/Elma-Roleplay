export function chooseCharacterCard(): Promise<{
  path: string;
  name: string;
} | null> {
  return new Promise((resolve, reject) => {
    const fail = (error: { errMsg?: string }) =>
      /cancel/i.test(error.errMsg || "")
        ? resolve(null)
        : reject(new Error("无法选择文件，请检查文件访问权限。"));
    // #ifdef APP-PLUS
    uni.chooseImage({
      count: 1,
      sizeType: ["original"],
      sourceType: ["album"],
      success: (result) => {
        const path = result.tempFilePaths[0];
        resolve({ path, name: path.split("/").pop() || "角色卡.png" });
      },
      fail,
    });
    // #endif
    // #ifdef MP-WEIXIN
    uni.chooseMessageFile({
      count: 1,
      type: "file",
      extension: ["png", "json"],
      success: (result) => {
        const file = result.tempFiles[0];
        resolve({ path: file.path, name: file.name });
      },
      fail,
    });
    // #endif
    // #ifndef APP-PLUS || MP-WEIXIN
    uni.chooseFile({
      count: 1,
      type: "all",
      extension: [".png", ".json"],
      success: (result) => {
        const path = result.tempFilePaths[0];
        const file = (result.tempFiles as { name?: string }[] | undefined)?.[0];
        resolve({
          path,
          name: file?.name || path.split("/").pop() || "角色卡",
        });
      },
      fail,
    });
    // #endif
  });
}
