#!/usr/bin/env bash
# TS 类型生成脚本（P0-d）。可重复执行。
# 优先 npx openapi-typescript 从 openapi.yaml 生成 ts/openapi.gen.ts；
# 失败（离线/无 node）时提示使用手写兜底 ts/api.d.ts。
set -u
cd "$(dirname "$0")"

OUT="ts/openapi.gen.ts"
mkdir -p ts

if command -v npx >/dev/null 2>&1; then
  if npx --yes openapi-typescript openapi.yaml -o "$OUT"; then
    echo "[gen-ts] OK -> $OUT（自动生成，勿手改）"
    echo "[gen-ts] 手写精简类型见 ts/api.d.ts（契约对齐的兜底/离线版）"
    exit 0
  fi
  echo "[gen-ts] openapi-typescript 生成失败（可能离线或 npm 源不可达）"
else
  echo "[gen-ts] 未找到 npx（需 Node.js）"
fi

echo "[gen-ts] 兜底：请直接使用手写类型 ts/api.d.ts（与 openapi.yaml 对齐；"
echo "[gen-ts] 契约变更时先改 openapi.yaml，再手工同步该文件并通知对端）"
exit 0
