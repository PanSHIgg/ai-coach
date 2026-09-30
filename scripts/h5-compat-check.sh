#!/usr/bin/env bash
# F7 兼容性核对复现脚本（H5 产物 + 管理后台产物，浏览器真实渲染）
# 用法：bash scripts/h5-compat-check.sh
# 前提：miniapp/node_modules、admin/node_modules 已装；PG/Redis 可用；agent-browser 已装。
# 端口段：H5 5177 / admin 4177 / backend 9100。
# 说明：仅做只读核对，不修改仓库源码与产物；临时文件写入 /tmp。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-$(command -v python3.12 || command -v python3 || true)}"
: "${PY:?未找到 python3.12/python3，请用 PY=/path/to/your/python3.12 指定（需 >=3.12）}"
H5_PORT=5177
ADM_PORT=4177
API_PORT=9100
TMP="$(mktemp -d /tmp/f7-compat.XXXXXX)"
PIDS=()

cleanup() {
  for p in "${PIDS[@]:-}"; do kill "$p" 2>/dev/null || true; done
  agent-browser --session f7h5 close  >/dev/null 2>&1 || true
  agent-browser --session f7adm close >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "== 1/5 构建产物 =="
(cd "$ROOT/miniapp" && npm run build:h5)
(cd "$ROOT/admin" && npm run build)

echo "== 2/5 起后端 :$API_PORT =="
(cd "$ROOT/backend" && DATABASE_URL="postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/ai_coach" \
  REDIS_URL="redis://127.0.0.1:6379/0" "$PY" -m uvicorn app.main:app --port "$API_PORT" --host 127.0.0.1) &
PIDS+=($!)
sleep 4
export PGPASSWORD=postgres
psql -h 127.0.0.1 -U postgres -d ai_coach -v ON_ERROR_STOP=1 -f "$ROOT/data/sql/003_phase3_admin_seed.sql" >/dev/null

echo "== 3/5 临时静态服务（H5/admin 均补同源 /api 反代）=="
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
node "$TMP/serve.mjs" "$ROOT/miniapp/dist/build/h5" "$H5_PORT" "http://127.0.0.1:$API_PORT" & PIDS+=($!)
node "$TMP/serve.mjs" "$ROOT/admin/dist" "$ADM_PORT" "http://127.0.0.1:$API_PORT" & PIDS+=($!)
sleep 1

echo "== 4/5 H5 三档 × 主要页面 =="
OVL='(()=>{const d=document.documentElement;return JSON.stringify({sw:d.scrollWidth,cw:d.clientWidth})})()'
agent-browser --session f7h5 open >/dev/null
for W in 375 768 1440; do
  agent-browser --session f7h5 set viewport "$W" 812 >/dev/null
  for p in index/index record/record community/community merchant/merchant profile/profile order/list; do
    agent-browser --session f7h5 errors --clear >/dev/null
    agent-browser --session f7h5 open "http://127.0.0.1:$H5_PORT/#/pages/$p" >/dev/null; sleep 1
    ov=$(printf '%s' "$OVL" | agent-browser --session f7h5 eval --stdin)
    ec=$(agent-browser --session f7h5 errors | grep -c . || true)
    echo "H5 W=$W $p overflow=$ov errors=$ec"
  done
done

echo "== 5/5 后台三档 × 主要页面（含 1920）=="
agent-browser --session f7adm set viewport 1440 900 >/dev/null
agent-browser --session f7adm open "http://127.0.0.1:$ADM_PORT/#/login" >/dev/null; sleep 1
agent-browser --session f7adm snapshot -i   # 用快照中的 textbox/button ref 完成登录（admin/Admin@123456）
echo "提示：手动 fill 账号/密码并 click 登录后，对 #/dashboard #/merchants #/orders #/content-audit 逐档核对。"
echo "临时目录：$TMP（退出时自动清理）"