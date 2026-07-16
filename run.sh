#!/usr/bin/env bash
# MemoryVault — one-command local runner for macOS / Linux.
#   ./run.sh          → install everything + start the app
#   ./run.sh full     → also install optional API packages (OpenAI, Stripe, …)
#   ./run.sh test     → run the test suite
#   ./run.sh demo     → run the terminal walkthrough
set -e

cd "$(dirname "$0")"
MODE="${1:-run}"

# 1. Python check
if ! command -v python3 >/dev/null 2>&1; then
  echo "❌ Python 3 not found. Install it:  brew install python"
  exit 1
fi
echo "✅ $(python3 --version)"

# 2. Virtual environment (private box so your Mac's Python stays clean)
if [ ! -d venv ]; then
  echo "📦 Creating virtual environment…"
  python3 -m venv venv
fi
# shellcheck disable=SC1091
source venv/bin/activate

# 3. Install dependencies
echo "📥 Installing core dependencies…"
pip install -q --upgrade pip
pip install -q -r requirements.txt

if [ "$MODE" = "full" ]; then
  echo "📥 Installing optional API packages (OpenAI, Stripe, AWS, WorkOS)…"
  pip install -q openai stripe boto3 workos "psycopg[binary]" || \
    echo "⚠️  some optional packages failed — that's OK, they're only needed if you paste those keys"
fi

# 4. .env — the single place you paste keys
if [ ! -f .env ]; then
  cp .env.example .env
  echo "📝 Created .env  — open it and paste any API keys you have (optional)."
fi

# 5. Branch off by mode
case "$MODE" in
  test)
    echo "🧪 Running tests…"
    python -m pytest tests/ -q
    ;;
  demo)
    echo "🎬 Running the walkthrough…"
    python demo.py
    ;;
  *)
    echo ""
    echo "🔎 Activation status (what your keys turned on):"
    python setup_check.py || true
    echo ""
    echo "🚀 Starting MemoryVault…"
    echo "   → Dashboard : http://localhost:8000"
    echo "   → React UI  : http://localhost:8000/react   (has the Connect tab)"
    echo "   → API docs  : http://localhost:8000/api/docs"
    echo "   (press Ctrl+C to stop)"
    echo ""
    exec uvicorn memoryvault.api:app --host 0.0.0.0 --port 8000
    ;;
esac
