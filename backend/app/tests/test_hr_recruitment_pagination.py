from uuid import uuid4

from app.db.session import SessionLocal
from app.models import HrRecruitmentCandidate


def test_recruitment_opt_in_pages_preserve_legacy_order_filters_totals_and_scope(client, auth_headers):
    marker = f"RECRUIT-PAGE-{uuid4().hex[:10]}"
    stages = ("applied", "screening", "interview", "offer", "hired", "rejected")
    with SessionLocal() as db:
        rows = [
            HrRecruitmentCandidate(
                factory_code="MIL",
                full_name=f"{marker} Candidate {index:03d}",
                phone=f"+99890{index:07d}",
                stage=stages[index % len(stages)],
            )
            for index in range(205)
        ]
        outsider = HrRecruitmentCandidate(
            factory_code="ECO",
            full_name=f"{marker} hidden factory candidate",
            stage="applied",
        )
        db.add_all([*rows, outsider])
        db.commit()
        expected_ids = [int(row.id) for row in reversed(rows)]
        expected_interviews = sum(index % len(stages) == stages.index("interview") for index in range(205))
        expected_stage_counts = {
            stage: db.query(HrRecruitmentCandidate).filter_by(factory_code="MIL", stage=stage).count()
            for stage in stages
        }

    pages = []
    for page in (1, 2, 3):
        response = client.get(
            "/api/hr/recruitment",
            headers=auth_headers,
            params={"page": page, "page_size": 100, "q": marker},
        )
        assert response.status_code == 200, response.text
        pages.append(response.json())

    assert [len(page["rows"]) for page in pages] == [100, 100, 5]
    assert [page["total"] for page in pages] == [205, 205, 205]
    assert [page["has_more"] for page in pages] == [True, True, False]
    assert all(page["stage_counts"] == expected_stage_counts for page in pages)
    assert [row["id"] for page in pages for row in page["rows"]] == expected_ids
    assert all(marker in row["full_name"] for page in pages for row in page["rows"])

    filtered = client.get(
        "/api/hr/recruitment",
        headers=auth_headers,
        params={"page": 1, "page_size": 100, "q": marker, "stage": "interview"},
    )
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["total"] == expected_interviews
    assert {row["stage"] for row in filtered.json()["rows"]} == {"interview"}

    legacy = client.get(
        "/api/hr/recruitment",
        headers=auth_headers,
        params={"limit": 500, "q": marker},
    )
    assert legacy.status_code == 200, legacy.text
    assert isinstance(legacy.json(), list)
    assert [row["id"] for row in legacy.json()] == expected_ids
    assert client.get("/api/hr/recruitment?page=1&page_size=501", headers=auth_headers).status_code == 422
    assert client.get("/api/hr/recruitment?page=1&page_size=100").status_code == 401
