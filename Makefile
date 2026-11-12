# The agent environment (environments/agent.yaml) on this computer: see scripts/agent_env.py.
# Runs with the hangar commit CI pins (.github/workflows/check.yml; tests/test_agent_env.py keeps them equal).
HANGAR_REF := 0f1367a7c3b62edbb1c49210e458d8f98eac17c1
AGENT_ENV := uv run --no-project --python 3.12 --with "hangar @ git+https://github.com/Sean-Koval/hangar@$(HANGAR_REF)" \
	--with pyyaml python scripts/agent_env.py

.PHONY: agent-env agent-env-check agent-env-down agent-env-policy

agent-env:            ## build and start it, clone TICKET_KEY's inputs, print the pins and `ai-dlc doctor`
	$(AGENT_ENV) up $(ARGS)

agent-env-check:      ## two fresh instances report the same, nothing is mounted, off-list hosts are refused
	$(AGENT_ENV) check $(ARGS)

agent-env-down:
	$(AGENT_ENV) down

agent-env-policy:     ## the egress allowlist hangar resolves for it
	$(AGENT_ENV) policy
