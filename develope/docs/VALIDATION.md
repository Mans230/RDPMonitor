# Validation, rollout and rollback

## Automated checks

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
