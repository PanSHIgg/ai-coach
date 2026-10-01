<template>
  <view class="post">
    <!-- 发帖：无 id -->
    <view v-if="mode === 'compose'" class="post__compose">
      <textarea
        v-model="content"
        class="post__textarea"
        maxlength="2000"
        placeholder="分享今天的饮食或运动心得…"
      />
      <view class="post__switch">
        <text class="post__label">匿名发布</text>
        <switch :checked="anonymous" color="#22c55e" @change="onAnonymous" />
      </view>
      <view class="post__switch">
        <text class="post__label">类型</text>
        <radio-group class="post__types" @change="onType">
          <label v-for="t in TYPES" :key="t.value" class="post__type">
            <radio :value="String(t.value)" :checked="postType === t.value" color="#22c55e" />
            <text>{{ t.label }}</text>
          </label>
        </radio-group>
      </view>
      <CButton block :loading="submitting" @click="submit">发布</CButton>
    </view>

    <!-- 详情：带 id -->
    <template v-else>
      <CSkeleton v-if="loading" type="card" />
      <CError v-else-if="error" @retry="loadDetail" />
      <template v-else-if="post">
        <view class="post-card">
          <view class="post-card__head">
            <text class="post-card__name">{{ post.user.nickname }}</text>
            <text class="post-card__time">{{ fmtTime(post.created_at) }}</text>
          </view>
          <text v-if="post.title" class="post-card__title">{{ post.title }}</text>
          <text class="post-card__content">{{ post.content }}</text>
          <view class="post-card__foot">
            <text class="post-card__action" @tap="toggleLike">
              <image
                class="post-card__act-icon"
                :src="post.liked ? '/static/icons/ic-heart.png' : '/static/icons/ic-heart-o.png'"
                mode="aspectFit"
              />
              {{ post.like_count }}
            </text>
            <text class="post-card__action">
              <image class="post-card__act-icon" src="/static/icons/ic-chat.png" mode="aspectFit" />
              {{ post.comment_count }}
            </text>
            <text v-if="post.anonymous" class="post-card__time">匿名</text>
          </view>
        </view>

        <view class="post__comments">
          <text class="post__section">评论</text>
          <CEmpty v-if="!comments.length" icon="empty-chat" text="还没有评论" button-text="" />
          <view v-for="c in comments" :key="c.id" class="comment">
            <text class="comment__name">{{ c.user.nickname }}</text>
            <text class="comment__content">{{ c.content }}</text>
          </view>
        </view>

        <view class="post__bar">
          <input v-model="draft" class="post__input" placeholder="写评论…" maxlength="500" />
          <CButton size="sm" :loading="commenting" @click="submitComment">发送</CButton>
        </view>
      </template>
    </template>
  </view>
</template>

<script setup lang="ts">
/**
 * FE5 · 动态（发帖 / 详情 / 点赞 / 评论）— Phase 4 (M4)
 * 契约：POST /api/community/post、GET /api/community/post/{id}、.../like、.../comment*
 * 【假设】无 id=发帖页；带 id=详情页。违规内容后端返回 audit_status=0，进审核队列不展示。
 */
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'

import {
  createComment,
  createPost,
  getPost,
  likePost,
  listComments,
  unlikePost,
} from '@/api/community'
import type { CommunityCommentOut, CommunityPostOut } from '@/types/api'
import { useToast } from '@/composables/useToast'

const toast = useToast()

const TYPES = [
  { value: 1, label: '动态' },
  { value: 2, label: '经验' },
  { value: 3, label: '打卡' },
] as const

const mode = ref<'compose' | 'detail'>('compose')
const postId = ref(0)

/* 发帖态 */
const content = ref('')
const anonymous = ref(false)
const postType = ref<1 | 2 | 3>(1)
const submitting = ref(false)

/* 详情态 */
const loading = ref(false)
const error = ref(false)
const post = ref<CommunityPostOut | null>(null)
const comments = ref<CommunityCommentOut[]>([])
const draft = ref('')
const commenting = ref(false)

function fmtTime(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString()
}

function onAnonymous(e: Event) {
  const detail = (e as unknown as { detail: { value: boolean } }).detail
  anonymous.value = Boolean(detail.value)
}

function onType(e: Event) {
  const detail = (e as unknown as { detail: { value: string } }).detail
  postType.value = Number(detail.value) as 1 | 2 | 3
}

async function submit() {
  if (!content.value.trim()) {
    toast.info({ title: '请输入内容' })
    return
  }
  submitting.value = true
  try {
    const res = await createPost({
      content: content.value.trim(),
      anonymous: anonymous.value,
      post_type: postType.value,
    })
    toast.info({
      title: res.audit_status === 0 ? '已提交，审核通过后展示' : '发布成功',
    })
    setTimeout(() => uni.navigateBack(), 600)
  } catch {
    // request 层已 toast
  } finally {
    submitting.value = false
  }
}

async function loadDetail() {
  loading.value = true
  error.value = false
  try {
    post.value = await getPost(postId.value)
    comments.value = (await listComments(postId.value, { page_size: 50 })).items
  } catch {
    error.value = true
  } finally {
    loading.value = false
  }
}

async function toggleLike() {
  if (!post.value) return
  try {
    const res = post.value.liked ? await unlikePost(post.value.id) : await likePost(post.value.id)
    post.value.liked = res.liked
    post.value.like_count = res.like_count
  } catch {
    // request 层已 toast；失败不改本地态
  }
}

async function submitComment() {
  if (!draft.value.trim() || !post.value) {
    toast.info({ title: '请输入评论' })
    return
  }
  commenting.value = true
  try {
    await createComment(post.value.id, { content: draft.value.trim() })
    draft.value = ''
    await loadDetail()
  } catch {
    // request 层已 toast
  } finally {
    commenting.value = false
  }
}

onLoad((options?: Record<string, string>) => {
  const id = Number(options?.id || 0)
  if (id) {
    mode.value = 'detail'
    postId.value = id
    void loadDetail()
  }
})
</script>

<style lang="scss" scoped>
.post {
  padding: $space-md;
  padding-bottom: calc(#{$space-xl} + env(safe-area-inset-bottom));

  &__compose {
    padding: $space-md;
    background: $card;
    border-radius: $radius;
    box-shadow: $shadow;
  }

  &__textarea {
    width: 100%;
    height: 260rpx;
    padding: $space-sm;
    font-size: $t-26;
    background: $bg;
    border-radius: $radius-sm;
  }

  &__switch {
    @include flex-between;

    padding: $space-sm 0;
  }

  &__label {
    font-size: $t-26;
    color: $text-1;
  }

  &__types {
    display: flex;
    gap: $space-md;
  }

  &__type {
    display: flex;
    align-items: center;
    font-size: $t-24;
    color: $text-2;
  }

  &__comments {
    margin-top: $space-md;
  }

  &__section {
    display: block;
    margin-bottom: $space-sm;
    font-size: $t-28;
    font-weight: 600;
    color: $text-1;
  }

  &__bar {
    display: flex;
    align-items: center;
    gap: $space-sm;
    margin-top: $space-md;
  }

  &__input {
    flex: 1;
    height: 72rpx;
    padding: 0 $space-sm;
    font-size: $t-26;
    background: $card;
    border: 1rpx solid $border;
    border-radius: $radius-sm;
  }
}

.post-card {
  padding: $space-md;
  background: $card;
  border-radius: $radius;
  box-shadow: $shadow;

  &__head {
    @include flex-between;

    margin-bottom: $space-xs;
  }

  &__name {
    font-size: $t-26;
    font-weight: 500;
    color: $text-1;
  }

  &__time {
    font-size: $t-22;
    color: $text-3;
  }

  &__title {
    display: block;
    margin-bottom: $space-xs;
    font-size: $t-28;
    font-weight: 600;
    color: $text-1;
  }

  &__content {
    display: block;
    font-size: $t-26;
    color: $text-1;
  }

  &__foot {
    display: flex;
    gap: $space-lg;
    margin-top: $space-sm;
  }

  &__action {
    display: flex;
    align-items: center;
    gap: 6rpx;
    font-size: $t-24;
    color: $text-2;
  }

  &__act-icon {
    width: 30rpx;
    height: 30rpx;
  }
}

.comment {
  padding: $space-sm 0;
  border-top: 1rpx solid $border;

  &__name {
    display: block;
    font-size: $t-24;
    color: $text-2;
  }

  &__content {
    display: block;
    font-size: $t-26;
    color: $text-1;
  }
}
</style>
