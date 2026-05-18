#!/bin/bash
set -euo pipefail

echo "Adicionando .gitignore e removendo arquivos compilados do índice..."

# Ensure we're on the feature branch
BRANCH="feature/discovery-election-2026-05-18"
CURRENT=$(git rev-parse --abbrev-ref HEAD)
echo "Current branch: $CURRENT"
if [ "$CURRENT" != "$BRANCH" ]; then
  echo "Checking out $BRANCH"
  git checkout $BRANCH
fi

# Add .gitignore
git add .gitignore || true

# Find tracked compiled/cache files
TO_REMOVE=$(git ls-files -z | tr '\0' '\n' | grep -E '(^|/)(__pycache__|.*\.pyc$|\.pytest_cache/|\.py[cod]$)' || true)
if [ -n "$TO_REMOVE" ]; then
  echo "Tracked compiled/cache files found. Removing from index:"
  echo "$TO_REMOVE"
  echo "$TO_REMOVE" | while IFS= read -r f; do
    git rm --cached --ignore-unmatch "$f" || true
  done
  git commit -m "chore: remove compiled files and add .gitignore" || true
else
  echo "No tracked compiled/cache files found. Committing .gitignore if new."
  if git status --porcelain | grep -q "^A  \.gitignore"; then
    git commit -m "chore: add .gitignore" || true
  else
    echo "Nothing to commit."
  fi
fi

# Push changes
echo "Pushing branch to origin..."
git push origin HEAD || true

# Show status and recent commits
 echo "\nGit status porcelain:"; git status --porcelain || true
 echo "\nRecent commits:"; git --no-pager log --oneline -n 6 || true
 echo "\nFiles still tracked matching patterns:"; git ls-files | grep -E '(__pycache__|\.pyc$|\.pytest_cache)' || true
