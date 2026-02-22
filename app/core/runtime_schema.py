from sqlalchemy import Engine, inspect, text


def ensure_runtime_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "assessments" not in table_names:
        return

    assessment_columns = {
        column["name"] for column in inspector.get_columns("assessments")
    }
    edit_request_columns = (
        {column["name"] for column in inspector.get_columns("edit_requests")}
        if "edit_requests" in table_names
        else set()
    )

    with engine.begin() as connection:
        if "is_prompted" not in assessment_columns:
            connection.execute(
                text(
                    "ALTER TABLE assessments "
                    "ADD COLUMN is_prompted BOOLEAN NOT NULL DEFAULT 0"
                )
            )

        if "edit_requests" in table_names:
            if "requested_score" not in edit_request_columns:
                connection.execute(
                    text(
                        "ALTER TABLE edit_requests "
                        "ADD COLUMN requested_score INTEGER"
                    )
                )
            if "requested_is_prompted" not in edit_request_columns:
                connection.execute(
                    text(
                        "ALTER TABLE edit_requests "
                        "ADD COLUMN requested_is_prompted BOOLEAN"
                    )
                )
            if "requested_assessment_date" not in edit_request_columns:
                connection.execute(
                    text(
                        "ALTER TABLE edit_requests "
                        "ADD COLUMN requested_assessment_date DATE"
                    )
                )
            if "requested_comment" not in edit_request_columns:
                connection.execute(
                    text(
                        "ALTER TABLE edit_requests "
                        "ADD COLUMN requested_comment TEXT"
                    )
                )
            if "applied_assessment_id" not in edit_request_columns:
                connection.execute(
                    text(
                        "ALTER TABLE edit_requests "
                        "ADD COLUMN applied_assessment_id VARCHAR(36)"
                    )
                )
