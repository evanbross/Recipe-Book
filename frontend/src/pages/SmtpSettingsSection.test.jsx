/*!
 * Copyright (c) 2026 ZombieTech LLC. All rights reserved.
 *
 * SPDX-License-Identifier: PolyForm-Strict-1.0.0
 * See LICENSE in the project root for the full terms.
 *
 * Licensing inquiries: license@zombietech.biz
 */
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  getSignInMethods, getSmtpSettings, testSmtpSettings, updateSmtpSettings,
} from '../api/client'
import { useMe } from '../api/useMe'
import { renderWithProviders } from '../test/render'
import SmtpSettingsSection from './SmtpSettingsSection'

vi.mock('../api/client')
vi.mock('../api/useMe')
vi.mock('react-hot-toast', () => ({ default: { error: vi.fn(), success: vi.fn() } }))

const ME = { user: { email: 'admin@example.com' }, is_admin: true }
const SMTP = {
  host: 'smtp.example.com', port: 587, user: 'mailer', use_tls: true,
  from_address: 'recipes@example.com', password_set: true, source: 'database',
}

describe('SmtpSettingsSection', () => {
  // ai: gpt-5 | 2026-11-21
  beforeEach(() => {
    vi.clearAllMocks()
    getSignInMethods.mockResolvedValue({ has_password: true, passkeys: [], google: [] })
  })

  // ai: gpt-5 | 2026-11-21
  it('is hidden from non-admin users', () => {
    useMe.mockReturnValue({ data: { ...ME, is_admin: false } })
    renderWithProviders(<SmtpSettingsSection />)
    expect(screen.queryByRole('heading', { name: 'Outgoing Mail' })).not.toBeInTheDocument()
    expect(getSmtpSettings).not.toHaveBeenCalled()
  })

  // ai: gpt-5 | 2026-11-21
  it('saves server-wide SMTP settings without resending the saved password', async () => {
    useMe.mockReturnValue({ data: ME })
    getSmtpSettings.mockResolvedValue(SMTP)
    updateSmtpSettings.mockResolvedValue({ ...SMTP, host: 'smtp2.example.com' })
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<SmtpSettingsSection />)

    const host = await screen.findByLabelText('SMTP host')
    await waitFor(() => expect(host).toHaveValue('smtp.example.com'))
    await user.clear(host)
    await user.type(host, 'smtp2.example.com')
    await user.click(screen.getByRole('button', { name: 'Save settings' }))

    await waitFor(() => expect(updateSmtpSettings).toHaveBeenCalled())
    expect(updateSmtpSettings.mock.calls[0][0]).toEqual({
      host: 'smtp2.example.com', port: 587, user: 'mailer', password: null,
      use_tls: true, from_address: 'recipes@example.com',
    })
  })

  // ai: gpt-5 | 2026-11-21
  it('sends a test message to the signed-in administrator', async () => {
    useMe.mockReturnValue({ data: ME })
    getSmtpSettings.mockResolvedValue(SMTP)
    testSmtpSettings.mockResolvedValue({})
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<SmtpSettingsSection />)

    const button = await screen.findByRole('button', { name: 'Send test to admin@example.com' })
    await waitFor(() => expect(button).toBeEnabled())
    await user.click(button)
    await waitFor(() => expect(testSmtpSettings).toHaveBeenCalledOnce())
  })
})
