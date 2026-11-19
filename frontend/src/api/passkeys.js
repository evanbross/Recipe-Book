/*!
 * Copyright (c) 2026 ZombieTech LLC. All rights reserved.
 *
 * SPDX-License-Identifier: PolyForm-Strict-1.0.0
 * See LICENSE in the project root for the full terms.
 *
 * Licensing inquiries: license@zombietech.biz
 */
// ai: claude-opus-5-5 | 2026-11-19
// Each passkey ceremony: ask the API for options, let the browser and the
// authenticator answer them (@simplewebauthn/browser), send the answer back.
import { startAuthentication, startRegistration } from '@simplewebauthn/browser'
import {
  passkeyLoginOptions, passkeyLoginVerify, passkeyRegisterOptions, passkeyRegisterVerify,
  reauthPasskeyOptions, reauthPasskeyVerify,
} from './client'

/** Whether this browser can use passkeys at all. */
export const passkeysSupported = () => typeof window !== 'undefined' && window.PublicKeyCredential !== undefined

/** The user closed the browser's passkey prompt, or it timed out: nothing to report. */
export const isPasskeyCancelled = (err) => err?.name === 'NotAllowedError' || err?.name === 'AbortError'

/** Sign in with whichever passkey the user picks; the passkey names the account. */
export async function signInWithPasskey() {
  const { flow_id: flowId, options } = await passkeyLoginOptions()
  const credential = await startAuthentication({ optionsJSON: options })
  await passkeyLoginVerify(flowId, credential)
}

/** Create a passkey for the signed-in user. Resolves to the stored passkey. */
export async function addPasskey(name) {
  const { flow_id: flowId, options } = await passkeyRegisterOptions()
  const credential = await startRegistration({ optionsJSON: options })
  return passkeyRegisterVerify(flowId, credential, name)
}

/** Prove it's you again with one of your own passkeys. */
export async function reauthWithPasskey() {
  const { flow_id: flowId, options } = await reauthPasskeyOptions()
  const credential = await startAuthentication({ optionsJSON: options })
  await reauthPasskeyVerify(flowId, credential)
}
