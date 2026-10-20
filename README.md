# Nintendo → Gravk

Export directly from your Nintendo Account, or use the Exophase fallback below. Both tools run on Linux and macOS with Bash and Python 3.9+, without extra Python packages.

## Direct Nintendo export

```bash
bash nintendo.sh export -o gravk-nintendo.csv --save-json nintendo-history.json
```

On the first run, the script prints a Nintendo sign-in link and opens your browser:

1. Sign in on **accounts.nintendo.com** with the account you want to export.
2. At account selection, right-click **Select this person** and copy its link address. Do not follow the link; copy the whole `npf…://auth#…` address.
3. Paste the link into the script's terminal prompt. The paste is hidden.
4. The script exchanges the code with Nintendo, saves the session locally, and exports the CSV. The raw history is also saved when `--save-json` is supplied.

If Safari reports “the address is invalid” after clicking **Select this person**,
it may be trying to open the app callback (`npf…://auth#…`). Dismiss the alert,
return to the account-selection page, and right-click the button → **Copy Link**.
Paste that link into the terminal prompt of the same running exporter, not Safari
or chat. If you restarted the exporter, use its new sign-in URL; old callbacks
will fail the state check. If the error occurs before Nintendo's sign-in page
loads, try `bash nintendo.sh login --no-browser` and manually open the complete
printed `https://accounts.nintendo.com/…` URL, keeping it on one line.

Future exports reuse the local session. Choose a new filename or pass `--force` to replace an existing CSV. A raw JSON backup always needs a new filename. Neither credentials nor callbacks should be pasted into chat or committed to a repository.

```bash
# Explicit sign-in, or switch accounts:
bash nintendo.sh login
# Print the sign-in URL without opening a browser:
bash nintendo.sh login --no-browser
# Subsequent exports:
bash nintendo.sh export -o gravk-nintendo.csv --force
# Convert an existing backup without signing in:
bash nintendo.sh export --input-json nintendo-history.json -o gravk-offline.csv
# Delete the saved local session:
bash nintendo.sh logout
```

The password is entered only on Nintendo's website. Session files are outside the repository, with file permissions `0600`: `~/Library/Application Support/nintendo-to-gravk/session.json` on macOS, or `$XDG_CONFIG_HOME/nintendo-to-gravk/session.json` on Linux (default `~/.config`). This is a local plaintext credential file, not OS keychain storage. Logout deletes that file; it does not revoke authorization at Nintendo. To use another session location, put `--session-file PATH` before the command.

The exporter reads title totals from `playHistories`; it does not add recent daily records to those totals. Minutes are converted to decimal hours. It preserves separate source title/platform entries and stops on conflicting duplicate totals. It leaves completion dates and scores blank. Source platform labels `Nintendo Switch`, `Switch`, `Nintendo Switch 2`, and `Switch 2`, plus API codes `HAC` (Switch) and `BEE` (Switch 2), are recognized case-insensitively. Other platform names/codes stop the conversion for review. With `--save-json`, the response is retained even if conversion fails, so you can inspect source platform values without signing in again. After verifying a value, map it explicitly:

```bash
bash nintendo.sh export --input-json nintendo-history.json \
  --platform-map 'SOURCE_CODE=Nintendo Switch' -o gravk-nintendo.csv
```

You can also map supported Nintendo platform names to the exact labels your Gravk importer accepts. Historical 3DS/Wii U records require explicit mappings. There is no guarantee that Nintendo retained all past activity. Check cross-console totals against the Store app before combining anything in Gravk.

This uses an undocumented Nintendo Store/My Nintendo API, following protocols observed in [nscard](https://github.com/ChengChung/nscard/blob/main/client/nintendo/user/playhistory.go), [Nintendo Switch Box](https://github.com/sigming/nintendo-switch-box/blob/master/src/nintendo.py), and [Raycast](https://github.com/raycast/extensions/blob/main/extensions/switch-game-play-history/src/helpers/nintendo.ts). It needs no Exophase account or third-party signing service. It is independently written and is not an official Nintendo integration. API/app-version changes can break it. Real account sign-in, token exchange, and history retrieval succeeded locally on 2026-10-20. CSV conversion was checked against the saved response, and the user reported that the result works for them. Gravk import completion was not independently observed; detailed cross-console accounting remains to be checked.

See [NINTENDO-RESEARCH.md](NINTENDO-RESEARCH.md) for the protocol research.

## Exophase fallback

Export the Nintendo Switch and Switch 2 games on a public Exophase profile to a CSV matching the Gravk import template. Runs on Linux and macOS with Bash and Python 3.9+; no Python packages, Nintendo password, or API keys required.

This is a community tool, unaffiliated with Nintendo, Exophase, or Gravk. It reads Exophase; it does not sign into Nintendo, trigger a sync, or upload anything to Gravk.

## Quick start

Download or clone this repository, then run:

```bash
bash export.sh YOUR_EXOPHASE_USERNAME -o gravk-nintendo.csv
# A public profile URL also works:
bash export.sh https://www.exophase.com/user/YOUR_EXOPHASE_USERNAME/ -o gravk-nintendo.csv
```

Python 3 is usually available through your Linux package manager. On macOS, install Python 3 from python.org or `brew install python` if needed.

Open Gravk's CSV import, select the generated file, and review the preview before confirming. Map `hours` using the **hours** unit. According to the supplied Gravk import rules, values are rounded to whole hours on import; the CSV retains four-decimal precision. Confirm exact platform matching and rounding in the preview. This tool matches the supplied CSV structure; a live Gravk upload has not been verified.

If Gravk expects another platform label:

```bash
bash export.sh YOUR_EXOPHASE_USERNAME --switch-platform Switch --switch2-platform 'Switch 2'
```

An existing output is preserved unless you pass `--force`.

## Set up your Nintendo source

1. In your Switch profile settings, allow all users to view your play activity. This makes activity public; only do this if you want public tracking.
2. In your own Exophase account's **Service Details**, enter your Nintendo Switch friend code.
3. Run a profile sync in Exophase and verify that your Nintendo games and hours appear. Keep your Exophase profile public for this exporter.

A friend code is not a complete history export. Exophase collects the activity Nintendo exposes, generally the latest 20 games, and retains games it has already seen. Older missing games may need to be played again and then synced. This script cannot recover hidden or untracked history, and it does not query arbitrary Nintendo accounts directly.

## When Exophase blocks command-line requests

Exophase may present a browser challenge. The exporter stops and reports the error; it does not solve challenges or bypass access controls.

### Saved profile page

Open your public Exophase profile in your browser, let it load, and save the page as HTML. Then run:

```bash
bash export.sh --profile-html profile.html -o gravk-nintendo.csv
```

Alternatively, view the profile's page source and find `playerProfileId`. Use its value (the Exophase profile ID, not your Nintendo friend code):

```bash
bash export.sh --player-id YOUR_PLAYER_ID -o gravk-nintendo.csv
```

Both options still require access to the games API.

### Offline JSON conversion

If the games API is blocked too, open this URL in your browser, substituting the player ID:

```text
https://api.exophase.com/public/player/YOUR_PLAYER_ID/games?page=1&environment=&sort=1&showHidden=0
```

Save the JSON response as `page-1.json`. Repeat with `page=2`, `page=3`, etc., until the `games` array is empty or the response is exactly `{"success": false}`. Supply all nonempty pages in order:

```bash
bash export.sh --input-json page-1.json page-2.json -o gravk-nintendo.csv
```

Offline mode converts only the pages supplied; it cannot verify that you've saved the complete history. Save raw JSON, not a screenshot or an HTML wrapper. If the API is unavailable in your browser, wait and try later.

## CSV mapping

The exact column order is:

```csv
title,hours,completedAt,platform,status,userScore,platinum,steamDeck,favorite
```

| Column | Mapping |
| --- | --- |
| `title` | Exophase title; CSV quoting and Unicode are preserved |
| `hours` | Hours + minutes / 60, rounded to 4 decimal places; missing time stays blank |
| `completedAt` | Blank by default; Gravk also accepts a last-played date here, but the exporter does not infer completion |
| `platform` | Nintendo Switch or Nintendo Switch 2; configurable |
| `status` | `played`, matching the supplied template |
| `userScore` | Blank |
| `platinum`, `steamDeck`, `favorite` | `false` defaults, not inferred preferences |

Only Switch and Switch 2 records are included. Repeated records with the same game ID and platform are deduplicated. A record listing both Switch platforms is exported once under the Switch label, with a warning. Its console-specific playtime is unavailable, so the label is a grouping choice rather than proof of which console was used. Records without game IDs use title and platform as the deduplication key. Zero playtime remains zero; unknown playtime stays blank and produces a warning.

The tool requests every API page until an empty page or the exact end-of-list response `{"success": false}` after a populated page, fails on malformed responses or repeated pages, and writes the CSV only after all pages have been processed. Network failures do not leave a partial export. Offline inputs must use the same `{"success": true, "games": [...]}` response schema.

### Gravk import behavior

Based on the supplied importer rules:

- `title` is the only required field. The first row contains column headers; reviews and ratings are optional and are not inferred from Nintendo activity.
- `played` is a supported case-insensitive status. The exporter supplies it explicitly, so status does not depend on Gravk's hours-based fallback.
- Select **hours** when mapping `hours`. Gravk rounds values to a whole number; for example, the CSV retains `1.5167` for 91 minutes, while the imported value loses minute precision. The exact rounding behavior near half-hour boundaries still needs preview validation.
- All matched games are added as owned; games played for at least an hour are also logged. Check sub-hour entries in the preview because the interaction between this threshold and rounding has not been validated.
- Platform names are matched automatically. Check Switch and Switch 2 matches separately in the preview; built-in exporter labels have not yet been validated in a real import.
- `false` is accepted for `platinum`, `steamDeck`, and `favorite`. Scores, if supplied independently, must be between 0 and 100.
- Catalog matching may be incomplete. Review missing games and the preview before confirming.

## Development

```bash
python3 -m unittest discover -s tests -v
bash -n nintendo.sh export.sh
```

The tests use synthetic fixtures and mocked HTTP responses. Live Exophase retrieval has been exercised. A Gravk import has not been validated from this environment. Exophase's JSON endpoint is undocumented and may change.

## Publish your own repository

Generated CSV, JSON, and saved HTML files are ignored by Git because they may contain personal activity data. Review staged files before publishing; do not commit cookies, tokens, or credentials.

This checkout already has a GitHub remote. Before publishing, run the tests, review `git status --short` and the complete staged diff, and confirm that only source, synthetic tests, documentation, license, and CI files are included. Commit those files explicitly rather than adding personal export directories. The GitHub Actions workflow tests Python 3.9 and 3.14 on Linux and macOS; hosted runs still need to pass after publishing.

### Live validation checklist

1. Run the direct exporter in your own interactive terminal. Keep the callback in its hidden prompt, and keep the session outside this checkout.
2. Save raw history outside the checkout with `--save-json`. If conversion stops on a platform code, inspect its meaning before adding a mapping.
3. Compare per-title minutes and shared title IDs across consoles with the Nintendo Store app. Keep console entries separate until overlapping totals are understood; do not sum recent daily records.
4. In Gravk, review the CSV import preview for platform matches, whole-hour rounding (with the hours unit selected), blank dates, and boolean defaults. Check at least one fractional-hour game and any shared-console title against the source before confirming.
5. Record successful account retrieval and Gravk validation separately. Account retrieval has succeeded locally, and the user reported that the resulting export works. Distinguish that report from independently observed import completion; synthetic tests alone do not establish either live step.

## References

- [Exophase's Nintendo tracking setup and limitations](https://www.exophase.com/281290/nintendo-switch-playtime-tracking-added/)
- [Nintendo's play activity instructions](https://en-americas-support.nintendo.com/app/answers/detail/a_id/22366/)
- [Nintendo Exophase Importer](https://github.com/MatisAgr/Nintendo-Exophase-Importer): reference for the undocumented API schema. This exporter is independently written.

## License

MIT; see [LICENSE](LICENSE).
