---
name: gke-diagnose
description: Use when a ticket involves a service running on GKE (crash loops, pending pods, failed rollouts, resource pressure). Diagnoses cluster state read-only through the `gke` MCP server; never changes the cluster.
---

# Read-only GKE diagnosis

The `gke` MCP server is a Kubernetes MCP server started with `--read-only`, using a kubeconfig whose identity has
only viewer rights (for example `roles/container.viewer`). A PreToolUse hook also blocks mutating `kubectl`, `helm`
and `gcloud container` commands in the shell. Diagnosis only: the fix goes in a pull request to the code or the
manifests, and the deploy pipeline applies it.

## Steps

1. **Locate.** Confirm the cluster context and namespace from the ticket. List the workload's pods and their status,
   restarts and age.
2. **Describe.** For an unhealthy pod: its events, container states (`Waiting` reason, `lastState.terminated` exit
   code and reason) and the node it runs on.
3. **Logs.** The current and the previous container's logs (`previous: true` after a restart), last 200 lines.
   For anything older, use the `splunk-logs` skill.
4. **Rollout.** The deployment's or statefulset's current and previous ReplicaSets, image tags and rollout
   conditions. Compare the image tag with the commit the ticket mentions.
5. **Resources.** Requests and limits against usage (`top` metrics if available), `OOMKilled` reasons, pending pods'
   scheduling events (insufficient CPU or memory, taints, affinity).
6. **Config.** ConfigMap keys the workload mounts (names and non-secret values). Never read Secret values: list
   Secret names only.

## Common readings

| You see | It usually means |
| --- | --- |
| `CrashLoopBackOff`, exit code 1 | the app fails at start: read the previous container's logs |
| `OOMKilled`, exit code 137 | memory limit too low or a leak: compare usage over time |
| `ImagePullBackOff` | wrong tag or registry permissions: check the image reference |
| `Pending` with `FailedScheduling` | requests too large, taints, or the node pool is full |
| Readiness probe failures | slow start or a wrong probe path/port: compare with the app's health endpoint |

## Reporting

Write the diagnosis in the PR or the ticket: what is wrong, the evidence (object names, events, log excerpts without
secrets) and the proposed fix. If the fix is operational (scale, restart, roll back), say so and leave it to a person.
