# The local runner's environment (flightdeck docs/local.md): flightdeck at the task's base, with its locked
# dependencies installed and the project itself left out, so the tests import the agent's tree (test.sh puts src/
# first). hangar trials use the variant's environment instead; it needs the same dependencies (README.md).
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.11.32
RUN git clone https://github.com/Sean-Koval/flightdeck.git /workspace && git -C /workspace checkout -q --detach 6a79ebc1f3689b8185e14c29b4b24eba5d4f038d \
    && cd /workspace && uv export --frozen --no-hashes --no-emit-project --all-groups > /tmp/requirements.txt \
    && uv pip install --system -r /tmp/requirements.txt pytest
WORKDIR /workspace
