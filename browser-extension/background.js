/*!
 * Copyright (c) 2026 ZombieTech LLC. All rights reserved.
 *
 * SPDX-License-Identifier: PolyForm-Strict-1.0.0
 * See LICENSE in the project root for the full terms.
 *
 * Licensing inquiries: license@zombietech.biz
 */

// ai: claude-opus-5-5 | 2026-11-16
// Service worker: does the capture so it keeps running after the popup closes.
// It reads the tab's HTML as the browser loaded it (sites like Serious Eats refuse
// the server's own fetch) and posts it to the app's /capture/html route.

import { captureKey, getAppUrl } from './config.js';

// Claude extraction usually takes 10-60 s. Chrome 116+ keeps the worker alive
// while a fetch is pending, so this is the real upper bound.
const CAPTURE_TIMEOUT_MS = 180_000;

const BADGES = {
    working: { text: '…', color: '#6b7280' },
    saved: { text: '✓', color: '#16a34a' },
    error: { text: '!', color: '#dc2626' },
};

// Tabs with a capture in flight; guards against a double click starting two.
const inFlight = new Set();

// ai: claude-opus-5-5 | 2026-11-16
function isCaptureMessage(message) {
    return message?.type === 'capture'
        && Number.isInteger(message.tabId)
        && typeof message.tabUrl === 'string'
        && Array.isArray(message.tagIds)
        && message.tagIds.every(Number.isInteger);
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!isCaptureMessage(message)) {
        return false;
    }
    captureTab(message.tabId, message.tabUrl, message.tagIds);  // ai: claude-opus-5-5 | 2026-11-16
    sendResponse({ started: true });
    return false;
});

chrome.tabs.onRemoved.addListener((tabId) => {
    chrome.storage.session.remove(captureKey(tabId));
});

async function captureTab(tabId, tabUrl, tagIds) {
    if (inFlight.has(tabId)) {
        return;
    }
    inFlight.add(tabId);
    try {
        await setState(tabId, { tabUrl, status: 'working' });
        const outcome = await runCapture(tabId, tagIds);  // ai: claude-opus-5-5 | 2026-11-16
        await setState(tabId, { tabUrl, ...outcome });
    } finally {
        inFlight.delete(tabId);
    }
}

async function runCapture(tabId, tagIds) {
    let page;
    try {
        const [injection] = await chrome.scripting.executeScript({
            target: { tabId },
            func: () => ({ url: location.href, html: document.documentElement.outerHTML }),
        });
        page = injection?.result;
    } catch (err) {
        console.warn('[capture] could not read tab', tabId, err);
        return failure("This page can't be read by extensions (browser pages and extension stores are off-limits).");
    }
    if (!page?.html) {
        return failure('Could not read this page.');
    }

    const appUrl = await getAppUrl();
    let res;
    try {
        res = await fetch(`${appUrl}/api/capture/html`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: page.url, html: page.html, tag_ids: tagIds }),  // ai: claude-opus-5-5 | 2026-11-16
            signal: AbortSignal.timeout(CAPTURE_TIMEOUT_MS),
        });
    } catch (err) {
        if (err.name === 'TimeoutError') {
            return failure(`Recipe App didn't answer within ${CAPTURE_TIMEOUT_MS / 1000} seconds.`);
        }
        console.warn('[capture] request failed', err);
        return failure(`Could not reach Recipe App at ${appUrl}. Is it running?`);
    }

    const body = await res.json().catch(() => null);
    if (!res.ok) {
        return failure(describeError(res.status, body));
    }
    // ai: claude-opus-5-5 | 2026-11-16
    // When the app isn't running, Caddy still answers 200 with an empty body, so
    // res.ok alone doesn't mean a recipe was saved.
    if (!Number.isInteger(body?.id)) {
        return failure(`Recipe App isn't answering at ${appUrl}. Is it running?`);
    }
    return {
        status: 'saved',
        title: body.title || '(untitled)',
        recipeUrl: `${appUrl}/recipes/${body.id}`,
    };
}

// FastAPI reports HTTPException errors as {detail: "..."} and request-validation
// errors (e.g. HTML over the size limit) as {detail: [{msg: "..."}, ...]}.
function describeError(status, body) {
    const detail = body?.detail;
    if (typeof detail === 'string') {
        return detail;
    }
    if (Array.isArray(detail) && detail.length > 0) {
        return `Recipe App rejected the page: ${detail.map((d) => d?.msg).filter(Boolean).join('; ')}`;
    }
    return `Recipe App error (HTTP ${status}).`;
}

function failure(message) {
    return { status: 'error', message };
}

async function setState(tabId, state) {
    await chrome.storage.session.set({ [captureKey(tabId)]: state });
    const badge = BADGES[state.status];
    try {
        await chrome.action.setBadgeBackgroundColor({ tabId, color: badge.color });
        await chrome.action.setBadgeText({ tabId, text: badge.text });
    } catch (err) {
        // The tab was closed while the capture ran; there is no badge to update.
        console.debug('[capture] badge not updated', tabId, err);
    }
}
