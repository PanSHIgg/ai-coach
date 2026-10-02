/**
 * Vitest 全局 setup：注入 `uni` 全局桩，并在每个用例前重置存储与桩调用记录。
 * 仅清理 uni 桩，不影响各测试文件自建的 module mock。
 */
import { beforeEach } from 'vitest'
import { createUniMock } from './helpers/uni'

const uni = createUniMock()

;(globalThis as unknown as { uni: unknown }).uni = uni

beforeEach(() => {
  uni.__reset()
})