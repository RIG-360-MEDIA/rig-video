#!/usr/bin/env bash
# What CI runs (GitHub's runners, .github/workflows/tests.yml). Also runs on a laptop.
#   tests/ci.sh static    secrets in the tree, Python compiles, shell syntax, site type-check + build
#   tests/ci.sh python    the pytest suite (parallel); RIGVIDEO_TEST_PG = a throwaway Postgres for the migration tests
#   tests/ci.sh browser   build the site, then the Playwright journeys against the real API (tests/e2e)
# PYTHON / NPM can be overridden. Needs: python with tests/requirements.txt, node 22.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PYTHON:-python}

case "${1:-}" in
static)
  fail=0
  echo "== secrets"
  if git ls-files -z -- . ':!deploy/check.sh' ':!tests/ci.sh' | xargs -0 grep -nIE \
     'gsk_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{30,}|ghp_[A-Za-z0-9]{30,}|github_pat_|xox[bp]-|-----BEGIN [A-Z ]*PRIVATE KEY|postgres(ql)?://[^ "'"'"'$]+:[^ "'"'"'@$]+@|AKIA[0-9A-Z]{16}|hf_[A-Za-z0-9]{30,}|ya29\.'; then
    echo "secret-looking text above: keys live in ~/.config on the machines, never in git"; fail=1
  else echo "none"; fi
  echo "== python compiles"
  git ls-files '*.py' | xargs "$PY" -m py_compile && echo ok || fail=1
  echo "== shell syntax"
  for f in $(git ls-files '*.sh'); do bash -n "$f" || { echo "bad: $f"; fail=1; }; done; echo ok
  echo "== site type-check + build"
  (cd web && npm ci --no-audit --no-fund --loglevel=error && npm run build 2>&1 | tail -3) || fail=1
  exit $fail ;;
python)
  "$PY" -m pytest -n auto -q ;;
browser)
  (cd web && npm ci --no-audit --no-fund --loglevel=error && npm run build >/dev/null)
  rm -rf dist && cp -r web/dist dist                      # the API serves the site from dist/, as on trijya-7
  cd tests/e2e && npm ci --no-audit --no-fund --loglevel=error && npx playwright install --with-deps chromium >/dev/null
  PYTHON="$PY" npx playwright test ;;
*)
  echo "usage: tests/ci.sh static|python|browser" >&2; exit 2 ;;
esac
