#!/bin/bash
# Double-click in Finder to start the GUI on macOS (installs everything on the first start).
cd "$(dirname "$0")" || exit 1

command -v uv >/dev/null 2>&1 || export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
    echo "uv is not installed. Install it with:"
    echo "    curl -LsSf https://astral.sh/uv/install.sh | sh"
    read -r -n1 -p "Press any key to close."
    exit 1
fi

# Keep the environment on the local disk: the repository may live on a network
# drive shared with Windows, where a .venv would be slow and clash between systems.
export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-$HOME/Library/Caches/OddViscosityExperiment/venv}"
unset VIRTUAL_ENV

if ! uv run odd-viscosity-gui; then
    read -r -n1 -p "The GUI exited with an error (see above). Press any key to close."
fi
