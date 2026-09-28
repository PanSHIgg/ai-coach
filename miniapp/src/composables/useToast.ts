/**
 * useToast · uni.showToast 轻封装（P0-b，§4.9：Toast 黑底白字、1.5s 自动消失）
 *
 * 用法：
 *   const toast = useToast()
 *   toast.success('记录成功')
 *   toast.error('网络开小差了')
 *   toast.loading('上传中...')
 *   toast.hideLoading()
 */
export interface ToastOptions {
  title: string
  /** 展示时长 ms，默认 1500（§4.9） */
  duration?: number
}

export function useToast() {
  /** 成功提示（icon: success） */
  const success = ({ title, duration = 1500 }: ToastOptions) => {
    uni.showToast({ title, icon: 'success', duration })
  }

  /**
   * 错误提示。
   * 【假设】微信 showToast 无 error 图标，降级 icon: 'none'（黑底白字文字态）。
   */
  const error = ({ title, duration = 1500 }: ToastOptions) => {
    uni.showToast({ title, icon: 'none', duration })
  }

  /** 纯文字提示（同上降级） */
  const info = ({ title, duration = 1500 }: ToastOptions) => {
    uni.showToast({ title, icon: 'none', duration })
  }

  /** 加载中（mask 防穿透；须配对调用 hideLoading） */
  const loading = (title = '加载中...', mask = true) => {
    uni.showLoading({ title, mask })
  }

  const hideLoading = () => {
    uni.hideLoading()
  }

  return { success, error, info, loading, hideLoading }
}
