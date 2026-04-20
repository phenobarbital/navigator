"""
Navigator Init Command.
Creates basic project structure for Navigator applications.
"""
from pathlib import Path
from . import BaseCommand


class InitCommand(BaseCommand):
    """Initialize a new Navigator project with basic structure."""

    help = "Initialize a new Navigator project with basic directory structure and configuration files."
    _version: str = "1.0.0"
    default_action: str = "create"

    def parse_arguments(self, parser):
        """Add custom arguments for the init command."""
        parser.add_argument(
            "--app-name",
            type=str,
            default="navigator",
            help="Name of the application (default: navigator)"
        )
        parser.add_argument(
            "--app-title",
            type=str,
            default="Navigator",
            help="Title of the application (default: Navigator)"
        )
        parser.add_argument(
            "--host",
            type=str,
            default="0.0.0.0",
            help="Application host (default: 0.0.0.0)"
        )
        parser.add_argument(
            "--port",
            type=int,
            default=5000,
            help="Application port (default: 5000)"
        )

    def create(self, options, **kwargs):
        """Create the basic Navigator project structure."""
        path = Path(kwargs["project_path"]).resolve()

        # Define file contents
        env_content = f"""CONFIG_FILE=etc/navigator.ini

[application]
APP_HOST={options.host}
APP_LOGNAME={options.app_title}
APP_PORT={options.port}
"""

        navigator_ini_content = f"""[info]
OWNER: TROC
APP_NAME: {options.app_name}
SITE_ID: 1
APP_TITLE: {options.app_title}

[logging]
logdir: /tmp/navigator/log/
logging_echo: true
## Rotating file log:
filehandler_enabled: true

[ssl]
SSL: false
# CERT: /etc/ssl/certs/trocglobal.com.crt
# KEY: /etc/ssl/certs/trocglobal.com.key
"""

        output = "Navigator project initialized successfully."

        if options.debug:
            self.write(":: Initializing Navigator Project", level="INFO")
            self.write("= Creating basic project structure", level="WARN")

        try:
            # Step 1: Create directory structure
            self.write("* Step 1: Creating directory structure")

            # Create env folder
            self._create_dir(path, "env")

            # Create etc folder
            self._create_dir(path, "etc")

            # Create settings folder with __init__.py
            self._create_dir(path, "settings", touch_init=True)

            # and Apps folder:
            self._create_dir(path, "apps", touch_init=True)

            # Step 2: Create .env file
            self.write("* Step 2: Creating .env file")
            self._save_file(path, ".env", env_content)

            # Step 3: Create navigator.ini file
            self.write("* Step 3: Creating navigator.ini configuration file")
            etc_path = path.joinpath("etc")
            self._save_file(etc_path, "navigator.ini", navigator_ini_content)

            self.write("* Project initialization completed successfully!")

            if options.debug:
                self.write("  - Created: env/ directory", level="DEBUG")
                self.write("  - Created: etc/ directory", level="DEBUG")
                self.write("  - Created: settings/ directory with __init__.py", level="DEBUG")
                self.write("  - Created: .env file", level="DEBUG")
                self.write("  - Created: etc/navigator.ini file", level="DEBUG")

        except Exception as err:
            self.write(f":: Error during initialization: {err!s}", level="ERROR")
            output = "Failed to initialize project."

        return output

    def configure(self):
        """Configure the command (override to avoid template parser setup)."""
        # We don't need the template parser for the init command
        pass

    def run(self, options, **kwargs):
        """Default run method - alias for create."""
        return self.create(options, **kwargs)
