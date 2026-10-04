<template>
  <view class="post">
    <view v-if="mode === 'compose'" class="post__compose">
      <textarea
        v-model="content"
        class="post__textarea"
        maxlength="2000"
        placeholder="分享今天的饮食或运动心得…"
      />
      <!-- 图片（COS 直传，最多 3 张） -->
      <view class="post__images">
        <view v-for="(p, i) in imagePaths" :key="p" class="post__image-item">
          <image class="post__image" :src="p" mode="aspectFill" />
          <text class="post__image-del" @tap="removeImage(i)">×</text>
        </view>
        <view
          v-if="imagePaths.length < MAX_IMAGES"
          class="post__image-add"
          @tap="chooseImages"
        >
          <text class="post__image-add-icon">＋</text>
          <text class="post__image-add-text">图片</text>
        </view>
      </view>

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
            <image
              v-if="!post.anonymous && post.user.avatar_url && !avatarFail[post.user.id]"
              class="post-card__avatar"
              :src="post.user.avatar_url"
              mode="aspectFill"
              @error="avatarFail[post.user.id] = true"
            />
            <view v-else class="post-card__avatar post-card__avatar--ph">
              <text class="post-card__avatar-txt">{{ avatarText(post.anonymous ? '匿' : post.user.nickname) }}</text>
            </view>
            <view class="post-card__meta">
              <text class="post-card__name">{{ post.anonymous ? '匿名' : post.user.nickname }}</text>
              <text class="post-card__time">{{ fmtTime(post.created_at) }}</text>
            </view>
          </view>
          <text v-if="post.title" class="post-card__title">{{ post.title }}</text>
          <text class="post-card__content">{{ post.content }}</text>
          <view v-if="post.images?.length" class="post-card__images">
            <image
              v-for="(img, i) in post.images"
              :key="i"
              class="post-card__image"
              :src="img"
              mode="aspectFill"
            />
          </view>
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
          </view>
        </view>

        <view class="post__comments">
          <text class="post__section">评论</text>
          <CEmpty v-if="!comments.length" icon="empty-chat" text="还没有评论" button-text="" />
          <view v-for="c in comments" :key="c.id" class="comment">
            <image
              v-if="!c.anonymous && c.user.avatar_url && !avatarFail[c.user.id]"
              class="comment__avatar"
              :src="c.user.avatar_url"
              mode="aspectFill"
              @error="avatarFail[c.user.id] = true"
            />
            <view v-else class="comment__avatar comment__avatar--ph">
              <text class="comment__avatar-txt">{{ avatarText(c.anonymous ? '匿' : c.user.nickname) }}</text>
            </view>
            <view class="comment__body">
              <text class="comment__name">{{ c.anonymous ? '匿名' : c.user.nickname }}</text>
              <text class="comment__content">{{ c.content }}</text>
            </view>
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
import { uploadImage } from '@/utils/upload'

const toast = useToast()

/** 发帖最多 3 张图（COS 直传，公开读 URL 写入 images） */
const MAX_IMAGES = 3

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
/** 已选本地图片（提交时直传 COS → images） */
const imagePaths = ref<string[]>([])

/* 详情态 */
const loading = ref(false)
const error = ref(false)
const post = ref<CommunityPostOut | null>(null)
const comments = ref<CommunityCommentOut[]>([])
const draft = ref('')
const commenting = ref(false)
/** 点赞/取消的in-flight 守卫：快速双击时后一次直接返回，不发重复请求
 * （后端 like/unlike 幂等，无数据不一致，但会多打一次请求）。 */
const liking = ref(false)
/** 头像加载失败的用户 id → 回退首字占位圆 */
const avatarFail = ref<Record<number, boolean>>({})

function fmtTime(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString()
}

/** 头像占位：取昵称首字符 */
function avatarText(nickname: string): string {
  return nickname ? nickname.slice(0, 1) : '友'
}

function onAnonymous(e: Event) {
  const detail = (e as unknown as { detail: { value: boolean } }).detail
  anonymous.value = Boolean(detail.value)
}

function onType(e: Event) {
  const detail = (e as unknown as { detail: { value: string } }).detail
  postType.value = Number(detail.value) as 1 | 2 | 3
}

/** 选择图片（最多 MAX_IMAGES 张） */
function chooseImages() {
  const remain = MAX_IMAGES - imagePaths.value.length
  if (remain <= 0) return
  uni.chooseImage({
    count: remain,
    sizeType: ['compressed'],
    sourceType: ['album', 'camera'],
    success: (res) => {
      imagePaths.value = [...imagePaths.value, ...(res.tempFilePaths as string[])]
    },
  })
}

/** 移除已选图片 */
function removeImage(index: number) {
  imagePaths.value.splice(index, 1)
}

async function submit() {
  if (!content.value.trim()) {
    toast.info({ title: '请输入内容' })
    return
  }
  submitting.value = true
  try {
    // 图片直传 COS（公开读 URL）；配置缺失/失败会返回 null，若有图但全部失败则中止
    let images: string[] = []
    if (imagePaths.value.length) {
      const urls = await Promise.all(imagePaths.value.map((p) => uploadImage(p, 'post')))
      images = urls.filter((u): u is string => !!u)
      if (!images.length) {
        toast.error({ title: '图片上传失败，请重试或去掉图片' })
        return
      }
    }
    const res = await createPost({
      content: content.value.trim(),
      anonymous: anonymous.value,
      post_type: postType.value,
      images,
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
  if (!post.value || liking.value) return
  liking.value = true
  try {
    const res = post.value.liked ? await unlikePost(post.value.id) : await likePost(post.value.id)
    post.value.liked = res.liked
    post.value.like_count = res.like_count
  } catch {
    // request 层已 toast；失败不改本地态
  } finally {
    liking.value = false
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
    border: 1rpx solid $disabled; // 比 $border 深一档：卡片边界更明显
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

  &__images {
    display: flex;
    flex-wrap: wrap;
    gap: $space-sm;
    margin-top: $space-sm;
  }

  &__image-item {
    position: relative;
    width: 160rpx;
    height: 160rpx;
  }

  &__image {
    width: 160rpx;
    height: 160rpx;
    border-radius: $radius-sm;
  }

  &__image-del {
    position: absolute;
    top: -12rpx;
    right: -12rpx;
    width: 40rpx;
    height: 40rpx;
    font-size: $t-26;
    line-height: 40rpx;
    color: #fff;
    text-align: center;
    background: $danger;
    border-radius: 50%;
  }

  &__image-add {
    @include flex-center(column);

    width: 160rpx;
    height: 160rpx;
    background: $bg;
    border: 1rpx dashed $border;
    border-radius: $radius-sm;
  }

  &__image-add-icon {
    font-size: 44rpx;
    color: $text-3;
  }

  &__image-add-text {
    font-size: $t-22;
    color: $text-3;
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
    padding: $space-md;
    margin-top: $space-md;
    background: $card;
    border: 1rpx solid $disabled; // 比 $border 深一档：卡片边界更明显
    border-radius: $radius;
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
    border: 1rpx solid $disabled; // 比 $border 深一档：卡片边界更明显
    border-radius: $radius-sm;
  }
}

.post-card {
  padding: $space-md;
  background: $card;
  border: 1rpx solid $disabled; // 比 $border 深一档：卡片边界更明显
  border-radius: $radius;
  box-shadow: $shadow;

  &__head {
    display: flex;
    align-items: center;
    gap: $space-sm;
    margin-bottom: $space-sm;
  }

  &__avatar {
    flex-shrink: 0;
    width: 80rpx;
    height: 80rpx;
    background: $bg;
    border-radius: 50%;

    &--ph {
      @include flex-center;

      background: rgba($brand, 0.15);
    }
  }

  &__avatar-txt {
    font-size: $t-28;
    font-weight: 600;
    color: $brand-dark;
  }

  &__meta {
    display: flex;
    flex: 1;
    flex-direction: column;
    gap: 2rpx;
    min-width: 0;
  }

  &__name {
    font-size: $t-24;
    font-weight: 600;
    color: $text-2;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
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
    font-size: $t-28;
    line-height: 1.6;
    color: $text-1;
  }

  &__images {
    display: flex;
    flex-wrap: wrap;
    gap: $space-sm;
    margin-top: $space-sm;
  }

  &__image {
    width: 200rpx;
    height: 200rpx;
    border-radius: $radius-sm;
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
  display: flex;
  gap: $space-sm;
  padding: $space-sm 0;
  border-top: 1rpx solid $border;

  &__avatar {
    flex-shrink: 0;
    width: 56rpx;
    height: 56rpx;
    background: $bg;
    border-radius: 50%;

    &--ph {
      @include flex-center;

      background: rgba($brand, 0.15);
    }
  }

  &__avatar-txt {
    font-size: $t-22;
    font-weight: 600;
    color: $brand-dark;
  }

  &__body {
    flex: 1;
    min-width: 0;
  }

  &__name {
    display: block;
    margin-bottom: 4rpx;
    font-size: $t-22;
    font-weight: 600;
    color: $text-2;
  }

  &__content {
    display: block;
    font-size: $t-26;
    line-height: 1.6;
    color: $text-1;
  }
}
</style>
