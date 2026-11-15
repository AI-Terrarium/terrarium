"""Collect public engagement and rank catalog works by observable support."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
import re
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


PLATFORM_NAMES = {"github": "GitHub", "x": "X", "bilibili": "Bilibili", "huggingface": "Hugging Face",
                  "reddit": "Reddit", "youtube": "YouTube"}
RANKING_METHOD = "public-support-v1"


def parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(frozen=True)
class Source:
    platform: str
    identifier: str
    url: str

    @property
    def key(self):
        return f"{self.platform}:{self.identifier}"


def source_for_url(url):
    parsed = urlsplit(url)
    host = parsed.hostname
    parts = parsed.path.strip("/").split("/")
    if host == "github.com" and len(parts) >= 2:
        identifier = "/".join(parts[:2]).removesuffix(".git").lower()
        return Source("github", identifier, f"https://github.com/{identifier}")
    if host == "huggingface.co" and len(parts) >= 3 and parts[0] == "spaces":
        identifier = "/".join(parts[1:3])
        return Source("huggingface", identifier, f"https://huggingface.co/spaces/{identifier}")
    if host in ("x.com", "twitter.com", "www.x.com"):
        match = re.search(r"/status/(\d+)", parsed.path)
        if match:
            return Source("x", match[1], f"https://x.com/i/status/{match[1]}")
    if host in ("www.bilibili.com", "bilibili.com"):
        match = re.search(r"/video/(BV[\w]+)", parsed.path)
        if match:
            return Source("bilibili", match[1], f"https://www.bilibili.com/video/{match[1]}/")
    if host in ("www.reddit.com", "reddit.com"):
        match = re.search(r"/comments/([a-z0-9]+)", parsed.path)
        if match:
            return Source("reddit", match[1], f"https://www.reddit.com/comments/{match[1]}/")
    if host in ("www.youtube.com", "youtube.com", "youtu.be"):
        from urllib.parse import parse_qs
        identifier = parts[0] if host == "youtu.be" else parse_qs(parsed.query).get("v", [None])[0]
        if identifier:
            return Source("youtube", identifier, f"https://www.youtube.com/watch?v={identifier}")
    return None


def source_refs(entry):
    urls = (entry.url, entry.code, *getattr(entry, "social_urls", ()))
    return {source.key: source for url in urls if url
            if (source := source_for_url(url)) is not None}


def canonical_work_url(url):
    """Match a work's links without depending on scheme or a trailing slash."""
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    return host + parsed.path.rstrip("/") + ("?" + parsed.query if parsed.query else "")


def request_json(url, headers=None, body=None):
    request = Request(url, data=json.dumps(body).encode() if body is not None else None,
                      headers={"User-Agent": "Terrarium/1.0 (public work catalog)",
                               "Accept": "application/json", **(headers or {})})
    with urlopen(request, timeout=20) as response:
        return json.load(response)


def mapped_counts(data, mapping):
    # Missing counters remain missing; they must not become made-up zeroes.
    return {name: int(data[field]) for name, field in mapping.items()
            if isinstance(data.get(field), (int, float)) and data[field] >= 0}


def collect_one(source, get=request_json):
    identifier = source.identifier
    preview_url = None
    if source.platform == "x":
        token = os.environ.get("X_BEARER_TOKEN")
        if token:
            payload = get("https://api.x.com/2/tweets/" + identifier + "?tweet.fields=created_at,public_metrics",
                          {"Authorization": f"Bearer {token}"})
            data = payload["data"]
            metrics = mapped_counts(data["public_metrics"], {"likes": "like_count", "views": "impression_count",
                                    "comments": "reply_count", "shares": "retweet_count", "favorites": "bookmark_count"})
            if "repost_count" in data["public_metrics"]:
                metrics["shares"] = int(data["public_metrics"]["repost_count"])
        else:
            # X's public embed response supplies likes/comments; it often omits
            # views and shares. Only fields actually returned enter the snapshot.
            data = get("https://cdn.syndication.twimg.com/tweet-result?" + urlencode(
                {"id": identifier, "lang": "en", "token": "0"}))
            metrics = mapped_counts(data, {"likes": "favorite_count", "comments": "conversation_count"})
        published = data["created_at"]
    elif source.platform == "bilibili":
        payload = get("https://api.bilibili.com/x/web-interface/view?" + urlencode({"bvid": identifier}))
        if payload["code"] != 0:
            raise ValueError(f"Bilibili returned code {payload['code']}")
        data = payload["data"]
        metrics = mapped_counts(data["stat"], {"views": "view", "likes": "like", "comments": "reply",
                                "shares": "share", "favorites": "favorite", "coins": "coin"})
        published = datetime.fromtimestamp(data["pubdate"], timezone.utc).isoformat()
        preview_url = data.get("pic")
    elif source.platform == "huggingface":
        data = get("https://huggingface.co/api/spaces/" + identifier)
        if data.get("private"):
            raise ValueError("Space is private")
        metrics = mapped_counts(data, {"likes": "likes"})
        published = data["createdAt"]
    elif source.platform == "reddit":
        data = get(source.url + ".json?limit=1")[0]["data"]["children"][0]["data"]
        # Reddit exposes net score, not a raw like count.
        metrics = mapped_counts(data, {"comments": "num_comments"})
        metrics["net_votes"] = int(data["score"])
        published = datetime.fromtimestamp(data["created_utc"], timezone.utc).isoformat()
    elif source.platform == "youtube":
        key = os.environ.get("YOUTUBE_API_KEY")
        if not key:
            raise ValueError("YOUTUBE_API_KEY not configured")
        data = get("https://www.googleapis.com/youtube/v3/videos?" + urlencode(
            {"id": identifier, "part": "snippet,statistics", "key": key}))["items"][0]
        metrics = {name: int(data["statistics"][field]) for name, field in
                   {"views": "viewCount", "likes": "likeCount", "comments": "commentCount"}.items()
                   if field in data["statistics"]}
        published = data["snippet"]["publishedAt"]
    else:
        raise ValueError("Unsupported single-source collector")
    if not metrics:
        raise ValueError("No public engagement counters returned")
    parse_time(published)  # Reject invalid/missing publication dates.
    result = {"platform": source.platform, "url": source.url, "published_at": published, "metrics": metrics}
    if preview_url:
        result["preview_url"] = preview_url.replace("http://", "https://", 1)
    return result


def collect_github(sources, get=request_json):
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return {}, [{"source": source.key, "reason": "GITHUB_TOKEN not configured"} for source in sources]
    records, unavailable = {}, []
    for start in range(0, len(sources), 30):
        batch = sources[start:start + 30]
        fields = []
        for index, source in enumerate(batch):
            owner, name = source.identifier.split("/")
            fields.append(f"r{index}: repository(owner: {json.dumps(owner)}, name: {json.dumps(name)}) {{"
                          " isPrivate stargazerCount forkCount createdAt }")
        payload = get("https://api.github.com/graphql", {"Authorization": f"Bearer {token}",
                      "Content-Type": "application/json"}, {"query": "query { " + " ".join(fields) + " }"})
        for error in payload.get("errors", []):
            if error.get("type") != "NOT_FOUND":
                raise ValueError("GitHub query failed; this platform was excluded")
        for index, source in enumerate(batch):
            node = payload["data"][f"r{index}"]
            if node is None or node["isPrivate"]:
                unavailable.append({"source": source.key, "reason": "Not public or not found"})
                continue
            records[source.key] = {"platform": "github", "url": source.url, "published_at": node["createdAt"],
                                   "metrics": {"stars": node["stargazerCount"], "forks": node["forkCount"]}}
    return records, unavailable


def fetch_metrics(entries, now, get=request_json):
    sources = {}
    for entry in entries:
        sources.update(source_refs(entry))
    github = [source for source in sources.values() if source.platform == "github"]
    try:
        records, unavailable = collect_github(github, get)
    except (OSError, ValueError, KeyError, TypeError) as error:
        records = {}
        unavailable = [{"source": source.key, "reason": f"GitHub unavailable ({type(error).__name__})"} for source in github]

    def fetch(source):
        try:
            return source.key, collect_one(source, get), None
        except (OSError, ValueError, KeyError, IndexError, TypeError) as error:
            # Error bodies/URLs may contain API keys. Persist only a safe class.
            reason = "YOUTUBE_API_KEY not configured" if source.platform == "youtube" and not os.environ.get("YOUTUBE_API_KEY") else type(error).__name__
            return source.key, None, {"source": source.key, "reason": reason}

    with ThreadPoolExecutor(max_workers=4) as pool:
        for key, record, failure in pool.map(fetch, [s for s in sources.values() if s.platform != "github"]):
            if failure:
                unavailable.append(failure)
            else:
                records[key] = record
    if not records:
        raise RuntimeError("No public engagement could be measured; previous showcase retained")
    return {"schema_version": 1, "updated_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "method": RANKING_METHOD,
            "sources": dict(sorted(records.items())), "unavailable": sorted(unavailable, key=lambda item: item["source"])}


def support_count(record):
    metrics = record["metrics"]
    return max(0, metrics.get("likes", metrics.get("stars", metrics.get("net_votes", 0))))


def secondary_count(record):
    return sum(max(0, record["metrics"].get(key, 0))
               for key in ("comments", "shares", "favorites", "coins", "forks"))


def rank_entries(entries, state):
    """Most-loved ordering: public support first, other interactions break ties."""
    if not state["updated_at"]:
        return []
    now = parse_time(state["updated_at"])
    available = {}
    for key, record in state["sources"].items():
        if parse_time(record["published_at"]) <= now and support_count(record) > 0:
            available[key] = record
    ranked = []
    for entry in entries:
        candidates = {key: available[key] for key in source_refs(entry) if key in available}
        if not candidates:
            continue
        # Multiple posts about the same work on one platform do not stack.
        best = {}
        for key, record in sorted(candidates.items(), key=lambda item: (
                -support_count(item[1]), -secondary_count(item[1]), item[0])):
            best.setdefault(record["platform"], (key, record))
        evidence = dict(sorted(best.values(), key=lambda item: (-support_count(item[1]), item[0])))
        support = sum(support_count(record) for record in evidence.values())
        ranked.append((entry, support, evidence))
    ranked.sort(key=lambda row: (-row[1], -sum(secondary_count(record) for record in row[2].values()),
                                 not bool(row[0].thumbnail), row[0].collection, row[0].title.casefold()))
    selected, used = [], set()
    for row in ranked:
        all_sources = set(source_refs(row[0]))
        if used.intersection(all_sources):
            continue
        selected.append(row)
        used.update(all_sources)
        if len(selected) == 4:
            break
    return selected


def evidence_labels(records, chinese=False, metric_names=None, prefix_labels=False, separator=","):
    names = {"views": "播放", "likes": "赞", "stars": "Star", "comments": "评论", "shares": "分享",
             "favorites": "收藏", "coins": "投币", "forks": "Fork", "net_votes": "净票"}
    labels = []
    for record in records.values():
        values = record["metrics"]
        metrics = []
        for key in ("views", "likes", "stars", "net_votes", "comments", "shares", "favorites", "coins", "forks"):
            if key in values and values[key] != 0:
                label = metric_names[key] if metric_names else names[key] if chinese else key.replace("_", " ")
                if not chinese and not metric_names and values[key] == 1:
                    label = label.removesuffix("s")
                number = f"{values[key]:,}".replace(",", separator)
                metrics.append(f"{label}: {number}" if prefix_labels else f"{number} {label}")
        labels.append((record["url"], PLATFORM_NAMES[record["platform"]] + " · " + " · ".join(metrics)))
    return labels
