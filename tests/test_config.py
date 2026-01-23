import pytest
import os
import tempfile
import yaml
from src.config import Config


@pytest.fixture
def sample_config_file():
    """Create a temporary config file for testing."""
    config_data = {
        "amazon": {
            "domain": "amazon.com",
            "check_frequency": 3600,
            "daily_check_time": "09:00"
        },
        "database": {
            "host": "localhost",
            "user": "root",
            "database": "kindle_deals"
        },
        "storage": {
            "browser_session_path": "~/.kindle-deals/browser-session"
        },
        "email": {
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "from_address": "test@example.com",
            "to_addresses": ["recipient@example.com"],
            "subject_template": "Kindle Deal Alert: {title}"
        },
        "deals": {
            "max_price": 4.00,
            "min_discount_percent": 50,
            "notification_cooldown_days": 30
        },
        "scraping": {
            "headless": True,
            "page_load_timeout": 30000,
            "element_timeout": 10000,
            "check_delay": 2000,
            "action_delay": 500
        }
    }

    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(config_data, f)
        temp_path = f.name

    yield temp_path

    # Cleanup
    os.unlink(temp_path)


def test_load_config(sample_config_file):
    """Test loading configuration from YAML file."""
    config = Config(sample_config_file)
    assert config is not None


def test_get_top_level_key(sample_config_file):
    """Test getting a top-level configuration key."""
    config = Config(sample_config_file)
    assert config.get("amazon") == {
        "domain": "amazon.com",
        "check_frequency": 3600,
        "daily_check_time": "09:00"
    }


def test_get_nested_key_with_dot_notation(sample_config_file):
    """Test getting nested configuration values using dot notation."""
    config = Config(sample_config_file)
    assert config.get("amazon.domain") == "amazon.com"
    assert config.get("amazon.check_frequency") == 3600
    assert config.get("database.host") == "localhost"
    assert config.get("email.smtp_port") == 587


def test_get_deeply_nested_key(sample_config_file):
    """Test getting deeply nested values."""
    config = Config(sample_config_file)
    assert config.get("scraping.headless") is True
    assert config.get("deals.max_price") == 4.00


def test_get_nonexistent_key(sample_config_file):
    """Test getting a nonexistent key returns None."""
    config = Config(sample_config_file)
    assert config.get("nonexistent") is None
    assert config.get("amazon.nonexistent") is None
    assert config.get("nonexistent.nested.key") is None


def test_get_with_default_value(sample_config_file):
    """Test getting a nonexistent key with a default value."""
    config = Config(sample_config_file)
    assert config.get("nonexistent", "default") == "default"
    assert config.get("amazon.nonexistent", 123) == 123


def test_get_list_value(sample_config_file):
    """Test getting a list value from configuration."""
    config = Config(sample_config_file)
    to_addresses = config.get("email.to_addresses")
    assert isinstance(to_addresses, list)
    assert to_addresses == ["recipient@example.com"]


def test_mysql_password_from_env(sample_config_file, monkeypatch):
    """Test that MySQL password is loaded from environment variable."""
    monkeypatch.setenv("MYSQL_PASSWORD", "test_mysql_pass")
    config = Config(sample_config_file)
    assert config.get("database.password") == "test_mysql_pass"


def test_mysql_password_empty_when_no_env(sample_config_file, monkeypatch):
    """Test that MySQL password is empty when env var is not set."""
    monkeypatch.delenv("MYSQL_PASSWORD", raising=False)
    config = Config(sample_config_file)
    assert config.get("database.password") == ""


def test_email_password_from_env(sample_config_file, monkeypatch):
    """Test that email password is loaded from environment variable."""
    monkeypatch.setenv("KINDLE_DEALS_PASSWORD", "test_email_pass")
    config = Config(sample_config_file)
    assert config.get("email.password") == "test_email_pass"


def test_email_password_empty_when_no_env(sample_config_file, monkeypatch):
    """Test that email password is empty when env var is not set."""
    monkeypatch.delenv("KINDLE_DEALS_PASSWORD", raising=False)
    config = Config(sample_config_file)
    assert config.get("email.password") == ""


def test_both_passwords_from_env(sample_config_file, monkeypatch):
    """Test that both passwords are loaded from their respective env vars."""
    monkeypatch.setenv("MYSQL_PASSWORD", "mysql_secret")
    monkeypatch.setenv("KINDLE_DEALS_PASSWORD", "email_secret")
    config = Config(sample_config_file)
    assert config.get("database.password") == "mysql_secret"
    assert config.get("email.password") == "email_secret"


def test_file_not_found():
    """Test that loading a nonexistent file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        Config("/nonexistent/path/config.yaml")


def test_invalid_yaml():
    """Test that loading invalid YAML raises an error."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write("invalid: yaml: content: [[[")
        temp_path = f.name

    try:
        with pytest.raises(yaml.YAMLError):
            Config(temp_path)
    finally:
        os.unlink(temp_path)
