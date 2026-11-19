"""Start disposable loopback-only fixtures for the receiving browser regression.

From the repository root: python backend/app/tests/sewing_receive_pagination_browser.py
Start Next on 18823 with API_URL=http://127.0.0.1:18822, then run
frontend/scripts/test-sewing-receive-load-more.browser.mjs from frontend/.
Restart this fixture process before repeating the browser receipt test.
"""
import json
from pathlib import Path
import sys


def main():
    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root / "backend"))
    # This existing conftest sets DATABASE_URL to a fresh tempfile SQLite DB
    # before importing the application; no production configuration is used.
    from app.tests.conftest import test_engine
    from app.core.config import settings
    from app.db.base import Base
    from app.db.seed import seed
    from app.tests.test_sewing_receive_pagination import waiting_batches

    settings.CORS_ORIGINS = "http://127.0.0.1:18823"
    Base.metadata.create_all(test_engine)
    seed()
    fixtures = {}
    for factory, count in (("MIL", 49), ("BST", 123), ("ECO", 3)):
        order, ids = waiting_batches(factory, count)
        fixtures[factory] = {"order": order, "ids": ids}
    output = root / "outputs/load-more"
    output.mkdir(parents=True, exist_ok=True)
    (output / "fixture.json").write_text(json.dumps(fixtures), encoding="utf-8")

    from app.main import app
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=18822, access_log=False)


if __name__ == "__main__":
    main()
