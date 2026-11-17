/*!
 * Copyright (c) 2026 ZombieTech LLC. All rights reserved.
 *
 * SPDX-License-Identifier: PolyForm-Strict-1.0.0
 * See LICENSE in the project root for the full terms.
 *
 * Licensing inquiries: license@zombietech.biz
 */
// ai: claude-opus-5-5 | 2026-11-17
import { screen } from '@testing-library/react'
import { Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { getMe } from '../api/client'
import RequireAuth from '../components/RequireAuth'
import { renderWithProviders } from '../test/render'
import Login from './Login'

vi.mock('../api/client', () => ({ getMe: vi.fn(), SIGN_IN_URL: '/api/auth/login' }))

const notSignedIn = () => Object.assign(new Error('401'), { response: { status: 401 } })

function renderRoutes(route) {
  return renderWithProviders(
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/" element={<RequireAuth><p>Recipes</p></RequireAuth>} />
    </Routes>,
    { route },
  )
}

describe('sign-in', () => {
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

  it('explains a refused sign-in', async () => {
    getMe.mockRejectedValue(notSignedIn())
    renderRoutes('/login?error=not_invited')
    expect(await screen.findByRole('alert')).toHaveTextContent(/hasn't been invited/)
  })
})
