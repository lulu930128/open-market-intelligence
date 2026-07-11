from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi import status

from app.routers import market_family_helpers as helpers


class NotFoundError(Exception):
    pass


class InvalidTreeError(Exception):
    pass


class DuplicateItemError(Exception):
    pass


class MarketFamilyRouterHelpersTests(unittest.TestCase):
    def test_fetch_error_maps_to_bad_gateway(self) -> None:
        error = helpers.fetch_error(RuntimeError("provider failed"))

        self.assertEqual(error.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertEqual(error.detail, "provider failed")

    def test_watchlist_group_error_maps_known_statuses(self) -> None:
        not_found = helpers.watchlist_group_error(
            NotFoundError("missing"),
            not_found_errors=(NotFoundError,),
            bad_request_errors=(InvalidTreeError,),
        )
        invalid = helpers.watchlist_group_error(
            InvalidTreeError("bad tree"),
            not_found_errors=(NotFoundError,),
            bad_request_errors=(InvalidTreeError,),
        )
        fallback = helpers.watchlist_group_error(
            RuntimeError("other"),
            not_found_errors=(NotFoundError,),
            bad_request_errors=(InvalidTreeError,),
        )

        self.assertEqual(not_found.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(invalid.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(fallback.status_code, status.HTTP_400_BAD_REQUEST)

    def test_watchlist_item_error_maps_duplicate_to_conflict(self) -> None:
        duplicate = helpers.watchlist_item_error(
            DuplicateItemError("duplicate"),
            not_found_errors=(NotFoundError,),
            duplicate_errors=(DuplicateItemError,),
        )

        self.assertEqual(duplicate.status_code, status.HTTP_409_CONFLICT)

    def test_watchlist_group_target(self) -> None:
        self.assertEqual(helpers.watchlist_group_target(None), "all")
        self.assertEqual(helpers.watchlist_group_target(7), "group:7")

    def test_enqueue_serialized_job_uses_canonical_shape(self) -> None:
        db = object()
        task = Mock()
        job = SimpleNamespace(id=10)

        with (
            patch(
                "app.routers.market_family_helpers.job_service.enqueue_job",
                return_value=(job, True),
            ) as enqueue,
            patch(
                "app.routers.market_family_helpers.job_service.serialize_job",
                return_value={"id": 10},
            ) as serialize,
        ):
            result = helpers.enqueue_serialized_job(
                db=db,  # type: ignore[arg-type]
                job_type="market.job",
                target="all",
                request={"group_id": None},
                message="Queued.",
                task=task,
                task_args=("a", 1),
            )

        self.assertEqual(result, {"id": 10})
        enqueue.assert_called_once_with(
            db=db,
            job_type="market.job",
            target="all",
            request={"group_id": None},
            progress_total=1,
            message="Queued.",
            task=task,
            task_args=("a", 1),
        )
        serialize.assert_called_once_with(job)


if __name__ == "__main__":
    unittest.main()
