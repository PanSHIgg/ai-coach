<template>
  <div class="login-wrapper">
    <div class="login-card">
      <h1 class="login-title">AI 饮食管控教练</h1>
      <p class="login-subtitle">Phase 3 独立管理后台</p>

      <el-form label-position="top" @submit.prevent="onSubmit">
        <el-form-item label="账号">
          <el-input v-model="form.username" placeholder="请输入账号" size="large" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" show-password placeholder="请输入密码" size="large" @keyup.enter="onSubmit" />
        </el-form-item>
        <el-button type="primary" size="large" style="width: 100%" :loading="loading" @click="onSubmit">
          登 录
        </el-button>
      </el-form>

      <el-divider />
      <div class="seed-box">
        <div class="seed-title">演示种子账号（点击填充）</div>
        <div v-for="s in seeds" :key="s.username" class="seed-item" @click="fill(s)">
          <span>{{ s.label }}</span>
          <span class="seed-account">{{ s.username }} / {{ s.password }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { adminLogin } from '@/api/admin'
import { isNetworkError } from '@/api/client'
import { setAuth } from '@/composables/auth'

const router = useRouter()

const form = reactive({ username: '', password: '' })
const loading = ref(false)

const seeds = [
  { label: '超管', username: 'admin', password: 'Admin@123456' },
  { label: '运营', username: 'ops', password: 'Admin@123456' },
  { label: '商家', username: 'merchant1', password: 'Merchant@123' },
]

function fill(s: { username: string; password: string }): void {
  form.username = s.username
  form.password = s.password
}

async function onSubmit(): Promise<void> {
  if (!form.username || !form.password) {
    ElMessage.warning('请输入账号与密码')
    return
  }
  loading.value = true
  try {
    const data = await adminLogin({ username: form.username, password: form.password })
    setAuth(data)
    ElMessage.success(`欢迎，${data.username}`)
    router.push('/dashboard')
  } catch (err) {
    if (isNetworkError(err)) {
      ElMessage.error('无法连接后端服务，请确认 http://127.0.0.1:8000 已启动')
    }
    // 业务错误已由拦截器统一弹出 message
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.seed-box {
  font-size: 13px;
}

.seed-title {
  color: #6b7280;
  margin-bottom: 8px;
}

.seed-item {
  display: flex;
  justify-content: space-between;
  padding: 6px 8px;
  border-radius: 6px;
  cursor: pointer;
  color: #374151;
}

.seed-item:hover {
  background: #ecfbf2;
}

.seed-account {
  color: #9ca3af;
  font-family: monospace;
}
</style>
