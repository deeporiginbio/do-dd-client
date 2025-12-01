#!/bin/sh

# Detect shell type
if [ -n "$ZSH_VERSION" ]; then
    SHELL_TYPE="zsh"
elif [ -n "$BASH_VERSION" ]; then
    SHELL_TYPE="bash"
elif [ -n "$FISH_VERSION" ]; then
    SHELL_TYPE="fish"
else
    SHELL_TYPE="sh"
fi

# Pretty print function
print_step() {
    printf "\033[1;34m🧬==>\033[0m %s\n" "$1"
}

# Check if uv is installed
if ! command -v uv >/dev/null 2>&1; then
    print_step "Installing uv..."
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- https://astral.sh/uv/install.sh | sh
    else
        echo "Error: Neither curl nor wget is installed. Please install one of them first."
        exit 1
    fi
else
    print_step "uv is already installed, skipping installation"
fi

# Source uv environment based on shell type
if [ -f "$HOME/.local/bin/env" ] && [ "$SHELL_TYPE" != "fish" ]; then
    print_step "Sourcing uv environment for $SHELL_TYPE"
    . "$HOME/.local/bin/env"
elif [ -f "$HOME/.local/bin/env.fish" ] && [ "$SHELL_TYPE" = "fish" ]; then
    print_step "Sourcing uv environment for fish"
    source "$HOME/.local/bin/env.fish"
fi

print_step "Initializing uv..."
uv init

print_step "Installing Python 3.13..."
uv python install 3.13

print_step "Installing deeporigin with core and tools extras..."
uv add --upgrade deeporigin --extra core --extra tools

print_step "Installation complete!"

