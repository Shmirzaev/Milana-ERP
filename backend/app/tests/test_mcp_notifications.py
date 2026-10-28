def test_mcp_notification_send_creates_notification_and_audit(client, auth_headers):
    me = client.get("/api/auth/me", headers=auth_headers)
    assert me.status_code == 200
    user_id = me.json()["id"]

    payload = {
        "target_type": "user_id",
        "user_id": user_id,
        "title": "MCP test notification",
        "message": "Created through the controlled MCP notification API.",
        "link": "/sales-orders/1",
        "entity_type": "SalesOrder",
        "entity_id": 1,
    }
    created = client.post("/api/notifications/send", json=payload, headers=auth_headers)
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["created_count"] == 1
    assert body["recipients"] == [{"user_id": user_id, "name": me.json()["name"]}]

    notifications = client.get("/api/notifications?limit=10", headers=auth_headers)
    assert notifications.status_code == 200
    assert any(
        row["title"] == payload["title"]
        and row["message"] == payload["message"]
        and row["link"] == payload["link"]
        for row in notifications.json()
    )

    audit = client.get("/api/audit-logs?action=mcp_send_notification&limit=10", headers=auth_headers)
    assert audit.status_code == 200
    assert any(
        row["action"] == "mcp_send_notification"
        and row["new_value"]["recipient_user_ids"] == [user_id]
        and row["new_value"]["title"] == payload["title"]
        for row in audit.json()
    )

