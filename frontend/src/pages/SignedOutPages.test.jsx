/*!
 * Copyright (c) 2026 ZombieTech LLC. All rights reserved.
 *
 * SPDX-License-Identifier: PolyForm-Strict-1.0.0
 * See LICENSE in the project root for the full terms.
 *
 * Licensing inquiries: license@zombietech.biz
 */
// ai: claude-opus-5-5 | 2026-11-19
import { StrictMode } from 'react'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { register, resetPassword, verifyEmail } from '../api/client'
import { renderWithProviders } from '../test/render'
import Register from './Register'
import ResetPassword from './ResetPassword'
import VerifyEmail from './VerifyEmail'

vi.mock('../api/client')

const apiError = (status, detail) => Object.assign(new Error(String(status)), { response: { status, data: { detail } } })

describe('Register', () => {
  async function submit(email) {
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<Register />, { route: '/register' })
    await user.type(screen.getByLabelText('Email'), email)
    await user.type(screen.getByLabelText('Password'), 'twelve chars plus')
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    return screen.findByRole('heading', { name: 'Check your email' })
  }

  it.each(['new@example.com', 'existing@example.com'])(
    'shows the same confirmation for any 202 (%s)', async (email) => {
      register.mockResolvedValue({ status: 202 })
      const heading = await submit(email)
      // Identical wording whether or not the address had an account.
      expect(heading.parentElement).toHaveTextContent(
        `We sent a message to ${email}. Follow the link in it to finish signing up.`,
      )
    },
  )

  it('explains a weak password', async () => {
    register.mockRejectedValue(apiError(422, 'weak_password:same_as_email'))
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<Register />, { route: '/register' })
    await user.type(screen.getByLabelText('Email'), 'cook@example.com')
    await user.type(screen.getByLabelText('Password'), 'cook@example.com')
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    expect(await screen.findByRole('alert')).toHaveTextContent("can't be your email")
  })
})

describe('VerifyEmail', () => {
  const renderVerify = (route) => renderWithProviders(
    <StrictMode>
      <Routes>
        <Route path="/verify-email" element={<VerifyEmail />} />
        <Route path="/" element={<p>Recipes</p>} />
      </Routes>
    </StrictMode>,
    { route },
  )

  it('posts the single-use token once under StrictMode, then opens the app', async () => {
    verifyEmail.mockResolvedValue({})
    renderVerify('/verify-email?token=abc')
    expect(await screen.findByText('Recipes')).toBeInTheDocument()
    expect(verifyEmail).toHaveBeenCalledTimes(1)
    expect(verifyEmail).toHaveBeenCalledWith('abc')
  })

  it('explains a used link', async () => {
    verifyEmail.mockRejectedValue(apiError(400, 'invalid_token'))
    renderVerify('/verify-email?token=abc')
    expect(await screen.findByRole('alert')).toHaveTextContent(/expired or was already used/)
  })

  it('tells a confirmed but uninvited user to ask for an invite', async () => {
    verifyEmail.mockRejectedValue(apiError(403, 'not_invited'))
    renderVerify('/verify-email?token=abc')
    expect(await screen.findByText(/isn't part of a household yet/)).toBeInTheDocument()
  })
})

describe('ResetPassword', () => {
  it('posts only on submit, then asks the user to sign in', async () => {
    resetPassword.mockResolvedValue({})
    const user = userEvent.setup({ delay: null })
    renderWithProviders(<ResetPassword />, { route: '/reset-password?token=t1' })
    expect(resetPassword).not.toHaveBeenCalled()

    await user.type(screen.getByLabelText('New password'), 'a brand new passphrase')
    await user.click(screen.getByRole('button', { name: 'Set password' }))

    await waitFor(() => expect(resetPassword).toHaveBeenCalledWith('t1', 'a brand new passphrase'))
    expect(await screen.findByRole('heading', { name: 'Password changed' })).toBeInTheDocument()
  })
})
