# File DEC-0042: Raw inbox sources expire after 30 days

For each draft, in this order:
- [ ] retention-job: search the tracker for "Plan item: DEC-0042#retention-job". If a ticket has it, write its
      key into filed_as and skip. Otherwise create it from retention-job.md (summary, description, the three
      labels, parent), link it implements DEC-0042, and write its key into filed_as.
- [ ] retention-check: search the tracker for "Plan item: DEC-0042#retention-check". If a ticket has it, write its
      key into filed_as and skip. Otherwise create it from retention-check.md (summary, description, the three
      labels, parent), link it implements DEC-0042, add its blocked-by links, and write its key into filed_as.
- [ ] retention-check: replace "DEC-0042#retention-job" in Start after and its blocked-by link with the key filed
      for retention-job.
Every ticket stays `proposed`. Only you change an execution label to exec:agent.
Not ready, not drafted:
- retention-notice: Which one repository does this change, and which command proves the reminder appears?
