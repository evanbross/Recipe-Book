/*!
 * Copyright (c) 2026 ZombieTech LLC. All rights reserved.
 *
 * SPDX-License-Identifier: PolyForm-Strict-1.0.0
 * See LICENSE in the project root for the full terms.
 *
 * Licensing inquiries: license@zombietech.biz
 */
// ai: claude-opus-5-5 | 2026-11-17
import { useQuery } from '@tanstack/react-query'
import { getMe } from './client'

export const ME_QUERY_KEY = ['me']

export const isNotSignedIn = (error) => error?.response?.status === 401

/** The signed-in user, household and role. A 401 is an answer ("not signed
 *  in"), not a failure worth retrying. */
export function useMe() {
  return useQuery({
    queryKey: ME_QUERY_KEY,
    queryFn: getMe,
    staleTime: 5 * 60_000,
    retry: (failureCount, error) => !isNotSignedIn(error) && failureCount < 1,
  })
}
