from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.api.routes.production_extra import export_process_html
from app.schemas import Bundle, Customer, Model, ModelImage, ProductionOrder, SalesOrder
from app.db.base import Base


@pytest.fixture
def sessions():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


def _measure(sessions, count, distinct):
    suffix = uuid4().hex[:8]
    with sessions() as db:
        refs = []
        for i in range(count if distinct else 1):
            customer = Customer(name=f'Customer <{i}>')
            model = Model(code=f'EXP{suffix}F{i}-V1', name=f'Model <{i}>',
                          details_json={'legacy_import': i % 2 == 1})
            db.add_all([customer, model])
            db.flush()
            sales = SalesOrder(order_no=f'EXP-SO-{suffix}-{i}', customer_id=customer.id)
            db.add_all([sales, ModelImage(model_id=model.id, image_type='model', is_primary=True,
                                         file_url=f'/storage/model-files/{suffix}-{i}.webp')])
            db.flush()
            refs.append((model.id, sales.id))
        for i in range(count):
            model_id, sales_id = refs[i if distinct else 0]
            db.add(ProductionOrder(production_no=f'EXP-PO-{suffix}-{i:03d}',
                                   production_type='client_order', source_type='standard',
                                   model_id=model_id, sales_order_id=sales_id,
                                   planned_quantity=1, status='new'))
        db.flush()
        db.expunge_all()
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith('SELECT'):
                statements.append(statement)

        event.listen(db.bind, 'before_cursor_execute', capture)
        try:
            response = export_process_html(db, SimpleNamespace(), factory=None)
        finally:
            event.remove(db.bind, 'before_cursor_execute', capture)
        html = response.body.decode()
        assert response.media_type == 'text/html'
        assert response.status_code == 200
        rows = html.split('<tbody>', 1)[1].split('</tbody>', 1)[0].split('</tr>')
        for i in range(count):
            reference = i if distinct else 0
            matches = [row for row in rows if f'EXP-PO-{suffix}-{i:03d}</b>' in row]
            assert len(matches) == 1
            row = matches[0]
            assert f'EXP-SO-{suffix}-{reference}' in row
            assert f'Customer &lt;{reference}&gt;' in row
            assert f'Model &lt;{reference}&gt;' in row
            assert f"src='/storage/model-files/{suffix}-{reference}.webp'" in row
        assert html.index(f'EXP-PO-{suffix}-{count - 1:03d}') <= html.index(f'EXP-PO-{suffix}-000')
        db.rollback()
        return len(statements)


@pytest.mark.parametrize('distinct', [False, True], ids=['shared', 'distinct'])
def test_export_reference_queries_are_bounded(sessions, distinct):
    counts = [_measure(sessions, size, distinct) for size in (1, 10, 50)]
    assert max(counts) - min(counts) <= 2, counts

def test_export_preserves_missing_references_and_family_image(sessions):
    with sessions() as db:
        base = Model(code='FAMILY', name='Base', details_json={'general': {'model_no': 'FAMILY'}})
        variant = Model(code='FAMILY-V2', name='Variant <two>',
                        details_json={'general': {'model_no': 'FAMILY', 'variant_no': 'V2'}})
        db.add_all([base, variant])
        db.flush()
        db.add(ModelImage(model_id=base.id, file_url='/storage/model-files/family.webp',
                          image_type='model', is_primary=True))
        db.add_all([
            ProductionOrder(production_no='PO-FAMILY', production_type='client_order',
                            model_id=variant.id, sales_order_id=999991, planned_quantity=2,
                            service_customer_name='Fallback & customer', status='new'),
            ProductionOrder(production_no='PO-MISSING', production_type='client_order',
                            model_id=999992, planned_quantity=3, status='new'),
        ])
        db.flush()
        db.expunge_all()
        response = export_process_html(db, SimpleNamespace(), factory=None)
        html = response.body.decode()
        assert html.index('PO-MISSING') < html.index('PO-FAMILY')
        assert 'Fallback &amp; customer' in html
        assert 'Variant &lt;two&gt;' in html
        assert '/storage/model-files/family.webp' in html
        assert '999992' in html and 'No image' in html
        db.rollback()


def test_export_factory_filter_and_row_escaping(sessions):
    with sessions() as db:
        model = Model(code='FILTER-V1', name='Model <&>')
        customer = Customer(name='Customer <&>')
        db.add_all([model, customer])
        db.flush()
        sales = SalesOrder(order_no='SO-<FILTER>', customer_id=customer.id)
        db.add_all([sales, ModelImage(model_id=model.id, image_type='model', is_primary=True,
                                      file_url='/storage/model-files/filter.webp?x=1&y=2')])
        db.flush()
        for name, factory, source, status in (
            ('ECO-STANDARD', 'ECO', 'standard', 'new'),
            ('ECO-USLUGA', 'ECO', 'usluga', 'new'),
            ('MIL-STANDARD', 'MIL', 'standard', 'new'),
            ('MIL-USLUGA', 'MIL', 'usluga', 'new'),
            ('ECO-CLOSED', 'ECO', 'standard', 'closed'),
        ):
            order = ProductionOrder(production_no=name, production_type='client_order',
                                    source_type=source, model_id=model.id, sales_order_id=sales.id,
                                    planned_quantity=1, status=status)
            db.add(order)
            db.flush()
            db.add(Bundle(bundle_no=f'B-{name}', barcode=f'BC-{name}',
                          production_order_id=order.id, model_id=model.id, color='white',
                          size='M', quantity=1, sewing_factory_code=factory, status='created'))
        db.flush()
        db.expunge_all()
        eco_user = SimpleNamespace(factory_code='ECO', session_factory_code='ECO')
        eco = export_process_html(db, eco_user, factory='ECO').body.decode()
        rows = eco.split('<tbody>', 1)[1].split('</tbody>', 1)[0].split('</tr>')
        for name in ('ECO-STANDARD', 'ECO-USLUGA'):
            matches = [row for row in rows if f'<b>{name}</b>' in row]
            assert len(matches) == 1
            row = matches[0]
            assert 'SO-&lt;FILTER&gt;' in row
            assert 'Customer &lt;&amp;&gt;' in row
            assert 'Model &lt;&amp;&gt;' in row
            assert "src='/storage/model-files/filter.webp?x=1&amp;y=2'" in row
        assert all(name not in eco for name in ('MIL-STANDARD', 'MIL-USLUGA', 'ECO-CLOSED'))
        unscoped = export_process_html(db, eco_user, factory=None).body.decode()
        assert all(name in unscoped for name in ('ECO-STANDARD', 'MIL-STANDARD'))
        assert all(name not in unscoped for name in ('ECO-USLUGA', 'MIL-USLUGA', 'ECO-CLOSED'))
        db.rollback()
