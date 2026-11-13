# The agent environment (environments/agent.yaml) on this computer, run by hangar: `hangar env local` (KAN-472;
# hangar's docs/environments/local-run.md). This repository holds only the definition and its variable contract.
# Runs with the hangar commit CI pins (.github/workflows/check.yml; tests/test_agent_env.py keeps them equal).
HANGAR_REF := c7a2de229aecbad9b82d9cddd6112776dc6c9c5a
WITH_HANGAR := uv run --no-project --python 3.12 --with "hangar @ git+https://github.com/Sean-Koval/hangar@$(HANGAR_REF)"
LOCAL := $(WITH_HANGAR) hangar env local
SPEC := agent --env-dir environments/roles --env-dir environments --harnesses harnesses
INPUTS := --contract environments/agent.env.example --clone code=CODE_REPO --clone knowledge=KNOWLEDGE_REPO
# What two instances must print the same: the tools, then `ai-dlc doctor` on the cloned inputs (hangar prints the
# model, the pins in the spec's env and each clone's commit before it).
REPORT := --report-cmd 'ai-dlc --version; claude --version; python --version; uv --version; gh --version | head -1; \
	root=/workspace/code; [ -f $$root/ai-dlc.toml ] || root=/workspace; \
	ai-dlc doctor --root $$root --machine $$HOME/.agent-env/machine.toml'

.PHONY: agent-env agent-env-check agent-env-down agent-env-policy agent-env-pins

agent-env-pins:       ## the spec's pins agree with what they name (also part of scripts/check_registry.py)
	$(WITH_HANGAR) python scripts/check_registry.py . --agent-pins

agent-env: agent-env-pins  ## build and start it, clone TICKET_KEY's inputs, print the pins and `ai-dlc doctor`
	$(LOCAL) up $(SPEC) $(INPUTS) $(REPORT) $(ARGS)

agent-env-check: agent-env-pins  ## two fresh instances report the same; nothing mounted; egress and DNS refused off-list
	$(LOCAL) check $(SPEC) $(INPUTS) $(REPORT) $(ARGS)

agent-env-down:
	$(LOCAL) down

agent-env-policy:     ## the egress allowlist hangar resolves for it
	$(LOCAL) policy $(SPEC)
