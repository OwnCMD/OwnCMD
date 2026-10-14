# Reviewed 2026-09-25: LTS OS/Node/Java and supported stable release lines.
# --pull in install.sh refreshes patch releases without crossing these major lines.
FROM node:24-trixie-slim AS node
FROM mongo:8.0-noble AS mongo
FROM golang:1.27-trixie AS go
FROM rust:1.98-trixie AS rust
FROM ubuntu:26.04
ARG DEBIAN_FRONTEND=noninteractive
# Rebuild apt layers on each installer run, even if upstream base tags are unchanged.
ARG ASTER_RUNTIME_REFRESH=manual
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PLAYWRIGHT_BROWSERS_PATH=/opt/browsers RUSTUP_HOME=/usr/local/rustup PATH=/work/.local/bin:/opt/python/bin:/usr/local/go/bin:/usr/local/cargo/bin:/usr/lib/postgresql/18/bin:$PATH
COPY --from=go /usr/local/go /usr/local/go
COPY --from=rust /usr/local/cargo /usr/local/cargo
COPY --from=rust /usr/local/rustup /usr/local/rustup
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=mongo /usr/bin/mongod /usr/local/bin/mongod
COPY --from=mongo /usr/bin/mongodump /usr/local/bin/mongodump
COPY --from=mongo /usr/bin/mongorestore /usr/local/bin/mongorestore
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
RUN echo "Runtime refresh: $ASTER_RUNTIME_REFRESH" \
 && apt-get update && apt-get upgrade -y \
 && apt-get install -y --no-install-recommends \
 bash util-linux build-essential clang cmake ninja-build pkg-config gdb git curl wget ca-certificates \
 ripgrep jq unzip zip tar gzip bzip2 xz-utils zstd 7zip libarchive-tools file patch openssh-client procps \
 python3.14 python3.14-venv python3.14-dev openjdk-25-jdk-headless ruby ruby-dev php-cli php-sqlite3 composer \
 sqlite3 libsqlite3-dev postgresql-18 postgresql-client-18 redis-server redis-tools \
 libssl-dev libcurl4t64 libgssapi-krb5-2 libldap2 libsasl2-2 libsnappy1v5 \
 fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
# Keep system Python managed by apt; allow non-root pip --user in the writable HOME.
RUN python3.14 -m venv --system-site-packages /opt/python
COPY requirements.txt /opt/requirements.txt
RUN pip install --no-cache-dir -r /opt/requirements.txt && pip check
RUN playwright install --with-deps chromium && chmod -R a+rX /opt/browsers \
 && rm -rf /var/lib/apt/lists/*
RUN npm install -g typescript tsx pnpm eslint prettier
COPY templates /opt/templates
RUN cd /opt/templates/mern && npm ci --no-audit --no-fund && npm run build
# Ubuntu base images can reserve UID 1000 for an unused default account.
RUN if getent passwd ubuntu >/dev/null; then userdel -r ubuntu; fi \
 && useradd -u 1000 -m agent && mkdir /work && chown 1000:1000 /work \
 && python --version && node --version && gcc --version \
 && java -version && initdb --version && mongod --version && mongodump --version
COPY server.py /opt/server.py
COPY verify_runtime.py verify_toolchains.py verify_browser.py /opt/
USER 1000:1000
WORKDIR /work
EXPOSE 8001
CMD ["python","-m","uvicorn","server:app","--app-dir","/opt","--host","0.0.0.0","--port","8001","--no-access-log"]
