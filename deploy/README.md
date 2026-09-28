# deploy/ 部署文件说明

| 文件 | 用途 |
| --- | --- |
| `docker-compose.yml` | 一键编排 postgres:16 + redis:7 + api(backend 构建) + nginx |
| `Dockerfile.backend` | 后端镜像：python:3.12-slim，装 requirements、拷 backend、uvicorn 多 worker 非 root 启动 |
| `nginx.conf` | 入口路由：`/api/`→api:8000、`/admin/`→后台静态、`/uploads/`→媒体；gzip、限流 100r/s；443 占位 |

## 启动

```bash
# 在 code/ 根目录执行
cp .env.example .env
docker compose -f deploy/docker-compose.yml up -d
```

| 服务 | 地址 |
| --- | --- |
| Nginx 入口 | http://localhost |
| API 文档 | http://localhost/api/docs |
| PostgreSQL | localhost:5432 |
| Redis | localhost:6379 |

只起依赖、后端本地调试：

```bash
docker compose -f deploy/docker-compose.yml up -d postgres redis
```
