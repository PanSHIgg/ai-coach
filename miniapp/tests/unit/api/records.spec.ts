/**
 * api/records · 微信运动步数同步（scope.werun 授权预检 / 后端真源解读 / 文案单一真源）
 *
 * 为什么必须是新文件：
 *  - tests/unit/api/restApis.spec.ts 的模型是「薄封装 → 断言 request() 调用契约 + 结果原样透传」，
 *    且只覆盖 task/privacy/report；本文件的步数链路含**客户端授权状态机**与**后端 steps_source 解读**，
 *    必须给全局 uni 注入 getSetting/authorize/getWeRunData 三个小程序能力桩并按分支同步回包，
 *    与 restApis「mockResolvedValue(哨兵) 即结束」的用例结构不兼容（合并会让它背上用不到的桩装配）。
 *  - tests/unit/api/merchantAdmin.spec.ts 锁在商家 token 域，同样不导入 @/api/records。
 *  - tests/helpers/uni.ts 的基桩刻意不含这三个能力（只读文件，不在本用例可写范围），故桩在本文件内装配、
 *    afterEach 归还，不污染其它 spec。
 *
 * 环境事实（src/api/request.ts:25-26 已固化）：**vitest 不做 uni 条件编译**，源码里 #ifdef MP-WEIXIN
 * 与 #ifndef MP-WEIXIN 两段都会执行。因此本文件的断言口径是：
 *  - preflightWeRunAuth 的分支判定 → 通过「uni.getSetting / authorize / getWeRunData 是否被调用」断言
 *    （这是可观测的本项目行为，不依赖被抢先 resolve 的 promise 结果）；
 *  - syncStepsFromWeRun 返回的 status 由同步执行的 #ifndef 分支先 resolve，**不是**微信端语义结果，
 *    故不对其断言（§2.9：不断言编译管线/框架自身行为）；三态语义改由纯函数 describeStepsSync 直接覆盖；
 *  - 同一原因（已实测：getSetting 返回 scope.werun=true 且 getWeRunData 成功回包时，上报体仍是
 *    {date, steps:0}、status 仍是 unavailable），「取到加密数据 → payload 带 encrypted_data/iv」这条
 *    分支在单测里不可达，只能由真机/小程序端验证，故本文件不设该用例（写了必红）；
 *  - 能力桩回调一律**同步回包**，沿用 tests/unit/api/merchantAdmin.spec.ts 的 respond() 约定。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { request } from '@/api/request'
import { describeStepsSync, syncStepsFromWeRun } from '@/api/records'
import type { WeRunStepsSyncResult, WeRunSyncStatus, StepsSource } from '@/api/records'
import type { StepsSyncData } from '@/types/api'
import type { UniMock } from '../../helpers/uni'

vi.mock('@/api/request', () => ({ request: vi.fn() }))

const requestMock = vi.mocked(request)

/** 本用例需要的三个小程序能力桩（基桩 UniMock 不含，见文件头说明） */
interface WeRunUniMock extends UniMock {
  getSetting: ReturnType<typeof vi.fn>
  authorize: ReturnType<typeof vi.fn>
  getWeRunData: ReturnType<typeof vi.fn>
}

const uni = (globalThis as unknown as { uni: WeRunUniMock }).uni

type Callbacks<TRes> = { success?: (res: TRes) => void; fail?: (err: { errMsg: string }) => void }

interface WeRunScenario {
  /** getSetting 回包的 authSetting；微信实际在「未决定」时省略 scope.werun 键 */
  authSetting?: Record<string, boolean>
  /** getSetting 直接失败（授权态不可判定） */
  settingFails?: boolean
  /** authorize 被拒绝 */
  authorizeFails?: boolean
  /** getWeRunData 取到的加密数据；缺省 = 取不到（模拟器无计步数据 / fail） */
  weRunData?: { encryptedData: string; iv: string }
}

/** 按微信端语义装配能力桩：回调同步回包，未配置的数据一律走 fail（不伪造） */
function stubWeRun(scenario: WeRunScenario = {}) {
  uni.getSetting.mockImplementation((opts: Callbacks<{ authSetting: Record<string, boolean> }>) => {
    if (scenario.settingFails) opts.fail?.({ errMsg: 'getSetting:fail' })
    else opts.success?.({ authSetting: scenario.authSetting ?? {} })
  })
  uni.authorize.mockImplementation((opts: Callbacks<unknown>) => {
    if (scenario.authorizeFails) opts.fail?.({ errMsg: 'authorize:fail' })
    else opts.success?.({})
  })
  uni.getWeRunData.mockImplementation((opts: Callbacks<{ encryptedData: string; iv: string }>) => {
    if (scenario.weRunData) opts.success?.(scenario.weRunData)
    else opts.fail?.({ errMsg: 'getWeRunData:fail' })
  })
}

beforeEach(() => {
  requestMock.mockReset()
  uni.getSetting = vi.fn()
  uni.authorize = vi.fn()
  uni.getWeRunData = vi.fn()
})

afterEach(() => {
  const bag = uni as unknown as Record<string, unknown>
  delete bag.getSetting
  delete bag.authorize
  delete bag.getWeRunData
})

/** 后端 8,000 步 / 校准 33 kcal 的真实回包样例（千分位与估算措辞都在此可见） */
const SYNC_DATE = '2026-10-02'
const ENCRYPTED = { encryptedData: 'cipher-blob', iv: 'cipher-iv' }

/* ---------- ① steps_source 是文案唯一真源（表驱动单用例） ---------- */

interface WordingCase {
  name: string
  status: WeRunSyncStatus
  /** 后端 steps_source；undefined = 字段缺失（联调期），按最保守口径 */
  source: StepsSource | undefined
  /** 后端回传的实际入库步数 */
  steps: number
  /** 期望：文案能否宣称「已同步微信运动 N 步」 */
  claimsReal: boolean
  /** 期望：是否给「去开启微信运动」引导（仅未授权） */
  needGuide: boolean
}

const wordingCases: WordingCase[] = [
  { name: 'steps_source=1 → 唯一可说「已同步微信运动」', status: 'granted', source: 1, steps: 8000, claimsReal: true, needGuide: false },
  { name: 'steps_source=2（用客户端传入 steps）→ 估算口径', status: 'granted', source: 2, steps: 0, claimsReal: false, needGuide: false },
  { name: 'steps_source=3（按 PAL 估算）→ 估算口径', status: 'granted', source: 3, steps: 0, claimsReal: false, needGuide: false },
  { name: 'steps_source 缺失 → 最保守估算口径', status: 'granted', source: undefined, steps: 0, claimsReal: false, needGuide: false },
  { name: 'unauthorized（未授权）→ 估算口径 + 引导', status: 'unauthorized', source: 3, steps: 0, claimsReal: false, needGuide: true },
  { name: 'unavailable（已授权但没取到加密数据）→ 估算口径无引导', status: 'unavailable', source: 3, steps: 0, claimsReal: false, needGuide: false },
]

describe('describeStepsSync · 文案与引导以后端 steps_source 为唯一真源', () => {
  it.each(wordingCases)('$name', (c) => {
    /** describeStepsSync 只从 data 读 delta_calories，真源/步数取 res.source / res.steps */
    const data = {
      neat_calibrated: 0,
      met: 0,
      delta_calories: 33,
      steps: c.steps,
      steps_source: c.source ?? 3,
    } satisfies StepsSyncData
    const res: WeRunStepsSyncResult = {
      data,
      status: c.status,
      source: c.source,
      // 与 syncStepsFromWeRun 的推导保持一致：只有后端确认 source===1 才算真实步数
      isRealSteps: c.source === 1,
      steps: c.steps,
    }

    const msg = describeStepsSync(res)

    expect(msg.tone).toBe(c.claimsReal ? 'success' : 'info')
    expect(msg.title.includes('已同步微信运动')).toBe(c.claimsReal)
    // 非真源一律「按活动水平估算」措辞，且不得报出步数冒充微信运动结果
    expect(msg.title.includes('按活动水平估算')).toBe(!c.claimsReal)
    expect(/\d[\d,]*\s*步/.test(msg.title)).toBe(c.claimsReal)
    expect(msg.sourceLabel.includes('微信运动真实数据')).toBe(c.claimsReal)
    // 引导入口只属于「未授权」，估算降级不可误导用户去 openSetting
    expect(msg.needGuide).toBe(c.needGuide)
  })
})

/**
 * 回填措辞（G3a 的 31 天回填是曲线唯一能被填满的来源，措辞必须只跟随后端确认）。
 * 独立于 wordingCases：那批用例断言的是"能不能说真实步数"，这里断言的是"能不能说回填了历史"，
 * 两者正交——尤其最后一行：估算分支即使收到 backfilled_days 也不许报，否则等于谎称有历史。
 */
const backfillCases = [
  { name: 'source=1 且 backfilled_days=30 → Toast 与来源行都说回填', source: 1 as const, backfilled: 30, mentions: true },
  { name: 'source=1 但缺 backfilled_days → 不提回填', source: 1 as const, backfilled: undefined, mentions: false },
  { name: 'source=1 但 backfilled_days=0 → 不提回填', source: 1 as const, backfilled: 0, mentions: false },
  { name: 'source=2 即使带 backfilled_days=30 → 绝不提回填（防谎报历史）', source: 2 as const, backfilled: 30, mentions: false },
]

describe('describeStepsSync · 「已回填 N 天历史」只跟随后端确认', () => {
  it.each(backfillCases)('$name', (c) => {
    const data = {
      neat_calibrated: 0,
      met: 0,
      delta_calories: 33,
      steps: 8000,
      steps_source: c.source,
      ...(c.backfilled === undefined ? {} : { backfilled_days: c.backfilled }),
    } satisfies StepsSyncData
    const msg = describeStepsSync({
      data,
      status: 'granted',
      source: c.source,
      isRealSteps: c.source === 1,
      steps: 8000,
    })
    expect(msg.title.includes('回填')).toBe(c.mentions)
    expect(msg.sourceLabel.includes('回填')).toBe(c.mentions)
  })
})

/* ---------- ② 后端真源/步数读取：非法值安全 + 拿不到加密数据仍上报 steps:0 ---------- */

interface SyncCase {
  name: string
  /** /api/steps/sync 的后端回包（联调期可能缺字段或给出非法值） */
  response: Record<string, unknown>
  source: StepsSource | undefined
  isRealSteps: boolean
  steps: number
}

const syncCases: SyncCase[] = [
  { name: 'steps_source=1 → 真源与步数均以后端为准', response: { steps_source: 1, steps: 8123, delta_calories: 33 }, source: 1, isRealSteps: true, steps: 8123 },
  { name: 'steps_source=7（非法）→ 不认作真源', response: { steps_source: 7, steps: 8123 }, source: undefined, isRealSteps: false, steps: 8123 },
  { name: 'steps=-5（非法）→ 归零，不回退任何客户端常量', response: { steps_source: 3, steps: -5 }, source: 3, isRealSteps: false, steps: 0 },
  { name: '回包缺 steps_source/steps → 最保守口径', response: {}, source: undefined, isRealSteps: false, steps: 0 },
]

describe('syncStepsFromWeRun · 上报契约与后端真源读取', () => {
  it.each(syncCases)('$name', async (c) => {
    // 已授权但取不到加密数据（开发者工具模拟器无计步数据）
    stubWeRun({ authSetting: { 'scope.werun': true } })
    requestMock.mockResolvedValue(c.response)

    const res = await syncStepsFromWeRun(SYNC_DATE)

    // 取不到加密数据也必须发出本次同步：steps 传 0 交后端按 PAL 估算，且不夹带任何伪造字段
    expect(requestMock).toHaveBeenCalledWith('/api/steps/sync', {
      method: 'POST',
      data: { date: SYNC_DATE, steps: 0 },
    })
    expect(res.source).toBe(c.source)
    expect(res.isRealSteps).toBe(c.isRealSteps)
    expect(res.steps).toBe(c.steps)
  })
})

/* ---------- ③ scope.werun 授权预检三条分支（微信官方口径） ---------- */

interface AuthCase {
  name: string
  scenario: WeRunScenario
  /** 期望是否走到取加密数据（= 预检判定为已授权） */
  fetchesWeRun: boolean
  authorizeCalls: number
}

const authCases: AuthCase[] = [
  {
    name: '已授权（scope.werun === true）→ 直接放行，不再 authorize',
    scenario: { authSetting: { 'scope.werun': true }, weRunData: ENCRYPTED },
    fetchesWeRun: true,
    authorizeCalls: 0,
  },
  {
    name: '曾明确拒绝（=== false）→ 判未授权且不得再调 authorize（微信此时不弹框）',
    scenario: { authSetting: { 'scope.werun': false } },
    fetchesWeRun: false,
    authorizeCalls: 0,
  },
  {
    name: '未决定（键不存在）→ 才用 authorize 主动申请',
    scenario: { authSetting: {}, weRunData: ENCRYPTED },
    fetchesWeRun: true,
    authorizeCalls: 1,
  },
  {
    name: '未决定且本次拒绝 → 不再取微信运动数据',
    scenario: { authSetting: {}, authorizeFails: true },
    fetchesWeRun: false,
    authorizeCalls: 1,
  },
]

describe('preflightWeRunAuth · scope.werun 三态（true/false/缺键）', () => {
  it.each(authCases)('$name', async (c) => {
    stubWeRun(c.scenario)
    requestMock.mockResolvedValue({ steps_source: 3, steps: 0 })

    await syncStepsFromWeRun(SYNC_DATE)

    expect(uni.getSetting).toHaveBeenCalledTimes(1)
    expect(uni.authorize).toHaveBeenCalledTimes(c.authorizeCalls)
    if (c.authorizeCalls) {
      expect(uni.authorize).toHaveBeenCalledWith(expect.objectContaining({ scope: 'scope.werun' }))
    }
    expect(uni.getWeRunData).toHaveBeenCalledTimes(c.fetchesWeRun ? 1 : 0)
  })
})
