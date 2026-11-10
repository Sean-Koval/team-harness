-- Prototype: one row per session, the SDLC read of it (ticket -> PR -> CI -> review -> merge).
with s as (
  select split_part(run_id, '/turn/', 1) as session, *,
    regexp_extract(coalesce(tool_input,''), '\b(KAN|[A-Z][A-Z0-9]+)-\d+\b', 0) as key
  from step_labels
),
r as (select split_part(run_id, '/turn/', 1) as session, count(*) as turns, sum(cost_usd) as usd,
        sum(epoch(finished_at) - epoch(started_at)) as wall_s from runs group by 1)
select r.session, r.turns as prompts, round(r.usd, 2) as usd, round(r.wall_s / 60) as mins,
  mode(nullif(s.key, '')) as ticket,
  count(*) filter (where tool_name like '%create_pull_request' or list_contains(shell_ops, 'pr.open')) as prs_opened,
  count(*) filter (where tool_name like '%merge_pull_request' or tool_input like 'gh pr merge%') as merges,
  count(*) filter (where tool_input like '%actions/runs%' or tool_input like 'gh pr checks%' or tool_input like 'sleep %') as ci_waits,
  count(*) filter (where tool_name like '%pull_request_read' or tool_name like '%review%') as review_reads,
  count(*) filter (where tool_name like '%Jira%' or tool_name like '%jira%') as jira_calls,
  count(*) filter (where 'edit' = any(labels)) as edits,
  count(*) filter (where 'test' = any(labels)) as test_runs,
  count(*) filter (where tool_ok = false) as tool_errors
from r join s using (session) group by all order by usd desc;
