#!/bin/sh
# Runs pytest with the given arguments, recording the run for greendots in the susa project's
# /var/opt/greendots2/susa/<commit>-<n>, where n is one more than the commit's last run's.
set -e
root="$(cd "$(dirname "$0")/.." && pwd)"
project=/var/opt/greendots2/susa
run="$project/$(git -C "$root" rev-parse --short HEAD)"
n=1
for previous in "$run"-*; do
    if [ -e "$previous" ] && [ "${previous##*-}" -ge "$n" ]; then
        n=$((${previous##*-} + 1))
    fi
done
mkdir -p "$project"
mkdir "$run-$n"
exec uv run --project "$root" pytest --greendots "$run-$n" "$@"
