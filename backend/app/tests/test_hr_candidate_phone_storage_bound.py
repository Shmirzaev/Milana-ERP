"""Keep recruitment phone values within their PostgreSQL VARCHAR column."""


def test_candidate_phone_accepts_column_limit_and_rejects_overflow(client, auth_headers):
    accepted = client.post(
        "/api/hr/recruitment",
        headers=auth_headers,
        json={"full_name": "Phone Bound Candidate", "phone": "1" * 64},
    )
    assert accepted.status_code == 201, accepted.text

    rejected = client.post(
        "/api/hr/recruitment",
        headers=auth_headers,
        json={"full_name": "Overflow Candidate", "phone": "1" * 65},
    )
    assert rejected.status_code == 422, rejected.text

    candidates = client.get("/api/hr/recruitment", headers=auth_headers)
    assert candidates.status_code == 200, candidates.text
    assert [row["full_name"] for row in candidates.json()] == ["Phone Bound Candidate"]
