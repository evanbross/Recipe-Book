/*!
 * Copyright (c) 2026 ZombieTech LLC. All rights reserved.
 *
 * SPDX-License-Identifier: PolyForm-Strict-1.0.0
 * See LICENSE in the project root for the full terms.
 *
 * Licensing inquiries: license@zombietech.biz
 */
// ai: claude-opus-5-5 | 2026-11-14
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import toast from 'react-hot-toast'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  getEmailAuthStatus, getEmailSettings, getHousehold, getMe, getWatchedSites, updateEmailSettings,
} from '../api/client'
import { renderWithProviders } from '../test/render'
import Settings from './Settings'

vi.mock('../api/client')
vi.mock('react-hot-toast', () => ({ default: { error: vi.fn(), success: vi.fn() } }))

const SAVED = {
  auto_import: false,
  labels: ['Dinner', 'Baking'],
  scan_inbox: true,
  inbox_lookback_days: 14,
  max_per_folder: 25,
}

// ai: claude-opus-5-5 | 2026-11-17
const ME = { user: { id: 1, email: 'owner@example.com', display_name: 'Owner' }, household: { id: 1, name: 'Home' }, role: 'owner' }
const HOUSEHOLD = {
  id: 1,
  name: 'Home',
  members: [
    { user_id: 1, email: 'owner@example.com', display_name: 'Owner', role: 'owner' },
    { user_id: 2, email: 'cook@example.com', display_name: null, role: 'member' },
  ],
  invites: [{ id: 7, email: 'guest@example.com', created_at: '2026-11-17T00:00:00Z' }],
}

const updatePayloads = () => updateEmailSettings.mock.calls.map(([variables]) => variables)

describe('Settings — email scan form', () => {
  beforeEach(() => {
    getEmailAuthStatus.mockResolvedValue({ authenticated: true })
    getEmailSettings.mockResolvedValue(SAVED)
    getWatchedSites.mockResolvedValue([])
    getMe.mockResolvedValue(ME)  // ai: claude-opus-5-5 | 2026-11-17
    getHousehold.mockResolvedValue(HOUSEHOLD)
    updateEmailSettings.mockImplementation((data) => Promise.resolve(data))
  })

  it('fills the form from the saved settings', async () => {
    renderWithProviders(<Settings />)

    expect(await screen.findByLabelText('Inbox lookback')).toHaveValue(14)
    expect(screen.getByLabelText('Max per folder')).toHaveValue(25)
    expect(screen.getByRole('checkbox', { name: /Auto-import/ })).not.toBeChecked()
    expect(screen.getByRole('checkbox', { name: /Scan Inbox/ })).toBeChecked()
    expect(screen.getByRole('button', { name: 'Remove Dinner' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove Baking' })).toBeInTheDocument()
  })

  it('saves the edited values', async () => {
    const user = userEvent.setup()
    renderWithProviders(<Settings />)
    const lookback = await screen.findByLabelText('Inbox lookback')

    await user.clear(lookback)
    await user.type(lookback, '7')
    await user.click(screen.getByRole('button', { name: 'Remove Baking' }))
    await user.click(screen.getByRole('button', { name: /Save Settings/ }))

    await waitFor(() => expect(updatePayloads()).toEqual([{ ...SAVED, labels: ['Dinner'], inbox_lookback_days: 7 }]))
  })

  it('rejects an empty lookback without saving', async () => {
    // Out-of-range numbers are already stopped by the input's native min/max
    // validation; an empty field passes that (not `required`) and reaches the JS check.
    const user = userEvent.setup()
    renderWithProviders(<Settings />)
    const lookback = await screen.findByLabelText('Inbox lookback')

    await user.clear(lookback)
    await user.click(screen.getByRole('button', { name: /Save Settings/ }))

    expect(toast.error).toHaveBeenCalledWith('Enter a valid number of days (minimum 1).')
    expect(updateEmailSettings).not.toHaveBeenCalled()
  })

  it('re-syncs the form when the settings are refetched after a save', async () => {
    const user = userEvent.setup()
    renderWithProviders(<Settings />)
    const maxPerFolder = await screen.findByLabelText('Max per folder')
    // The server normalizes what it stores; the refetch must win over local state.
    getEmailSettings.mockResolvedValue({ ...SAVED, max_per_folder: 100 })

    await user.click(screen.getByRole('button', { name: /Save Settings/ }))

    await waitFor(() => expect(maxPerFolder).toHaveValue(100))
  })
})
