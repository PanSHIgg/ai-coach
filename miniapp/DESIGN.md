# miniapp · 设计系统说明（P0-b）

> 依据 `docs/split/02-UI设计规范.md`（§4 设计令牌）与 `docs/split/03-页面布局与交互说明.md`（§5.8 通用状态）实现。
> 代码为单一真源，本文档为对照说明与接入指引。

## 1. 文件清单与职责

| 文件 | 职责 |
| --- | --- |
| `src/styles/tokens.scss` | 设计令牌单一真源：SCSS 变量 + `@mixin css-tokens`（CSS 变量双形式）；零选择器输出，可被 uni.scss 安全注入 |
| `src/styles/mixins.scss` | 通用 mixin：flex-center / flex-between / ellipsis / ellipsis-multi / safe-area-bottom / hairline / press / fade-up / skeleton-pulse / spin |
| `src/styles/base.scss` | 全局基础：page 级 CSS 变量输出（@include css-tokens）、极简 reset、全局 keyframes（fade-up / skeleton-pulse / spin）、少量工具类（.flex-center/.flex-between/.ellipsis/.ellipsis-2/.safe-bottom/.card） |
| `src/uni.scss` | uni-app 约定入口：仅 @import tokens + mixins（自动注入每个组件，零 CSS 输出） |
| `src/components/*.vue` | 基础组件 ×10（见 §3）；由 `src/pages.json` 的 easycom 规则 `^C(.*) → @/components/C$1.vue` 自动解析，无需 barrel 导出 |
| `src/pages.json` | 页面路由 + easycom 配置真源（见 §4.3） |
| `src/composables/useToast.ts` | uni.showToast 轻封装（success/error/info/loading/hideLoading） |

## 2. 设计令牌对照表（文档值 → 变量名）

### 2.1 色彩（§4.1 + §4.12 健康三色）

| 用途 | 文档值 | SCSS 变量 | CSS 变量 |
| --- | --- | --- | --- |
| 主色（进度/主按钮/品牌） | #22C55E | `$brand` | `--brand` |
| 主色按压/深底 | #16A34A | `$brand-dark` | `--brand-dark` |
| 警告（接近预算，琥珀） | #F59E0B | `$warn` | `--warn` |
| 危险（超标/删除/过期） | #EF4444 | `$danger` | `--danger` |
| 信息/运动 | #3B82F6 | `$info` | `--info` |
| 成功/达标 | #10B981 | `$success` | `--success` |
| 健康三色·绿（>80） | = success | `$health-good` | `--health-good` |
| 健康三色·黄（60-80） | = warn | `$health-mid` | `--health-mid` |
| 健康三色·红（<60） | = danger | `$health-bad` | `--health-bad` |
| 页面背景 | #F5F6F8 | `$bg` | `--bg` |
| 卡片底色 | #FFFFFF | `$card` | `--card` |
| 主文字 | #1F2937 | `$text-1` | `--text-1` |
| 次要文字 | #6B7280 | `$text-2` | `--text-2` |
| 占位/辅助 | #9CA3AF | `$text-3` | `--text-3` |
| 分割线/输入框边 | #E5E7EB | `$border` | `--border` |
| 禁用底（§4.6） | #D1D5DB | `$disabled` | — |

### 2.2 字体（§4.2，行高 1.5、标题 500、数值 700）

| 文档令牌 | 值/字重 | SCSS 变量 | 用途 |
| --- | --- | --- | --- |
| `--t-32` | 32rpx / 500 | `$t-32` | 页面标题 |
| `--t-28` | 28rpx / 500 | `$t-28` | 模块标题、卡标题、主按钮 |
| `--t-26` | 26rpx / 400 | `$t-26` | 正文 |
| `--t-24` | 24rpx / 400 | `$t-24` | 次要正文、按钮 |
| `--t-22` | 22rpx / 400 | `$t-22` | 辅助说明、标签 |
| `--t-num-lg` | 56rpx / 700 | `$t-num-lg` | 环形图中心数字 |
| `--t-num-md` | 40rpx / 700 | `$t-num-md` | 大数值（已摄入/消耗） |

主字体 PingFang SC：`$font-family`（base.scss 中 page 级已设置，行高 1.5）。

### 2.3 间距（§4.3，4 点栅格）

| 令牌 | 值 | SCSS 变量 | 用途 |
| --- | --- | --- | --- |
| xs | 8rpx | `$space-xs` | 微间距 |
| sm | 16rpx | `$space-sm` | 小间距 |
| md | 24rpx | `$space-md` | 页面左右内边距 |
| lg | 32rpx | `$space-lg` | 卡片内边距 |
| xl | 48rpx | `$space-xl` | 区块间距 |

### 2.4 圆角 / 阴影 / 层级 / 动效（§4.1/§4.4/§4.14）

| 组 | 令牌 → 变量 | 值 |
| --- | --- | --- |
| 圆角 | `$radius-sm` / `$radius` / `$radius-lg`（CSS：`--radius-sm/--radius/--radius-lg`） | 8 / 16 / 24rpx |
| 阴影 | `$shadow`（卡片）/ `$shadow-lg`（弹窗） | 0 4rpx 16rpx rgba(0,0,0,.06) / 0 8rpx 32rpx rgba(0,0,0,.12) |
| z-index【假设】 | `$z-nav:100` `$z-fab:200` `$z-mask:500` `$z-popup:600` `$z-dialog:700` `$z-toast:900` | 导航 < FAB < 遮罩 < 底部弹层 < 对话框 < Toast |
| 动效 | `$duration-fast:150ms` `$duration-base:300ms` `$duration-ring:800ms` `$ease-out` | 按压 / 卡片进场 fade-up / 环形图进度 |

### 2.5 双形式使用说明

- **SCSS 变量**：组件 `<style lang="scss">` 内直接用（uni.scss 自动注入 tokens + mixins）。
- **CSS 变量**：base.scss 在 `page` 上输出一次（`@include css-tokens`），供运行时动态样式（内联 style、JS 拼样式）使用。
- **暗色模式**：§4.13 首期不做；tokens.scss 的 css-tokens 内已留 `prefers-color-scheme: dark` 注释模板。

## 3. 组件 API

### CButton（§4.6）

| prop | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| type | `'primary' \| 'secondary' \| 'ghost' \| 'danger'` | `'primary'` | 主/次/文字/危险；禁用统一底 #D1D5DB |
| size | `'lg' \| 'md' \| 'sm'` | `'lg'` | 高 88 / 72 / 56rpx【假设】md/sm 文档未定义 |
| loading | boolean | false | 显示 spinner 并拦截点击 |
| disabled | boolean | false | |
| block | boolean | false | 通栏全宽 |

emit：`click(ev)`。按压态 opacity .85（@include press）。

```vue
<CButton block :loading="submitting" @click="onSave">保存</CButton>
<CButton type="secondary" size="md" @click="onCancel">取消</CButton>
```

### CCard（§4.11）

| prop | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| title | string | '' | 标题（优先 #title 插槽） |
| padding | boolean | true | false 时 flush 贴边 |

插槽：`title`（覆盖标题）、`extra`（标题行右侧操作）、默认内容。

```vue
<CCard title="摄入明细">
  <template #extra><text class="link">全部 →</text></template>
  ...
</CCard>
```

### CField + CInput（§4.7）

- CField props：`label` / `required`（红星）/ `error`（红字，优先显示）/ `hint`；默认插槽放输入控件。
- CInput：`v-model`（modelValue + update:modelValue）、`placeholder`、`type`（text/number/digit/idcard）、`disabled`、`maxlength`；emit `focus / blur / confirm`。高 88rpx、聚焦边框变 `--brand`。

```vue
<CField label="体重" required :error="errors.weight" hint="单位 kg">
  <CInput v-model="form.weight" type="digit" placeholder="如 68.5" />
</CField>
```

### CSkeleton（§5.8 加载中）

| prop | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| type | `'line' \| 'card'` | `'line'` | 行骨架 / 卡片骨架（标题条 + 3 行） |
| rows | number | 3 | line 形态行数，末行 60% 宽 |

```vue
<CSkeleton v-if="loading" type="card" />
```

### 通用状态组件（§5.8）

| 组件 | 默认 icon / 文案 | 默认按钮 | emit | 场景 |
| --- | --- | --- | --- | --- |
| CEmpty | 🍽️ / 还没有记录 | 去记录 | `action` | 列表为空 |
| CError | ⚠️ / 网络开小差了 | 重试 | `retry` | 请求失败 |
| CNoPermission | 🔒 / 登录后查看 | 去登录 | `action` | 未登录/无权限 |
| CNoBenefit | — / 该功能需进阶版 | 立即开通 | `action` | 权益未开通：默认插槽灰显（grayscale + opacity .4）+ 浮层 |

```vue
<CEmpty v-if="!list.length" @action="goRecord" />
<CError v-else-if="failed" @retry="reload" />
<CNoBenefit @action="goSubscribe">
  <TrendChart :data="lockedData" />
</CNoBenefit>
```

### CRingProgress（§4.12 评分环，CSS conic-gradient 方案）

| prop | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| percent | number | 必填 | 0-100，自动钳制 |
| size | number | 240 | 直径 rpx |
| strokeWidth | number | 24 | 环宽 rpx |
| color | string | #22C55E（= $brand） | 进度色，按健康区间传 `--health-*` 对应色值 |
| trackColor | string | #E5E7EB（= $border） | 轨道色 |
| holeColor | string | #FFFFFF（= $card） | 中心挖空底色 |

插槽：默认插槽渲染中心内容（分数/文字）。实现：外层 conic-gradient 圆 + 内层挖空圆形成环；【假设】不用 canvas，先 CSS 方案。

```vue
<CRingProgress :percent="78" :color="healthColor">
  <view class="score">
    <text class="score__num" style="font-size:56rpx;font-weight:700">78</text>
    <text class="score__label">轻度超重</text>
  </view>
</CRingProgress>
```

## 4. 接入说明（前端脚手架轨 P0-f 需要做的）

1. `App.vue` 的 `<style lang="scss">` 中：`@import './styles/base.scss';`（全局仅此一次，输出 page CSS 变量 / reset / keyframes）。
2. `uni.scss` 已由本任务提供（src/uni.scss），脚手架勿重复创建。
3. easycom 自动注册（可选，pages.json）：

```json
"easycom": { "autoscan": false, "custom": { "^C(.*)": "@/components/C$1.vue" } }
```

4. TS 类型：`.vue` 模块声明（shims-vue.d.ts）与 `@` 别名由脚手架配置。

## 5. 【假设】记录

1. **z-index 层级**：文档未定义，自定义六级（100/200/500/600/700/900，最小够用）。
2. **健康三色**：§4.12 只定义区间阈值（<60 红 / 60-80 琥珀 / >80 绿），色值复用语义色 success/warn/danger。
3. **按钮尺寸**：文档只定义主按钮高 88rpx，md=72 / sm=56 按 4 点栅格推导。
4. **error Toast**：微信 showToast 无 error 图标，降级 `icon: 'none'`（黑底白字，仍满足 §4.9）。
5. **conic-gradient 兼容**：需较新 WebView/基础库；不支持机型环形图退化为纯轨道色（内容插槽不受影响），后续可换 canvas 方案。
6. **图标占位**：未引 uni-icons 依赖（脚手架统一决定），状态组件用 emoji 占位，icon prop 可替换。
7. **零散色值**：禁用底 #D1D5DB（§4.6 有值无令牌名）、输入框禁用底 #F9FAFB、状态插画底 #F3F4F6，文档未定义取常用灰阶。
8. **CSS 变量输出方式**：设计为 @mixin（uni.scss 注入零输出），由 base.scss 在 page 上 @include 一次，避免每个组件重复一份变量块。
