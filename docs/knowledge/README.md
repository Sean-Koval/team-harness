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

Every page gives macOS and Windows commands. The Windows commands have not been run on Windows yet: each one is
marked **untested on Windows**.

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

## What is not on main yet

Some steps rely on work that is still open. Each such step says so where it appears.

| Work | What changes for you when it lands |
| --- | --- |
| KAN-433, one install | One command installs ai-dlc, the harness and the knowledge clone, and `ai-dlc doctor` checks them. Until then, quickstart steps 1 to 3 do it by hand |
| team-harness #32 (KAN-431) | Adds the `knowledge-context`, `query-knowledge` and `whats-next` skills. Until then, use the `ai-dlc knowledge records` commands directly |
| ai-dlc #266 (KAN-466) | Adds `ai-dlc knowledge why`, and makes each record's evidence carry its quote, speaker and time |
| ai-dlc #172 | Supports installing ai-dlc natively on Windows. Until then, ai-dlc on Windows is unsupported, and every Windows step that runs `ai-dlc` may fail |
| KAN-457, KAN-458 | Meeting transcripts arrive in the inbox by themselves, and a nightly batch opens the records PRs |
| KAN-450 | Written sign-off on what may be stored, and on how a meeting opts out |
| KAN-475 | Creates a separate knowledge repository for a customer |
