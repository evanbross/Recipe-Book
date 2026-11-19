# Phase 0: Sign-in Methods

**Project:** Recipe App
**Branch:** `evan-2026-11-19-phase0-sign-in-methods` (based on `evan-2026-11-17-google-login`)
**Stack:** FastAPI (sync route handlers, matching the existing routers) + SQLAlchemy 2.x + PostgreSQL + Alembic; React 18 (plain JS, Vite) + TanStack Query + axios
**Goal:** Every user can sign in with a **password**, a **passkey**, or **Google**, and can link several of these to one account. Password accounts verify their email address and can reset a forgotten password; the emails go out through `zt_common.smtp`.

Read this whole document before writing code. Where it says **verify**, check the installed library's actual API instead of trusting this text.

---

## 1. Scope

### In scope
1. Accounts with any mix of: one password, any number of passkeys, any number of linked Google accounts.
2. Password registration with email verification, password sign-in, forgot/reset password, set/change/remove password.
3. Passkey sign-in (no username typed: discoverable credentials), adding, renaming and removing passkeys.
4. Google: stored by Google's stable user ID (`sub`), not by email. Link and unlink Google from Settings.
5. **Re-authentication** ("prove it's you again") before any change to sign-in methods, using any method the user has.
6. Throttling of failed password sign-ins and of outgoing account emails.
7. Frontend: login page with all three methods, register / verify / forgot / reset pages, and a "Sign-in methods" section in Settings.

### Out of scope (later phases — do not build)
- Facebook and Apple sign-in (Phase E). Structure the code so a provider is one more value of `user_identities.provider`, but write no code for them.
- Sessions without a household, the Admin/Household role choice, `AUTH_ADMIN_EMAILS`, home household (Phase A). **The household gate stays exactly as it is now:** after any successful authentication, `SignInService` decides the household; a user with no invite and no allowlist entry gets `not_invited`.
- Changing an account's email address, deleting an account.
- Per-IP throttling. Behind the dev Caddy every request comes from the Docker gateway IP (`172.18.0.1` in `server.log`), so per-IP limits would lump all users together until uvicorn trusts Caddy's `X-Forwarded-For`. Leave a `# TODO(per-ip-throttle)` comment where the throttle lives; it belongs with deployment work.

---

## 2. Decisions already made (do not revisit)

| Topic | Decision |
|---|---|
| Linking | A sign-in method is added **only from Settings, while signed in and recently re-authenticated**. Never merge accounts because two methods share an email address. |
| Legacy Google users | Users created by the current Google flow have no stored `sub`. A Google sign-in whose verified email matches a user with **no** identities, **no** password and **no** passkeys adopts that user (stores the identity). Any other email match is refused with `link_required`. |
| Password storage | argon2id via `argon2-cffi`'s `PasswordHasher()` defaults. Rehash on sign-in when `check_needs_rehash` says so. |
| Password rules | 12–256 characters, must not equal the email address (case-insensitive). No composition rules. |
| Registration | Never reveals whether an address has an account: always `202 Accepted`. The email sent differs (verification link vs. "you already have an account, reset your password here"). The user row is created **only when the link is followed**, so nobody can squat an address by registering it. |
| Passkeys | `webauthn` (py_webauthn) **3.0.1** on the server, `@simplewebauthn/browser` **14.0.0** in the frontend. Resident keys required, user verification preferred, attestation `none`. |
| Relying party | `rp_id` = host of `settings.public_url` (`recipe-app.localhost`), expected origin = `settings.public_url`. Derived, never configured separately. |
| Email | `zt_common.smtp.send_email` with an `SmtpConfig` built from new settings. Locally: `../infra` MailHog, `localhost:11025`, read at http://mailhog.localhost. |
| Re-auth window | 10 minutes (`REAUTH_WINDOW_MINUTES`). |
| Sign-in throttle | 5 failed password attempts per email address in 15 minutes ⇒ `429` until the window passes. Counted for unknown addresses too. |
| Email throttle | 3 account emails per address per hour. Over the limit the request still returns `202` but sends nothing (logged). |

---

## 3. Dependencies

`backend/pyproject.toml` `[project] dependencies` — add:
```
"argon2-cffi>=25.1.0",
"webauthn>=3.0.1,<4",
```
Run `uv lock` and commit `uv.lock`. `zt-common` is already a dependency (`zt_common.smtp`).

`frontend/package.json` `dependencies` — add `"@simplewebauthn/browser": "14.0.0"` (exact pin, like `react-router-dom`). Commit `package-lock.json`.

**Verify** in `@simplewebauthn/browser` 14: `startRegistration({ optionsJSON })` and `startAuthentication({ optionsJSON })` take an object with `optionsJSON` (the v11+ signature) and return the credential JSON to POST back. Check the package's `.d.ts` before writing the calls.

---

## 4. Configuration (`backend/app/config.py`)

Add to `Settings` (keep `SettingsConfigDict`; never `class Config`):

```python
# Account emails (verification, password reset) through zt_common.smtp.
# Defaults reach ../infra's MailHog from the host.
smtp_host: str = "localhost"
smtp_port: int = 11025
smtp_user: str = ""
smtp_password: str = ""
smtp_use_tls: bool = False
smtp_from_address: str = "noreply@recipe-app.local"
reauth_window_minutes: int = 10
```

Add properties (single source of truth — derive, don't add settings):

```python
@property
def webauthn_rp_id(self) -> str:
    """The passkey relying-party ID: the public URL's host."""
    host = urlparse(self.public_url).hostname
    if not host:
        raise ValueError(f"APP_PUBLIC_URL {self.public_url!r} has no host")
    return host

@property
def smtp_config(self) -> SmtpConfig:  # from zt_common.smtp
    ...
```

Add the same keys, commented, to `backend/.env.example` and to the `.env` template string in `config.py` (the one `_ensure_env_file` writes). Keep the three lists identical.

---

## 5. Data model — migration `009_sign_in_methods.py`

`revision = "009"`, `down_revision = "008"`. Models go in `backend/app/database/tenancy.py` next to `User` and `UserSession` (they are user-level, **not** `TenantScoped`). Use `Mapped`/`mapped_column` only; timestamps `DateTime(timezone=True)` with `default=_utcnow` (the module's existing helper).

### 5.1 `users` — add columns
| Column | Type | Notes |
|---|---|---|
| `email_verified_at` | `timestamptz NULL` | Backfill: `UPDATE users SET email_verified_at = created_at` (every existing user came through Google, which verified the address). |
| `webauthn_user_handle` | `bytea NULL UNIQUE` | 32 random bytes, created the first time the user registers a passkey. Never the numeric user ID. |

### 5.2 `user_identities` (new)
| Column | Type | Notes |
|---|---|---|
| `id` | serial PK | |
| `user_id` | FK `users.id` `ON DELETE CASCADE`, indexed | |
| `provider` | `varchar(20)` | `'google'` only in this phase. |
| `subject` | `varchar(255)` | Provider's stable user ID (Google `sub`). |
| `email` | `varchar(320)` | The provider account's email at link time, lower-cased. Display only. |
| `created_at` | `timestamptz` | |
Constraint: `UNIQUE (provider, subject)` named `user_identities_provider_subject_key`.

### 5.3 `password_credentials` (new)
| Column | Type | Notes |
|---|---|---|
| `user_id` | PK, FK `users.id` `ON DELETE CASCADE` | One password per user. |
| `password_hash` | `varchar(255)` | argon2id encoded string. |
| `created_at`, `updated_at` | `timestamptz` | |

### 5.4 `webauthn_credentials` (new)
| Column | Type | Notes |
|---|---|---|
| `id` | serial PK | |
| `user_id` | FK `users.id` `ON DELETE CASCADE`, indexed | |
| `credential_id` | `bytea UNIQUE` | Raw bytes from `VerifiedRegistration.credential_id`. |
| `public_key` | `bytea` | `VerifiedRegistration.credential_public_key`. |
| `sign_count` | `bigint` | Update from `VerifiedAuthentication.new_sign_count` on each use. |
| `transports` | `jsonb NOT NULL server_default '[]'` | From the browser's registration response; used in `allowCredentials` for re-auth. |
| `name` | `varchar(100)` | User's label; default `"Passkey"` + date. |
| `backed_up` | `boolean` | `credential_backed_up`. |
| `created_at`, `last_used_at` | `timestamptz` (`last_used_at` NULL) | |

### 5.5 `email_tokens` (new) — verification and reset links
| Column | Type | Notes |
|---|---|---|
| `id` | serial PK | |
| `token_hash` | `varchar(64) UNIQUE` | SHA-256 hex of the token, via the existing `hash_session_token`. The raw token only ever exists in the email. |
| `purpose` | `varchar(20)` | `'register'` or `'password_reset'`. |
| `email` | `varchar(320)`, indexed | Lower-cased. |
| `user_id` | FK `users.id` `ON DELETE CASCADE NULL` | Set for `password_reset`; NULL for `register` (no user yet). |
| `password_hash` | `varchar(255) NULL` | For `register`: the hash of the password chosen at registration, so it never has to be re-entered. |
| `display_name` | `varchar(200) NULL` | For `register`. |
| `created_at`, `expires_at` | `timestamptz` | Register: 24 h. Reset: 1 h. |
| `used_at` | `timestamptz NULL` | Single use. |

### 5.6 `login_attempts` (new) — throttle
| Column | Type | Notes |
|---|---|---|
| `id` | bigserial PK | |
| `email` | `varchar(320)`, indexed with `created_at` | Lower-cased; recorded whether or not an account exists. |
| `succeeded` | `boolean` | |
| `created_at` | `timestamptz` | |

### 5.7 `user_sessions` — add columns
| Column | Type | Notes |
|---|---|---|
| `auth_method` | `varchar(20) NOT NULL server_default 'google'` | `'password' \| 'passkey' \| 'google'`. Backfill is the default. |
| `authenticated_at` | `timestamptz NOT NULL server_default now()` | When this session last proved who the user is. Re-auth bumps it. |

`downgrade()` drops everything in reverse order. Run `alembic upgrade head`, then `alembic downgrade 008`, then `alembic upgrade head` again against a scratch database to prove both directions.

---

## 6. Backend services

Follow the existing layering: routers validate and respond; services in `backend/app/services/` hold the logic and take a `Session` in their constructor; services flush, **routers commit**. Catch specific exceptions; `except Exception` is not acceptable here.

### 6.1 `services/passwords.py` — `PasswordHasherService`
- `hash(password: str) -> str`
- `verify(password_hash: str, password: str) -> bool` — catches `argon2.exceptions.VerifyMismatchError` (→ `False`) and `InvalidHashError` (log and → `False`).
- `needs_rehash(password_hash: str) -> bool`
- `validate_new(password: str, email: str) -> None` — raises `WeakPasswordError(reason)` for the rules in §2.
- Module-level `DUMMY_HASH` computed once: when the email is unknown, verify against it so a miss takes as long as a wrong password (no timing oracle for account existence).

### 6.2 `services/account_email.py` — `AccountEmailService`
- No DB access. `send_verification(to, link)`, `send_already_registered(to, reset_link)`, `send_password_reset(to, link)`.
- Plain-text bodies, subjects prefixed `RecipeBox — `. Links are `f"{settings.public_url}/verify-email?token=…"` and `/reset-password?token=…`.
- Calls `zt_common.smtp.send_email(settings.smtp_config, …)`. Let `SmtpDeliveryError` propagate (log-and-re-raise pattern is already inside zt_common).
- **Connection lifetime:** callers must commit and leave the DB session **before** sending (sending can take up to 10 s). Pattern in routes: do DB work inside the request, `db.commit()`, then call the email service. Never send inside a `with all_tenants_session()` block.

### 6.3 `services/sign_in_methods.py`

**`IdentityService`** — finds or links provider identities.
- `user_for_google(identity: GoogleIdentity) -> User | None`: lookup by `(google, identity.subject)`. If none and a user has `identity.email` with no identities, no password and no passkeys (legacy rule §2), create the identity and return that user. If an email match has any other method → raise `LinkRequiredError`. Otherwise `None`.
- `link_google(user_id: int, identity: GoogleIdentity) -> UserIdentity`: raises `AlreadyLinkedError` if `(google, sub)` belongs to anyone (including this user). Insert-and-catch-`IntegrityError` inside `begin_nested()`, not select-then-insert (see `_create_user` in `services/auth.py` for the pattern).
- `unlink(user_id, identity_id)`: raises `LastMethodError` if it is the user's only method.

**`PasswordService`**
- `authenticate(email, password) -> int` (user_id): checks the throttle first (`ThrottledError(retry_after_seconds)`), records the attempt, raises `InvalidCredentialsError` for unknown email or wrong password (identical behaviour, dummy-hash timing). Rehashes when needed.
- `start_registration(email, password, display_name) -> EmailToSend | None`: validates the password; if a user with that email exists, returns an "already registered" email carrying a fresh reset token; otherwise creates a `register` token holding the hash. Returns `None` when the email throttle is hit.
- `complete_registration(token) -> int` (user_id): consumes the token (`InvalidTokenError` if missing, used or expired). Creates the user with `email_verified_at = now`, the password credential, and returns the id. If a user with the email was created meanwhile (e.g. via Google), attach the password to that user only if it has **no** password yet; else `InvalidTokenError`.
- `start_reset(email) -> EmailToSend | None`: only for an existing user; `None` otherwise (route still returns 202).
- `complete_reset(token, new_password) -> int`: sets the password, sets `email_verified_at` if NULL, deletes **all** sessions of the user.
- `set_password(user_id, new_password)`, `remove_password(user_id)` (`LastMethodError`).
- `EmailToSend` is a small frozen dataclass `(kind, to, link)`; the route sends it after committing.

**`PasskeyService`**
- `registration_options(user: User) -> tuple[str, dict]` → `(flow_id, options_json_dict)`. Creates `webauthn_user_handle` if missing. `exclude_credentials` = the user's existing passkeys. `authenticator_selection=AuthenticatorSelectionCriteria(resident_key=ResidentKeyRequirement.REQUIRED, user_verification=UserVerificationRequirement.PREFERRED)`. Store `(user_id, challenge)` in a `PendingStore` (reuse `services/google_oauth.PendingStore`, ttl 300 s) under `flow_id`.
- `register(user_id, flow_id, credential: dict, name: str | None) -> WebAuthnCredential`: pop the flow (must belong to `user_id`), `verify_registration_response(credential=…, expected_challenge=…, expected_rp_id=settings.webauthn_rp_id, expected_origin=settings.public_url)`; store the result.
- `authentication_options(user_id: int | None) -> tuple[str, dict]`: with `user_id=None` (sign-in) send **no** `allow_credentials` (discoverable); with a user (re-auth) list that user's credentials with their transports.
- `authenticate(flow_id, credential: dict, expected_user_id: int | None) -> int`: find the row by the credential's raw id (`base64url_to_bytes(credential["rawId"])`), verify with `verify_authentication_response(…, credential_public_key=row.public_key, credential_current_sign_count=row.sign_count)`. If `expected_user_id` is set and differs → `InvalidCredentialsError`. A `new_sign_count` that is non-zero and not greater than the stored one is a cloned-authenticator signal: log a warning and refuse. Update `sign_count`, `last_used_at`.
- Catch `webauthn.helpers.exceptions.WebAuthnException` (base class) → `InvalidCredentialsError`. **Verify** the exception names in 3.0.1 before relying on subclasses.
- `rename(user_id, credential_pk, name)`, `remove(user_id, credential_pk)` (`LastMethodError`).

**`MethodSummary`** — `methods_for(user_id) -> SignInMethodsOut` and `count_methods(user_id) -> int` (password + passkeys + identities), used by every `LastMethodError` check. One implementation, called from all three services.

### 6.4 Changes to existing code
- `services/google_oauth.py`: `GoogleIdentity` gains `subject: str` from `claims["sub"]` (raise `ValueError` if absent) and `auth_time: int | None` from `claims.get("auth_time")`.
- `services/auth.py` `SignInService`: split the household part out so every method shares it. New entry point `resolve_household(user: User, email_for_invites: str) -> int` (the invite-acceptance / allowlist / oldest-membership logic that is there now). `sign_in(identity)` becomes: `IdentityService.user_for_google` → else create user (still only if invited or allowlisted, as now) **and** its Google identity → `resolve_household`. Password and passkey sign-in call `resolve_household(user, user.email)`.
- `SessionService.create(user_id, tenant_id, auth_method: str)` sets `auth_method` and `authenticated_at`. Add `mark_reauthenticated(token)`. Add `delete_all_for_user(user_id, except_token: str | None = None)`.
- `AuthContext` gains `session_id: int` and `authenticated_at: datetime`; `get_current_auth` selects them.
- New dependency `require_recent_auth(auth = Depends(get_current_auth)) -> AuthContext`: if `now - authenticated_at > reauth_window` raise `HTTPException(403, detail="reauth_required")`. The frontend keys on that exact string.
- New dependency `require_app_origin(request)`: for every sign-in-method **management** route (everything under §7.3), refuse with 403 unless `Origin` equals `settings.public_url`. The global middleware lets any `chrome-extension://` origin write, which is right for recipe capture but not for changing how someone signs in.

---

## 7. Routes

All in `backend/app/routes/auth.py` (split into `routes/auth_password.py` and `routes/auth_passkeys.py` if a file passes ~300 lines; same `/auth` prefix, `tags=["auth"]`, included in `main.py` **without** the signed-in dependency, like `auth.router`). Every route: `response_model`, typed Pydantic request models in `app/schemas`, explicit `status_code`. Error bodies use `detail` with a short code string the frontend maps to text (same as the existing `?error=` codes).

Setting the cookie: factor the `set_cookie(...)` call from `complete()` into one helper `_set_session_cookie(response, token)` and use it everywhere.

### 7.1 Public sign-in
| Method & path | Body | Success | Errors |
|---|---|---|---|
| `POST /auth/password/login` | `{email, password}` | `204` + cookie | `401 invalid_credentials`, `429 too_many_attempts` (+ `Retry-After` header), `403 not_invited` / `unverified_email` |
| `POST /auth/password/register` | `{email, password, display_name?}` | `202` always (after sending) | `422 weak_password:<reason>` (only validation errors are revealed), `502 email_failed` |
| `POST /auth/password/verify` | `{token}` | `204` + cookie | `400 invalid_token`, `403 not_invited` (account **is** created; tell them to ask for an invite) |
| `POST /auth/password/forgot` | `{email}` | `202` always | `502 email_failed` only when a send to an existing account fails |
| `POST /auth/password/reset` | `{token, password}` | `204` (no cookie; they sign in) | `400 invalid_token`, `422 weak_password:<reason>` |
| `POST /auth/passkeys/login/options` | — | `200 {flow_id, options}` | |
| `POST /auth/passkeys/login/verify` | `{flow_id, credential}` | `204` + cookie | `401 invalid_credentials`, `403 not_invited` |
| `GET /auth/login` (existing) | — | Google, as now | adds `?error=link_required` |

### 7.2 Re-authentication (signed in)
| Method & path | Body | Effect |
|---|---|---|
| `POST /auth/reauth/password` | `{password}` | Checks the **session user's** password (throttled like sign-in) → `mark_reauthenticated` → `204`. |
| `POST /auth/reauth/passkey/options` | — | Options listing only this user's passkeys. |
| `POST /auth/reauth/passkey/verify` | `{flow_id, credential}` | Must resolve to the session user → `204`. |
| `GET /auth/reauth/google` | — | Google with `prompt=login` and `max_age=0`. The OAuth state carries `purpose="reauth"`, the user id and the session id. The localhost callback requires the returned `sub` to be one of this user's identities **and** `auth_time` within the last 5 minutes, then issues a ticket; `/auth/complete` requires the ticket's session id to equal the cookie's session, then bumps `authenticated_at` instead of creating a session, and redirects to `/settings?reauth=ok`. **Verify** in a real browser that Google returns `auth_time` when `max_age` is sent. |

### 7.3 Managing methods (signed in, `require_recent_auth` except the GET, `require_app_origin` on writes)
| Method & path | Body | Success | Errors |
|---|---|---|---|
| `GET /auth/methods` | — | `200 SignInMethodsOut` (`has_password`, `passkeys[{id, name, created_at, last_used_at, backed_up}]`, `google[{id, email, created_at}]`, `reauth_valid_until`) | |
| `PUT /auth/password` | `{password}` | `204`; deletes the user's **other** sessions | `422 weak_password:<reason>` |
| `DELETE /auth/password` | — | `204` | `409 last_method` |
| `POST /auth/passkeys/register/options` | — | `200 {flow_id, options}` | |
| `POST /auth/passkeys/register/verify` | `{flow_id, credential, name?}` | `201 PasskeyOut` | `400 invalid_credential` |
| `PATCH /auth/passkeys/{id}` | `{name}` | `200 PasskeyOut` | `404` |
| `DELETE /auth/passkeys/{id}` | — | `204` | `404`, `409 last_method` |
| `GET /auth/google/link` | — | Google `prompt=select_account`; state `purpose="link"` + user id + session id; completion redirects to `/settings?linked=google` | redirect `?error=already_linked` |
| `DELETE /auth/identities/{id}` | — | `204` | `404`, `409 last_method` |

Routes that take a `{id}` look it up **with** `user_id == auth.user_id`; a row belonging to someone else is a `404`, never a `403`.

### 7.4 Google state
Replace `_login_states: PendingStore[str]` with `PendingStore[GoogleFlowState]`, a frozen dataclass `(code_verifier, purpose: Literal["sign_in","link","reauth"], user_id: int | None, session_id: int | None)`. The ticket store holds a matching `TicketPayload` dataclass. One callback handles all three purposes, branching on `purpose`. Keep the existing "talk to Google before opening a DB session" ordering.

---

## 8. Frontend

All new files get the JS header from `../Dev-Standards/Headers/FileHeader_JS.txt` and a `// ai: <model-id> | <date>` line.

### 8.1 API (`frontend/src/api/client.js`)
Add one function per route in §7 (e.g. `passwordLogin`, `register`, `verifyEmail`, `forgotPassword`, `resetPassword`, `passkeyLoginOptions`, `passkeyLoginVerify`, `getSignInMethods`, `setPassword`, `removePassword`, `passkeyRegisterOptions`, `passkeyRegisterVerify`, `renamePasskey`, `removePasskey`, `unlinkIdentity`, `reauthPassword`, `reauthPasskeyOptions`, `reauthPasskeyVerify`) and URL constants `GOOGLE_LINK_URL`, `GOOGLE_REAUTH_URL`. The existing axios interceptor in `client.js` redirects to `/login` on a 401 — make sure a `401 invalid_credentials` from `/auth/password/login` and `/auth/reauth/*` does **not** trigger that redirect (exclude those URLs the way `/auth/me` already is).

### 8.2 Pages and routes (`App.jsx`, all **outside** `RequireAuth`)
- `pages/Login.jsx` — email + password form; "Sign in with a passkey" button; existing "Sign in with Google" link; links to `/register` and `/forgot-password`. Add messages for `link_required`, `already_linked`, `invalid_credentials`, `too_many_attempts` (show minutes from `Retry-After`), `invalid_token`. On success: `queryClient.invalidateQueries(['me'])` then navigate to `/`.
- `pages/Register.jsx` → after `202`, a "Check your email" state that never says whether the address already had an account.
- `pages/VerifyEmail.jsx` — reads `?token=`, POSTs once (StrictMode guard: `useRef(false)` per `REACT_STANDARDS.md`), then navigates to `/` or shows the error.
- `pages/ForgotPassword.jsx`, `pages/ResetPassword.jsx` (same StrictMode rule if anything POSTs on mount; the reset form posts on submit, which is fine).
- Hide the passkey button when `window.PublicKeyCredential` is undefined.

### 8.3 Settings — `pages/SignInMethodsSection.jsx` (+ `.module.css`, + test)
Rendered in `Settings.jsx` next to `<HouseholdSection />`. Shows password (set / change / remove), passkeys (add / rename / remove, with last-used dates), Google accounts (link / unlink). Remove buttons are disabled when the item is the user's only method (the server still enforces it).

**Re-auth flow:** any call that fails with `403` and `detail === "reauth_required"` opens a `ReauthDialog` offering the methods the user has (password field, passkey button, "Continue with Google" link to `GOOGLE_REAUTH_URL`), then retries the original action once. After returning from Google (`?reauth=ok`), show a note asking the user to repeat the action. Use `window.confirm(...)` (qualified form) before removing a method.

Every write checks the response before refetching (`res.ok` / axios rejection) and shows an error instead of silently refetching.

---

## 9. Tests

Backend tests run against the real PostgreSQL test database (existing `conftest.py`), never a mocked DB. Use the existing `anon_client` for flows that need real cookies. Write pytest functions, plain `assert`.

### 9.1 Required support code
- `backend/tests/soft_authenticator.py` — a software passkey for tests: generate an ES256 key (`cryptography`, already a `webauthn` dependency), and build real `navigator.credentials.create()` / `.get()` response JSON (clientDataJSON with the challenge and `settings.public_url` origin, authenticatorData with the RP ID hash, flags UP|UV, sign count; attestation `none`). Tests must go through the **real** `verify_registration_response` / `verify_authentication_response`; mocking the webauthn library is not acceptable.
- A fixture that captures outgoing email by monkeypatching `zt_common.smtp.smtplib.SMTP` (same approach as `infra/zt-common/tests/test_smtp.py`) **and** one test that sends through real MailHog, skipped when MailHog isn't running.

### 9.2 Cases (each a separate test)
Migration: upgrade → downgrade → upgrade on a scratch DB; existing users get `email_verified_at`; existing sessions get `auth_method='google'`.
Password: register → email contains link → verify creates user + password + session + household (allowlisted); register for an existing address sends the "already registered" email and creates no token of purpose `register`; register response identical (status and body) for new and existing addresses; weak passwords (11 chars, equal to email) rejected; token single-use and expiry; login success sets cookie with `auth_method='password'`; wrong password and unknown email both `401` with identical bodies; 6th failure in 15 min → `429` with `Retry-After`, also for an unknown address; rehash on login when parameters change; reset deletes all sessions; reset for unknown email sends nothing and returns `202`; email throttle (4th email in an hour not sent); SMTP failure → `502 email_failed` and the token row is still committed (connection was released before sending).
Passkeys: register options require recent auth; register → verify stores the credential; login with the soft authenticator (discoverable, no allow list) → session `auth_method='passkey'`; wrong origin / wrong RP ID / replayed challenge / unknown credential all `401`; sign-count regression refused; another user's passkey can't re-auth this user; rename/remove; removing the last method → `409`.
Google: new user with `sub` creates identity; legacy user (no methods) adopted on first sign-in; email match with a password → `link_required`, nothing created; link from Settings stores identity; linking a `sub` owned by someone else → `already_linked`; reauth callback with `auth_time` older than 5 min refused; `/auth/complete` for a reauth ticket from a different session refused.
Re-auth & management: management routes `403 reauth_required` when `authenticated_at` is 11 minutes old, succeed after `/auth/reauth/password`; `PUT /auth/password` ends other sessions but keeps the current one; management writes from `Origin: chrome-extension://x` refused; another user's passkey/identity id → `404`.
Existing: `test_every_non_public_route_refuses_anonymous_requests` must still pass — add the new public routes (§7.1) to `PUBLIC_ROUTES` explicitly, not by loosening the check. The §7.2/§7.3 routes are on the public `auth.router`, so each must declare `get_current_auth` (directly or through `require_recent_auth`) itself; this test is what proves it. Extend `_concrete()` so the new `{id}` path parameter becomes `1` like the others.

Frontend (vitest): Login renders all three methods and the new error messages; passkey button hidden without `PublicKeyCredential`; Register shows the same confirmation for any `202`; VerifyEmail posts once under StrictMode; SignInMethodsSection disables removing the only method and opens the re-auth dialog on `reauth_required`, then retries.

Run targeted test files while iterating; the full backend suite (`cd backend && uv run pytest`) and `cd frontend && npm test && npm run build` once before handing back.

---

## 10. Manual checks in a real browser (after the code passes)

These can only fail for real, so list the result of each in the hand-back notes:
1. Chrome accepts `recipe-app.localhost` as the passkey RP ID on `http://recipe-app.localhost` (secure-context `.localhost` rule). If it doesn't, stop and report — do not switch to `localhost` silently, because cookies and the RP ID must share a host.
2. Register a passkey with Windows Hello, sign out, sign in with it (no email typed).
3. Register a password account; the verification email appears in MailHog with a working link.
4. Forgot password → reset → old sessions in another browser profile are signed out.
5. Google re-auth: Google asks for the password again and the session's `authenticated_at` moves.
6. Link a second Google account from Settings; sign out; sign in with it.

---

## 11. Standards checklist (Dev-Standards — re-read before starting)

- New Python files: `../Dev-Standards/Headers/FileHeader_Python.txt` verbatim; `# ai: <model-id> | 2026-11-19` (actual date) before each new function/class.
- `datetime.now(timezone.utc)` / the module's `_utcnow`; never `utcnow()`.
- All imports at the top; no `__import__`; no importing `_private` names from another module (`PendingStore` and `hash_session_token` are public — use those).
- Sync `def` route handlers, as every existing router here is; do not mix async in.
- Never put a raw `str(exc)` in a response.
- `pass` only in genuinely empty blocks; stubs raise `NotImplementedError`.
- Hooks before early returns; `useRef(false)` guard for any mutating `useEffect`; `window.confirm`.
- Run `npm run build` after JSX edits.
- Commit trailer `AI-Model: <model-id>`.

## 12. Hand-back notes
List: files created/changed, anything in this spec you could not follow and why, every **verify** item and what you found, and the §10 results you could not perform (they will be done by hand).
