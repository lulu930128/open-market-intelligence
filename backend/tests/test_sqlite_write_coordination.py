from __future__ import annotations

import unittest
from unittest.mock import MagicMock, call, patch

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db.write_coordination import (
    SqliteWriteBusyError,
    is_sqlite_locked_error,
    run_with_sqlite_write_retry,
)


def _sqlite_session() -> MagicMock:
    db = MagicMock(spec=Session)
    db.get_bind.return_value.dialect.name = "sqlite"
    return db


class SqliteWriteCoordinationTests(unittest.TestCase):
    def test_retries_complete_action_after_rolling_back_locked_snapshot(self) -> None:
        db = _sqlite_session()
        action = MagicMock(
            side_effect=[
                OperationalError(
                    "UPDATE radar",
                    {},
                    Exception("database is locked"),
                ),
                {"status": "persisted"},
            ]
        )

        with patch("app.db.write_coordination.time.sleep") as sleep:
            result = run_with_sqlite_write_retry(
                db,
                action,
                retry_delays_seconds=(0.15,),
                reset_session_before_attempt=True,
            )

        self.assertEqual(result, {"status": "persisted"})
        self.assertEqual(action.call_count, 2)
        self.assertEqual(db.rollback.call_count, 3)
        sleep.assert_called_once_with(0.15)

    def test_exhausted_lock_is_exposed_as_retryable_busy_error(self) -> None:
        db = _sqlite_session()
        locked = OperationalError(
            "INSERT snapshot",
            {},
            Exception("database table is locked"),
        )

        with patch("app.db.write_coordination.time.sleep"):
            with self.assertRaises(SqliteWriteBusyError) as raised:
                run_with_sqlite_write_retry(
                    db,
                    MagicMock(side_effect=locked),
                    retry_delays_seconds=(0.0,),
                )

        self.assertIs(raised.exception.__cause__, locked)
        self.assertEqual(db.rollback.call_args_list, [call(), call()])

    def test_non_lock_operational_error_is_not_reclassified(self) -> None:
        db = _sqlite_session()
        error = OperationalError(
            "INSERT snapshot",
            {},
            Exception("disk I/O error"),
        )

        with self.assertRaises(OperationalError) as raised:
            run_with_sqlite_write_retry(db, MagicMock(side_effect=error))

        self.assertIs(raised.exception, error)
        db.rollback.assert_called_once_with()
        self.assertFalse(is_sqlite_locked_error(error))


if __name__ == "__main__":
    unittest.main()
