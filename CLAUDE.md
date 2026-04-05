# Recipe App — Claude Code Instructions

## Stack

- **Backend**: FastAPI + SQLAlchemy + PostgreSQL, served via Uvicorn
- **Frontend**: React (Vite)
- **Storage**: Cloudflare R2 (S3-compatible, via boto3)
- **AI**: Anthropic Claude API (vision + text extraction)
- **Infra**: Docker Compose for local dev

## Best Practices

### Python
- Always use type hints on function signatures and class attributes
- Prefer OOP over procedural/functional style — use classes to encapsulate related state and behavior
- Follow PEP 8 naming: `snake_case` for functions/variables, `PascalCase` for classes, `UPPER_CASE` for constants

### General
- Write clear, self-documenting code; add comments only where the logic isn't obvious
- Don't add speculative abstractions — solve the problem at hand, not hypothetical future ones
- Prefer editing existing files over creating new ones
- SOLID principles and clean architecture
- Proper separation of concerns
- Secure coding patterns (no injection risks, no overly broad exception catches, validate at boundaries)
- Idiomatic use of the language and framework — prefer stdlib/framework features over hand-rolled solutions
- Consistent naming and style conventions already present in the codebase
