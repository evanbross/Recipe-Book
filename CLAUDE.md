@../Dev-Standards/COMMON_CODING_STANDARDS.md
@../Dev-Standards/PYTHON_STANDARDS.md
@../Dev-Standards/DATABASE_STANDARDS.md
@../Dev-Standards/JAVASCRIPT_TYPESCRIPT_STANDARDS.md
@../Dev-Standards/REACT_STANDARDS.md
@../Dev-Standards/FASTAPI_STANDARDS.md
@../Dev-Standards/TESTING_STANDARDS.md
@../Dev-Standards/INFRASTRUCTURE_STANDARDS.md

## SQLAlchemy / Python Datetime

Never use `datetime.utcnow` as a column default — it is deprecated in Python 3.12+. Always use `lambda: datetime.now(timezone.utc)` instead:

```python
# Wrong
created_at = Column(DateTime, default=datetime.utcnow)

# Right
created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
```

## Pydantic Settings

Always use `SettingsConfigDict` instead of the inner `class Config` pattern, which is deprecated in Pydantic v2:

```python
# Wrong
class Settings(BaseSettings):
    class Config:
        env_file = ".env"

# Right
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")
```
