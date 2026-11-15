/*!
 * Copyright (c) 2026 ZombieTech LLC. All rights reserved.
 *
 * SPDX-License-Identifier: PolyForm-Strict-1.0.0
 * See LICENSE in the project root for the full terms.
 *
 * Licensing inquiries: license@zombietech.biz
 */
// ai: claude-opus-5-5 | 2026-11-14
import { act, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  getEmailAuthStatus, getEmailScanStatus, getEmailSettings, startEmailScan,
} from '../api/client'
import { renderWithProviders } from '../test/render'
import EmailScanTab from './EmailScanTab'

vi.mock('../api/client')
vi.mock('react-hot-toast', () => ({ default: { error: vi.fn(), success: vi.fn() } }))

const IDLE = { running: false, processed: 0, total: 0, imported: 0, no_recipe: 0, errors: [] }

function runningSince(msAgo) {
  return {
    ...IDLE, running: true, processed: 3, total: 10,
    started_at: new Date(Date.now() - msAgo).toISOString(),
  }
}

describe('EmailScanTab', () => {
  beforeEach(() => {
    getEmailAuthStatus.mockResolvedValue({ authenticated: true })
    getEmailSettings.mockResolvedValue({ auto_import: true, labels: ['Cooking'], scan_inbox: false })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('opens the progress dialog on load when a scan is already running', async () => {
    getEmailScanStatus.mockResolvedValue(runningSince(5_000))

    renderWithProviders(<EmailScanTab />)

    expect(await screen.findByRole('heading', { name: 'Scanning Gmail…' })).toBeInTheDocument()
  })

  it('stays closed when idle, and opens when a scan is started', async () => {
    getEmailScanStatus.mockResolvedValue(IDLE)
    startEmailScan.mockImplementation(() => {
      getEmailScanStatus.mockResolvedValue(runningSince(0))
      return Promise.resolve({ started: true })
    })
    const user = userEvent.setup()
    renderWithProviders(<EmailScanTab />)

    const scanButton = await screen.findByRole('button', { name: /Scan Now/ })
    expect(screen.queryByRole('heading', { name: 'Scanning Gmail…' })).not.toBeInTheDocument()

    await user.click(scanButton)

    expect(await screen.findByRole('heading', { name: 'Scanning Gmail…' })).toBeInTheDocument()
  })

  it('ticks the elapsed time while a scan runs', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    getEmailScanStatus.mockResolvedValue(runningSince(5_000))
    renderWithProviders(<EmailScanTab />)

    expect(await screen.findByText(/5s elapsed/)).toBeInTheDocument()

    await act(() => vi.advanceTimersByTimeAsync(3_000))

    expect(screen.getByText(/8s elapsed/)).toBeInTheDocument()
  })
})
