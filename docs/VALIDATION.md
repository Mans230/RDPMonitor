# Validation, rollout and rollback

## Automated checks

The 2026-10-27 RDP connectivity follow-up passed 188 Python tests and the existing
9 JavaScript tests, with all 31 locked runtime versions matching. New tests use
synthetic effective-policy snapshots for Shadow, disabled enum states, broad and
loopback-exempt blocks, GPO origin, scoped blocks, custom ports, malformed inventory
and firewall-activation hazards. The collector is parsed by Windows PowerShell
without executing native queries. No live rule toggling or external probing was
performed; see [RDP connectivity validation limits](RDP-CONNECTIVITY.md).

From the changed checkout:

```powershell
python -B -m unittest discover -s tests -v
node --test tests/test_webconsole_user_flow.js
python -B scripts/lock_dependencies.py
```

Python tests mock external requests and native account/firewall/process mutations,
using temporary files. HTTP tests bind loopback on an ephemeral port with fake
credentials. JavaScript tests parse all inline scripts and execute real control
helpers with simulated prompts/fetch, not a full real-browser test. Node is test
tooling, not an application runtime requirement.

Regressions cover cross-channel last-admin safety, failed inventory, account gates,
password policy, nonce replay/expiry/session/payload binding, generic confirmations,
callback/text budgets, queue capacity, diagnostic deadline/admission/recovery,
native timeout clamping, ACL failures, credential redaction, usage rotation and
concurrent writes, and named-operator attribution/revocation.

`requirements.lock.txt` pins 31 installed runtime dependencies captured on CPython
3.14.8 / Windows AMD64. No host packages were installed/updated. This is not a fresh
solver result, wheel-hash lock, latest-version claim, or compatibility validation
for every older Python version. In a matching isolated environment install with
`python -m pip install -r requirements.lock.txt`. Other environments should resolve
`requirements.txt`, run checks and generate their own snapshot with
`python -B scripts/lock_dependencies.py --write`.

## Disposable Windows VM verification

### Bot/RDP follow-up, 2026-10-24

Local final checks: 170 Python tests and 9 JavaScript tests passed; all 31 locked
runtime versions matched. Generated PowerShell Security queries passed the actual
Windows PowerShell parser without executing the queries. `git diff --check` passed.
The [review](BOT-SECURITY-REVIEW.md) distinguishes command-card coverage from live
handler execution and describes the remaining event/firewall limits.

The existing control design was preserved (no direction draw or palette change).
Chromium button fixtures using the actual CSS passed at 1440/768/390px with zero
failures before/after; two unused-space warnings reflect the isolated component
fixture. Final screenshots were inspected at all widths: busy labels remain
readable for default/primary/danger buttons, busy borders are visible, and phone
targets are 44px tall. Local `.taste-skill/` artifacts are excluded from Git.
The full login page still has pre-existing gradient/shadow findings; this is not
a whole-dashboard visual certification. No photos or generated assets were added.

Control critique: the idea is to make request progress visible on the control
that initiated it. The live behavior is press, disabled busy state and restoration.
Final component scores: design 7, usability 8, creativity 6, content 8 (7.2 overall).
The initial weak busy contrast, variant border overrides and 38px phone targets
were corrected; whole-page composition is outside this scoped score.

On the real HTML in the collaborative browser, mocked fetch and two clicks on
Capture screen produced one preparation plus one screenshot action, with
`aria-busy=true` while waiting and the original button restored after completion.
No screenshot or Telegram message was actually captured/sent. Snapshot automation
timed out twice; screenshot inspection used the skill's Chromium fallback.

A copied folder/worktree isolates source, not Windows side effects. Do not install
two copies against the production machine, bot or scheduled tasks. Use a disposable
VM with separate credentials and confirm independent provider-console recovery.

1. Check interactive/SYSTEM task startup, DPAPI access and supervisor recovery.
2. Test real localized admin inventory, last-admin refusal and competing panel/bot
   account mutations. Include inventory failures and disabled account management.
3. Exercise all action families, expired/replayed/mismatched nonces, cancelled UI
   dialogs, queue overload, and owner/operator revocation.
4. Exercise slow diagnostics/native timeouts and check later controls still work.
5. Inspect effective ACLs and simulate failures only on disposable files. Run a
   backup and isolated restore drill with actual rclone/restic configuration.
6. Inspect usage actors, redaction, rotation and admission-vs-completion semantics.

## Complete-revision deployment and rollback

Use a reviewed PR revision. Save the previous complete application revision,
configuration, task definitions and protected credentials. In the approved
maintenance window stop old processes, replace the entire code bundle (including
new helper modules and matching HTML), and start exactly one suite. Copying only
the changed monitor file into an old installation is unsupported.

If checks fail, stop the new revision, restore the previous complete code and
saved configuration/tasks, then verify status, Telegram, local login and backup
operation from the provider console. Code rollback cannot undo account deletion,
file restoration, firewall changes or other actions already performed.

For this session only, `.baseline/` and `.checkpoints/batch2/` are local snapshots
under `develope`; run `python -B scripts/verify_isolation.py` there to compare
original hashes. These snapshots/check outputs are excluded from the PR and absent
from a fresh clone. They are not deployment backups or a substitute for VM testing.
