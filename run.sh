#!/bin/bash

# run.sh - Setup script for Open Octopus
#
# This script:
# 1. Sets up the Python virtual environment (venv)
# 2. Installs dependencies
# 3. Creates shortcuts for 'octopus-ask' and 'octopus-tui' in this directory
#
# Usage:
#   ./run.sh

set -e

# 1. Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: python3 could not be found."
    exit 1
fi

# 2. Setup venv
if [ ! -f "venv/bin/python" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
    
    # Initial install
    source venv/bin/activate
    echo "🔽 Installing dependencies..."
    pip install --upgrade pip
    pip install -e ".[agent]"
    pip freeze > requirements.txt
else
    source venv/bin/activate
fi

# 3. Ensure dependencies are installed (check for octopus executable)
if [ ! -f "venv/bin/octopus" ]; then
    echo "� Updating dependencies..."
    pip install -e ".[agent]"
    pip freeze > requirements.txt
fi

# 4. Create Wrappers
echo "🔗 Creating command shortcuts..."

# Wrapper: octopus-ask
cat > octopus-ask << 'EOF'
#!/bin/bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$DIR/config.txt" ]; then
    set -a
    source "$DIR/config.txt"
    set +a
fi
exec "$DIR/venv/bin/octopus-ask" "$@"
EOF
chmod +x octopus-ask

# Wrapper: octopus-tui (maps to 'octopus' command)
cat > octopus-tui << 'EOF'
#!/bin/bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$DIR/config.txt" ]; then
    set -a
    source "$DIR/config.txt"
    set +a
fi
exec "$DIR/venv/bin/octopus" "$@"
EOF
chmod +x octopus-tui

# Wrapper: octopus (standard name)
cat > octopus << 'EOF'
#!/bin/bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$DIR/config.txt" ]; then
    set -a
    source "$DIR/config.txt"
    set +a
fi
exec "$DIR/venv/bin/octopus" "$@"
EOF
chmod +x octopus

echo "✅ Setup complete!"
echo ""
echo "You can now run:"
echo "  ./octopus-ask \"How much usage?\""
echo "  ./octopus-tui"
echo ""
echo "Or add this directory to your PATH to run them from anywhere."
