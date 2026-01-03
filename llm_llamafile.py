"""LLM plugin for llamafile - manages local llamafile server automatically."""
import atexit
import hashlib
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Dict, Any

import llm
from llm.default_plugins.openai_models import Chat
from pydantic import Field


# Configuration
DEFAULT_PORT = 8080
DEFAULT_IDLE_TIMEOUT = 300  # 5 minutes
LLAMAFILE_VERSION = "0.8.13"  # Update this to use newer versions

# Platform-specific paths
if platform.system() == "Windows":
    CACHE_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "llm-llamafile"
else:
    CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "llm-llamafile"

STATE_FILE = CACHE_DIR / "server.json"
BINARY_DIR = CACHE_DIR / "bin"


def get_platform_info() -> tuple[str, str]:
    """Return (os_name, arch) for llamafile binary selection."""
    system = platform.system()
    machine = platform.machine().lower()

    if system == "Darwin":
        os_name = "macos"
        arch = "arm64" if machine in ("arm64", "aarch64") else "amd64"
    elif system == "Linux":
        os_name = "linux"
        arch = "arm64" if machine in ("arm64", "aarch64") else "amd64"
    elif system == "Windows":
        os_name = "windows"
        arch = "amd64"  # llamafile primarily supports x64 on Windows
    else:
        raise RuntimeError(f"Unsupported platform: {system}")

    return os_name, arch


def get_llamafile_url(version: str = LLAMAFILE_VERSION) -> str:
    """Get download URL for llamafile binary."""
    os_name, arch = get_platform_info()

    # Llamafile releases universal binaries
    # Check https://github.com/Mozilla-Ocho/llamafile/releases
    base_url = f"https://github.com/Mozilla-Ocho/llamafile/releases/download/{version}"

    if os_name == "windows":
        filename = "llamafile.exe"
    else:
        filename = "llamafile"

    return f"{base_url}/{filename}"


def download_llamafile(force: bool = False) -> Path:
    """Download llamafile binary if not present."""
    BINARY_DIR.mkdir(parents=True, exist_ok=True)

    binary_name = "llamafile.exe" if platform.system() == "Windows" else "llamafile"
    binary_path = BINARY_DIR / f"{binary_name}-{LLAMAFILE_VERSION}"

    if binary_path.exists() and not force:
        return binary_path

    url = get_llamafile_url()
    print(f"Downloading llamafile {LLAMAFILE_VERSION} from {url}...", file=sys.stderr)

    try:
        with urllib.request.urlopen(url, timeout=300) as response:
            with open(binary_path, 'wb') as f:
                shutil.copyfileobj(response, f)

        # Make executable on Unix
        if platform.system() != "Windows":
            binary_path.chmod(0o755)

        print(f"Downloaded to {binary_path}", file=sys.stderr)
        return binary_path
    except Exception as e:
        if binary_path.exists():
            binary_path.unlink()
        raise RuntimeError(f"Failed to download llamafile: {e}")


class ServerManager:
    """Manages llamafile server lifecycle with idle timeout."""

    def __init__(self, port: int = DEFAULT_PORT, idle_timeout: int = DEFAULT_IDLE_TIMEOUT):
        self.port = port
        self.idle_timeout = idle_timeout
        self.process: Optional[subprocess.Popen] = None
        self._state_file = STATE_FILE

        # Register cleanup on exit
        atexit.register(self._cleanup)

    def _load_state(self) -> Optional[Dict[str, Any]]:
        """Load server state from file."""
        if not self._state_file.exists():
            return None
        try:
            with open(self._state_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def _save_state(self, state: Dict[str, Any]):
        """Save server state to file."""
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._state_file, 'w') as f:
            json.dump(state, f, indent=2)

    def _clear_state(self):
        """Clear server state file."""
        if self._state_file.exists():
            self._state_file.unlink()

    def is_running(self) -> bool:
        """Check if server is running."""
        state = self._load_state()
        if not state:
            return False

        pid = state.get("pid")
        if not pid:
            return False

        # Check if process exists
        try:
            if platform.system() == "Windows":
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}"],
                    capture_output=True,
                    text=True,
                    check=False
                )
                return str(pid) in result.stdout
            else:
                os.kill(pid, 0)
                return True
        except (OSError, subprocess.SubprocessError):
            self._clear_state()
            return False

    def wait_for_ready(self, timeout: float = 30) -> bool:
        """Wait for server to be ready."""
        start = time.time()
        while time.time() - start < timeout:
            try:
                req = urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}/health",
                    timeout=1
                )
                req.close()
                return True
            except (urllib.error.URLError, OSError):
                time.sleep(0.5)
        return False

    def _start_watchdog(self, server_pid: int):
        """Spawn a background watchdog process that kills server after idle timeout."""
        if self.idle_timeout <= 0:
            return

        if platform.system() == "Windows":
            # On Windows, spawn a detached Python process as watchdog
            script = f'''
import time
import sys
import subprocess
from pathlib import Path

state_file = Path(r"{self._state_file}")
idle_timeout = {self.idle_timeout}
server_pid = {server_pid}

while True:
    time.sleep(30)
    if not state_file.exists():
        sys.exit(0)
    try:
        mtime = state_file.stat().st_mtime
        if time.time() - mtime > idle_timeout:
            subprocess.run(["taskkill", "/F", "/PID", str(server_pid)], capture_output=True)
            state_file.unlink(missing_ok=True)
            sys.exit(0)
    except:
        sys.exit(0)
'''
            subprocess.Popen(
                [sys.executable, "-c", script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            # On Unix, fork a detached watchdog process
            pid = os.fork()
            if pid == 0:
                # Child process - detach from parent
                os.setsid()

                # Fork again to ensure we're fully detached
                pid2 = os.fork()
                if pid2 == 0:
                    # Grandchild - the actual watchdog
                    # Close all file descriptors
                    sys.stdout.close()
                    sys.stderr.close()
                    sys.stdin.close()

                    while True:
                        time.sleep(30)
                        if not self._state_file.exists():
                            os._exit(0)
                        try:
                            mtime = self._state_file.stat().st_mtime
                            if time.time() - mtime > self.idle_timeout:
                                os.kill(server_pid, signal.SIGTERM)
                                self._state_file.unlink(missing_ok=True)
                                os._exit(0)
                        except (OSError, FileNotFoundError):
                            os._exit(0)

                # Parent of grandchild exits immediately
                os._exit(0)

    def touch(self):
        """Reset idle timeout by updating state file mtime."""
        if self._state_file.exists():
            try:
                self._state_file.touch()
            except OSError:
                pass

    def start(self, model_path: Optional[Path] = None, context_size: int = 8192,
              n_gpu_layers: int = -1) -> bool:
        """Start the llamafile server."""
        if self.is_running():
            self.touch()
            return True

        # Use provided model or download a default one
        if not model_path:
            # For now, expect user to provide a model
            # In future, could download a default small model
            raise RuntimeError(
                "No model specified. Please provide a model path or download a llamafile model.\n"
                "See: https://github.com/Mozilla-Ocho/llamafile#quickstart"
            )

        if not model_path.exists():
            raise RuntimeError(f"Model not found: {model_path}")

        # Get llamafile binary
        binary_path = download_llamafile()

        # Build command
        cmd = [
            str(binary_path),
            "-m", str(model_path),
            "--server",
            "--host", "127.0.0.1",
            "--port", str(self.port),
            "--ctx-size", str(context_size),
            "--n-gpu-layers", str(n_gpu_layers),
        ]

        # Start server
        kwargs = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }

        if platform.system() == "Windows":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True

        try:
            self.process = subprocess.Popen(cmd, **kwargs)

            # Save state
            self._save_state({
                "pid": self.process.pid,
                "port": self.port,
                "model": str(model_path),
                "started_at": time.time(),
            })

            # Wait for server to be ready
            if not self.wait_for_ready():
                self.stop()
                raise RuntimeError("Server failed to start - check model compatibility")

            # Start watchdog for idle timeout
            self._start_watchdog(self.process.pid)

            return True
        except Exception as e:
            self._clear_state()
            raise RuntimeError(f"Failed to start server: {e}")

    def stop(self):
        """Stop the server and clean up state."""
        state = self._load_state()
        if not state:
            return

        pid = state.get("pid")
        if not pid:
            return

        try:
            if platform.system() == "Windows":
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid)],
                    capture_output=True,
                    check=False
                )
            else:
                os.kill(pid, signal.SIGTERM)
                # Give it a moment to shut down gracefully
                time.sleep(1)
        except (OSError, subprocess.SubprocessError):
            pass
        finally:
            self._clear_state()

    def _cleanup(self):
        """Cleanup on exit."""
        if self.is_running():
            self.stop()

    def get_status(self) -> Dict[str, Any]:
        """Get server status information."""
        if not self.is_running():
            return {"running": False}

        state = self._load_state()
        return {
            "running": True,
            "pid": state.get("pid"),
            "port": state.get("port"),
            "model": state.get("model"),
            "uptime": time.time() - state.get("started_at", time.time()),
        }


# Global server manager
_manager: Optional[ServerManager] = None


def get_manager() -> ServerManager:
    """Get or create the global server manager."""
    global _manager
    if _manager is None:
        _manager = ServerManager()
    return _manager


class Llamafile(Chat):
    """LLM plugin for llamafile with automatic server management."""

    needs_key = None
    key_env_var = None

    class Options(llm.Options):
        model_path: Optional[str] = Field(
            default=None,
            description="Path to llamafile model file"
        )
        port: int = Field(
            default=DEFAULT_PORT,
            description="Port for llamafile server"
        )
        idle_timeout: int = Field(
            default=DEFAULT_IDLE_TIMEOUT,
            description="Idle timeout in seconds (0 to disable)"
        )
        context_size: int = Field(
            default=8192,
            description="Context size for the model"
        )
        n_gpu_layers: int = Field(
            default=-1,
            description="Number of layers to offload to GPU (-1 for all)"
        )

    def __init__(self, model_id: str = "llamafile"):
        self.model_id = model_id
        self._manager = None

    def __str__(self):
        return f"Llamafile: {self.model_id}"

    def execute(self, prompt, stream, response, conversation):
        """Execute a prompt against the llamafile server."""
        # Get options
        options = prompt.options
        model_path = options.model_path
        port = options.port
        idle_timeout = options.idle_timeout
        context_size = options.context_size
        n_gpu_layers = options.n_gpu_layers

        # Initialize manager if needed
        if self._manager is None or self._manager.port != port:
            self._manager = ServerManager(port=port, idle_timeout=idle_timeout)

        # Ensure server is running
        if not self._manager.is_running():
            if not model_path:
                # Try to get from environment
                model_path = os.environ.get("LLM_LLAMAFILE_MODEL")

            if not model_path:
                raise llm.ModelError(
                    "No model specified. Set LLM_LLAMAFILE_MODEL environment variable "
                    "or use --option model_path <path>"
                )

            self._manager.start(
                model_path=Path(model_path),
                context_size=context_size,
                n_gpu_layers=n_gpu_layers
            )

        # Touch to reset idle timeout
        self._manager.touch()

        # Set API base and delegate to parent Chat class
        self.api_base = f"http://127.0.0.1:{port}/v1"
        self.model_name = self.model_id

        return super().execute(prompt, stream, response, conversation)


@llm.hookimpl
def register_models(register):
    """Register llamafile model."""
    register(Llamafile("llamafile"))


@llm.hookimpl
def register_commands(cli):
    """Register CLI commands for server management."""
    import click

    @cli.group(name="llamafile")
    def llamafile_group():
        """Manage llamafile server."""
        pass

    @llamafile_group.command(name="status")
    def status():
        """Show llamafile server status."""
        manager = get_manager()
        status = manager.get_status()

        if status["running"]:
            click.echo(f"Status: Running")
            click.echo(f"PID: {status['pid']}")
            click.echo(f"Port: {status['port']}")
            click.echo(f"Model: {status['model']}")
            click.echo(f"Uptime: {status['uptime']:.1f}s")
        else:
            click.echo("Status: Not running")

    @llamafile_group.command(name="stop")
    def stop():
        """Stop the llamafile server."""
        manager = get_manager()
        if manager.is_running():
            manager.stop()
            click.echo("Server stopped")
        else:
            click.echo("Server not running")

    @llamafile_group.command(name="start")
    @click.option("--model", "-m", help="Path to model file",
                  default=lambda: os.environ.get("LLM_LLAMAFILE_MODEL"))
    @click.option("--port", "-p", default=DEFAULT_PORT, help="Server port")
    @click.option("--context-size", "-c", default=8192, help="Context size")
    @click.option("--gpu-layers", "-g", default=-1, help="GPU layers (-1 for all)")
    def start(model, port, context_size, gpu_layers):
        """Start the llamafile server."""
        if not model:
            click.echo("Error: No model specified. Use --model or set LLM_LLAMAFILE_MODEL", err=True)
            return

        manager = ServerManager(port=port)
        try:
            manager.start(
                model_path=Path(model),
                context_size=context_size,
                n_gpu_layers=gpu_layers
            )
            click.echo(f"Server started on port {port}")
        except Exception as e:
            click.echo(f"Error: {e}", err=True)

    @llamafile_group.command(name="download")
    @click.option("--force", "-f", is_flag=True, help="Force re-download")
    def download(force):
        """Download llamafile binary."""
        try:
            binary_path = download_llamafile(force=force)
            click.echo(f"Llamafile binary: {binary_path}")
        except Exception as e:
            click.echo(f"Error: {e}", err=True)
