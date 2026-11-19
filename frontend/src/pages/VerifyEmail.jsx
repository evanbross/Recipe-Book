/*!
 * Copyright (c) 2026 ZombieTech LLC. All rights reserved.
 *
 * SPDX-License-Identifier: PolyForm-Strict-1.0.0
 * See LICENSE in the project root for the full terms.
 *
 * Licensing inquiries: license@zombietech.biz
 */
// ai: claude-opus-5-5 | 2026-11-19
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { verifyEmail } from '../api/client'
import { ME_QUERY_KEY } from '../api/useMe'
import AuthCard from '../components/AuthCard'
import { errorCode, messageForCode, messageForError } from '../utils/authMessages'

/** The emailed sign-up link lands here: create the account and sign in. */
export default function VerifyEmail() {
  const [params] = useSearchParams()
  const token = params.get('token')
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [error, setError] = useState(token ? null : messageForCode('invalid_token'))
  const [notInvited, setNotInvited] = useState(false)
  // The link is single-use: StrictMode's second effect run must not post it again.
  const hasPosted = useRef(false)

  useEffect(() => {
    if (!token || hasPosted.current) return
    hasPosted.current = true
    verifyEmail(token)
      .then(async () => {
        await queryClient.invalidateQueries({ queryKey: ME_QUERY_KEY })
        navigate('/', { replace: true })
      })
      .catch((err) => {
        if (errorCode(err) === 'not_invited') setNotInvited(true)
        else setError(messageForError(err))
      })
  }, [token, navigate, queryClient])

  if (notInvited) {
    return (
      <AuthCard title="Email confirmed">
        <p>
          Your account is ready, but it isn&apos;t part of a household yet. Ask a household owner to
          invite your email address, then sign in.
        </p>
        <Link to="/login">Go to sign in</Link>
      </AuthCard>
    )
  }
  if (error) {
    return (
      <AuthCard title="Couldn't confirm your email" error={error}>
        <Link to="/register">Sign up again</Link>
      </AuthCard>
    )
  }
  return <AuthCard title="Confirming your email…" />
}
