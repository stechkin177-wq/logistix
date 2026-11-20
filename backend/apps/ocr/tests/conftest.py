import pytest

from apps.ocr.tests.helpers import ocr_company


@pytest.fixture
def oco(make_company):
    return ocr_company(make_company)
