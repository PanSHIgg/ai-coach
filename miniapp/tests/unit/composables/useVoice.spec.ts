/**
 * composables/useVoice · 非小程序端（H5/App）降级
 *
 * H5 等端不具备录音能力（uni.getRecorderManager 缺失），useVoice 应保持
 * supported=false，start() 只给出提示、不调用录音、不抛错。
 */
import { describe, it, expect, vi } from 'vitest'
import { createUniMock } from '../../helpers/uni'

describe('useVoice · 非小程序端降级', () => {
  it('无录音能力时 start() 仅提示不支持，不抛错且不进入录音态', async () => {
    // 模拟 H5：全局 uni 无 getRecorderManager
    const h5Uni = createUniMock()
    delete (h5Uni as { getRecorderManager?: unknown }).getRecorderManager
    ;(globalThis as unknown as { uni: unknown }).uni = h5Uni
    vi.resetModules()

    const { useVoice } = await import('@/composables/useVoice')
    const tips: string[] = []
    const voice = useVoice({ onResult: vi.fn(), onTip: (message: string) => tips.push(message) })

    expect(voice.supported).toBe(false)
    expect(() => voice.start()).not.toThrow()
    expect(tips).toEqual(['当前环境暂不支持语音，请手动输入'])
    expect(voice.recording.value).toBe(false)
  })
})