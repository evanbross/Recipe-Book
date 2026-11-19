/*!
 * Copyright (c) 2026 ZombieTech LLC. All rights reserved.
 *
 * SPDX-License-Identifier: PolyForm-Strict-1.0.0
 * See LICENSE in the project root for the full terms.
 *
 * Licensing inquiries: license@zombietech.biz
 */
// ai: claude-opus-5-5 | 2026-11-19
// The one place sign-in error codes become text. Codes arrive two ways: as
// ?error=<code> after a Google redirect, and as an API error's `detail`.

export const REAUTH_REQUIRED = 'reauth_required'

const MESSAGES = {
  // Google redirects
  not_invited: "This account hasn't been invited yet. Ask the household owner to invite your email address.",
  unverified_email: "This account's email address hasn't been verified, so it can't be used to sign in.",
  cancelled: 'Sign-in was cancelled.',
  expired: 'That took too long or was already used. Please try again.',
  google_error: "Couldn't complete sign-in with Google. Please try again.",
  not_configured: "Google sign-in isn't set up on this server (Google credentials or API_PORT missing). Check the server log.",
  link_required:
    'That Google account has the same email as an account that signs in another way. Sign in that way, '
    + 'then link Google from Settings.',
  already_linked: 'That Google account is already linked to an account.',
  reauth_failed: "Google didn't ask for your password just now, so it can't confirm it's you. Please try again.",
  reauth_wrong_account: "That isn't a Google account linked to you. Choose one you've linked.",
  // API errors
  invalid_credentials: "That didn't match. Check the email and password, or try another way to sign in.",
  invalid_credential: "That passkey couldn't be saved. Please try again.",
  invalid_token: 'That link has expired or was already used. Please ask for a new one.',
  email_failed: "We couldn't send the email just now. Please try again in a few minutes.",
  last_method: "You can't remove your only way to sign in. Add another one first.",
  untrusted_origin: 'That change has to be made from the app itself.',
  [REAUTH_REQUIRED]: "Please confirm it's you first.",
  not_found: 'That no longer exists.',
}

const WEAK_PASSWORD = {
  too_short: 'Use at least 12 characters.',
  too_long: 'Use at most 256 characters.',
  same_as_email: "Your password can't be your email address.",
}

/** The error code an API error carries, or null (network failure, odd body). */
export function errorCode(err) {
  const detail = err?.response?.data?.detail
  return typeof detail === 'string' ? detail : null
}

/** Text for a code, from ?error= or an API detail. */
export function messageForCode(code) {
  if (code?.startsWith('weak_password:')) {
    return WEAK_PASSWORD[code.slice('weak_password:'.length)] ?? 'Choose a stronger password.'
  }
  return MESSAGES[code] ?? 'Something went wrong. Please try again.'
}

/** Text for an API error, including throttling ("wait N minutes"). */
export function messageForError(err) {
  if (!err?.response) return "Can't reach Recipe App. Is the server running?"
  if (err.response.status === 429) {
    const seconds = Number(err.response.headers?.['retry-after'])
    const minutes = Number.isFinite(seconds) && seconds > 0 ? Math.ceil(seconds / 60) : 15
    return `Too many tries. Please wait ${minutes} minute${minutes === 1 ? '' : 's'} and try again.`
  }
  return messageForCode(errorCode(err))
}

/** The server wants the user to prove it's them again before this change. */
export const isReauthRequired = (err) => err?.response?.status === 403 && errorCode(err) === REAUTH_REQUIRED
