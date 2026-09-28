/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 后端 API 基地址（Mock Server 默认 http://localhost:9000） */
  readonly VITE_API_BASE: string
  /** 是否 Mock 态（true：开发态 mock 登录） */
  readonly VITE_USE_MOCK: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
