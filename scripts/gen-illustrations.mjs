/**
 * 空态插画生成：Tabler Icons 官方路径 + 浅薄荷圆盘 → 256×256 PNG
 *
 * `empty-sport` 的脉冲线就是 Tabler `activity`（`M3 12h4l3 8l4-16l3 8h4`），
 * `empty-chat` ≈ `message-2`、`empty-crown` ≈ `trophy`——既有插画本就出自这套图标，
 * 所以新增一张必须走同源图标，而不是自己画几何。
 *
 * 圆盘与描边参数是从 `empty-sport.png` 实测出来的，不是猜的：
 * 圆盘 = `#19bf59` @ alpha 20/255（在白底上才显得浅），半径 112（alpha>0 覆盖 x=16..239）；
 * 描边 = `#22c55e`，实心段 5px + 两侧各 1px 抗锯齿 = 笔宽 7；
 * 图形实心包围盒统一为 111×111 居中（sport/chat/crown 三张实测完全一致）。
 *
 * 用法：node scripts/gen-illustrations.mjs
 * 依赖：@resvg/resvg-js（SVG 光栅化，装一次即可，不进 miniapp 的 dependencies）
 *   npm i --prefix /tmp/svgtool @resvg/resvg-js
 * 图标来源：Tabler Icons（MIT），路径经 Iconify API 取回
 *   https://api.iconify.design/tabler/<name>.svg
 */

import { writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)

/**
 * resvg 是原生光栅器，只为出图服务，不进 miniapp 的 dependencies。
 * 用 RESVG_PATH 指向装好的包目录；缺了就明确报错，不静默退化。
 */
function loadResvg() {
  const id = process.env.RESVG_PATH ?? '@resvg/resvg-js'
  try {
    return require(id).Resvg
  } catch {
    console.error(
      `找不到 ${id}\n先执行：npm i --prefix /tmp/svgtool @resvg/resvg-js\n` +
        '再：RESVG_PATH=/tmp/svgtool/node_modules/@resvg/resvg-js node scripts/gen-illustrations.mjs',
    )
    process.exit(1)
  }
}

const Resvg = loadResvg()

const SIZE = 256
const DISC = { r: 112, fill: '#19bf59', opacity: 20 / 255 }
const STROKE_COLOR = '#22c55e'
const STROKE_W = 7
const GLYPH_BOX = 111 // 图形实心包围盒边长（实测三张既有插画一致）
const ICON_VIEW = 18 // Tabler 24×24 网格里，这些图标实际占 3..21

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const OUT_DIR = join(ROOT, 'miniapp/src/static/illustrations')

/** name → Tabler 图标名 + 官方 path d（MIT，取自 api.iconify.design/tabler/<name>.svg） */
const ICONS = {
  'empty-group': {
    tabler: 'users',
    d: 'M5 7a4 4 0 1 0 8 0a4 4 0 1 0-8 0M3 21v-2a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v2m1-17.87a4 4 0 0 1 0 7.75M21 21v-2a4 4 0 0 0-3-3.85',
  },
  'empty-battle': {
    tabler: 'swords',
    d: 'M21 3v5l-11 9l-4 4l-3-3l4-4l9-11zM5 13l6 6m3.32-1.68L18 21l3-3l-3.365-3.365M10 5.5L8 3H3v5l3 2.5',
  },
}

function svgOf({ d }) {
  const scale = (GLYPH_BOX - STROKE_W) / ICON_VIEW
  const sw = STROKE_W / scale
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${SIZE}" height="${SIZE}" viewBox="0 0 ${SIZE} ${SIZE}">
  <circle cx="128" cy="128" r="${DISC.r}" fill="${DISC.fill}" fill-opacity="${DISC.opacity}"/>
  <g transform="translate(128,128) scale(${scale}) translate(-12,-12)"
     fill="none" stroke="${STROKE_COLOR}" stroke-width="${sw}"
     stroke-linecap="round" stroke-linejoin="round">
    <path d="${d}"/>
  </g>
</svg>`
}

for (const [file, icon] of Object.entries(ICONS)) {
  const png = new Resvg(svgOf(icon), { fitTo: { mode: 'width', value: SIZE } }).render().asPng()
  writeFileSync(join(OUT_DIR, `${file}.png`), png)
  console.log(`${file}.png  ← tabler:${icon.tabler}  ${png.length}B`)
}
