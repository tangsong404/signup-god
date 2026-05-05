"""Shared test fixtures."""

from __future__ import annotations

import pytest

from registrars.deepseek.config import DeepSeekConfig


@pytest.fixture
def deepseek_config() -> DeepSeekConfig:
    return DeepSeekConfig(device_id="test-device-id")
