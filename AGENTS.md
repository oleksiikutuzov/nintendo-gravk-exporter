# Nintendo → Gravk: contributor and agent instructions

## Goal and scope

Build a public, MIT-licensed Linux/macOS command-line tool that exports the
account owner's Nintendo games and playtime directly into Gravk CSV format.
Keep the working Exophase exporter as a fallback. Use Bash entry points and
Python 3.9+ standard library only; preserve compatibility with both platforms.
This is an unofficial integration using undocumented APIs.

Read this file and inspect the working tree before changing anything. Preserve
existing local changes. Continue routine implementation, fixes, and verification
without repeated confirmation requests. Human Nintendo sign-in and Gravk review
are necessary validation steps; never substitute mocked results for them.

## Repository map

- `nintendo.sh`, `nintendo.py`: direct Nintendo login, logout, online export,
  and offline conversion.
- `export.sh`, `export.py`: public Exophase fallback; `export.py` also defines
  the shared CSV headers and atomic CSV writer used by the direct exporter.
- `tests/test_nintendo.py`, `tests/test_export.py`: synthetic fixtures and mocked
  HTTP tests. Keep all test data synthetic.
- `README.md`: usage, CSV mapping, limitations, and release instructions.
- `NINTENDO-RESEARCH.md`: protocol research, references, and validation gaps.
- `.github/workflows/tests.yml`: Python 3.9 and 3.14 on Linux and macOS.
- `.gitignore`: personal exports, credentials, browser saves, and caches.
- `LICENSE`: MIT; retain the license and copyright notice.

## Privacy and credentials

- Never ask for passwords, callback links, session tokens, access tokens, or
  cookies in chat. Passwords belong only on Nintendo's website; callbacks go
  into the local terminal's hidden prompt.
- Never put credentials in command arguments, shell history, diagnostic output,
  public examples, fixtures, commits, or issue/PR descriptions.
- Keep the owner's account identifiers and actual activity out of public files.
  Do not copy identifiers from conversation history into documentation.
- Session files default to `~/Library/Application Support/nintendo-to-gravk/session.json`
  on macOS and `$XDG_CONFIG_HOME/nintendo-to-gravk/session.json` on Linux
  (default base `~/.config`). Keep them outside the repository, owned by the user,
  with mode `0600`. They are plaintext credentials, not keychain entries.
- Use `private/` for local history/CSV artifacts or an external private directory.
  Git ignores CSV, JSON, HTML, HAR, logs, session/cookie files, and private exports.
  Ignore rules are a guardrail: inspect staged contents before committing.
- Inspect only the response fields needed for diagnosis. Do not dump credentials,
  whole personal histories, or raw server error bodies into chat or logs.
- Do not follow redirects on credential-bearing requests. Preserve TLS checking
  and the explicit Nintendo endpoint allowlist.
- Logout deletes the local session; it does not revoke authorization at Nintendo.

## Commands

Run live sign-in/export in the user's interactive local terminal:

```bash
mkdir -p private
bash nintendo.sh export --save-json private/nintendo-history.json -o private/gravk-nintendo.csv
bash nintendo.sh login
bash nintendo.sh login --no-browser
bash nintendo.sh logout
```

Offline conversion and an explicit, verified source-platform mapping:

```bash
bash nintendo.sh export --input-json private/nintendo-history.json -o private/gravk-offline.csv
bash nintendo.sh export --input-json private/nintendo-history.json --platform-map 'SOURCE_CODE=Nintendo Switch' -o private/gravk-mapped.csv
```

`--session-file PATH` is a global option placed before the subcommand. Existing
CSV files require `--force` to replace; raw JSON backups require a new filename.
Preserve complete-file publication and existing outputs on conversion failure.
Never let an output overwrite a session or its input JSON.

Fallback example (use placeholders, never the owner's actual profile):

```bash
bash export.sh YOUR_EXOPHASE_USERNAME -o private/gravk-exophase.csv
```

## Direct Nintendo protocol

Treat these as researched implementation observations, not a stable contract:

- Client ID: `5c38e31cd085304b`.
- Authorize: `https://accounts.nintendo.com/connect/1.0.0/authorize`.
- Callback: `npf5c38e31cd085304b://auth`.
- Generate fresh random state and a PKCE SHA-256 challenge. Validate callback
  scheme/host, state, and exactly one authorization code before exchanging it.
- Session exchange: form POST to
  `https://accounts.nintendo.com/connect/1.0.0/api/session_token`.
- Access-token exchange: JSON POST to
  `https://accounts.nintendo.com/connect/1.0.0/api/token`, with grant type
  `urn:ietf:params:oauth:grant-type:jwt-bearer-session-token`.
- History: GET
  `https://app-api.znej.nintendo.com/api/v2.0/users/me/play_histories`, using
  bearer access token, `gentry-locale`, and app User-Agent.
- Observed community User-Agent: `com.nintendo.znej/3.0.3 (iOS/26.0.1)`.
- Owner history needs neither Exophase nor the third-party signing service used
  by Nintendo's separate Coral API. Do not conflate those protocols.

History conversion rules:

- Read `playHistories`: `titleId`, `titleName`, `platform` (older `deviceType`),
  `totalPlayedMinutes`, and first/last-played dates.
- `recentPlayHistories` contains daily subsets. Never add them to title totals.
- Require nonnegative integer minutes; reject missing/invalid totals rather
  than inventing zero. Preserve actual zero.
- Recognize Nintendo Switch / Switch and Nintendo Switch 2 / Switch 2,
  case-insensitively, plus `HAC` (Switch) and `BEE` (Switch 2). Unknown source codes must stop conversion; verify their
  meaning before adding built-ins or using repeatable `--platform-map` options.
- Save opt-in raw JSON before conversion so unknown platforms can be reviewed
  without another authenticated request.
- Deduplicate by title ID and source platform. Conflicting totals are errors.
  Keep cross-console entries separate until real data establishes whether their
  totals overlap. Do not infer hardware from game titles or blindly aggregate.

## Gravk CSV contract

Keep this exact current header order, with a header in the first row:

```csv
title,hours,completedAt,platform,status,userScore,platinum,steamDeck,favorite
```

- `title`: required game title; preserve Unicode and use proper CSV quoting.
- `hours`: direct Nintendo minutes / 60, rounded to four decimal places in CSV.
  Exophase unknown time stays blank. Select **hours** in Gravk's field mapping.
  Gravk rounds imports to whole hours; do not pre-round away the CSV precision.
  Half-hour boundaries and the threshold interaction still need live review.
- `completedAt`: blank by default. Gravk accepts completion or last-played dates,
  but the exporter must not imply completion from play activity.
- `platform`: mapped source platform. Gravk matches names automatically;
  verify exact Switch and Switch 2 catalog matches in the preview.
- `status`: `played`, a supported case-insensitive value. Do not infer finished,
  completed, or abandoned status from playtime.
- `userScore`: blank; independent ratings, if supplied, must be 0–100. Gravk
  also accepts `rating` and optional `review`, but do not invent either or add
  columns without a reason to change the current contract.
- `platinum`, `steamDeck`, `favorite`: `false` defaults, not inferred preferences.
  Gravk accepts true/false, 1/0, and yes/no for favorite.

Gravk's supplied rules support Backlog, Finished, Dropped, Endless, Played,
Playing, and Completed case-insensitively. Completion aliases: Done and End;
dropped alias: Abandoned; played aliases: Queue and Waiting (also Endless).
Missing/unrecognized status is inferred from hours, so keep explicit `played`.

All matched games become owned; games played for at least one hour also become
logged. Matching can be incomplete. Review the preview, including fractional-hour
and sub-hour games, status, platform, dates, and booleans, before confirming.

## Verification and honest reporting

Baseline as of 2026-10-20:

- All 17 local tests passed, using synthetic data and mocked requests.
- Shell syntax checks passed. CI is configured; hosted CI has not been verified.
- Prior Exophase live retrieval succeeded. Keep personal results out of public files.
- Direct Nintendo sign-in/token exchange and authenticated history retrieval
  succeeded with a real account locally. Hardware codes `HAC` and `BEE` were
  observed; mapping follows Nintendo model families. Cross-console accounting
  still needs comparison with the Nintendo Store app.
- The generated CSV was checked against the saved response. The user reported
  that the result works for them; import completion was not independently
  observed. Do not infer that every platform match or rounding boundary was checked.

Do not claim end-to-end success or mark either live step complete without actual
evidence. Update documentation when validation changes, without publishing
personal activity. Separate protocol reachability, mocked tests, authenticated
retrieval, CSV conversion, and successful Gravk import in reports.

Run after relevant code changes:

```bash
python3 -m unittest discover -s tests -v
bash -n nintendo.sh export.sh
git diff --check
```

Add meaningful regression coverage for discovered bugs, especially parsing,
deduplication, accounting, secret redaction, and output preservation. Do not use
live account calls in CI. Keep Exophase pagination safeguards and its distinction
between unknown and zero playtime. Do not bypass browser challenges.

## Remaining work and release

### Git workflow

- Make atomic commits: one coherent, reviewable change per commit, with its
  relevant tests. Split independent implementation, CI, and documentation work.
- Keep each commit usable; commit shared dependencies before code that uses them.
- Stage explicit paths and inspect the complete staged diff before committing.
  Never include personal exports, credentials, caches, or unrelated local work.
- Run relevant checks before committing and use descriptive commit messages.
- Verify the final working-tree state and report the commits created.
- Commit locally when requested; pushing or publishing is a separate action.

### Next steps

1. Help the user complete direct sign-in locally without sharing credentials.
2. Inspect actual response structure and platform values privately; verify
   per-title and cross-console accounting against the Nintendo Store app.
3. Fix demonstrated issues and add synthetic regression cases.
4. Produce the owner's private CSV and validate the Gravk preview/import.
5. Update validation notes, review source and staged files for personal data,
   run checks, and prepare the public MIT release.

An `origin` remote already exists; inspect it rather than replacing it or
reinitializing Git. Do not claim that local changes are committed, pushed,
public, or covered by successful hosted CI unless verified.

Research references are in `NINTENDO-RESEARCH.md`, including nscard, Nintendo
Switch Box, Raycast, nintendo-go, and nxapi. Recheck upstream sources when
diagnosing protocol drift; do not treat old observations as current proof.
