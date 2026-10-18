import json
from pathlib import Path

import pytest

from harvest.http import PoliteClient

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str):
    text = (FIXTURES / name).read_text("utf-8")
    return json.loads(text) if name.endswith(".json") else text


class FakeSleep:
    """Records requested sleeps instead of waiting, so tests run instantly."""

    def __init__(self):
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


@pytest.fixture
def fake_sleep():
    return FakeSleep()


@pytest.fixture
async def client(fake_sleep):
    async with PoliteClient(min_interval=1.0, sleep=fake_sleep) as c:
        yield c
