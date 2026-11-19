"""Local synthetic QA only; conftest creates fresh isolated DB and media paths."""
import json
import os
from pathlib import Path
import shutil
import tempfile

if os.environ.get("MANUAL_PACKAGING_LOCAL_QA") != "1":
    raise SystemExit("Set MANUAL_PACKAGING_LOCAL_QA=1")

from app.tests.conftest import test_engine, TestSessionLocal  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.seed import seed  # noqa: E402
from app.main import app  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.schemas import User  # noqa: E402
import uvicorn  # noqa: E402

assert test_engine.dialect.name == "sqlite"
settings.CORS_ORIGINS = "http://127.0.0.1:3088,http://localhost:3000"
output = Path(os.environ["MANUAL_PACKAGING_QA_OUTPUT"])
if os.environ.get("MANUAL_PACKAGING_REUSE_QA") == "1":
    prior = Path(json.loads((output / 'qa-database.json').read_text())['database']).resolve()
    assert prior.is_relative_to(Path(tempfile.gettempdir()).resolve()) and prior.parent.name.startswith('erp-test-')
    test_engine.dispose()
    shutil.copyfile(prior, test_engine.url.database)
Base.metadata.create_all(test_engine)
seed()
with TestSessionLocal() as db:
    for email, factory in [("besttex.packaging@example.com", "BST"), ("eco.cotton.packaging@example.com", "ECO")]:
        db.query(User).filter_by(email=email).one().factory_code = factory
    db.commit()
output.mkdir(parents=True, exist_ok=True)
(output / 'qa-database.json').write_text(json.dumps({'database': test_engine.url.database}), encoding='utf-8')
print("Synthetic Packaging QA on loopback port 8168", flush=True)
uvicorn.run(app, host="127.0.0.1", port=8168, log_level="warning")
