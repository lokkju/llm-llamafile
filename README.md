# llm-llamafile

[![PyPI](https://img.shields.io/pypi/v/llm-llamafile.svg)](https://pypi.org/project/llm-llamafile/)
[![Changelog](https://img.shields.io/github/v/release/simonw/llm-llamafile?include_prereleases&label=changelog)](https://github.com/simonw/llm-llamafile/releases)
[![Tests](https://github.com/simonw/llm-llamafile/actions/workflows/test.yml/badge.svg)](https://github.com/simonw/llm-llamafile/actions/workflows/test.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/simonw/llm-llamafile/blob/main/LICENSE)

Run local LLM models with llamafile integration for the LLM CLI tool.

This plugin automatically manages llamafile server lifecycle, downloads the llamafile binary, and provides an easy interface to local LLM models.

## Features

- **Automatic server management**: Starts llamafile server on-demand, stops after idle timeout
- **Binary management**: Automatically downloads the appropriate llamafile binary for your platform
- **Idle timeout**: Server shuts down after 5 minutes of inactivity (configurable)
- **Cross-platform**: Works on Linux, macOS, and Windows
- **GPU support**: Automatic GPU offloading when available
- **CLI commands**: Manage server with `llm llamafile` commands

## Installation

Install this plugin in the same environment as [LLM](https://llm.datasette.io/):
```bash
llm install llm-llamafile
```

## Quick Start

1. Download a llamafile model (e.g., from [HuggingFace](https://huggingface.co/models?other=llamafile)):
   ```bash
   wget https://huggingface.co/Mozilla/Meta-Llama-3.1-8B-Instruct-llamafile/resolve/main/Meta-Llama-3.1-8B-Instruct.Q6_K.llamafile
   chmod +x Meta-Llama-3.1-8B-Instruct.Q6_K.llamafile  # On Unix systems
   ```

2. Set the model path:
   ```bash
   export LLM_LLAMAFILE_MODEL=/path/to/Meta-Llama-3.1-8B-Instruct.Q6_K.llamafile
   ```

3. Use the model:
   ```bash
   llm -m llamafile "What are 3 interesting facts about pelicans?"
   ```

The plugin will automatically:
- Download the llamafile binary (first run only)
- Start the server with your model
- Execute your query
- Keep the server running for subsequent queries
- Shut down after 5 minutes of inactivity

## Usage

### Basic Query

```bash
llm -m llamafile "Your prompt here"
```

### With Options

```bash
# Specify model path inline
llm -m llamafile --option model_path /path/to/model.llamafile "Your prompt"

# Change port
llm -m llamafile --option port 8081 "Your prompt"

# Adjust context size
llm -m llamafile --option context_size 16384 "Your prompt"

# Disable GPU (CPU only)
llm -m llamafile --option n_gpu_layers 0 "Your prompt"

# Disable idle timeout (server stays running)
llm -m llamafile --option idle_timeout 0 "Your prompt"
```

### Server Management

The plugin provides CLI commands to manage the llamafile server:

```bash
# Check server status
llm llamafile status

# Start server manually
llm llamafile start --model /path/to/model.llamafile

# Start with options
llm llamafile start --model /path/to/model.llamafile --port 8081 --context-size 16384

# Stop server
llm llamafile stop

# Download/update llamafile binary
llm llamafile download

# Force re-download binary
llm llamafile download --force
```

## Configuration

### Environment Variables

- `LLM_LLAMAFILE_MODEL`: Default model path
- `XDG_CACHE_HOME`: Cache directory (Unix, defaults to `~/.cache`)
- `LOCALAPPDATA`: Cache directory (Windows, defaults to `%LOCALAPPDATA%`)

### Options

All options can be passed via `--option` flag:

| Option | Default | Description |
|--------|---------|-------------|
| `model_path` | `$LLM_LLAMAFILE_MODEL` | Path to llamafile model |
| `port` | `8080` | Server port |
| `idle_timeout` | `300` | Idle timeout in seconds (0 to disable) |
| `context_size` | `8192` | Model context size |
| `n_gpu_layers` | `-1` | GPU layers to offload (-1 for all) |

### Cache Locations

The plugin stores files in platform-specific cache directories:

- **Linux/macOS**: `~/.cache/llm-llamafile/`
  - Binary: `~/.cache/llm-llamafile/bin/llamafile-{version}`
  - State: `~/.cache/llm-llamafile/server.json`

- **Windows**: `%LOCALAPPDATA%\llm-llamafile\`
  - Binary: `%LOCALAPPDATA%\llm-llamafile\bin\llamafile.exe-{version}`
  - State: `%LOCALAPPDATA%\llm-llamafile\server.json`

## How It Works

1. **First run**: Downloads llamafile binary for your platform
2. **On query**: Checks if server is running; starts it if needed
3. **Server startup**: Launches llamafile with your model and spawns a watchdog process
4. **Query execution**: Forwards request to local server; updates state file mtime
5. **Watchdog monitoring**: Detached watchdog process monitors state file mtime
6. **Idle timeout**: After 5 minutes of no mtime updates, watchdog kills server
7. **Next query**: Server restarts automatically when needed

The watchdog process is fully detached and persists after the `llm` command exits, ensuring proper idle timeout even when the parent process terminates.

## Advanced Usage

### Using Different Models

You can switch between models by specifying different paths:

```bash
# Use model A
llm -m llamafile --option model_path /path/to/modelA.llamafile "Query 1"

# Use model B (will restart server with new model)
llm -m llamafile --option model_path /path/to/modelB.llamafile "Query 2"
```

### Streaming Responses

```bash
llm -m llamafile "Write a long story" --stream
```

### System Prompts

```bash
llm -m llamafile -s "You are a helpful coding assistant" "Explain Python decorators"
```

### Conversations

```bash
# Start a conversation
llm chat -m llamafile

# Continue an existing conversation
llm chat -m llamafile --continue
```

## Troubleshooting

### Server won't start

Check if the model file exists and is a valid llamafile:
```bash
llm llamafile status
file $LLM_LLAMAFILE_MODEL
```

### Binary download fails

Manually download and specify binary location:
```bash
llm llamafile download --force
```

### GPU not detected

Check GPU layers setting:
```bash
llm -m llamafile --option n_gpu_layers -1 "test"  # -1 = all layers to GPU
```

### Port already in use

Use a different port:
```bash
llm -m llamafile --option port 8081 "Your prompt"
```

## Development

To set up this plugin locally, first checkout the code. Then create a new virtual environment:
```bash
cd llm-llamafile
python3 -m venv venv
source venv/bin/activate
```

Install the dependencies and test dependencies:
```bash
pip install -e '.[test]'
```

To run the tests:
```bash
pytest
```

## Credits

- Built on [llamafile](https://github.com/Mozilla-Ocho/llamafile) by Mozilla
- Plugin for [LLM](https://llm.datasette.io/) by Simon Willison

## License

Apache 2.0
