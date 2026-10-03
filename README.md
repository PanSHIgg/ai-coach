# AI 饮食管控教练

微信小程序用户端 + FastAPI 后端 + Vue3 管理后台的一体化 monorepo。核心能力：微信登录、身体档案、热量账户（BMR/TDEE/步数校准）、拍照识别记录饮食、AI 对话（RAG + 次数限制）、饭点决策、商家/SKU/券/订单核销、体重趋势、社区与五种社交。

## 目录结构

```
backend/    FastAPI（app/: api, services, models, schemas, core, tasks）+ pytest
miniapp/    uni-app 小程序（Vue3 + TS + Pinia，交付目标 mp-weixin）
admin/      Vue3 管理后台（Element Plus，H5 SPA，部署于 /admin）
contracts/ 契约真源 openapi.yaml + 两份 TS 类型副本（三方一致性由后端测试守护）
data/       建表 SQL（36 表）、种子数据（食物库 / SKU / RAG）、导入脚本
deploy/     docker-compose.yml、Dockerfile.*、nginx.conf、prometheus/grafana、部署说明
perf/       本机压测工具（seed_bulk.py + harness.py）
scripts/    辅助脚本（h5-compat-check.sh）
docs/       需求交付文档（只读基线，勿改）
```

## 快速开始

```bash
cp .env.example .env          # 按需填写密钥，开发环境可先留空
docker compose -f deploy/docker-compose.yml --env-file .env up -d
```

完整部署说明（分阶段上线步骤、监控栈、灰度与回滚）见 **[`deploy/README.md`](deploy/README.md)**。

启动后：

| 服务 | 地址 |
| --- | --- |
| Nginx 入口 | http://localhost |
| API（反代 /api/） | http://localhost/api/docs |
| 管理后台（/admin/） | http://localhost/admin/ |
| PostgreSQL | localhost:5432（postgres/postgres） |
| Redis | localhost:6379 |
| Prometheus / Grafana | localhost:9090 / localhost:3000 |

端口与栈的完整说明详见 `deploy/README.md`。

## Git Flow 约定

- `main`：生产分支，仅接受从 `develop` 发版合并，打 tag 触发发布。
- `develop`：开发集成分支，所有 feature PR 合入 develop。
- `feature/xxx`：功能分支，从 develop 拉出，PR 合回 develop。
- 提交信息前缀：`feat:` `fix:` `refactor:` `test:` `docs:` `chore:`。

## 开发约定

- **注释写「为什么」，不写「是什么」**：默认不写复述代码的注释（复述元素语义的 HTML 注释、给紧邻 `title` 重复一遍的标签都删掉）；括号里补决策依据的才留。
- **禁止注释掉的死代码**：删掉而不是注释掉。
- **不可删的注释**：`noqa` / `#ifdef` 等条件编译标记、安全守卫注释、`§x.x` 文档锚点追溯。
- **禁止硬行号引用**：`file.py:54-56` 必然随改动失效，引用到文件为止。
- Python：`ruff`（select = E/F/W/I/UP/B，line-length 100）+ `black`，pytest（`backend/` 内执行）；两者在 CI 均**非阻断**。
- 前端：TypeScript 严格模式 + `vue-tsc --noEmit` type-check + 构建校验，**无独立 linter**；`.prettierrc.json` 保留供手工格式化。

## 工具

仓库的 agent 技能包（`.agents/`）已移出 git 跟踪，clone 后需自行安装浏览器自动化工具（本地 H5 / 管理后台渲染核对用）：

```bash
npm i -g agent-browser && agent-browser install
```
