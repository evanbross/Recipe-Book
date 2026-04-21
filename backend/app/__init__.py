import sys
from app.database import schemas

# Register as app.schemas so both `from app import schemas` and
# `from app.schemas import X` resolve to the same module.
sys.modules.setdefault("app.schemas", schemas)
