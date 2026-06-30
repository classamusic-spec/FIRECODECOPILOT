#!/usr/bin/env bash
# Fail loudly if any copyrighted / sensitive file is tracked by git.
# Run after building and after every ingest:  bash scripts/check_containment.sh
set -euo pipefail

echo "Checking that no copyrighted or sensitive files are tracked by git..."

# Patterns that must NEVER be committed.
PATTERNS=("code_books/" "data/" "extracted_text/" ".env" ".pdf" ".epub" ".sqlite" ".db")

tracked=$(git ls-files || true)
violations=0

for p in "${PATTERNS[@]}"; do
  if echo "$tracked" | grep -i -- "$p" >/dev/null 2>&1; then
    echo "  ❌ VIOLATION: something matching '$p' is tracked by git!"
    echo "$tracked" | grep -i -- "$p" | sed 's/^/      /'
    violations=$((violations+1))
  fi
done

if [ "$violations" -eq 0 ]; then
  echo "  ✅ Clean. No code books, data, secrets, or PDFs are tracked."
else
  echo ""
  echo "  Fix: git rm --cached <file>, confirm .gitignore covers it, and re-check."
  exit 1
fi
