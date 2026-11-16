/*!
 * Copyright (c) 2026 ZombieTech LLC. All rights reserved.
 *
 * SPDX-License-Identifier: PolyForm-Strict-1.0.0
 * See LICENSE in the project root for the full terms.
 *
 * Licensing inquiries: license@zombietech.biz
 */

// ai: claude-opus-5-5 | 2026-11-16
// Options page: where the Recipe App runs. Saving asks the browser for permission
// to reach that address, then checks the app answers on it.

import { DEFAULT_APP_URL, getAppUrl, setAppUrl } from './config.js';

const form = document.getElementById('form');
const input = document.getElementById('app-url');
const statusEl = document.getElementById('status');

document.getElementById('default-url').textContent = DEFAULT_APP_URL;
input.value = await getAppUrl();

function show(message, kind) {
    statusEl.className = `status ${kind}`;
    statusEl.textContent = message;
}

form.addEventListener('submit', async (event) => {
    event.preventDefault();

    let origin;
    try {
        const parsed = new URL(input.value.trim());
        if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
            throw new TypeError('not http(s)');
        }
        origin = parsed.origin;
    } catch {
        show(`Enter a full address such as ${DEFAULT_APP_URL}`, 'error');
        return;
    }

    // Must be the first await: the browser only shows the permission prompt
    // while it still counts as part of the user's click.
    const granted = await chrome.permissions.request({ origins: [`${origin}/*`] });
    if (!granted) {
        show("Not saved: the extension can't send recipes to that address without permission.", 'error');
        return;
    }
    await setAppUrl(origin);
    input.value = origin;

    try {
        const res = await fetch(`${origin}/api/health`, { signal: AbortSignal.timeout(5000) });
        if (!res.ok) {
            show(`Saved, but ${origin}/api/health answered HTTP ${res.status}. Is that the Recipe App?`, 'error');
            return;
        }
        show('Saved. Recipe App is reachable.', 'ok');
    } catch {
        show(`Saved, but Recipe App isn't answering at ${origin}. Is it running?`, 'error');
    }
});
