import platform
import pytest
import time
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from urllib.error import URLError
import llm_llamafile


def test_get_platform_info():
    """Test platform detection."""
    os_name, arch = llm_llamafile.get_platform_info()
    assert os_name in ("linux", "macos", "windows")
    assert arch in ("amd64", "arm64")


def test_get_llamafile_url():
    """Test URL generation for llamafile download."""
    url = llm_llamafile.get_llamafile_url("0.8.13")
    assert "github.com/Mozilla-Ocho/llamafile" in url
    assert "0.8.13" in url

    if platform.system() == "Windows":
        assert url.endswith("llamafile.exe")
    else:
        assert url.endswith("llamafile")


def test_server_manager_initialization():
    """Test ServerManager initialization."""
    manager = llm_llamafile.ServerManager(port=8081, idle_timeout=600)
    assert manager.port == 8081
    assert manager.idle_timeout == 600
    assert manager.process is None


def test_server_manager_state_operations(tmp_path):
    """Test state save/load/clear operations."""
    state_file = tmp_path / "test_state.json"
    manager = llm_llamafile.ServerManager()
    manager._state_file = state_file

    # Test save
    manager._save_state({"pid": 12345, "port": 8080})
    assert state_file.exists()

    # Test load
    state = manager._load_state()
    assert state["pid"] == 12345
    assert state["port"] == 8080

    # Test clear
    manager._clear_state()
    assert not state_file.exists()


def test_server_manager_not_running_without_state(tmp_path):
    """Test that is_running returns False when no state file exists."""
    state_file = tmp_path / "nonexistent_state.json"
    manager = llm_llamafile.ServerManager()
    manager._state_file = state_file

    assert not manager.is_running()


@patch('urllib.request.urlopen')
def test_wait_for_ready_success(mock_urlopen):
    """Test successful health check."""
    mock_response = MagicMock()
    mock_urlopen.return_value = mock_response

    manager = llm_llamafile.ServerManager()
    assert manager.wait_for_ready(timeout=1)
    mock_urlopen.assert_called()


@patch('urllib.request.urlopen')
def test_wait_for_ready_timeout(mock_urlopen):
    """Test health check timeout."""
    mock_urlopen.side_effect = URLError("Connection refused")

    manager = llm_llamafile.ServerManager()
    assert not manager.wait_for_ready(timeout=0.5)


def test_llamafile_model_initialization():
    """Test Llamafile model initialization."""
    model = llm_llamafile.Llamafile("test-model")
    assert model.model_id == "test-model"
    assert str(model) == "Llamafile: test-model"


def test_llamafile_model_options():
    """Test that Llamafile model has correct options."""
    model = llm_llamafile.Llamafile()
    options_class = model.Options

    # Check that required options exist
    assert hasattr(options_class, '__annotations__')
    annotations = options_class.__annotations__

    assert 'model_path' in annotations
    assert 'port' in annotations
    assert 'idle_timeout' in annotations
    assert 'context_size' in annotations
    assert 'n_gpu_layers' in annotations


def test_cache_dir_path():
    """Test that cache directory is set correctly."""
    cache_dir = llm_llamafile.CACHE_DIR
    assert isinstance(cache_dir, Path)

    if platform.system() == "Windows":
        assert "llm-llamafile" in str(cache_dir)
    else:
        assert ".cache/llm-llamafile" in str(cache_dir)


def test_binary_dir_path():
    """Test that binary directory path is correct."""
    binary_dir = llm_llamafile.BINARY_DIR
    assert isinstance(binary_dir, Path)
    assert binary_dir.name == "bin"


@patch('llm_llamafile.download_llamafile')
@patch('subprocess.Popen')
def test_server_start_with_invalid_model(mock_popen, mock_download):
    """Test that starting server with non-existent model raises error."""
    manager = llm_llamafile.ServerManager()

    with pytest.raises(RuntimeError, match="Model not found"):
        manager.start(model_path=Path("/nonexistent/model.llamafile"))


def test_touch_updates_mtime(tmp_path):
    """Test that touch() updates state file mtime."""
    state_file = tmp_path / "test_state.json"
    manager = llm_llamafile.ServerManager(idle_timeout=10)
    manager._state_file = state_file

    # Create state file
    manager._save_state({"pid": 12345, "port": 8080})
    original_mtime = state_file.stat().st_mtime

    # Wait a bit then touch
    time.sleep(0.1)
    manager.touch()

    # mtime should be updated
    new_mtime = state_file.stat().st_mtime
    assert new_mtime > original_mtime


def test_constants():
    """Test that constants are defined correctly."""
    assert llm_llamafile.DEFAULT_PORT == 8080
    assert llm_llamafile.DEFAULT_IDLE_TIMEOUT == 300
    assert isinstance(llm_llamafile.LLAMAFILE_VERSION, str)
    assert len(llm_llamafile.LLAMAFILE_VERSION) > 0
