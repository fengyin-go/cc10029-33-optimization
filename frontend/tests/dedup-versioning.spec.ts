import { expect, test } from '@playwright/test'

/**
 * 去重策略版本化重算 E2E：
 * 阈值调整 -> 数据报告（旧/新阈值、范围、保留记录、重复证据、口径冲突、调用链）
 * -> 报告确认 -> 去重落地清单 -> 存储业务面回写展示 -> 版本唯一当前。
 */
test.describe('去重策略版本化重算', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/dedup')
    // 已启用的种子策略 DEDU-0003（id=3）必须存在，可在其上发起重算。
    await expect(page.getByTestId('recompute-3')).toBeVisible()
  })

  test('阈值重算生成数据报告，可对照新旧保留记录与重复证据', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (e) => errors.push(e.message))
    page.on('response', (r) => {
      if (r.url().includes('/api/') && r.status() >= 400 && r.status() !== 409) {
        errors.push(`${r.status()} ${r.url()}`)
      }
    })

    // 在已启用策略 DEDU-0003 上发起阈值重算
    const targetRow = page.locator('tbody tr', { hasText: 'DEDU-0003' })
    await targetRow.getByTestId('recompute-3').click()
    await expect(page.getByTestId('recompute-panel')).toBeVisible()
    await expect(page.getByTestId('recompute-old')).toHaveValue('0.8')

    await page.getByTestId('recompute-new').fill('0.7')
    await page.getByTestId('submit-recompute').click()

    const reportPanel = page.getByTestId('report-panel')
    await expect(reportPanel).toBeVisible()

    // 报告必须记录旧阈值、新阈值与重新判定范围
    await expect(reportPanel).toContainText('0.8 → 0.7')
    await expect(reportPanel).toContainText('全量历史批次')

    // 新旧口径保留记录对照与新口径重复证据都可回看
    await expect(page.getByTestId('old-caliber-row')).toContainText('旧口径')
    await expect(page.getByTestId('new-caliber-row')).toContainText('新口径')
    const evidenceRows = page.getByTestId('evidence-table').locator('tbody tr')
    expect(await evidenceRows.count()).toBeGreaterThan(0)
    await expect(evidenceRows.first()).toContainText('0.7')

    // 存在口径冲突明细，且数据来源调用链可追溯
    await expect(page.getByTestId('conflict-table')).toBeVisible()
    await expect(page.getByTestId('trace-chain')).toBeVisible()
    await expect(page.getByTestId('trace-chain')).toContainText('去重策略数据报告')

    // 去重版本面板：同一策略只有一个当前版本
    await expect(page.getByTestId('version-panel')).toBeVisible()
    const currentRows = page.getByTestId('version-panel').locator('tbody tr[data-current="true"]')
    await expect(currentRows).toHaveCount(1)

    expect(errors).toEqual([])
  })

  test('指定范围重算时范围外记录不标记新口径，落地清单回写存储面', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (e) => errors.push(e.message))
    page.on('response', (r) => {
      if (r.url().includes('/api/') && r.status() >= 400 && r.status() !== 409) {
        errors.push(`${r.status()} ${r.url()}`)
      }
    })

    await page.getByTestId('recompute-3').click()
    await page.getByTestId('recompute-new').fill('0.6')
    await page.getByTestId('recompute-scope-mode').selectOption('partial')
    await page.getByTestId('recompute-batches').fill('BATCH-A,BATCH-B')
    await page.getByTestId('submit-recompute').click()

    const reportPanel = page.getByTestId('report-panel')
    await expect(reportPanel).toBeVisible()
    // 覆盖 9 条、范围外 3 条，范围外表格列出 BATCH-C 的记录
    await expect(reportPanel).toContainText('9 / 3')
    const outOfScope = page.getByTestId('out-of-scope-table').locator('tbody tr')
    expect(await outOfScope.count()).toBe(3)

    // 确认报告后生成去重落地清单（内联成功消息，不弹模态框）
    await page.getByTestId('confirm-report').click()
    await expect(page.getByTestId('confirm-report')).toBeDisabled()
    await page.getByTestId('write-landing').click()
    await expect(page.getByTestId('landing-message')).toContainText('去重落地清单')

    // 跳到存储落地业务面，验证回写的去重落地清单同源可见
    await page.goto('/storage', { waitUntil: 'domcontentloaded' })
    const landingPanel = page.getByTestId('dedup-landing-panel')
    await expect(landingPanel).toBeVisible()
    const landingRows = page.getByTestId('dedup-landing-table').locator('tbody tr[data-testid^="landing-row-"]')
    await expect(landingRows.first()).toBeVisible()
    expect(await landingRows.count()).toBeGreaterThanOrEqual(3)
    // 清单中既有新口径判定，也保留未进入范围记录的原口径标记
    const panelText = await landingPanel.innerText()
    expect(panelText).toContain('新口径')
    expect(panelText).toContain('未进入重算范围')

    expect(errors).toEqual([])
  })
})
