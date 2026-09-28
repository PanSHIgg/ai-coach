# miniapp · AI 饮食管控教练用户端（uni-app 小程序）

P0-f 前端脚手架：uni-app Vue3 + Vite + TS + Pinia，编译目标微信小程序（mp-weixin）与 H5。
基础组件库 / 设计令牌见 `DESIGN.md`（P0-b 交付，本工程直接使用）。

## 快速开始

```bash
# 0) 先起 Mock Server（34 接口 canned，默认端口 9000）
node ../contracts/mock/server.mjs

# 1) 安装依赖（@dcloudio 系列版本需保持一致，见 package.json）
npm install

# 2) 微信小程序：编译产物在 dist/dev/mp-weixin，用微信开发者工具「导入项目」指向该目录
npm run dev:mp-weixin

# 2') H5：浏览器直接访问提示的本地地址
npm run dev:h5

# 生产构建
npm run build:mp-weixin   # 产物 dist/build/mp-weixin
npm run build:h5          # 产物 dist/build/h5

# 类型检查
npm run type-check
```

> tabBar 图标为占位路径（`static/tab/*.png`），首次运行前可放任意 81×81 png 或先在微信开发者工具中忽略告警。

## 环境变量（.env.development）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `VITE_API_BASE` | `http://localhost:9000` | API 基地址（指向 contracts/mock/server.mjs） |
| `VITE_USE_MOCK` | `true` | Mock 态：登录页用固定 code 直接 mock 登录，不调 wx.login |

## 目录说明

```
miniapp/
├── index.html                 # H5 模板
├── vite.config.ts             # uni 插件 + @ 别名 → src
├── tsconfig.json              # paths: @/* → src/*
└── src/
    ├── main.ts                # createSSRApp + Pinia（组件走 easycom，无全局注册）
    ├── App.vue                # 仅一次 @import '@/styles/base.scss'；onLaunch 恢复登录态
    ├── manifest.json          # appid 占位 touristappid（联调时替换）
    ├── pages.json             # 5 Tab（首页/记录/社区/商家/我的）+ login/profile-edit/account-detail；easycom ^C(.*) → @/components
    ├── shime-uni.d.ts         # .vue 模块声明（uni 官方模板命名）
    ├── env.d.ts               # VITE_API_BASE / VITE_USE_MOCK 类型
    ├── api/                   # request.ts 封装 + auth/account/records/ai/profile 模块
    ├── stores/                # user（登录态）/ account（今日热量环）
    ├── types/api.d.ts         # 复制自 contracts/ts/api.d.ts（真源在契约库）
    ├── pages/                 # 8 个页面壳
    └── styles|components|composables|uni.scss   # P0-b 设计系统（只读复用）
```

## 请求封装要点（src/api/request.ts）

- 自动附 `Authorization: Bearer <token>`（storage key：`token` / `refresh_token`）
- HTTP 401 或业务 `code=1001`：用 refresh_token 静默刷新一次并**重放原请求**（并发只发一次）；失败清登录态 reLaunch 回登录页
  - 【假设】刷新端点 `/api/auth/refresh`（34 接口契约暂未包含，登录接口联调时对齐；Mock 未实现 → 404 视为刷新失败走登录）
- 业务 `code≠0`：useToast 提示 message，reject `Error(message)`；`silent` 选项不弹
- 成功统一返回 `envelope.data`

## 页面清单

| 页面 | 说明 |
| --- | --- |
| `pages/login/login` | 微信一键登录（Mock 态固定 code → 存 token → reLaunch 首页） |
| `pages/index/index` | 首页壳：问候+评分占位、CRingProgress 热量环、摄入/运动明细、快捷宫格、FAB 拍照 |
| `pages/record/record` | Tab 壳（CSkeleton→CEmpty 演示态，P1 接记录） |
| `pages/community/community` | Tab 壳（P4 接社区） |
| `pages/merchant/merchant` | Tab 壳（P3 接商家） |
| `pages/profile/profile` | Tab 壳：用户卡 + 入口菜单 + 退出登录 |
| `pages/profile/edit` | 身体档案表单壳（CField+CInput+CButton 分段控件） |
| `pages/account/detail` | 热量账户详情壳（今日概览 + 趋势占位） |

## 【假设】记录

1. 刷新端点 `/api/auth/refresh` 契约暂缺（见上）。
2. Mock 态登录用固定 `code='mock-code'`；正式联调在 `VITE_USE_MOCK≠true` 且 mp-weixin 端走 `uni.login`。
3. tabBar 图标 `static/tab/*.png` 为占位路径，待 UI 出图后替换。
4. manifest.json appid 占位 `touristappid`，联调时替换正式小程序 AppID。
5. 活动水平 5 档文案与每周目标 pace 档位（0.25/0.5/0.75/1.0 kg/周）为默认假设，待产品确认。
