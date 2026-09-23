import pytest


@pytest.mark.parametrize("user_id", [-1, 2_147_483_648])
def test_admin_user_routes_preserve_auth_and_not_found_for_unrepresentable_ids(
    client, auth_headers, user_id,
):
    path = f"/api/users/{user_id}"
    assert client.get(path).status_code == 401

    for method, kwargs in (
        ("GET", {}),
        ("PATCH", {"json": {"name": "must not be applied"}}),
        ("DELETE", {}),
    ):
        response = client.request(method, path, headers=auth_headers, **kwargs)
        assert response.status_code == 404, (method, response.text)
        assert response.json()["detail"] == "User not found"
