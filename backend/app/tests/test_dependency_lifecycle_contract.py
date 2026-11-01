from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_frontend_runtime_and_ci_use_node_24_lts():
    dockerfile = (REPOSITORY_ROOT / "frontend" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    base_images = [line for line in dockerfile.splitlines() if line.startswith("FROM ")]
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert base_images == [
        "FROM node:24-alpine AS dependencies",
        "FROM node:24-alpine AS builder",
        "FROM node:24-alpine AS runtime",
    ]
    assert 'node-version: "24"' in workflow
    assert 'node-version: "20"' not in workflow
    rehearsal = (REPOSITORY_ROOT / "scripts" / "rf013_frontend.Dockerfile").read_text(encoding="utf-8")
    assert [line for line in rehearsal.splitlines() if line.startswith("FROM ")] == ["FROM node:24-alpine"]
