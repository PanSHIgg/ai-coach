/**
 * 第三方 SDK 环境声明（COS 集成）。
 *
 * `cos-wx-sdk-v5` 未随包提供类型声明，且仅在小程序端条件编译引入，这里给出直传所需的
 * 最小声明；H5 端 `cos-js-sdk-v5` 自带 index.d.ts，无需另行声明。
 */
declare module 'cos-wx-sdk-v5' {
  interface CosOptions {
    getAuthorization: (options: unknown, callback: (data: unknown) => void) => void;
  }

  class COS {
    constructor(options: CosOptions);
    putObject(
      params: Record<string, unknown>,
      callback: (err: Error | null, data: Record<string, unknown>) => void,
    ): void;
  }

  export = COS;
}