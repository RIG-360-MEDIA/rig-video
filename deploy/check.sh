#!/usr/bin/env bash
# The gate every change passes (CI on each push/PR, and again before a release is installed). Runs on trijya-7, where
# the real interpreters live. Fails on: a secret in the tree, Python that does not compile, a failing self-test,
# a shell script with a syntax error, or a site that does not type-check/build. Builds web/dist for deploy.sh.
set -euo pipefail
SRC=$(cd "$(dirname "$0")/.." && pwd); cd "$SRC"
API_PY=${API_PY:-$HOME/anchor-studio/rigvideo-api-venv/bin/python}     # runs the API (app.py)
TOOLS_PY=${TOOLS_PY:-$HOME/.cache/anchor-tools/bin/python}             # runs the worker steps (worker.py)
NODE_BIN=${NODE_BIN:-$HOME/.nvm/versions/node/v22.23.5/bin}
fail=0; step() { echo; echo "== $*"; }

step "secrets"
if git ls-files -z -- . ':!deploy/check.sh' | xargs -0 grep -nIE \
   'gsk_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{30,}|ghp_[A-Za-z0-9]{30,}|github_pat_|xox[bp]-|-----BEGIN [A-Z ]*PRIVATE KEY|postgres(ql)?://[^ "'"'"'$]+:[^ "'"'"'@$]+@|AKIA[0-9A-Z]{16}|hf_[A-Za-z0-9]{30,}|ya29\.' ; then
  echo "secret-looking text above: keys live in ~/.config on the machines, never in git"; fail=1
else echo "none"; fi

step "python compiles"
git ls-files '*.py' | xargs "$TOOLS_PY" -m py_compile && echo ok || fail=1

step "shell syntax"
for f in $(git ls-files '*.sh'); do bash -n "$f" || { echo "bad: $f"; fail=1; }; done; echo ok

step "server self-tests"
export RIGVIDEO_APP=$SRC/studio-app
( cd server
  for t in test_*.py; do printf '%s: ' "$t"; "$API_PY" "$t" 2>&1 | tail -1 | tee /tmp/rv-check-$$; grep -qE '\bok\b' /tmp/rv-check-$$ || fail=1; done
  printf 'store selftest: '; "$API_PY" store.py 2>&1 | tail -1 | tee /tmp/rv-check-$$; grep -qE '\bok\b' /tmp/rv-check-$$ || fail=1
  printf 'worker selftest: '; "$TOOLS_PY" worker.py selftest 2>&1 | tail -1 | tee /tmp/rv-check-$$; grep -qE '\bok\b' /tmp/rv-check-$$ || fail=1
  rm -f /tmp/rv-check-$$; exit $fail ) || fail=1

step "site type-check + build"
( cd web && export PATH=$NODE_BIN:$PATH && npm ci --no-audit --no-fund --loglevel=error && npm run build 2>&1 | tail -4 ) || fail=1

echo; [ $fail = 0 ] && echo "CHECK PASSED" || echo "CHECK FAILED"
exit $fail
