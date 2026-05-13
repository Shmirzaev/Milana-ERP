#!/bin/sh
set -eu

# Always run the production server on Render. This avoids failures caused by
# stale/custom Docker command overrides in service settings.
exec npm run start -- -p "${PORT:-3000}"
