def test_active_production_limit_is_bounded_and_accepts_small_pages(client, auth_headers):
    bounded = client.get("/api/dashboard/active-production?limit=1", headers=auth_headers)
    assert bounded.status_code == 200, bounded.text
    assert isinstance(bounded.json(), list)

    rejected = client.get("/api/dashboard/active-production?limit=501", headers=auth_headers)
    assert rejected.status_code == 422, rejected.text
