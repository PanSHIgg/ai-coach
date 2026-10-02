#!/usr/bin/env bash
# F7 兼容性核对复现脚本（管理后台产物，浏览器真实渲染）
# 用法：bash scripts/h5-compat-check.sh
# 前提：admin/node_modules 已装；PG/Redis 可用；agent-browser 已装。
# 端口段：admin 4177 / backend 9100。
# 说明：仅做只读核对，不修改仓库源码与产物；临时文件写入 /tmp。
# 范围：本项目只交付微信小程序，H5 产物不进部署面，故此处不再核对 H5 渲染；
#       H5 构建能力（miniapp npm run build:h5）保留，需要临时视觉核对时自行起静态服务对照。
# 文件名说明：脚本名保留 h5 是历史名，实际核对对象是**管理后台这个 H5 SPA**（admin/dist 多档
#       viewport 浏览器渲染）；全仓无其他文件引用它，改名需自行同步本地书签/文档。
#       小程序 H5 通道的核对不在此脚本，见 dev_env.md §6（npm run dev:h5 + agent-browser）。
# 解释器：PY 需指向装了后端依赖的 ≥3.12 解释器；本机（Windows）实测用
#       PY=backend/.venv/Scripts/python.exe（系统 python3.12 无后端依赖）。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-$(command -v python3.12 || command -v python3 || true)}"
: "${PY:?未找到 python3.12/python3，请用 PY=/path/to/your/python3.12 指定（需 >=3.12）}"
ADM_PORT=4177
API_PORT=9100
TMP="$(mktemp -d /tmp/f7-compat.XXXXXX)"
PIDS=()

cleanup() {
  for p in "${PIDS[@]:-}"; do kill "$p" 2>/dev/null || true; done
  agent-browser --session f7adm close >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "== 1/4 构建产物 =="
(cd "$ROOT/admin" && npm run build)

echo "== 2/4 起后端 :$API_PORT =="
(cd "$ROOT/backend" && DATABASE_URL="postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/ai_coach" \
  REDIS_URL="redis://127.0.0.1:6379/0" "$PY" -m uvicorn app.main:app --port "$API_PORT" --host 127.0.0.1) &
PIDS+=($!)
sleep 4
export PGPASSWORD=postgres
psql -h 127.0.0.1 -U postgres -d ai_coach -v ON_ERROR_STOP=1 -f "$ROOT/data/sql/003_phase3_admin_seed.sql" >/dev/null

echo "== 3/4 临时静态服务（admin 补同源 /api 反代）=="
cat > "$TMP/serve.mjs" <<'JS'
import http from 'node:http'; import fs from 'node:fs'; import path from 'node:path'; import { URL } from 'node:url'
const [, , root, portArg, proxy] = process.argv; const rootP = path.resolve(root); const port = +portArg
const MIME={'.html':'text/html; charset=utf-8','.js':'text/javascript','.css':'text/css','.json':'application/json','.svg':'image/svg+xml','.png':'image/png','.ico':'image/x-icon'}
const srv=http.createServer((req,res)=>{
  if(proxy && req.url.startsWith('/api/')){const t=new URL(proxy);const p=http.request({hostname:t.hostname,port:t.port,path:req.url,method:req.method,headers:req.headers},r=>{res.writeHead(r.statusCode||502,r.headers);r.pipe(res)});p.on('error',e=>{res.writeHead(502);res.end(String(e))});return req.pipe(p)}
  let fp=path.join(rootP, decodeURIComponent(req.url.split('?')[0]))
  fs.stat(fp,(e,st)=>{if(e||!st.isFile())fp=path.join(rootP,'index.html');fs.readFile(fp,(e2,d)=>{if(e2){res.writeHead(404);return res.end('nf')}res.writeHead(200,{'content-type':MIME[path.extname(fp).toLowerCase()]||'application/octet-stream'});res.end(d)})})
})
srv.listen(port,'127.0.0.1',()=>console.log('serve',port,root,proxy||'no-proxy'))
JS
node "$TMP/serve.mjs" "$ROOT/admin/dist" "$ADM_PORT" "http://127.0.0.1:$API_PORT" & PIDS+=($!)
sleep 1

echo "== 4/4 后台三档 × 主要页面（含 1920）=="
agent-browser --session f7adm set viewport 1440 900 >/dev/null
agent-browser --session f7adm open "http://127.0.0.1:$ADM_PORT/#/login" >/dev/null; sleep 1
agent-browser --session f7adm snapshot -i   # 用快照中的 textbox/button ref 完成登录（admin/Admin@123456）
echo "提示：手动 fill 账号/密码并 click 登录后，对 #/dashboard #/merchants #/orders #/content-audit 逐档核对。"
echo "临时目录：$TMP（退出时自动清理）"