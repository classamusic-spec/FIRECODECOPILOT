#!/usr/bin/env bash
# Fail loudly if any copyrighted / sensitive file is tracked by git.
# Run after building and after every ingest:  bash scripts/check_containment.sh
#
# This guards Rule #1 (copyright containment): code books, extracted text,
# embeddings, the vector store, feedback DB, and secrets must NEVER be tracked.
set -euo pipefail

echo "Checking that no copyrighted or sensitive files are tracked by git..."

# Intentional, safe placeholders that ARE allowed to be tracked. These keep the
# (otherwise-gitignored) code_books/ and data/ directories present in the repo.
ALLOWLIST_REGEX='(^|/)(_PUT_PDFS_HERE\.txt|_GENERATED_AT_RUNTIME\.txt|\.env\.example)$|\.example$'

# Dangerous patterns, matched against tracked file paths (extended regex).
#   - anything under code_books/, data/, or extracted_text/
#   - real PDFs/ebooks, the vector store, the feedback DB, and secrets
PATTERNS=(
  '(^|/)code_books/'
  '(^|/)data/'
  '(^|/)extracted_text/'
  '\.(pdf|epub|mobi)$'
  '\.(sqlite|sqlite3|db)$'
  '(^|/)\.env($|\.)'
  '(^|/)config/code_cycles\.yaml$'
)

# All tracked files, minus the explicit allowlist.
tracked=$(git ls-files | grep -Ev "$ALLOWLIST_REGEX" || true)
violations=0

for p in "${PATTERNS[@]}"; do
  hits=$(echo "$tracked" | grep -Ei -- "$p" || true)
  if [ -n "$hits" ]; then
    echo "  ❌ VIOLATION: tracked file(s) match '$p':"
    echo "$hits" | sed 's/^/      /'
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
