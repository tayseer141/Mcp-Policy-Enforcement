"""
Unit tests for the runtime-configurable policy layer.

These run fully offline (SQLite, no OpenAI, no Postgres) and cover:
  - the NL -> structured draft heuristic parser,
  - catalog threshold validation,
  - the engine reading thresholds from the DB (incl. disable behaviour).
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.customer_model import Customer
from app.models.policy_model import Policy
from app.policy.engine import evaluate_policies
from app.services.policy_authoring_service import draft_policy_from_text


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    s.add(Customer(name="Ada", company="Acme Corp", credit_limit=1000))
    s.commit()
    yield s
    s.close()


# ---- NL draft parser -------------------------------------------------

def test_draft_delete_policy():
    d = draft_policy_from_text("don't let anyone delete more than 3 customers at once")
    assert d.valid
    assert d.policy_type == "max_delete_count"
    assert d.tool_name == "delete_customer"
    assert d.threshold == 3


def test_draft_credit_limit_policy_percent():
    d = draft_policy_from_text("cap credit-limit raises at 15%")
    assert d.valid
    assert d.policy_type == "max_credit_limit_raise_percent"
    assert d.threshold == 15


def test_draft_starting_credit_limit_policy():
    d = draft_policy_from_text("new customers can't start above 9000")
    assert d.valid
    assert d.policy_type == "max_starting_credit_limit"
    assert d.tool_name == "add_customer"
    assert d.threshold == 9000


def test_draft_invalid_when_unmappable():
    d = draft_policy_from_text("please be nice to everyone")
    assert not d.valid
    assert d.policy_type is None


def test_draft_invalid_without_number():
    d = draft_policy_from_text("limit how many customers can be deleted")
    assert not d.valid  # known type, but no usable number


# ---- Engine reads thresholds from DB ---------------------------------

def test_delete_limit_enforced_from_db(db):
    db.add(Policy(name="max_delete_count", policy_type="max_delete_count",
                  tool_name="delete_customer", threshold=2, enabled=True))
    db.commit()

    ok = evaluate_policies(db, None, "delete_customer", {"customer_ids": [1, 2]})
    assert ok.allowed
    blocked = evaluate_policies(db, None, "delete_customer", {"customer_ids": [1, 2, 3]})
    assert not blocked.allowed


def test_disabled_policy_not_enforced(db):
    db.add(Policy(name="max_delete_count", policy_type="max_delete_count",
                  tool_name="delete_customer", threshold=1, enabled=False))
    db.commit()

    # 5 deletes would normally exceed a limit of 1, but the policy is off.
    decision = evaluate_policies(db, None, "delete_customer", {"customer_ids": [1, 2, 3, 4, 5]})
    assert decision.allowed


def test_default_threshold_when_no_row(db):
    # No Policy rows at all -> catalog default (delete limit = 1) applies.
    decision = evaluate_policies(db, None, "delete_customer", {"customer_ids": [1, 2]})
    assert not decision.allowed


def test_credit_limit_raise_threshold_from_db(db):
    db.add(Policy(name="max_credit_limit_raise_percent", policy_type="max_credit_limit_raise_percent",
                  tool_name="update_credit_limit", threshold=10.0, enabled=True))
    db.commit()

    # current credit limit 1000, +10% allowed, +50% blocked
    ok = evaluate_policies(db, None, "update_credit_limit",
                           {"customer_id": 1, "new_credit_limit": 1100})
    assert ok.allowed
    blocked = evaluate_policies(db, None, "update_credit_limit",
                                {"customer_id": 1, "new_credit_limit": 1500})
    assert not blocked.allowed


def test_starting_credit_limit_threshold_from_db(db):
    db.add(Policy(name="max_starting_credit_limit", policy_type="max_starting_credit_limit",
                  tool_name="add_customer", threshold=5000, enabled=True))
    db.commit()

    ok = evaluate_policies(db, None, "add_customer",
                           {"name": "X", "company": "Acme", "credit_limit": 4000})
    assert ok.allowed
    blocked = evaluate_policies(db, None, "add_customer",
                                {"name": "Y", "company": "Acme", "credit_limit": 9000})
    assert not blocked.allowed


def test_starting_credit_limit_default_when_no_row(db):
    # No row -> catalog default (10000) applies.
    ok = evaluate_policies(db, None, "add_customer",
                           {"name": "Z", "company": "Acme", "credit_limit": 9000})
    assert ok.allowed
    blocked = evaluate_policies(db, None, "add_customer",
                                {"name": "Z", "company": "Acme", "credit_limit": 11000})
    assert not blocked.allowed