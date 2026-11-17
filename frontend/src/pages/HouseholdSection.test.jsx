/*!
 * Copyright (c) 2026 ZombieTech LLC. All rights reserved.
 *
 * SPDX-License-Identifier: PolyForm-Strict-1.0.0
 * See LICENSE in the project root for the full terms.
 *
 * Licensing inquiries: license@zombietech.biz
 */
// ai: claude-opus-5-5 | 2026-11-17
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getHousehold, getMe, inviteToHousehold, removeHouseholdMember, revokeInvite } from '../api/client'
import { renderWithProviders } from '../test/render'
import HouseholdSection from './HouseholdSection'

vi.mock('../api/client')
vi.mock('react-hot-toast', () => ({ default: { error: vi.fn(), success: vi.fn() } }))

const HOUSEHOLD = {
  id: 1,
  name: 'Home',
  members: [
    { user_id: 1, email: 'owner@example.com', display_name: 'Owner', role: 'owner' },
    { user_id: 2, email: 'cook@example.com', display_name: null, role: 'member' },
  ],
  invites: [{ id: 7, email: 'guest@example.com', created_at: '2026-11-17T00:00:00Z' }],
}
const meAs = (role, id = 1) => ({
  user: { id, email: 'x@example.com', display_name: null }, household: { id: 1, name: 'Home' }, role,
})

describe('HouseholdSection', () => {
  beforeEach(() => {
    getHousehold.mockResolvedValue(HOUSEHOLD)
    inviteToHousehold.mockImplementation((email) => Promise.resolve({ id: 8, email, created_at: '' }))
    revokeInvite.mockResolvedValue({})
    removeHouseholdMember.mockResolvedValue({})
  })

  it('lets the owner invite an email', async () => {
    getMe.mockResolvedValue(meAs('owner'))
    const user = userEvent.setup()
    renderWithProviders(<HouseholdSection />)

    await user.type(await screen.findByLabelText('Email address to invite'), '  new@example.com ')
    await user.click(screen.getByRole('button', { name: /Invite/ }))

    await waitFor(() => expect(inviteToHousehold).toHaveBeenCalled())
    expect(inviteToHousehold.mock.calls[0][0]).toBe('new@example.com')
  })

  it('lets the owner remove others (after confirming) but not themselves', async () => {
    getMe.mockResolvedValue(meAs('owner'))
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const user = userEvent.setup()
    renderWithProviders(<HouseholdSection />)

    await user.click(await screen.findByRole('button', { name: 'Remove cook@example.com' }))
    await waitFor(() => expect(removeHouseholdMember).toHaveBeenCalled())
    expect(removeHouseholdMember.mock.calls[0][0]).toBe(2)
    expect(screen.queryByRole('button', { name: 'Remove owner@example.com' })).not.toBeInTheDocument()
  })

  it('lets the owner cancel a pending invite', async () => {
    getMe.mockResolvedValue(meAs('owner'))
    const user = userEvent.setup()
    renderWithProviders(<HouseholdSection />)

    await user.click(await screen.findByRole('button', { name: 'Cancel invite for guest@example.com' }))
    await waitFor(() => expect(revokeInvite).toHaveBeenCalled())
    expect(revokeInvite.mock.calls[0][0]).toBe(7)
  })

  it('shows members a read-only list', async () => {
    getMe.mockResolvedValue(meAs('member', 2))
    renderWithProviders(<HouseholdSection />)

    expect(await screen.findByText('guest@example.com')).toBeInTheDocument()
    expect(screen.getByText(/Only the household owner/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Email address to invite')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Remove/ })).not.toBeInTheDocument()
  })
})
