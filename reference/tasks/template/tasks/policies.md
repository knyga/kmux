# Standing pre-approvals — what an agent does instead of parking

The owner's written standing answers, in one place, so an agent does not park a task on a question the
owner has already answered. **Every entry cites where the owner wrote it** (a task file, a message, a
date). A rule with no owner text behind it does not belong here: an agent's reading of the history is
not an approval. Agents may propose entries (as a `creator: user` `idea` task), never add them.

Until the owner writes entries, only the defaults below apply.

## (a) Spend inside a standing allowance — proceed, do not park

- **Source:** _none yet._ With no source, every paid call (LLM API, cloud resource) that is not the
  project's normal test suite parks with its measured price.

## (b) A product choice with a reversible default — ship the default, file a review row

- **Source:** _none yet._ Proposed default for the owner to adopt or strike:
  *reversible defaults ship; only irreversible, paid, or secret-bearing asks park.*
- **Reversible default** means the status quo, a flag that ships **off**, a setting whose default
  reproduces today's behaviour, or a copy change — undone by one switch or one revert, no stored data
  rewritten.
- **What to do (once adopted):** pick the reversible default, record it in `## Decisions` as
  `policy (tasks/policies.md § b): …`, finish the task, and file
  `tools/tasks index --create review-<slug> --type idea --priority p3 --creator user` restating the
  options, the default that shipped and how to switch.

## (c) What always parks

- **Secrets and accounts:** minting, rotating, reading or supplying a credential, key, token or
  password; logging an account in; connecting an app.
- **Spend** above any written allowance (park with the measured price).
- **Destructive data operations:** deleting, rewriting or backfilling data the owner keeps; anything
  with no undo.
- **Infrastructure the agent cannot reach:** dashboards, production config, deploys, DNS, billing.
- **Pushing or publishing** anything, unless the owner said so for this task or in an entry above.
