/**
 * pages/merchant/login.vue · 商家登录页
 *
 * 覆盖渲染 + 关键交互：表单校验拦截、登录成功状态流转（存 token + reLaunch）、
 * 登录失败内联报错、进入页面时已持商家 token 的自动跳转。merchantAdmin API 以 mock 隔离。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import CButton from '@/components/CButton.vue'
import CField from '@/components/CField.vue'
import CInput from '@/components/CInput.vue'
import type { UniMock } from '../../helpers/uni'

const { onShowMock } = vi.hoisted(() => ({ onShowMock: vi.fn() }))
vi.mock('@dcloudio/uni-app', () => ({ onShow: onShowMock }))
vi.mock('@/api/merchantAdmin', () => ({
  merchantLogin: vi.fn(),
  saveMerchantToken: vi.fn(),
  getMerchantToken: vi.fn(() => ''),
}))

import * as merchantAdmin from '@/api/merchantAdmin'
import LoginPage from '@/pages/merchant/login.vue'

const uni = (globalThis as unknown as { uni: UniMock }).uni
const merchantLoginMock = vi.mocked(merchantAdmin.merchantLogin)
const saveMerchantTokenMock = vi.mocked(merchantAdmin.saveMerchantToken)
const getMerchantTokenMock = vi.mocked(merchantAdmin.getMerchantToken)

function mountPage() {
  return mount(LoginPage, {
    global: { components: { CButton, CField, CInput } },
  })
}

async function fillCredentials(wrapper: ReturnType<typeof mount>, username: string, password: string) {
  const inputs = wrapper.findAllComponents(CInput)
  inputs[0].vm.$emit('update:modelValue', username)
  inputs[1].vm.$emit('update:modelValue', password)
  await nextTick()
}

async function tapLogin(wrapper: ReturnType<typeof mount>) {
  await wrapper.findComponent(CButton).trigger('tap')
  await flushPromises()
}

beforeEach(() => {
  onShowMock.mockClear()
  merchantLoginMock.mockReset()
  saveMerchantTokenMock.mockReset()
  getMerchantTokenMock.mockReset()
  getMerchantTokenMock.mockReturnValue('')
})

describe('merchant/login · 表单校验', () => {
  it('账号/密码为空时拦截提交并展示校验错误', async () => {
    const wrapper = mountPage()

    await tapLogin(wrapper)

    expect(merchantLoginMock).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('请输入商家账号')
    expect(wrapper.text()).toContain('请输入密码')
  })
})

describe('merchant/login · 提交流转', () => {
  it('登录成功后保存商家 token 并跳转后台', async () => {
    merchantLoginMock.mockResolvedValue({ token: 'mt-1' } as never)
    const wrapper = mountPage()

    await fillCredentials(wrapper, 'shop01', 'secret1')
    await tapLogin(wrapper)

    expect(merchantLoginMock).toHaveBeenCalledWith(
      { username: 'shop01', password: 'secret1' },
      true,
    )
    expect(saveMerchantTokenMock).toHaveBeenCalledWith('mt-1')
    expect(uni.reLaunch).toHaveBeenCalledWith({ url: '/pages/merchant/admin' })
  })

  it('登录失败时展示内联错误且不跳转', async () => {
    merchantLoginMock.mockRejectedValue(new Error('账号或密码错误'))
    const wrapper = mountPage()

    await fillCredentials(wrapper, 'shop01', 'wrong-pwd')
    await tapLogin(wrapper)

    expect(wrapper.text()).toContain('账号或密码错误')
    expect(saveMerchantTokenMock).not.toHaveBeenCalled()
    expect(uni.reLaunch).not.toHaveBeenCalled()
  })
})

describe('merchant/login · 已登录自动进入', () => {
  it('进入页面时已持商家 token 则直接跳转后台', async () => {
    getMerchantTokenMock.mockReturnValue('mt-existing')
    mountPage()

    const onShowCallback = onShowMock.mock.calls.at(-1)?.[0] as () => void
    onShowCallback()

    expect(uni.reLaunch).toHaveBeenCalledWith({ url: '/pages/merchant/admin' })
  })
})