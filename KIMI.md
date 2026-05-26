# Kimi Session Guardrails — Recipe App

Read this at the start of every session before touching code.

## Known Failure Modes (from prior reviews)

Do not repeat these.

### Python / FastAPI
1. **Never return raw `str(exc)` in HTTP `detail`.** Log the full exception server-side; return a sanitized message to the client.
2. **Never use SELECT-then-INSERT for upserts.** That pattern is racy. Try INSERT first, catch `IntegrityError`, then fall back to SELECT.
3. **ASCII-normalize slugs.** `lower().replace(" ", "-")` is not enough — non-ASCII characters like `é` leak through.
4. **Type-hint every function parameter and return value.** `db` is not optional — it must be `db: Session`.
5. **Remove dead `except Exception` blocks.** If a specific exception is already caught and re-raised above it, the generic handler is unreachable.
6. **Group stdlib imports at the top.** Do not place `from urllib.parse import ...` between app-level imports.
7. **Every new `.py` file must start with the copyright/license header.** Copy the template verbatim; do not abbreviate.

### React / Frontend
8. **Delete unused CSS module classes.** After removing JSX references, grep the `.module.css` file and delete orphaned classes.

---

## Pre-Submit Checks (run these before saying "done")

Paste the output of each command in your final response.

### Backend
```bash
cd backend

# 1. Import order & lint
ruff check app/ || echo "RUFF_FAILED"

# 2. Type checks
mypy app/ || echo "MYPY_FAILED"

# 3. Raw exception strings in HTTP detail
grep -rn 'detail=.*exc\|detail=.*e)' app/routes/*.py app/main.py || true

# 4. Dead except Exception after raise_for_status
grep -rn -B1 'except Exception as exc:' app/services/scraper.py || true

# 5. Missing file headers (files without Copyright in first 5 lines)
find app -name "*.py" | while read f; do
  head -n5 "$f" | grep -q "Copyright" || echo "MISSING_HEADER: $f"
done
```

### Frontend
```bash
cd frontend

# 1. Build must pass
npm run build || echo "BUILD_FAILED"

# 2. Unused CSS module classes
# List all classes referenced in JSX
# grep -roh 'styles\.[A-Za-z0-9_]*' src/pages/*.jsx src/components/*.jsx | sed 's/styles\.//' | sort -u > /tmp/used.txt
# List all classes defined in CSS
# grep -o '^\.[A-Za-z0-9_-]*' src/pages/*.module.css src/components/*.module.css | sed 's/^\.//' | sort -u > /tmp/defined.txt
# Diff them
# comm -23 /tmp/defined.txt /tmp/used.txt
```

---

## Done Criteria

Before declaring a task complete, confirm:

- [ ] I ran the backend checks above and they are clean (or I explained why a hit is acceptable).
- [ ] I ran `npm run build` in `frontend/` and it succeeded.
- [ ] I grepped for unused CSS module classes and removed any orphans.
- [ ] Any new `.py` file has the full copyright header.
- [ ] No raw `str(exc)` strings are returned to API callers.
