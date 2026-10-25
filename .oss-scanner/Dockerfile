# Reproducible, offline-auditable build of econte, in the layout Anthropic's
# OSS Scanner expects (https://github.com/anthropics/oss-scanner): everything
# the tests need is fetched here, at build time, and the audit itself runs
# with no network. Build from the repository root:
#
#   docker build -f .oss-scanner/Dockerfile -t econte-audit .
#   docker run --rm --network none econte-audit
#
# The CMD runs both implementations against the golden fixtures and the
# cross-language consistency check, exactly as CI does.
FROM node:22-bookworm-slim AS node

FROM python:3.12-bookworm

# Node 22, as in CI, from the official image (Debian bookworm's own nodejs
# package is 18, which is past end of life). Both images are bookworm, so the
# binary links against the same glibc.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && node --version && npm --version

WORKDIR /src
COPY . /src

RUN python -m pip install --no-cache-dir -e "./python[dev]"
RUN cd packages/econte && npm ci --ignore-scripts && npm run build

CMD ["sh", "-c", "cd python && pytest -q && cd ../packages/econte && npm test && cd ../.. && python scripts/cross_check_goldens.py"]
