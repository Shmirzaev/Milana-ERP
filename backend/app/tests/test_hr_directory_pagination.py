from app.models import Employee
from app.tests.conftest import TestSessionLocal


def _seed():
    with TestSessionLocal() as db:
        rows = [Employee(factory_code="MIL", full_name=f"Directory test {i:03d}", employee_no=str(90000+i),
                         status="active" if i < 30 else "inactive", hr_profile_json={str(j): j for j in range(5)} if i<15 else {})
                for i in range(61)]
        db.add_all(rows)
        db.add(Employee(factory_code="BST", full_name="Directory test other", employee_no="99999"))
        db.commit()
        return [r.id for r in rows]


def test_directory_pages_keep_search_totals_and_all_rows(client, auth_headers):
    ids = _seed()
    url = "/api/employees?page_size=50&search=Directory%20test"
    first = client.get(url+"&page=1", headers=auth_headers)
    assert first.status_code == 200, first.text
    body=first.json()
    assert isinstance(body, dict), "Directory must return page metadata instead of loading the whole list"
    assert body["total"] == 61 and len(body["rows"]) == 50 and body["has_more"]
    assert (body["active_total"],body["inactive_total"],body["profile_coverage_percent"]) == (30,31,25)
    second=client.get(url+"&page=2", headers=auth_headers).json()
    assert len(second["rows"]) == 11 and not second["has_more"]
    assert {r["id"] for r in body["rows"]+second["rows"]} == set(ids)
    assert isinstance(client.get('/api/employees', headers=auth_headers).json(), list)


def test_directory_selected_manager_is_retained_outside_first_options_page(client,auth_headers):
    ids=_seed()
    response=client.get(f'/api/employees/manager-options?search=Directory%20test&selected_id={ids[-1]}',headers=auth_headers)
    assert response.status_code == 200, response.text
    body=response.json()
    assert len(body['rows']) <= 50 and body['has_more']
    assert ids[-1] in {r['id'] for r in body['rows']}


def test_directory_search_treats_wildcards_literally(client,auth_headers):
    _seed()
    response=client.get('/api/employees?page=1&page_size=50&search=%25',headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()['total'] == 0


def test_directory_private_fields_and_profile_counts_stay_private(monkeypatch):
    from app.api.routes import hr
    from types import SimpleNamespace
    _seed()
    monkeypatch.setattr(hr, 'selected_factory_code', lambda _user: 'MIL')
    monkeypatch.setattr(hr, 'user_permissions', lambda _user: ['payroll.view'])
    with TestSessionLocal() as db:
        page = hr._employee_directory_page(db, SimpleNamespace(), search='Directory test', page=1, page_size=10)
    assert page['profile_coverage_percent'] is None
    assert all(not {'phone', 'salary', 'hr_profile_json'}.intersection(row) for row in page['rows'])


from app.tests.test_attendance_import_races import attendance_postgres_sessions  # noqa: E402,F401


def test_postgres_directory_profile_count_handles_legacy_json(attendance_postgres_sessions, monkeypatch):
    from app.api.routes import hr
    from types import SimpleNamespace
    sessions, _engine = attendance_postgres_sessions
    monkeypatch.setattr(hr, 'selected_factory_code', lambda _user: 'MIL')
    monkeypatch.setattr(hr, 'user_permissions', lambda _user: ['hr.employees'])
    with sessions() as db:
        db.add_all([Employee(factory_code='MIL', full_name=f'PG directory {i}', hr_profile_json=value)
                    for i, value in enumerate([{'a': 1, 'b': 2, 'c': 3, 'd': 4, 'e': 5}, {}, [], None])])
        db.add(Employee(factory_code='BST', full_name='PG directory hidden', hr_profile_json={str(i): i for i in range(5)}))
        db.commit()
        page = hr._employee_directory_page(db, SimpleNamespace(), search='PG directory', page=1, page_size=2)
    assert page['total'] == 4 and len(page['rows']) == 2 and page['has_more']
    assert page['profile_coverage_percent'] == 25
