# Maintaining the README showcase

## Languages, Contents and branding

`python3 scripts/build_readmes.py` rebuilds ten homepages and sixty category
pages. Run `python3 scripts/validate_readmes.py` to check language switches,
Contents destinations, game-genre anchors, asset paths and source counts.

Translations and the approved headline live in `scripts/locales.json`. English stays in the root `README.md`; the nine translated homepages are in `docs/i18n/`, with relative navigation and image paths generated automatically. The
English and Simplified Chinese category bodies inside `CATALOG` markers remain
the reviewed source; the other eight locales translate the navigation, category
introductions, genres and metadata labels. Work names, creator names, license
identifiers and original work descriptions stay in their source language.

The Contents section includes a category overview, per-category code/archive
counts, representative previews and links to the full collection in the selected
language. Games also link directly to fourteen genre sections. Featured choices
are configured in `scripts/build_readmes.py`; ranking remains data-driven.

`assets/logo.svg` is an unchanged copy of the supplied vector logo. All
homepages and category headers/footers use it. The original logo assets are kept
for reference. After catalog changes, run the homepage builder, then the showcase
renderer and navigation validator. The scheduled workflow performs these steps
for every language automatically.

The homepages give readers three reasons to return or contribute: discovery of
new works, broad coverage, and the collected source archive on Hugging Face.
The animated showcase supplies evidence of current activity. Both languages
share the same measurements, ranking and images.

## Build and refresh

```sh
python3 -m pip install -r scripts/requirements.txt
python3 -m unittest discover -s scripts -p 'test_*.py'
python3 scripts/refresh_showcase.py
```

The default build is offline, using `data/showcase.json` and the six English
category READMEs. Preserve the `SHOWCASE` marker pairs in both homepages. The
script derives entry, category, public-code and archive counts from category
pages; it validates their declared counts. Editorial figures (creator count,
browser-playable count and Three.js count) still come from the catalog review.

```sh
python3 scripts/refresh_showcase.py --refresh
```

This reads public engagement and generates the animated GIF, its first-frame
WebP for reduced-motion preferences, the data snapshot and both homepage blocks.
For ranked works without a catalog screenshot, available public video covers
are cached under `assets/showcase-previews/` and attributed by their source link.
Install Noto Sans CJK or set `SHOWCASE_FONT` to a Unicode font for CJK titles.

The workflow runs at 01:00, 09:00 and 17:00 UTC (09:00, 17:00 and 01:00 Beijing time), on relevant default-branch
changes, and through **Actions → Refresh README showcase → Run workflow**.
It becomes active when pushed to the default branch with Actions enabled and
permission to push updates. Protected branches may require the normal repository
change process. GitHub scheduling and image caching can delay refreshes; the
README therefore displays the measured sync time rather than promising a
per-visit live ranking.

## Platform and Hugging Face synchronization

Before refreshing metrics, `sync_public_catalog.py` reads a pinned public snapshot
from `AI-Terrarium/terrarium-open-works`. Scheduled runs wait up to five minutes
for the current eight-hour batch. Missing snapshots leave the existing catalog
in place. Invalid hashes or contracts fail the job before publication.

After the first successful import, edit `data/catalog.jsonl` for catalog changes;
category README bodies are generated from it. The first import preserves existing
reviewed README entries and attributions. Three-way merging keeps independent
GitHub edits and records conflicts for platform review. Missing entries never
delete work; an explicit `withdrawn` record is required. Platform decisions to
keep its values apply only to the exact GitHub record that was reviewed.

`data/catalog-sync-baseline.jsonl` retains the last HF input, and
`data/catalog-sync.json` acknowledges the published catalog hash. A `conflict`
receipt means local edits still need platform review; `ready` means the catalogs
match. Archive links come only from the real HF index. Existing archive paths
remain valid when a work's editorial form changes. The workflow commits these
files with all localized pages using its own `GITHUB_TOKEN`; it needs no HF write
token. The platform is the HF writer and exports public catalog fields only.
Source files require separate confirmation of redistribution permission.

For offline validation, run `python3 scripts/sync_public_catalog.py --snapshot
/path/to/snapshot --root /path/to/copy`, followed by the builders and validator.
The snapshot directory needs `catalog.jsonl`, `metadata.jsonl`, `catalog-sync.json`,
`catalog-creators.json`, `catalog-tags.json`, and `catalog-metrics.json`.

## Public sources and credentials

Sources are resolved from each work's publication, code and independent social-post links. `data/engagement-links.json` preserves original posts separately from playable URLs, so a work does not lose its engagement evidence when its primary link opens a demo.
The same repository, post or video is measured once, even when several entries
link to it. The category catalog also includes entries without previews.

| Platform | Signals | Access |
| --- | --- | --- |
| GitHub | Stars, forks | `GITHUB_TOKEN`; provided automatically by Actions |
| X | Likes, comments from public embeds | No credential; public embed availability can change |
| X with API access | Likes, impressions, replies, reposts, bookmarks when returned | Optional `X_BEARER_TOKEN` repository secret |
| Bilibili | Views, likes, replies, shares, favorites, coins | Public video metadata endpoint |
| Hugging Face Spaces | Likes | Public Space API |
| Reddit | Net votes, comments | Public post JSON, where accessible |
| YouTube | Views, likes, comments | Optional `YOUTUBE_API_KEY` repository secret |

Missing counters stay missing, rather than becoming estimated values. X embeds
often omit views and shares. Reddit's score is labeled net votes. A failed
platform is excluded and recorded in `unavailable`, with measurement coverage
shown below the showcase. A total outage leaves the previous snapshot intact.
Without any measured support, the banner explicitly falls back to recent releases. One available platform can supply a ranking; the coverage line identifies the actual platform count. Rebuilt snapshots over 12 hours old are marked
stale; published images always retain their actual last-sync timestamp.

The public X embed and Bilibili video endpoints are website interfaces rather
than stable developer API contracts. Failures are handled without fabricating
measurements. No login bypass or private post collection is used. For X's full
documented metrics, configure the optional official API credential.

## Popularity ordering

The method is `public-support-v1`: a Most Loved view of catalog entries, with
current public support counts shown on the cards. This does not claim to measure
recent growth or a platform's official trending algorithm.

1. Gather original publication, public code and linked social-post evidence for
   each catalog work. The engagement manifest validates that every linked work
   exists in the catalog. It currently includes exact-URL associations discovered
   in [awesome-fable-5.2](https://github.com/fengyiqicoder/awesome-fable-5.2/blob/6594d5b9084c61b8675f9c5586cb14e710fb73c3/data/works.json)
   (CC0 1.0). Counts are queried from the original platforms, not copied from that
   collection's cached `likes` field.
2. Primary support is the public like count, GitHub star count or positive Reddit
   net score, according to the source. Multiple posts on one platform contribute
   only the strongest post. Support from different platforms is added, with each
   platform's counters linked separately. This counts interactions, not unique
   people or statistically equivalent platform audiences.
3. Order by support count descending. Comments, shares, favorites, coins and
   forks break ties. Views are displayed as context and do not outweigh likes.
4. Do not penalize an older post or repository creation date, normalize a small
   platform's top result into a high score, or convert missing data into zero.
   The separate **Latest** section handles freshness. Future publication dates
   are excluded.
5. Show each underlying post or repository only once in the top four, even when
   multiple catalog entries share it. A source's absence from the measured set
   remains visible in the coverage information and data snapshot.

Maintain social-post links when adding works or changing their primary links.
Add reviewed associations to `data/engagement-links.json`; do not set a demo URL
as a replacement for an original post. Keeping these relations is necessary for
ranking coverage. Sources not yet linked cannot contribute. A regression check
ensures Starry Nightrider, Saltline and Oil paint retain their verified original
post links and that stronger support is not displaced by recency weighting.

References: [X public metrics](https://docs.x.com/x-api/posts/get-posts-by-ids),
[Hugging Face API](https://huggingface.co/docs/hub/api),
[GitHub repository metadata](https://docs.github.com/en/graphql/reference/repos),
[YouTube video statistics](https://developers.google.com/youtube/v3/docs/videos),
[Reddit post score](https://developers.reddit.com/docs/api/redditapi/models/classes/Post).

## Keep catalog freshness separate

Fetching heat does not discover new works or advance the catalog date. The
showcase uses the oldest category data date for the full-catalog snapshot.
After adding reviewed works, regenerate the category pages, update **Latest**
and editorial figures, then rerun the showcase script.

The upstream discovery data and generator are not present in this checkout.
If that generator also writes homepages, port the new prose and marker pairs
into its templates before regenerating them. Connect and verify that discovery
pipeline before claiming a daily catalog update or the fastest/broadest coverage
against other collections.

After the platform publishes a batch to HF, it dispatches `sync-catalog.yml` with the exact HF revision and batch ID. This catalog-only job validates that pair, renders all languages, and commits the receipt without refreshing engagement metrics or querying X. It shares the showcase concurrency group and checks out current main when it starts, preserving intervening GitHub edits. The existing eight-hour showcase schedule remains a fallback. A dispatch acknowledgement alone never means the catalogs match; the platform verifies the committed batch ID and both content hashes.

Archive Files links additionally require compatible author and canonical GitHub source identities. A matching slug cannot attach a different author's repository, even though the full HF archive index is retained for review.
