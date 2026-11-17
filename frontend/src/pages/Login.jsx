/*!
 * Copyright (c) 2026 ZombieTech LLC. All rights reserved.
 *
 * SPDX-License-Identifier: PolyForm-Strict-1.0.0
 * See LICENSE in the project root for the full terms.
 *
 * Licensing inquiries: license@zombietech.biz
 */
// ai: claude-opus-5-5 | 2026-11-17
import { Navigate, useSearchParams } from 'react-router-dom'
import { BookOpen } from 'lucide-react'
import { SIGN_IN_URL } from '../api/client'
import { useMe } from '../api/useMe'
import styles from './Login.module.css'

// Keys are the error codes the API's sign-in routes redirect back with.
const ERROR_MESSAGES = {
  not_invited: "This Google account hasn't been invited. Ask the household owner to invite your email address.",
  unverified_email: "Google hasn't verified this account's email address, so it can't be used to sign in.",
  cancelled: 'Sign-in was cancelled.',
  expired: 'That sign-in took too long or was already used. Please try again.',
  google_error: "Couldn't complete sign-in with Google. Please try again.",
  not_configured: "Sign-in isn't set up on this server (Google credentials or API_PORT missing). Check the server log.",
}

export default function Login() {
  const [params] = useSearchParams()
  const { data: me } = useMe()
  const errorCode = params.get('error')

  if (me) return <Navigate to="/" replace />

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <div className={styles.logo}><BookOpen size={26} /> RecipeBox</div>
        {errorCode && (
          <p className={styles.error} role="alert">
            {ERROR_MESSAGES[errorCode] ?? "Couldn't sign in. Please try again."}
          </p>
        )}
        <a className={`btn btn-primary ${styles.signIn}`} href={SIGN_IN_URL}>
          Sign in with Google
        </a>
      </div>
    </div>
  )
}
