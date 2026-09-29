from app.core.model_search import model_code_contains, normalized_model_code_key


def test_model_code_normalization_folds_latin_and_cyrillic_lookalikes():
    assert normalized_model_code_key("PJ-1000") == normalized_model_code_key("РJ-1000")
    assert normalized_model_code_key("СУПРЕМ") == "cyпpem"


def test_model_code_contains_matches_variant_codes_across_alphabets():
    assert model_code_contains("РJ-1000-194", "PJ-1000")
    assert model_code_contains("PJ-1000/4", "РJ-1000")
    assert not model_code_contains("TJ-1000", "PJ-1000")


def test_prefix_sort_uses_number_next_to_letters_and_normalizes_legacy_codes():
    from app.core.model_search import model_prefix_number, model_search_prefix

    assert model_search_prefix(" РJ ") == "pj"
    assert model_search_prefix("XJ5614") is None
    assert model_prefix_number("XJ5614-0031", "xj") == 5614
    assert model_prefix_number("ХJ-5415-9999", "xj") == 5415
    assert model_prefix_number("PXJ9999", "xj") == -1


def test_prefix_family_sort_is_applied_before_pagination(client, auth_headers):
    from app.db import session as session_module
    from app.models import Model

    # Insert the smallest family last so sorting by newest id would be wrong.
    with session_module.SessionLocal() as db:
        for model_no, variant in [("XJ5614", "0001"), ("XJ5614", "0002"), ("ХJ5415", "9999"), ("XJ999", "0001")]:
            db.add(Model(code=f"{model_no}-{variant}", name="Prefix sorting fixture", status="approved",
                         details_json={"general": {"model_no": model_no, "variant_no": variant}}, created_by=1))
        db.commit()
    returned = []
    for page in (1, 2, 3):
        response = client.get("/api/models/variant-groups", params={
            "q": "XJ", "name": "Prefix sorting fixture", "page": page, "page_size": 1,
            "compact": "true", "include_total": "true",
        }, headers=auth_headers)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["total"] == 3
        returned.append(payload["rows"][0]["group_model_no"])
        if page == 1:
            assert payload["rows"][0]["variant_count"] == 2
    assert returned == ["XJ5614", "ХJ5415", "XJ999"]


def test_postgres_prefix_sort_casts_numeric_family_part():
    from sqlalchemy import literal_column
    from sqlalchemy.dialects import postgresql
    from app.core.model_search import model_group_prefix_number_column

    expression = model_group_prefix_number_column(literal_column("models.model_group_key"), "xj").desc()
    sql = str(expression.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "^model:xj/?([0-9]+)" in sql
    assert "AS NUMERIC" in sql
    assert sql.endswith(" DESC")


def test_displayed_variant_search_finds_plain_and_prefixed_catalog_codes(client, auth_headers):
    from app.db import session as session_module
    from app.models import Model

    codes = ["PJ99101-009913", "PJ99102-V-009913"]
    with session_module.SessionLocal() as db:
        models = [Model(code=code, name="Variant search fixture", status="approved", created_by=1) for code in codes]
        db.add_all(models)
        db.commit()
        ids = {model.id for model in models}
    for query in ("V-009913", "V=009913", "009913"):
        response = client.get("/api/model-options", params={"search": query}, headers=auth_headers)
        assert response.status_code == 200, response.text
        assert ids <= {row["id"] for row in response.json()["items"]}
        response = client.get("/api/search", params={"q": query}, headers=auth_headers)
        assert response.status_code == 200, response.text
        results = [row for row in response.json() if row["type"] == "Model" and row["id"] in ids]
        assert len(results) == 2 and all("V-009913" in row["label"] for row in results)
    response = client.get("/api/model-options", params={"search": "PJ99101-V-009913"}, headers=auth_headers)
    assert response.status_code == 200 and response.json()["items"][0]["code"] == codes[0]
    with session_module.SessionLocal() as db:
        assert {model.code for model in db.query(Model).filter(Model.id.in_(ids))} == set(codes)
