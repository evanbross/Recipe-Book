/*!
 * Copyright (c) 2026 ZombieTech LLC. All rights reserved.
 *
 * SPDX-License-Identifier: PolyForm-Strict-1.0.0
 * See LICENSE in the project root for the full terms.
 *
 * Licensing inquiries: license@zombietech.biz
 */
// ai: claude-opus-5-5 | 2026-11-19
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { getMe, passwordLogin } from '../api/client'
import RequireAuth from '../components/RequireAuth'
import { renderWithProviders } from '../test/render'
import Login from './Login'

vi.mock('../api/client', () => ({
  getMe: vi.fn(),
  passwordLogin: vi.fn(),
  passkeyLoginOptions: vi.fn(),
  passkeyLoginVerify: vi.fn(),
  SIGN_IN_URL: '/api/auth/login',
}))

const notSignedIn = () => Object.assign(new Error('401'), { response: { status: 401 } })
const apiError = (status, detail, headers = {}) =>
  Object.assign(new Error(String(status)), { response: { status, data: { detail }, headers } })

function renderRoutes(route) {
  return renderWithProviders(
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/" element={<RequireAuth><p>Recipes</p></RequireAuth>} />
    </Routes>,
    { route },
  )
}

async function signInWithPassword(user) {
  await user.type(await screen.findByLabelText('Email'), 'cook@example.com')
  await user.type(screen.getByLabelText('Password'), 'some password')
  await user.click(screen.getByRole('button', { name: 'Sign in' }))
}

describe('sign-in', () => {
  afterEach(() => { delete window.PublicKeyCredential })

  it('sends a signed-out user from the app to the login page', async () => {
    getMe.mockRejectedValue(notSignedIn())
    renderRoutes('/')

    expect(await screen.findByRole('link', { name: 'Sign in with Google' })).toHaveAttribute('href', '/api/auth/login')
    expect(screen.queryByText('Recipes')).not.toBeInTheDocument()
  })

  it('shows the app to a signed-in user', async () => {
    getMe.mockResolvedValue({ user: { id: 1, email: 'a@example.com' }, household: { id: 1, name: 'H' }, role: 'owner' })
    renderRoutes('/')
    expect(await screen.findByText('Recipes')).toBeInTheDocument()
  })

  it('offers all three methods when the browser supports passkeys', async () => {
    window.PublicKeyCredential = function PublicKeyCredential() {}
    getMe.mockRejectedValue(notSignedIn())
    renderRoutes('/login')

    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Sign in with a passkey/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Sign in with Google' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Create an account' })).toHaveAttribute('href', '/register')
    expect(screen.getByRole('link', { name: 'Forgot password?' })).toHaveAttribute('href', '/forgot-password')
  })

  it('hides the passkey button when the browser has no passkeys', async () => {
    getMe.mockRejectedValue(notSignedIn())
    renderRoutes('/login')
    await screen.findByRole('button', { name: 'Sign in' })
    expect(screen.queryByRole('button', { name: /passkey/ })).not.toBeInTheDocument()
  })

  it.each([
    ['not_invited', /hasn't been invited/],
    ['link_required', /link Google from Settings/],
    ['already_linked', /already linked/],
    ['invalid_token', /expired or was already used/],
  ])('explains ?error=%s', async (code, text) => {
    getMe.mockRejectedValue(notSignedIn())
    renderRoutes(`/login?error=${code}`)
    expect(await screen.findByRole('alert')).toHaveTextContent(text)
  })

  it('explains a wrong password without leaving the page', async () => {
    getMe.mockRejectedValue(notSignedIn())
    passwordLogin.mockRejectedValue(apiError(401, 'invalid_credentials'))
    const user = userEvent.setup({ delay: null })
    renderRoutes('/login')

    await signInWithPassword(user)

    expect(await screen.findByRole('alert')).toHaveTextContent(/didn't match/)
    expect(passwordLogin).toHaveBeenCalledWith('cook@example.com', 'some password')
  })

  it('says how long to wait after too many attempts', async () => {
    getMe.mockRejectedValue(notSignedIn())
    passwordLogin.mockRejectedValue(apiError(429, 'too_many_attempts', { 'retry-after': '600' }))
    const user = userEvent.setup({ delay: null })
    renderRoutes('/login')

    await signInWithPassword(user)

    expect(await screen.findByRole('alert')).toHaveTextContent('wait 10 minutes')
  })

  it('goes to the app after a successful password sign-in', async () => {
    getMe.mockRejectedValueOnce(notSignedIn())
    passwordLogin.mockResolvedValue({})
    const user = userEvent.setup({ delay: null })
    renderRoutes('/login')
    getMe.mockResolvedValue({ user: { id: 1, email: 'cook@example.com' }, household: { id: 1, name: 'H' }, role: 'member' })

    await signInWithPassword(user)

    await waitFor(() => expect(screen.getByText('Recipes')).toBeInTheDocument())
  })
})
