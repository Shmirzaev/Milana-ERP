"""Semantic workbook rows/languages and HTTP contract before read extraction."""

from datetime import date, datetime, timezone
from io import BytesIO

import pytest
from openpyxl import load_workbook

from app.api.routes import attendance
from app.schemas import User
from app.tests.attendance_operation_fixtures import (
    attendance_database as attendance_database, ah as ah, headers,
)
from app.tests.test_attendance_overview_characterization import seed_read_profiles


@pytest.mark.parametrize('lang,title,complete,single,absent', [
    ('en', 'Daily attendance report', 'Arrival and departure', 'One scan only', 'No scans'),
    ('ru', 'Ежедневный отчёт о посещаемости', 'Приход и уход', 'Только один проход', 'Нет проходов'),
    ('uz', 'Kunlik davomat hisoboti', 'Kelish va ketish', 'Faqat bitta o‘tish', 'O‘tish yo‘q'),
])
def test_daily_report_semantic_rows_language_and_headers(ah, monkeypatch, lang, title, complete, single, absent):
    seed_read_profiles(ah)
    monkeypatch.setattr(attendance, 'utcnow', lambda: datetime(2026, 11, 5, 6, 7, tzinfo=timezone.utc))
    response = ah[2].get(f'/api/attendance/reports/daily.xlsx?day=2026-11-05&lang={lang}', headers=headers(ah))
    assert response.status_code == 200, response.text
    assert response.headers['content-type'] == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    assert response.headers['content-disposition'] == 'attachment; filename="attendance_daily_2026-11-05.xlsx"'
    sheet = load_workbook(BytesIO(response.content)).active
    assert sheet['A1'].value == title
    assert sheet['A2'].value.endswith('2026-11-05')
    assert sheet['A4'].value.endswith('2026-11-05 11:07')
    rows = {sheet.cell(index, 2).value: [sheet.cell(index, col).value for col in range(3, 8)]
            for index in range(7, sheet.max_row+1)}
    assert rows == {
        '735': ['A Current 735', complete, '07:00', '08:00', '01:00'],
        '736': ['B Absent 736', absent, None, None, None],
        '737': ['C Historical 737', single, '06:00', None, None],
    }
    assert sheet.freeze_panes == 'A7'


def test_daily_report_filters_default_language_and_authorization(ah):
    seed_read_profiles(ah)
    response = ah[2].get('/api/attendance/reports/daily.xlsx?day=2026-11-05&query=B%20Absent&usage=not_used', headers=headers(ah))
    assert response.status_code == 200
    sheet = load_workbook(BytesIO(response.content)).active
    assert sheet['A1'].value == 'Kunlik davomat hisoboti'
    assert sheet.max_row == 7 and sheet.cell(7, 2).value == '736'
    assert sheet.cell(7, 4).value == 'O‘tish yo‘q'
    assert ah[2].get('/api/attendance/reports/daily.xlsx').status_code == 401
    assert ah[2].get('/api/attendance/reports/daily.xlsx', headers=headers(ah, 'denied')).status_code == 403
    assert ah[2].get('/api/attendance/reports/daily.xlsx?lang=fr', headers=headers(ah)).status_code == 422


def test_daily_report_preserves_read_only_transaction(ah, monkeypatch):
    seed_read_profiles(ah)
    with ah[0]() as db:
        actor = db.get(User, ah[1]['hr'])
        def no_commit():
            raise AssertionError('Read operation must not commit')
        monkeypatch.setattr(db, 'commit', no_commit)
        response = attendance.download_daily_attendance_report(db, actor, date(2026, 11, 5), '', 'all', 'en')
        assert response.media_type == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        assert load_workbook(BytesIO(response.body)).active['A1'].value == 'Daily attendance report'
        assert not db.new and not db.dirty and not db.deleted
