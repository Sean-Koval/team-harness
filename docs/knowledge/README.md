# The knowledge system: teammate guide

The knowledge system turns what the team decides in meetings, chat and notes into records in a git repository. An
agent proposes the records as a pull request; a person reviews and merges them. These pages are for a teammate who
has never used it.

| Page | Answers |
| --- | --- |
| [quickstart.md](quickstart.md) | How do I get to my first merged record in 15 minutes? |
| [capture.md](capture.md) | What gets captured, and how do I say a decision so it is captured well? |
| [review.md](review.md) | How do I review a records PR in under 5 minutes? |
| [find.md](find.md) | How do I find out why we decided something? |

Every page gives macOS and Windows commands. CI on Windows parses every PowerShell block in these pages and runs the
sample copy from quickstart step 3 (`tests/test_guide_powershell.py`). Nobody has followed the guide end to end on
Windows yet (KAN-451), so each Windows block is still marked **untested on Windows**.

## Fill in before you share these pages

Words in double braces are specific to your company. Replace them in your team's copy; never in this repository.

| Placeholder | What it is |
| --- | --- |
| `{{harness_repo}}` | Clone URL of your team's copy of this team-harness repository |
| `{{knowledge_repo}}` | `owner/repo` of the team knowledge repository on GitHub |
| `{{ai_dlc_install}}` | Your company's approved way to install ai-dlc |
| `{{convention_owner}}` | Who answers capture questions and approves team conventions |
| `{{wiki_space}}` | The wiki space the records are rendered into |
| `{{customer_repo}}` | How a customer's own knowledge repository is named |

## Add a team work skill

A team skill reaches teammates in one command and one PR. Run it from a checkout of this repository, on a branch
named for your ticket. Keep company and customer names in a deny-list file on your own machine, one per line.

```sh
TEAM_HARNESS_DENY=~/.team-harness-deny python3 scripts/add_skill.py ~/skills/deploy-notes --harness work-default --key KAN-123
```

```powershell
$env:TEAM_HARNESS_DENY = "$HOME\.team-harness-deny"
py -3 scripts\add_skill.py "$HOME\skills\deploy-notes" --harness work-default --key KAN-123
```

The script refuses a skill without a `name` and `description`. It also refuses a vendor tool name, a secret, a
person, a site or a deny-list word: use a `{{placeholder}}` instead. It copies the skill to `shared/work-system/skills/` and
writes a changelog fragment. Commit only those two.

After merge the skill ships in the next `candidate` revision. `stable` moves only by `scripts/promote.py`, with a
flightdeck verdict and a second approver.

## What is not on main yet

Some steps rely on work that is still open. Each such step says so where it appears.

| Work | What changes for you when it lands |
| --- | --- |
| KAN-433, one install | One command installs ai-dlc, the harness and the knowledge clone, and `ai-dlc doctor` checks them. Until then, quickstart steps 1 to 3 do it by hand |
| ai-dlc #172 | Supports installing ai-dlc natively on Windows. Until then, ai-dlc on Windows is unsupported, and every Windows step that runs `ai-dlc` may fail |
| KAN-450 | Written sign-off on what may be stored, and on how a meeting opts out |
| KAN-475 | Creates a separate knowledge repository for a customer |
