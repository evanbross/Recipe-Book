/*!
 * Copyright (c) 2026 ZombieTech LLC. All rights reserved.
 *
 * SPDX-License-Identifier: PolyForm-Strict-1.0.0
 * See LICENSE in the project root for the full terms.
 *
 * Licensing inquiries: license@zombietech.biz
 */
// ai: claude-opus-5-5 | 2026-11-17
import { Navigate } from 'react-router-dom'
import { isNotSignedIn, useMe } from '../api/useMe'

/** Renders its children only for a signed-in user; otherwise sends them to /login. */
export default function RequireAuth({ children }) {
  const { isPending, error } = useMe()

  if (isPending) return null
  if (isNotSignedIn(error)) return <Navigate to="/login" replace />
  if (error) {
    return (
      <div className="empty-state">
        <h3>Can&apos;t reach Recipe App</h3>
        <p>The server didn&apos;t answer. Is it running?</p>
      </div>
    )
  }
  return children
}
