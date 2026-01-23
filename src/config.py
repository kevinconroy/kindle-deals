import os
import yaml
from typing import Any, Optional


class Config:
    """Configuration loader for Kindle Deals Monitor.

    Loads configuration from a YAML file and provides dot notation access
    to nested values. Also loads sensitive values (passwords) from
    environment variables.
    """

    def __init__(self, config_path: str):
        """
        Initialize configuration from YAML file.

        Args:
            config_path: Path to the YAML configuration file

        Raises:
            FileNotFoundError: If the config file doesn't exist
            yaml.YAMLError: If the YAML file is invalid
        """
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        with open(config_path, 'r') as f:
            self._config = yaml.safe_load(f)

        if self._config is None:
            self._config = {}

        # Load passwords from environment variables
        self._load_environment_secrets()

    def _load_environment_secrets(self):
        """Load sensitive configuration from environment variables."""
        # MySQL password from MYSQL_PASSWORD environment variable
        mysql_password = os.environ.get('MYSQL_PASSWORD', '')
        if 'database' not in self._config:
            self._config['database'] = {}
        self._config['database']['password'] = mysql_password

        # Email password from KINDLE_DEALS_PASSWORD environment variable
        email_password = os.environ.get('KINDLE_DEALS_PASSWORD', '')
        if 'email' not in self._config:
            self._config['email'] = {}
        self._config['email']['password'] = email_password

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a configuration value using dot notation.

        Args:
            key: Configuration key (supports dot notation, e.g., "amazon.domain")
            default: Default value to return if key doesn't exist

        Returns:
            The configuration value or default if not found

        Examples:
            >>> config.get("amazon.domain")
            "amazon.com"
            >>> config.get("deals.max_price")
            4.00
            >>> config.get("nonexistent", "default")
            "default"
        """
        # Split the key by dots to handle nested access
        keys = key.split('.')
        value = self._config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value
