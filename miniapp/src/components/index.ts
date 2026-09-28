/**
 * 基础组件库统一导出（P0-b）
 *
 * 用法一（页面内手动引入）：
 *   import { CButton, CCard } from '@/components'
 *
 * 用法二（easycom 自动注册，pages.json 配置）：
 *   "easycom": { "autoscan": false, "custom": { "^C(.*)": "@/components/C$1.vue" } }
 *   模板中直接写 <CButton /> <CCard /> 等，无需 import。
 */
export { default as CButton } from './CButton.vue'
export { default as CCard } from './CCard.vue'
export { default as CField } from './CField.vue'
export { default as CInput } from './CInput.vue'
export { default as CSkeleton } from './CSkeleton.vue'
export { default as CEmpty } from './CEmpty.vue'
export { default as CError } from './CError.vue'
export { default as CNoPermission } from './CNoPermission.vue'
export { default as CNoBenefit } from './CNoBenefit.vue'
export { default as CRingProgress } from './CRingProgress.vue'
