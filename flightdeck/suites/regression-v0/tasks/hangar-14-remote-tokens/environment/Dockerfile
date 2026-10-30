# The local runner's environment (flightdeck docs/local.md): hangar at the task's base, with its locked
# dependencies installed and the project itself left out, so the tests import the agent's tree (test.sh puts src/
# first). hangar trials use the variant's environment instead; it needs the same dependencies (README.md).
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.11.32
RUN git clone https://github.com/Sean-Koval/hangar.git /workspace && git -C /workspace checkout -q --detach 3be08f686f47ed2f9b54276b79f092f5b82fc314 \
    && cd /workspace && uv export --frozen --no-hashes --no-emit-project --all-groups > /tmp/requirements.txt \
    && uv pip install --system -r /tmp/requirements.txt pytest
WORKDIR /workspace
