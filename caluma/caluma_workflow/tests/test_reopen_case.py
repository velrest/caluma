import pytest
from django.core.exceptions import ValidationError
from graphene_django.utils.str_converters import to_const

from .. import api, models


def reopen_case_setup(case_status, work_item_statuses, case_factory, work_item_factory):
    case = case_factory(status=case_status)
    work_items = []

    for work_item_status in work_item_statuses:
        work_items.append(work_item_factory(case=case, status=work_item_status))

    return case, work_items


@pytest.mark.parametrize("use_graphql", [False, True])
def test_allow_completed_cases_to_be_reopened(
    db, admin_user, case_factory, work_item_factory, schema_executor, use_graphql
):
    completed_case, completed_work_items = reopen_case_setup(
        models.Case.STATUS_COMPLETED,
        [models.WorkItem.STATUS_COMPLETED],
        case_factory,
        work_item_factory,
    )

    if use_graphql:
        query = """
            mutation ReopenCase($input: ReopenCaseInput!) {
                reopenCase(input: $input) {
                    case {
                        status
                        workItems {
                            edges {
                                node {
                                    status
                                }
                            }
                        }
                    }
                    clientMutationId
                }
            }
        """

        inp = {
            "input": {
                "id": str(completed_case.pk),
                "workItems": [str(completed_work_items[0].pk)],
            }
        }

        result = schema_executor(query, variable_values=inp)
        assert not result.errors
        assert result.data["reopenCase"]["case"]["status"] == to_const(
            models.Case.STATUS_RUNNING
        )
        assert result.data["reopenCase"]["case"]["workItems"]["edges"][0]["node"][
            "status"
        ] == to_const(models.WorkItem.STATUS_READY)
    else:
        api.reopen_case(completed_case, completed_work_items, admin_user)

        completed_case.refresh_from_db()

        assert completed_case.status == models.Case.STATUS_RUNNING
        assert completed_work_items[0].status == models.WorkItem.STATUS_READY


def test_reject_suspended_cases_during_reopen(
    db,
    admin_user,
    case_factory,
    work_item_factory,
):
    suspended_case, work_items = reopen_case_setup(
        models.Case.STATUS_SUSPENDED,
        [models.WorkItem.STATUS_COMPLETED],
        case_factory,
        work_item_factory,
    )

    with pytest.raises(ValidationError):
        api.reopen_case(suspended_case, work_items, admin_user)


def test_require_at_least_1_work_item_during_case_reopening(
    db, admin_user, schema_executor, case_factory, work_item_factory
):
    case, completed_work_items = reopen_case_setup(
        models.Case.STATUS_COMPLETED,
        [models.WorkItem.STATUS_COMPLETED],
        case_factory,
        work_item_factory,
    )

    query = """
        mutation ReopenCase($input: ReopenCaseInput!) {
            reopenCase(input: $input) {
                case {
                    status
                }
                clientMutationId
            }
        }
    """

    inp = {"input": {"caseId": str(case.pk), "workItemIds": []}}

    result = schema_executor(query, variable_values=inp)
    assert result.errors


def test_only_supplied_work_items_readied(
    db, admin_user, schema_executor, case_factory, work_item_factory
):
    case, work_items = reopen_case_setup(
        models.Case.STATUS_COMPLETED,
        [
            models.WorkItem.STATUS_COMPLETED,
            models.WorkItem.STATUS_SKIPPED,
            models.WorkItem.STATUS_CANCELED,
        ],
        case_factory,
        work_item_factory,
    )

    api.reopen_case(case, [work_items[0]], admin_user)

    case.refresh_from_db()

    assert work_items[0].status == models.WorkItem.STATUS_READY
    assert work_items[1].status == models.WorkItem.STATUS_SKIPPED
    assert work_items[2].status == models.WorkItem.STATUS_CANCELED


def test_work_items_not_lost(
    db, admin_user, schema_executor, case_factory, work_item_factory
):
    case, work_items = reopen_case_setup(
        models.Case.STATUS_COMPLETED,
        [
            models.WorkItem.STATUS_COMPLETED,
            models.WorkItem.STATUS_SKIPPED,
            models.WorkItem.STATUS_CANCELED,
        ],
        case_factory,
        work_item_factory,
    )

    api.reopen_case(case, [work_items[0]], admin_user)

    case.refresh_from_db()

    assert work_items[0] in case.work_items.all()
    assert work_items[1] in case.work_items.all()
    assert work_items[2] in case.work_items.all()


def test_only_cases_without_parent_case(
    db, case_factory, work_item_factory, admin_user
):
    parent_case = case_factory()
    child_case, work_items = reopen_case_setup(
        models.Case.STATUS_COMPLETED,
        [
            models.WorkItem.STATUS_COMPLETED,
            models.WorkItem.STATUS_SKIPPED,
            models.WorkItem.STATUS_CANCELED,
        ],
        case_factory,
        work_item_factory,
    )

    child_case.family = parent_case
    child_case.save()

    with pytest.raises(ValidationError):
        api.reopen_case(child_case, work_items, admin_user)


def test_only_work_items_at_end_of_branch(
    db, case_factory, work_item_factory, admin_user
):
    case, work_items = reopen_case_setup(
        models.Case.STATUS_COMPLETED,
        [models.WorkItem.STATUS_COMPLETED],
        case_factory,
        work_item_factory,
    )

    # add a work item after the one returned by the reopen_case_setup
    work_item_factory(previous_work_item=work_items[0])

    with pytest.raises(ValidationError):
        api.reopen_case(case, work_items, admin_user)


def test_only_work_items_belonging_to_case(
    db, case_factory, work_item_factory, admin_user
):
    case, work_items = reopen_case_setup(
        models.Case.STATUS_COMPLETED,
        [models.WorkItem.STATUS_COMPLETED],
        case_factory,
        work_item_factory,
    )

    other_case_work_item = work_item_factory()

    with pytest.raises(ValidationError):
        api.reopen_case(case, [other_case_work_item], admin_user)
