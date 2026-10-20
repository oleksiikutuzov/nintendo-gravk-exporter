# Direct Nintendo to Gravk exporter: feasibility

Research date: 2026-10-20. The direct protocol is now implemented by nintendo.sh/nintendo.py; export.sh remains the Exophase fallback. Real account sign-in, token exchange, and history retrieval succeeded locally on 2026-10-20. The implementation has synthetic tests for authorization, HTTP requests, session permissions, and CSV conversion.

## Recommendation

Implement account-owner export using the Nintendo Store/My Nintendo play-history service. It avoids Exophase and the additional signing/encryption provider involved in the Nintendo Switch app (Coral) protocol. Each user authorizes their own account in Nintendo's browser sign-in page.

The generic friend-code route is a separate feature. Open-source client code implements friend-code resolution and public play-log lookup, but it still needs an authenticated querying client and is subject to Nintendo's visibility rules. It should not be advertised as an anonymous full-history API.

## Account-owner route

Observed in independent open-source clients:

1. Generate a random state and PKCE verifier; compute a base64url SHA-256 challenge.
2. Open `https://accounts.nintendo.com/connect/1.0.0/authorize` with client ID `5c38e31cd085304b`, redirect `npf5c38e31cd085304b://auth`, response type `session_token_code`, challenge method `S256`, challenge and state. Existing clients request scope `openid user user.mii user.email user.links[].id`; minimum viable scope has not been established.
3. User signs in on Nintendo's website. Copy the account-selection button's callback link into the local terminal. Validate callback origin/scheme, state, and required parameters before exchanging anything.
4. POST a form to `/connect/1.0.0/api/session_token` containing client_id, session_token_code, and session_token_code_verifier.
5. POST JSON to `/connect/1.0.0/api/token` containing client_id, session_token, and grant_type `urn:ietf:params:oauth:grant-type:jwt-bearer-session-token`.
6. GET `https://app-api.znej.nintendo.com/api/v2.0/users/me/play_histories` with bearer access_token, a supported app User-Agent, and gentry-locale such as en-US.

Recent clients use User-Agent `com.nintendo.znej/3.0.3 (iOS/26.0.1)`. This is an implementation observation, not a stable or officially supported contract. Older Raycast code uses `https://mypage-api.entry.nintendo.co.jp/api/v1/users/me/play_histories`; prioritize the newer app-api endpoint.

Expected response arrays are playHistories and recentPlayHistories, with hiddenTitleList and lastUpdatedAt also represented in client models. Per-title fields include titleId, titleName, platform (or older deviceType), totalPlayedMinutes, totalPlayedDays, firstPlayedAt, and lastPlayedAt. Recent daily play records are separate from title totals and must not be added to those totals.

Code inspected: [Nintendo Go auth](https://github.com/robtme/nintendo-go/blob/main/auth.go), [configuration](https://github.com/robtme/nintendo-go/blob/main/nintendo.go), [history](https://github.com/robtme/nintendo-go/blob/main/playhistory.go), [nscard](https://github.com/ChengChung/nscard/blob/main/client/nintendo/user/playhistory.go), [Nintendo Switch Box](https://github.com/sigming/nintendo-switch-box/blob/master/src/nintendo.py), [Raycast helper](https://github.com/raycast/extensions/blob/main/extensions/switch-game-play-history/src/helpers/nintendo.ts).

These sources support feasibility; most do not constitute independently verified live tests. Nintendo Go's repository tests use a mock HTTP server. Token lifetimes described in community projects must not be treated as guarantees; handle expiry and revocation.

## Friend-code route

The current nxapi implementation has:

- Host: `https://api-lp1.znc.srv.nintendo.net`.
- `getUserByFriendCode`: POST `/v3/Friend/GetUserByFriendCode`, parameter.friendCode formatted without SW-.
- Response includes nsaId and basic profile data.
- `getPlayLog`: POST `/v4/User/PlayLog/Show`, parameter.nsaId.
- Response model is a list of games with name, imageUri, shopUri, totalPlayTime, and firstPlayedAt.
- Visibility enums include EVERYONE, FRIENDS, FAVORITE_FRIENDS, and SELF.

Authentication uses a different Nintendo client ID, `71b963c1b7b6d119`, and Coral account credentials. Current nxapi code obtains an f parameter via a provider and includes request encryption/decryption support. A dependency-free implementation would require substantially more work than the Store route. Do not assume an old imink-only example still supports current request requirements.

Source: [nxapi Coral client](https://github.com/samuelthomas2774/nxapi/blob/main/src/api/coral.ts), [types](https://github.com/samuelthomas2774/nxapi/blob/main/src/api/coral-types.ts), [provider code](https://github.com/samuelthomas2774/nxapi/blob/main/src/api/f.ts).

This resembles the architecture needed for a public tracker. It does not prove which endpoints Exophase uses. The source model alone also does not establish the units/rounding of totalPlayTime; verify against a known account before conversion.

## Live checks performed

Without credentials, the Store history endpoint returned HTTP 400 with code 400001 and request-validation failure. The friend-code lookup returned HTTP 200 carrying application status 9400, Bad request. Neither returned play activity. These observations establish reachability and rejection of these requests, not proof that all anonymous alternatives have been ruled out. No authentication bypass was attempted.

Nintendo documents an owner-visible All Activity list in the Store app, starting from account linkage, and up to one day of synchronization lag. Wii U/3DS history is limited to data through February 2020. See [Nintendo Support](https://en-americas-support.nintendo.com/app/answers/detail/a_id/68647/p/1128).

## Implementation outline

- Keep the existing Bash entry-point style and Python standard library runtime.
- Add a separate direct-Nintendo entry point, so existing Exophase usage remains valid.
- Provide interactive login, export with cached session, logout, and offline JSON conversion.
- Keep callback and session values out of command arguments, shell history, logs, and repository files. Read callback privately in the terminal, store the session outside the checkout with owner-only permissions, and clear pending login state after exchange.
- Restrict credential-bearing HTTP requests to expected Nintendo hosts, use TLS verification, and reject unexpected redirects.
- Validate live platform codes before defining Switch/Switch 2 mappings. Retain title ID and source platform in optional raw backups; do not guess the hardware from the title name.
- Convert totalPlayedMinutes / 60 into Gravk hours. Keep completion date and score blank and use the existing played status and boolean defaults.
- Test duplicate title/platform behavior against real Switch and Switch 2 data. Do not blindly sum entries when their totals may overlap.
- Preserve raw responses locally for review, with opt-in backups and Git ignore rules.
- Compare a signed-in export with the existing Exophase CSV for coverage and totals. Differences may be real synchronization/collection differences, not necessarily conversion bugs.

## Remaining validation

Authorized Nintendo sign-in and history retrieval succeeded locally. The response uses the documented field shape with `platform` codes `HAC` and `BEE`. Built-in mappings now follow Nintendo model families: [Switch HAC](https://en-americas-support.nintendo.com/app/answers/detail/a_id/58879/p/172) and [Switch 2 BEE](https://support.nintendo.com/jp/repair/price_switch2.html). This is an inference from observed API codes and official hardware names, not an official API enumeration. Coverage and cross-console accounting still need comparison with the Store app. The user can complete this locally without sharing their password or session token in chat. The supplied Gravk rules confirm that hours are rounded to whole numbers on import and platform names are matched automatically. Exact Switch/Switch 2 matches, rounding boundaries, and the owned/logged threshold still require an import preview; preserve decimal hours in the CSV and select the hours unit during mapping.

## User validation update (2026-10-20)

After local CSV generation and row-by-row checks against the saved response, the user reported that the result works for them. This is user-reported validation; import completion was not independently observed. Detailed platform matching, rounding boundaries, and cross-console accounting have not all been verified.
