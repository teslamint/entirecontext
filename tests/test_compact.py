from entirecontext.core.config import DEFAULT_CONFIG


def test_content_retention_days_default():
    assert DEFAULT_CONFIG["capture"]["content_retention_days"] == 30
