/*!
 * Copyright (c) 2026 ZombieTech LLC. All rights reserved.
 *
 * SPDX-License-Identifier: PolyForm-Strict-1.0.0
 * See LICENSE in the project root for the full terms.
 *
 * Licensing inquiries: license@zombietech.biz
 */
// ai: claude-opus-5-5 | 2026-11-19
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import toast from 'react-hot-toast'
import { getSignInMethods, reauthPassword, removePasskey, removePassword } from '../api/client'
import { renderWithProviders } from '../test/render'
import SignInMethodsSection from './SignInMethodsSection'

vi.mock('../api/client')
vi.mock('react-hot-toast', () => ({ default: { error: vi.fn(), success: vi.fn() } }))

const REAUTH = Object.assign(new Error('403'), { response: { status: 403, data: { detail: 'reauth_required' } } })
const PASSKEY = { id: 3, name: 'Laptop', created_at: '2026-11-19T00:00:00Z', last_used_at: null, backed_up: true }
const methodsWith = (overrides) => ({
  has_password: false, passkeys: [], google: [], reauth_valid_until: '2026-11-19T00:00:00Z', ...overrides,
})

describe('SignInMethodsSection', () => {
  beforeEach(() => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
  })

  it("won't let the user remove their only method", async () => {
    getSignInMethods.mockResolvedValue(methodsWith({ passkeys: [PASSKEY] }))
    renderWithProviders(<SignInMethodsSection />)
    expect(await screen.findByRole('button', { name: 'Remove Laptop' })).toBeDisabled()
  })

  it('lets the user remove a method when they have another', async () => {
    getSignInMethods.mockResolvedValue(methodsWith({ has_password: true, passkeys: [PASSKEY] }))
    removePasskey.mockResolvedValue({})
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<SignInMethodsSection />)

    await user.click(await screen.findByRole('button', { name: 'Remove Laptop' }))

    await waitFor(() => expect(removePasskey).toHaveBeenCalledWith(3))
    expect(toast.success).toHaveBeenCalledWith('Passkey removed.')
  })

  it('asks the user to confirm it is them, then retries the change once', async () => {
    getSignInMethods.mockResolvedValue(methodsWith({ has_password: true, passkeys: [PASSKEY] }))
    removePassword.mockRejectedValueOnce(REAUTH).mockResolvedValueOnce({})
    reauthPassword.mockResolvedValue({})
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<SignInMethodsSection />)

    await user.click(await screen.findByRole('button', { name: 'Remove' }))
    const dialog = await screen.findByRole('dialog', { name: "Confirm it's you" })
    await user.type(within(dialog).getByLabelText('Your password'), 'my password')
    await user.click(within(dialog).getByRole('button', { name: 'Confirm' }))

    await waitFor(() => expect(removePassword).toHaveBeenCalledTimes(2))
    expect(reauthPassword).toHaveBeenCalledWith('my password')
    expect(toast.success).toHaveBeenCalledWith('Password removed.')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('shows an error instead of a second dialog if the retry is refused too', async () => {
    getSignInMethods.mockResolvedValue(methodsWith({ has_password: true, passkeys: [PASSKEY] }))
    removePassword.mockRejectedValue(REAUTH)
    reauthPassword.mockResolvedValue({})
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<SignInMethodsSection />)

    await user.click(await screen.findByRole('button', { name: 'Remove' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('Your password'), 'my password')
    await user.click(within(dialog).getByRole('button', { name: 'Confirm' }))

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Please confirm it's you first."))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('offers only the methods the user has in the dialog', async () => {
    getSignInMethods.mockResolvedValue(methodsWith({
      passkeys: [PASSKEY], google: [{ id: 9, email: 'cook@gmail.com', created_at: '2026-11-19T00:00:00Z' }],
    }))
    removePasskey.mockRejectedValue(REAUTH)
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<SignInMethodsSection />)

    await user.click(await screen.findByRole('button', { name: 'Remove Laptop' }))
    const dialog = await screen.findByRole('dialog')

    expect(within(dialog).queryByLabelText('Your password')).not.toBeInTheDocument()
    expect(within(dialog).getByRole('link', { name: 'Continue with Google' })).toHaveAttribute(
      'href', '/api/auth/reauth/google',
    )
  })

  it('explains the result of a Google round trip', async () => {
    getSignInMethods.mockResolvedValue(methodsWith({ has_password: true }))
    renderWithProviders(<SignInMethodsSection />, { route: '/settings?error=already_linked' })
    expect(await screen.findByRole('status')).toHaveTextContent(/already linked/)
  })
})
