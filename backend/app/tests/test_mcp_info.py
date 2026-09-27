from app.core.config import settings


def _token_headers(client, email: str, password: str = "demo12345") -> dict[str, str]:
    response = client.post("/api/auth/token", data={"username": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_mcp_info_requires_super_admin(client, auth_headers, monkeypatch):
    # The advertised URL is configuration, not an assertion about production.
    # Keep this contract valid under the isolated API coverage runner too.
    monkeypatch.setattr(settings, "ERP_PUBLIC_BASE_URL", "http://127.0.0.1:8011/")
    response = client.get("/api/admin/mcp-info", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["server_name"] == "milana-erp"
    assert body["erp_api_base_url"] == "http://127.0.0.1:8011"
    assert body["claude_desktop_config"]["mcpServers"]["milana-erp"]["env"]["ERP_API_BASE_URL"] == "http://127.0.0.1:8011"
    assert body["claude_desktop_config"]["mcpServers"]["milana-erp"]["env"]["ERP_MCP_BEARER_TOKEN"] == "REPLACE_WITH_REAL_ERP_TOKEN"

    hr_headers = _token_headers(client, "hr@example.com")
    denied = client.get("/api/admin/mcp-info", headers=hr_headers)
    assert denied.status_code == 403, denied.text

