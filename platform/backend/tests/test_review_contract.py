"""The platform owns its review output contract; it must stay identical to the POC's copy."""

import importlib.util

import pytest

from app import review_contract
from app.core import config

EXPORTED = (
    "STEP",
    "EPISODE_V1",
    "REVIEW_V1",
    "EPISODE_V2",
    "REVIEW_V2",
    "REVIEW",
    "REVIEW_SCHEMA_VERSION",
    "LABEL",
    "DEDUP",
)


def load_poc_contract():
    path = config.PROJECT_ROOT / "poc" / "schemas.py"
    if not path.is_file():
        pytest.skip("POC sources are not present (for example inside the runtime image)")
    spec = importlib.util.spec_from_file_location("poc_schemas", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", EXPORTED)
def test_platform_contract_matches_poc(name):
    assert getattr(review_contract, name) == getattr(load_poc_contract(), name)


def test_new_reviews_use_schema_version_two():
    assert review_contract.REVIEW is review_contract.REVIEW_V2
    assert review_contract.REVIEW["properties"]["schema_version"]["enum"] == ["2"]
