import os
from dataclasses import dataclass
from typing import Optional
from pathlib import Path
import yaml

@dataclass
class ServiceConfig:
    github_token: str
    openai_api_key: str
    github_owner: str
    github_repo: str
    parser_dir: Optional[str] = None
    db_path: Optional[str] = None
    embeddings_model: str = "text-embedding-ada-002"
    completion_model: str = "gpt-4"

class ConfigManager:
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize configuration manager.
        
        Args:
            config_path: Path to config file (default: ~/.codebase_understanding/config.yml)
        """
        if config_path is None:
            config_path = os.path.join(
                os.path.expanduser("~"),
                ".codebase_understanding",
                "config.yml"
            )
        self.config_path = config_path

    def load_config(self) -> ServiceConfig:
        """Load configuration from file and environment variables."""
        config_data = {}
        
        # Load from config file if it exists
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r') as f:
                config_data = yaml.safe_load(f) or {}

        # Environment variables take precedence
        config = ServiceConfig(
            github_token=os.getenv('GITHUB_TOKEN') or config_data.get('github_token'),
            openai_api_key=os.getenv('OPENAI_API_KEY') or config_data.get('openai_api_key'),
            github_owner=os.getenv('GITHUB_OWNER') or config_data.get('github_owner'),
            github_repo=os.getenv('GITHUB_REPO') or config_data.get('github_repo'),
            parser_dir=os.getenv('PARSER_DIR') or config_data.get('parser_dir'),
            db_path=os.getenv('DB_PATH') or config_data.get('db_path'),
            embeddings_model=os.getenv('EMBEDDINGS_MODEL') or config_data.get('embeddings_model', "text-embedding-ada-002"),
            completion_model=os.getenv('COMPLETION_MODEL') or config_data.get('completion_model', "gpt-4")
        )

        # Validate required fields
        missing = []
        if not config.github_token:
            missing.append("GITHUB_TOKEN")
        if not config.openai_api_key:
            missing.append("OPENAI_API_KEY")
        if not config.github_owner:
            missing.append("GITHUB_OWNER")
        if not config.github_repo:
            missing.append("GITHUB_REPO")

        if missing:
            raise ValueError(f"Missing required configuration: {', '.join(missing)}")

        return config

    def save_config(self, config: ServiceConfig) -> None:
        """Save configuration to file."""
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        
        config_data = {
            'github_token': config.github_token,
            'openai_api_key': config.openai_api_key,
            'github_owner': config.github_owner,
            'github_repo': config.github_repo,
            'parser_dir': config.parser_dir,
            'db_path': config.db_path,
            'embeddings_model': config.embeddings_model,
            'completion_model': config.completion_model
        }

        with open(self.config_path, 'w') as f:
            yaml.dump(config_data, f) 