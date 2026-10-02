# miniapp · AI 饮食管控教练用户端（uni-app 小程序）

P0-f 前端脚手架：uni-app Vue3 + Vite + TS + Pinia，**交付目标只有微信小程序（mp-weixin）**。
`build:h5`/`dev:h5` 与源码里的 `#ifdef H5` 分支保留，但**H5 不进部署面**——只作 agent-browser 本地视觉回归通道（口径见 `dev_env.md §5/§6`）。
基础组件库 / 设计令牌见 `DESIGN.md`（P0-b 交付，本工程直接使用）。

## 快速开始

```bash
# 0) 先起后端全栈（本机没有 Mock Server 了：contracts/mock/ 已删除）
#    全栈跑在 WSL 的 compose（工程名 ai-coach，nginx :80 → /api → api:8000）：
#    timeout 60 wsl.exe -e bash -lc 'docker compose -f <repo>/deploy/docker-compose.yml up -d --build'
#    登录要真链路 → 仓库根 .env 必须有 WECHAT_APPID/WECHAT_SECRET；无凭证后端明确 1001

# 1) 安装依赖（@dcloudio 系列版本需保持一致，见 package.json）
npm install

# 2) 微信小程序：编译产物在 dist/build/mp-weixin（或 dev 模式 dist/dev/mp-weixin），
#    用微信开发者工具「导入项目」指向该目录。⚠️ 外部重新构建后工具不会自动重载，
#    需 cli quit + cli open 才加载新 bundle。
npm run dev:mp-weixin

# 2') H5（仅本地视觉回归通道，不是交付物）：npm run dev:h5 → http://localhost:5173
#     H5 无微信容器，拿不到 wx.login code，登录链路只在小程序侧验；此处只看渲染/交互/控制台。
npm run dev:h5

# 生产构建
npm run build:mp-weixin   # 【交付物】产物 dist/build/mp-weixin
npm run build:h5          # 【非交付物】只为守 #ifdef H5 分支不腐化

# 类型检查
npm run type-check
```

> tabBar 图标为占位路径（`static/tab/*.png`），首次运行前可放任意 81×81 png 或先在微信开发者工具中忽略告警。

## 环境变量（.env.development / .env.production）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `VITE_API_BASE` | 开发 `http://localhost`；生产空 | API 基址。开发指向本机 compose 的 nginx（:80 反代 `/api` → api:8000）；**生产 `.env.production` 留空 = H5 同源反代**，小程序必须填绝对域名（`uni.request` 不支持相对 URL）。`request.ts` 不再内置任何默认地址（兜底 `?? ''`），小程序端拿到空串会**启动即抛**（`MODE==='test'` 豁免，免得单测在干净 clone 上全红） |

> **已不存在 `VITE_USE_MOCK`**：Mock Server 与"Mock 态固定 code 登录"整体下线，登录一律走真实 `uni.login` → 后端 `code2session`。

## 目录说明

```
miniapp/
├── index.html                 # H5 模板（仅本地视觉回归通道用；H5 不进部署面）
├── vite.config.ts             # uni 插件 + @ 别名 → src
├── tsconfig.json              # paths: @/* → src/*
└── src/
    ├── main.ts                # createSSRApp + Pinia（组件走 easycom，无全局注册）
    ├── App.vue                # 仅一次 @import '@/styles/base.scss'；onLaunch 恢复登录态
    ├── manifest.json          # 两个 appid 别搞混：顶层 = DCloud 应用标识（仍占位 touristappid），mp-weixin.appid = 微信小程序 AppID（已填测试号，见「【假设】记录」4）
    ├── pages.json             # 5 Tab（首页/记录/社区/商家/我的）+ login/profile-edit/account-detail；easycom ^C(.*) → @/components
    ├── shime-uni.d.ts         # .vue 模块声明（uni 官方模板命名）
    ├── env.d.ts               # VITE_API_BASE 类型（VITE_USE_MOCK 已随 mock 一并移除）
    ├── api/                   # request.ts 封装 + auth/account/records/ai/profile 模块
    ├── stores/                # user（登录态）/ account（今日热量环）
    ├── types/api.d.ts         # 复制自 contracts/ts/api.d.ts（真源在契约库）
    ├── pages/                 # 8 个页面壳
    └── styles|components|composables|uni.scss   # P0-b 设计系统（只读复用）
```

## 请求封装要点（src/api/request.ts）

- 自动附 `Authorization: Bearer <token>`（storage key：`token` / `refresh_token`）
- HTTP 401 或业务 `code=1001`：用 refresh_token 静默刷新一次并**重放原请求**（并发只发一次）；失败清登录态 reLaunch 回登录页
  - 刷新端点 `/api/auth/refresh` **已在契约与后端落地**（openapi.yaml 有该路径，`endpoints/auth.py` 有实现），不再是早先记的"契约暂缺"假设
- 业务 `code≠0`：useToast 提示 message，reject `Error(message)`；`silent` 选项不弹
- 成功统一返回 `envelope.data`

## 页面清单

| 页面 | 说明 |
| --- | --- |
| `pages/login` | 微信一键登录：`uni.login` 拿真 code → `POST /api/auth/login` → 存 token → reLaunch 首页。**无任何 mock 兜底**（无凭证时后端返 1001，`uni.login` 失败会 toast 可见） |
| `pages/index/index` | 首页壳：问候+评分占位、CRingProgress 热量环、摄入/运动明细、快捷宫格、FAB 拍照 |
| `pages/record/record` | Tab 壳（CSkeleton→CEmpty 演示态，P1 接记录） |
| `pages/community/community` | Tab 壳（P4 接社区） |
| `pages/merchant/merchant` | Tab 壳（P3 接商家） |
| `pages/profile/profile` | Tab 壳：用户卡 + 入口菜单 + 退出登录 |
| `pages/profile/edit` | 身体档案表单壳（CField+CInput+CButton 分段控件） |
| `pages/account/detail` | 热量账户详情壳（今日概览 + 趋势占位） |

## 【假设】记录

1. 刷新端点 `/api/auth/refresh` 契约暂缺（见上）。
2. ~~Mock 态登录用固定 `code='mock-code'`~~ —— **该假设已作废**：`VITE_USE_MOCK` / `mock-code` / Mock Server 全部下线，登录只有 `uni.login` 真 code 一条路（mp-weixin 端）。H5 侧无微信容器，登录链路不在 H5 通道验收（见 `dev_env.md §6`）。
3. tabBar 图标 `static/tab/*.png` 为占位路径，待 UI 出图后替换。
4. `manifest.json` 里**有两个 `appid`，含义不同，别改错**（历史上本条写作"appid 占位 touristappid，联调时替换"，容易被误读成微信 AppID 仍是占位）：
   - **顶层 `appid`**（当前 `touristappid`）= **DCloud 应用标识**，供 uni-app 打包 / uni 统计使用，**与微信无关**；未注册 DCloud 账号前保持占位即可，**不要把它当成微信小程序 AppID 去替换**。
   - **`mp-weixin.appid`**（当前已是**测试号真实 AppID**，值见 `src/manifest.json`）= **微信小程序 AppID**，决定 `wx.login` 拿到的 code 属于哪个小程序。此处由用户明确授权填入，用于本地真微信登录联调；正式发布前替换为线上 AppID，并在公众平台「开发设置 → 服务器域名」登记构建产物实际使用的 `VITE_API_BASE` 域名。
5. 活动水平 5 档文案与每周目标 pace 档位（0.25/0.5/0.75/1.0 kg/周）为默认假设，待产品确认。
