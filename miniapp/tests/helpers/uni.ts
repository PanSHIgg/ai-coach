/**
 * uni 全局 API 可控桩（测试专用）。
 *
 * 被测源码（request.ts / merchantAdmin.ts / useVoice.ts 等）直接引用全局 `uni`，
 * 单测中通过 globalThis.uni 注入本桩，实现 storage / 跳转 / toast / 录音等完全可控。
 */
import { vi } from 'vitest'

export interface UniMock {
  __storage: Map<string, unknown>
  __reset: () => void
  getStorageSync: (key: string) => unknown
  setStorageSync: (key: string, value: unknown) => void
  removeStorageSync: (key: string) => void
  showToast: ReturnType<typeof vi.fn>
  showLoading: ReturnType<typeof vi.fn>
  hideLoading: ReturnType<typeof vi.fn>
  navigateTo: ReturnType<typeof vi.fn>
  redirectTo: ReturnType<typeof vi.fn>
  reLaunch: ReturnType<typeof vi.fn>
  getLocation: ReturnType<typeof vi.fn>
  request: ReturnType<typeof vi.fn>
  getRecorderManager: ReturnType<typeof vi.fn>
  getFileSystemManager: ReturnType<typeof vi.fn>
}

export function createUniMock(): UniMock {
  const storage = new Map<string, unknown>()

  const mock = {
    __storage: storage,
    __reset() {
      storage.clear()
      for (const value of Object.values(mock)) {
        const fn = value as { mockClear?: () => void }
        if (fn && typeof fn.mockClear === 'function') fn.mockClear()
      }
    },
    getStorageSync: (key: string) => (storage.has(key) ? storage.get(key) : ''),
    setStorageSync: (key: string, value: unknown) => {
      storage.set(key, value)
    },
    removeStorageSync: (key: string) => {
      storage.delete(key)
    },
    showToast: vi.fn(),
    showLoading: vi.fn(),
    hideLoading: vi.fn(),
    navigateTo: vi.fn(),
    redirectTo: vi.fn(),
    reLaunch: vi.fn(),
    getLocation: vi.fn(),
    request: vi.fn(),
    getRecorderManager: vi.fn(() => ({
      start: vi.fn(),
      stop: vi.fn(),
      onStop: vi.fn(),
      onError: vi.fn(),
    })),
    getFileSystemManager: vi.fn(() => ({ readFile: vi.fn() })),
  }

  return mock as unknown as UniMock
}