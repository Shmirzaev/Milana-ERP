from uuid import uuid4

from sqlalchemy import event

from app.models import Model, ModelImage
from app.tests.conftest import TestSessionLocal, test_engine


def test_super_data_rows_compute_binary_size_without_selecting_blob(client, auth_headers):
    marker = uuid4().hex[:10]
    data = b"super data should return this binary byte count without fetching the bytes"
    with TestSessionLocal() as db:
        model = Model(code=f"SD-{marker}", name="Super data projection", status="approved")
        db.add(model)
        db.flush()
        image = ModelImage(
            model_id=model.id,
            file_url=f"https://example.invalid/{marker}.webp",
            file_name="projection.webp",
            content_type="image/webp",
            file_data=data,
            image_type="model",
        )
        db.add(image)
        db.commit()
        image_id = int(image.id)

    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        response = client.get(
            "/api/admin/super-data/tables/model_images?page=1&page_size=10",
            headers=auth_headers,
        )
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert response.status_code == 200, response.text
    body = response.json()
    image_row = next(row for row in body["rows"] if row["id"] == image_id)
    assert image_row["file_data"] == {"__binary": True, "size": len(data)}
    row_reads = [statement for statement in statements if "select model_images." in statement]
    assert len(row_reads) == 1
    assert "length(model_images.file_data) as file_data" in row_reads[0]
    assert "model_images.file_data as model_images_file_data" not in row_reads[0]
    assert "limit ? offset ?" in row_reads[0]
