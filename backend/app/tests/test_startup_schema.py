def _harden_runtime_settings(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENV", "production")
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "JWT_SECRET", "jwt-secret-for-startup-tests-abcdefghijklmnopqrstuvwxyz")
    monkeypatch.setattr(settings, "FILE_SIGNING_SECRET", "file-secret-for-startup-tests-abcdefghijklmnopqrstuvwxyz")
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql+psycopg2://erp_user:secret@db:5432/erp")
    monkeypatch.setattr(settings, "CORS_ORIGINS", "https://erp.example.com")
    monkeypatch.setattr(settings, "GLOBAL_RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "GLOBAL_RATE_LIMIT_PER_MINUTE", 100)
    monkeypatch.setattr(settings, "GLOBAL_RATE_LIMIT_WINDOW_SECONDS", 60)
    monkeypatch.setattr(settings, "SHARED_STORE_URL", "redis://redis:6379/0")
    monkeypatch.setattr(settings, "REDIS_URL", "")
    monkeypatch.setattr(settings, "ALLOW_INSECURE_DEFAULT_ADMIN_LOGIN", False)
    monkeypatch.setattr(settings, "ALLOW_DEMO_RESET", False)


def test_production_startup_verifies_alembic_without_schema_sync(monkeypatch):
    from app import main
    from app.core.config import settings

    _harden_runtime_settings(monkeypatch)
    monkeypatch.setattr(settings, "STARTUP_SCHEMA_SYNC", False)
    calls: list[str] = []
    monkeypatch.setattr(main, "_verify_alembic_current", lambda: calls.append("verify"))
    monkeypatch.setattr(main, "_run_local_schema_sync", lambda: calls.append("schema_sync"))
    monkeypatch.delenv("RUN_SEED_ON_STARTUP", raising=False)

    main._run_startup()

    assert calls == ["verify"]


def test_production_startup_rejects_schema_sync(monkeypatch):
    import pytest

    from app import main
    from app.core.config import settings

    _harden_runtime_settings(monkeypatch)
    monkeypatch.setattr(settings, "STARTUP_SCHEMA_SYNC", True)
    monkeypatch.setattr(main, "_verify_alembic_current", lambda: None)
    monkeypatch.delenv("RUN_SEED_ON_STARTUP", raising=False)

    with pytest.raises(RuntimeError, match="STARTUP_SCHEMA_SYNC"):
        main._run_startup()
