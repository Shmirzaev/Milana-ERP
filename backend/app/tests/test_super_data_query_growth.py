"""The super-data table directory must count tables in one DB round trip."""

from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, insert
from sqlalchemy.orm import Session

from app.api.routes.super_data import _table_row_counts


def test_super_data_counts_preserve_table_names_and_counts_with_one_execute():
    metadata = MetaData()
    z_table = Table("z_table", metadata, Column("id", Integer, primary_key=True), Column("name", String))
    a_table = Table("a_table", metadata, Column("id", Integer, primary_key=True), Column("name", String))
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    with Session(engine) as db:
        db.execute(insert(a_table), [{"name": "one"}, {"name": "two"}])
        db.execute(insert(z_table), [{"name": "only"}])
        db.commit()

        execute_count = 0
        original_execute = db.execute

        def counted_execute(*args, **kwargs):
            nonlocal execute_count
            execute_count += 1
            return original_execute(*args, **kwargs)

        db.execute = counted_execute
        assert _table_row_counts(db, [a_table, z_table]) == {"a_table": 2, "z_table": 1}
        assert execute_count == 1
