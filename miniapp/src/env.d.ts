/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * 后端 API 基址，由 .env.[mode] 注入（开发 http://localhost = 本机 nginx 反代 /api）。
   * H5 生产可显式留空走同源反代；小程序端必须绝对 URL（见 api/request.ts 的启动断言）。
   */
  readonly VITE_API_BASE: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
