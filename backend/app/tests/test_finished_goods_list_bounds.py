from app.api.routes.finished_goods import list_branded, list_stock


class _Query:
    def __init__(self):
        self.limit_value = None

    def outerjoin(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def offset(self, value):
        self.offset_value = value
        return self

    def all(self):
        return []


class _Db:
    def __init__(self):
        self.query_obj = _Query()

    def query(self, *args, **kwargs):
        return self.query_obj


def test_finished_goods_list_clamps_limit_at_500():
    db = _Db()
    db.query_obj.offset_value = None
    list_stock(db, None, limit=401)
    assert db.query_obj.limit_value == 401
    assert db.query_obj.offset_value == 0

    list_stock(db, None, limit=9999)
    assert db.query_obj.limit_value == 500

    list_stock(db, None, limit=-1)
    assert db.query_obj.limit_value == 0


def test_branded_finished_goods_list_clamps_limit_at_500():
    db = _Db()
    db.query_obj.offset_value = None
    list_branded(db, None, limit=9999)
    assert db.query_obj.limit_value == 500
    assert db.query_obj.offset_value == 0
