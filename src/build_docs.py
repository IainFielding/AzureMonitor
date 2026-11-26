"""Generates a reference page for every workbook: what each tab and panel reports, and where its data comes from.

Run:  python src/build_docs.py        (after the workbook scripts)
Out:  docs/<workbook>.md, one per file in workbook/, and docs/README.md, the index

The pages are read from the generated workbook JSON, so they cannot drift from what the workbooks show. Each
panel is listed with its kind (table, chart, tiles), its data source, the tables or metrics it reads, its columns
and what it says when it finds nothing; the explanatory notes in the workbook appear where they sit on the page.
To improve a page, improve the workbook's own notes and titles in its build script and regenerate both.
"""

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKBOOKS = ROOT / "workbook"
OUT = ROOT / "docs"

SOURCES = {0: "Log Analytics", 1: "Azure Resource Graph", 12: "Azure Resource Manager"}
VISUALS = {"table": "Table", "tiles": "Tiles", "timechart": "Time chart", "barchart": "Bar chart",
           "piechart": "Pie chart", "areachart": "Area chart", "linechart": "Line chart", "scatterchart": "Scatter chart",
           "map": "Map", "graph": "Graph", "categoricalbar": "Bar chart"}
AGGREGATIONS = {1: "sum", 2: "min", 3: "max", 4: "average", 7: "count"}

# Table names: Log Analytics tables by name, and Resource Graph tables by their shape.
LA_TABLES = re.compile(
    r"^(AAD\w+|ADF\w+|ADX\w+|AGW\w+|ASim\w+|AVS\w+|AZFW\w+|AZKV\w+|AddonAzureBackup\w+|ApiManagement\w+|"
    r"App(Exceptions|Requests|Traces|Dependencies)|AuditLogs|AzureActivity|AzureDiagnostics|AzureMetrics|"
    r"AzureSiteRecovery\w+|CommonSecurityLog|DNSQueryLogs|DnsEvents|Event|FailedIngestion|SucceededIngestion|"
    r"Heartbeat|InsightsMetrics|LAQueryLogs|MicrosoftPurview\w+|NTA\w+|NWConnectionMonitor\w+|Operation|Perf|"
    r"Security(Alert|Event|Incident)|Sentinel(Audit|Health)|SigninLogs|StorageBlobLogs|Usage|WVD\w+)$")
ARG_TABLES = re.compile(r"^([a-z]+resources|[a-z]+changes|resourcecontainers)$")
CANDIDATE = re.compile(r"(?:^|\(|=|\bunion\b(?:\s+(?:isfuzzy|kind)=\w+)*)\s*([A-Za-z_]\w*)\b(?!\s*[=(:.\[])", re.M)


def tables(query, source):
    pattern = LA_TABLES if source == 0 else ARG_TABLES
    found = []
    for match in CANDIDATE.finditer(query):
        name = match.group(1)
        if pattern.match(name) and name not in found:
            found.append(name)
    return found


def split_top(text):
    """Split on commas that are not inside brackets or quotes."""
    parts, depth, quote, cur = [], 0, None, ""
    for ch in text:
        if quote:
            cur += ch
            if ch == quote:
                quote = None
            continue
        if ch in "'\"":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
            continue
        cur += ch
    parts.append(cur)
    return parts


def columns(query):
    """The columns of the last `project` in the query, when it is the shape of the result."""
    matches = list(re.finditer(r"^\|\s*project\s+(?!-)", query, re.M))
    if not matches:
        return []
    body = query[matches[-1].end():]
    end = re.search(r"^\|", body, re.M)
    body = body[:end.start()] if end else body
    cols = []
    for part in split_top(body):
        part = part.strip()
        if not part:
            continue
        name = part.split("=", 1)[0].strip() if re.match(r"^[\w\[\]' ]+\s*=", part) else part
        name = name.strip("[]'\" ")
        if re.fullmatch(r"\w+", name):
            cols.append(name)
    return cols


def humanise(name):
    words = name.split("-")[1:] or [name]
    return " ".join(words).capitalize()


def shift_headings(md):
    """Headings in a workbook note become at least level 3, so they sit under the page's tab headings."""
    out = []
    for line in md.splitlines():
        m = re.match(r"^(#+)\s", line)
        out.append(("#" * max(3, len(m.group(1)))) + line[len(m.group(1)):] if m else line)
    return "\n".join(out)


def plain(text):
    """Workbook parameter references ({Target}, {Month:label}) as the parameter's name in italics."""
    return re.sub(r"\{(\w+)(?::\w+)?\}", lambda m: m.group(1), text)


def spaced(name):
    """A column name as words: PoolType -> Pool Type, LastSeen -> Last Seen."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)


DEFAULT_DESCRIPTIONS = {6: "The subscriptions to read. Defaults to all you can see.",
                        4: "The period the log and metric panels cover."}


def labels_of(content):
    return {s["columnId"]: s["label"] for s in content.get("gridSettings", {}).get("labelSettings", [])}


def query_panel(item):
    c = item["content"]
    source = c["queryType"]
    title = c.get("title") or humanise(item["name"])
    lines = [f"#### {title}", ""]
    if source == 12:
        request = json.loads(c["query"])
        lines.append(f"*Table · {SOURCES[12]}*: `{request['method']} {request['path']}`")
        cols = [col["columnid"] for t in request.get("transformers", []) for col in t["settings"].get("columns", [])]
    else:
        kind = VISUALS.get(c.get("visualization", "table"), c.get("visualization", "table"))
        read = tables(c["query"], source)
        reads = f" · reads {', '.join(f'`{t}`' for t in read)}" if read else ""
        lines.append(f"*{kind} · {SOURCES.get(source, 'Query')}*{reads}")
        cols = columns(c["query"]) if c.get("visualization", "table") == "table" else []
    labels = labels_of(c)
    hidden = {f["columnMatch"] for f in c.get("gridSettings", {}).get("formatters", []) if f.get("formatter") == 5}
    cols = [labels.get(col, spaced(col)) for col in cols if col not in hidden]
    if cols:
        lines += ["", "Columns: " + ", ".join(cols) + "."]
    if c.get("noDataMessage"):
        lines += ["", f"When there is nothing to show: *{c['noDataMessage']}*"]
    return lines


def metrics_panel(item):
    c = item["content"]
    title = c.get("title") or humanise(item["name"])
    labels = labels_of(c)
    names = []
    for spec in c["metrics"]:
        metric = spec["metric"].split("--", 1)[1]
        label = labels.get(spec["metric"], metric)
        split = f", split by {spec['splitBy']}" if spec.get("splitBy") else ""
        names.append(f"{label} ({AGGREGATIONS.get(spec['aggregation'], 'value')}{split})")
    kind = "Tiles" if c.get("tileSettings") else ("Table, one row per resource" if c.get("chartType") == 0 else "Chart")
    return [f"#### {title}", "",
            f"*{kind} · Azure Monitor metrics* of `{c['resourceType']}`: {'; '.join(names)}."]


def parameter_rows(item):
    rows = []
    for p in item["content"]["parameters"]:
        if p.get("isHiddenWhenLocked") or not p.get("label"):
            continue
        text = p.get("description") or DEFAULT_DESCRIPTIONS.get(p["type"]) or (
            f"Which {p['label'].lower()} to include." if p["type"] == 5 else "")
        rows.append(f"| {p['label']} | {plain(text).replace('|', '/')} |")
    return rows


def render(items, level, tabs):
    """Markdown for a list of items. `tabs` maps a tab key to its label, for groups shown on a tab."""
    out = []
    for item in items:
        kind = item["type"]
        if kind == 1:
            md = item["content"]["json"].strip()
            if md.startswith("# "):  # the workbook's own title, handled by the caller
                continue
            out += [shift_headings(md) if md.startswith("#") else
                    "\n".join("> " + line if line else ">" for line in md.splitlines()), ""]
        elif kind == 3:
            out += query_panel(item) + [""]
        elif kind == 10:
            out += metrics_panel(item) + [""]
        elif kind == 12:
            vis = item.get("conditionalVisibility", {})
            content = item["content"]
            if vis.get("parameterName") in tabs and vis.get("value") in tabs[vis["parameterName"]]:
                out += [f"## Tab: {tabs[vis['parameterName']][vis['value']]}", ""]
                out += render(content["items"], 3, tabs)
            elif content.get("loadButtonText"):
                out += [f"### {content['loadButtonText']} (loads when asked)", ""]
                out += render(content["items"], level + 1, tabs)
            else:
                out += render(content["items"], level, tabs)
    return out


def page(path):
    wb = json.loads(path.read_text(encoding="utf-8"))
    items = wb["items"]

    def walk(xs):
        for x in xs:
            yield x
            if x["type"] == 12:
                yield from walk(x["content"]["items"])

    everything = list(walk(items))
    header = next((i["content"]["json"] for i in everything if i["type"] == 1 and i["content"]["json"].startswith("# ")), "")
    title = re.sub(r"\s*:?\s*\{[^}]+\}", "", header.splitlines()[0][2:]).strip() if header else path.stem
    intro = plain("\n".join(header.splitlines()[1:]).strip())
    tabs = {}
    for i in everything:
        if i["type"] == 11:
            for link in i["content"].get("links", []):
                if link.get("linkTarget") == "parameter":
                    tabs.setdefault(link["cellValue"], {})[link["subTarget"]] = link["linkLabel"]
    params = [row for i in everything if i["type"] == 9 for row in parameter_rows(i)]
    counts = {"queries": sum(1 for i in everything if i["type"] in (3, 10))}

    lines = [f"# {title}", "",
             f"*Reference for [{path.name}](../workbook/{path.name}). Generated from the workbook by "
             f"`src/build_docs.py`: do not edit by hand.*", ""]
    if intro:
        lines += [intro, ""]
    lines += [f"It has {counts['queries']} panels"
              + (f" across {sum(len(v) for v in tabs.values())} tabs" if tabs else "") + ". Each is listed below with "
              "what kind of panel it is, where its data comes from and, for tables, its columns. Log Analytics panels "
              "need the named tables in the selected workspace; see *Logs to collect* in the "
              "[main README](../README.md#logs-to-collect).", ""]
    if params:
        lines += ["## Parameters", "", "| Parameter | What it does |", "|---|---|", *params, ""]
    body = render([i for i in items if i["type"] not in (9, 11)], 2, tabs)
    if not tabs:
        body = ["## Panels", ""] + body
    lines += body
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text).rstrip() + "\n"
    return title, intro.split("\n")[0] if intro else "", text


def main():
    OUT.mkdir(exist_ok=True)
    index = ["# Workbook reference", "",
             "One page per workbook: every tab and panel, what it reports, and where its data comes from. Generated "
             "from the workbooks by `src/build_docs.py`. For which workbook to use when, see the "
             "[main README](../README.md).", "", "| Workbook | What it is for |", "|---|---|"]
    for path in sorted(WORKBOOKS.glob("*.workbook.json")):
        title, summary, text = page(path)
        name = path.name.replace(".workbook.json", ".md")
        (OUT / name).write_text(text, encoding="utf-8", newline="\n")
        index.append(f"| [{title}]({name}) | {summary.replace('|', '/')} |")
    (OUT / "README.md").write_text("\n".join(index) + "\n", encoding="utf-8", newline="\n")
    print(f"Wrote {len(index) - 6} pages and the index to {OUT}")


if __name__ == "__main__":
    main()
