from sqlalchemy import Engine, inspect, text


def ensure_runtime_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "assessments" not in table_names:
        return

    assessment_columns = {
        column["name"] for column in inspector.get_columns("assessments")
    }

    with engine.begin() as connection:
        if "is_prompted" not in assessment_columns:
            connection.execute(
                text(
                    "ALTER TABLE assessments "
                    "ADD COLUMN is_prompted BOOLEAN NOT NULL DEFAULT 0"
                )
            )
