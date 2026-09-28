# AI 饮食管控教练

微信小程序用户端 + FastAPI 后端 + 管理后台的一体化 monorepo。核心能力：微信登录、身体档案、热量账户（BMR/TDEE/步数校准）、拍照识别记录饮食、AI 对话（RAG + 次数限制）、饭点决策、商家/SKU/券/订单核销、体重趋势、社区与五种社交。

## 目录结构

```
/code
  /backend    FastAPI（app/: api, services, models, schemas, core, tasks）
  /miniapp    uni-app 小程序（Vue3 + TS + Pinia，编译微信小程序 + H5）
  /admin      Vue3 管理后台（H5，部署于 /admin）
  /deploy     docker-compose.yml、Dockerfile.*、nginx.conf、部署说明
  /data       建表 SQL、种子数据（食物库/SKU/RAG）、测试用例
  /docs       交付文档
```

## 快速开始

```bash
cp .env.example .env          # 按需填写密钥，开发环境可先留空
docker compose -f deploy/docker-compose.yml --env-file .env up -d
```

启动后：

| 服务 | 地址 |
| --- | --- |
| Nginx 入口 | http://localhost |
| API（反代 /api/） | http://localhost/api/docs |
| 管理后台（/admin/） | http://localhost/admin/ |
| PostgreSQL | localhost:5432（postgres/postgres） |
| Redis | localhost:6379 |

仅起依赖（后端本地跑 uvicorn 时）：

```bash
docker compose -f deploy/docker-compose.yml up -d postgres redis
```

## Git Flow 约定

- `main`：生产分支，仅接受从 `develop` 发版合并，打 tag 触发发布。
- `develop`：开发集成分支，所有 feature PR 合入 develop。
- `feature/xxx`：功能分支，从 develop 拉出，PR 合回 develop。
- 提交信息前缀：`feat:` `fix:` `refactor:` `test:` `docs:` `chore:`。

## 规范

- Python：ruff + black（line-length 100），pytest 单测（`backend/` 内执行）。
- 前端：eslint + prettier（配置见 `.prettierrc.json`），提交前自动格式化。
- 数据库迁移：Alembic 只加字段不删改列，保证可回滚。
- 环境变量：`.env` 不入库，以 `.env.example` 为模板。
