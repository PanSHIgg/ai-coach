/**
 * api/merchantAdmin · 商家自助 API（独立商家 token 域）
 *
 * 覆盖行为：
 *  1. 商家 token 存独立 storage key，读写清除均不污染用户 token；
 *  2. merchantLogin 请求构造（POST 路径 / 入参 / Authorization 按商家 token 注入）；
 *  3. merchantLogin 成功解包 envelope.data；
 *  4. 业务失败（code≠0）抛错并携带 code；
 *  5. 401 抛 code=1001（不做用户态刷新，不清用户登录态）。
 */
import { describe, it, expect } from 'vitest'
import {
  MERCHANT_TOKEN_KEY,
  getMerchantToken,
  saveMerchantToken,
  clearMerchantToken,
  merchantLogin,
} from '@/api/merchantAdmin'
import { BASE_URL } from '@/api/request'
import type { UniMock } from '../../helpers/uni'

const uni = (globalThis as unknown as { uni: UniMock }).uni

/** 让下一次 uni.request 立即以给定响应回包 */
function respond(statusCode: number, data: unknown) {
  uni.request.mockImplementation((opts: { success: (res: unknown) => void }) => {
    opts.success({ statusCode, data })
  })
}

describe('merchantAdmin · 商家 token 的存取隔离', () => {
  it('读写/清除仅作用于 merchant_token，不影响用户 token', () => {
    uni.setStorageSync('token', 'user-token')

    saveMerchantToken('merchant-token')
    expect(uni.getStorageSync(MERCHANT_TOKEN_KEY)).toBe('merchant-token')
    expect(getMerchantToken()).toBe('merchant-token')
    // 用户 token 未被覆盖
    expect(uni.getStorageSync('token')).toBe('user-token')

    clearMerchantToken()
    expect(getMerchantToken()).toBe('')
    expect(uni.getStorageSync(MERCHANT_TOKEN_KEY)).toBe('')
    // 清商家 token 不误伤用户 token
    expect(uni.getStorageSync('token')).toBe('user-token')
  })
})

describe('merchantAdmin · merchantLogin', () => {
  it.each([
    { stored: '', header: {} },
    { stored: 'm-tok', header: { Authorization: 'Bearer m-tok' } },
  ])('以 POST 提交到登录端点，并按商家 token 注入请求头（stored="$stored"）', async ({
    stored,
    header,
  }) => {
    if (stored) saveMerchantToken(stored)
    respond(200, { code: 0, message: 'ok', data: { token: 'new-token' } })

    await merchantLogin({ username: 'shop01', password: 'secret1' })

    expect(uni.request).toHaveBeenCalledTimes(1)
    expect(uni.request).toHaveBeenCalledWith(
      expect.objectContaining({
        url: `${BASE_URL}/api/merchant/login`,
        method: 'POST',
        data: { username: 'shop01', password: 'secret1' },
        header,
      }),
    )
  })

  it('成功时解包 envelope.data', async () => {
    const payload = { token: 'new-token', merchant: { id: 1 } }
    respond(200, { code: 0, message: 'ok', data: payload })

    await expect(merchantLogin({ username: 'shop01', password: 'secret1' })).resolves.toEqual(
      payload,
    )
  })

  it('业务失败（code≠0）时抛出携带 code 的错误', async () => {
    respond(200, { code: 2001, message: '定价越界' })

    await expect(
      merchantLogin({ username: 'shop01', password: 'secret1' }, true),
    ).rejects.toMatchObject({ message: '定价越界', code: 2001 })
  })

  it('HTTP 401 时抛出 code=1001，且不清用户登录态', async () => {
    uni.setStorageSync('token', 'user-token')
    respond(401, { code: 1001, message: 'unauthorized' })

    await expect(
      merchantLogin({ username: 'shop01', password: 'secret1' }, true),
    ).rejects.toMatchObject({ code: 1001 })

    expect(uni.getStorageSync('token')).toBe('user-token')
    // 商家域不触发用户态静默刷新
    expect(uni.reLaunch).not.toHaveBeenCalled()
  })
})