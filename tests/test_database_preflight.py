from scripts.database_preflight import classify_database_error


def test_database_error_classifies_quota():
    assert classify_database_error("ERROR: Your account or project has exceeded the quota.") == "QUOTA_EXCEEDED"


def test_database_error_classifies_network():
    assert classify_database_error("Network is unreachable") == "NETWORK_UNREACHABLE"


def test_database_error_classifies_timeout():
    assert classify_database_error("connection timed out") == "CONNECTION_TIMEOUT"


def test_database_error_defaults_to_unavailable():
    assert classify_database_error("connection refused") == "DATABASE_UNAVAILABLE"
