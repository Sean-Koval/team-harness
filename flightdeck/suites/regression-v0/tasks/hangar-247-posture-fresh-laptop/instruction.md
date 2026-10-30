A fresh `hangar up` on a laptop ends with `hangar doctor` failing one check, `intake posture: gateway`: the default
posture is `enforce` and `HANGAR_GATEWAY_URL` is unset. But no front door can send an intake job yet, so nothing is
refused, and the check's fix offers the weaker posture (`HANGAR_INTAKE_POSTURE=warn`) as if it were equal.

Change the check (`posture.doctor_checks`), under `enforce` without a gateway:

- No intake door configured (no GitHub webhook secret, Slack signing secret, Jira, GitHub Projects or inbound
  webhooks): `warn`, and the detail says nothing is refused yet (`nothing is refused yet`).
- A door configured: `fail`, naming the doors whose jobs are refused, e.g. `every job from GitHub is refused`, or
  `GitHub, Slack`, `Jira`, `inbound webhooks`.
- Either way give one fix, chosen by where hangar runs, from a new `posture.gateway_fix(settings, fleet)`: on
  Docker `hangar config set HANGAR_GATEWAY_URL http://host.docker.internal:8788`, followed on Linux by
  ` && hangar config set HANGAR_GATEWAY_HOST 172.17.0.1`; on GKE the in-cluster gateway URL. Never offer
  `HANGAR_INTAKE_POSTURE` as the fix.

The posture itself doesn't change: intake jobs are still refused at submit without the gateway. Run
`tests/test_posture.py`.
