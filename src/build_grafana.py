"""Generates the Grafana dashboards from the workbook definition.

Run:  python src/build_grafana.py
Out:  grafana/alz-platform-health.dashboard.json     every tab, one collapsible row each
      grafana/alz-platform-overview.dashboard.json   the Overview tab only

The dashboards are for Azure Monitor dashboards with Grafana (or Azure Managed Grafana) and use the Azure
Monitor data source. They are not written by hand: this script walks the workbook that build_workbook.py
builds and translates each item, so the two stay in step. Change a panel in build_workbook.py, run both
scripts, and commit all three JSON files.

What carries over: Resource Graph and Log Analytics queries (tables, tiles and charts), text, and the
subscription, workspace and name-pattern parameters. What does not: metric charts, because a Grafana metrics
query covers one subscription and region where a workbook chart covers the estate, and Resource Manager
queries, which the data source cannot make. Each row says how many panels it left behind in the workbook.
"""

import json
import pathlib
import re

import build_workbook as wb

OUT_DIR = pathlib.Path(__file__).resolve().parent.parent / "grafana"

DATASOURCE = {"type": "grafana-azure-monitor-datasource", "uid": "${ds}"}
COLUMNS = 24  # Grafana's grid is 24 columns wide

# Workbook status icon -> Grafana colour, and the marker put in front of a tile's name.
COLOURS = {"success": "green", "2": "orange", "4": "red", "unknown": "#808080",
           "Sev0": "dark-red", "Sev1": "red", "Sev2": "orange", "Sev3": "yellow", "Sev4": "blue"}
MARKERS = {"success": "🟢 ", "2": "🟠 ", "4": "🔴 ", "unknown": "⚪ "}

TEXT_PARAMS = ("BuildAgentPattern", "DcPattern", "StoragePattern")
PARAM = re.compile(r"(?<!\$)\{[A-Za-z]+(?::[A-Za-z]+)?\}")  # a workbook {Param}, not a Grafana ${var}


# ---------------------------------------------------------------------------
# Query translation
# ---------------------------------------------------------------------------

def translate(query):
    """Rewrite workbook parameter syntax as Grafana macros and variables."""
    query = re.sub(r"([\w.]+)\s+\{TimeRange\}", r"$__timeFilter(\1)", query)
    query = query.replace("{TimeRange:grain}", "$__interval")
    query = query.replace("{TimeRange:startISO}", "${__from:date:iso}")
    for name in TEXT_PARAMS:
        query = query.replace("{" + name + "}", "${" + name + ":raw}")
    left = PARAM.findall(query)
    if left:
        raise ValueError(f"workbook parameters with no Grafana equivalent: {sorted(set(left))}")
    return query


def target(content, fmt="table"):
    query = translate(content["query"])
    if content["queryType"] == 1:
        return {"refId": "A", "datasource": DATASOURCE, "queryType": "Azure Resource Graph",
                "subscriptions": ["$Subscription"],
                "azureResourceGraph": {"query": query, "resultFormat": "table"}}
    return {"refId": "A", "datasource": DATASOURCE, "queryType": "Azure Log Analytics",
            "azureLogAnalytics": {"query": query, "resultFormat": fmt, "resources": ["$Workspace"],
                                  "dashboardTime": False, "timeColumn": "TimeGenerated"}}


# ---------------------------------------------------------------------------
# Panels
# ---------------------------------------------------------------------------

def text_panel(item):
    md = item["content"]["json"]
    heading = md.startswith("#") and "\n" not in md
    height = 2 if heading else 3 if len(md) < 260 else 4 if len(md) < 520 else 5
    return {"type": "text", "title": "", "transparent": True,
            "options": {"mode": "markdown", "content": md}}, height


def stat_panel(item):
    """Workbook tiles: one stat per row, named by the tile title with a coloured marker for its state."""
    content = item["content"]
    tiles = content["tileSettings"]
    title, value = tiles["titleContent"]["columnMatch"], tiles["rightContent"]["columnMatch"]
    marker = "''"
    left = tiles.get("leftContent", {})
    if left.get("formatter") == 18:
        cases = [f"{left['columnMatch']} == '{t['thresholdValue']}', '{MARKERS.get(t['representation'], '')}'"
                 for t in left["formatOptions"]["thresholdsGrid"] if t["operator"] == "=="]
        if cases:
            marker = "case(" + ", ".join(cases) + ", '')"
    as_text = tiles["rightContent"].get("formatter") == 1
    query = dict(content)
    query["query"] = (content["query"]
                      + f"\n| extend TileName = strcat({marker}, tostring({title}))"
                      + f"\n| project Name = TileName, Value = {'tostring' if as_text else 'todouble'}({value})")
    panel = {
        "type": "stat", "title": content.get("title") or "", "datasource": DATASOURCE, "targets": [target(query)],
        "options": {"reduceOptions": {"values": True, "calcs": ["lastNotNull"], "fields": "/^Value$/", "limit": 60},
                    "textMode": "value_and_name", "colorMode": "none", "graphMode": "none",
                    "justifyMode": "center", "orientation": "auto", "wideLayout": False},
        "fieldConfig": {"defaults": {"noValue": content.get("noDataMessage", "No data")}, "overrides": []},
    }
    return panel, None


def _threshold_steps(grid):
    """Numeric icon thresholds as Grafana steps. The workbook lists the worst state first."""
    rows = [t for t in grid if t["operator"] in (">=", "<")]
    default = next((t for t in grid if t["operator"] == "Default"), None)
    base = COLOURS.get(default["representation"], "green") if default else "green"
    if rows and rows[0]["operator"] == ">=":
        steps = [{"color": base, "value": None}]
        for t in sorted(rows, key=lambda t: float(t["thresholdValue"])):
            steps.append({"color": COLOURS.get(t["representation"], "red"), "value": float(t["thresholdValue"])})
    else:
        # "below X is bad": the lowest band takes the worst colour and each threshold ends a band.
        ordered = sorted(rows, key=lambda t: float(t["thresholdValue"]))
        steps = [{"color": COLOURS.get(ordered[0]["representation"], "red"), "value": None}]
        for band, t in enumerate(ordered):
            colour = COLOURS.get(ordered[band + 1]["representation"], "orange") if band + 1 < len(ordered) else base
            steps.append({"color": colour, "value": float(t["thresholdValue"])})
    # Two thresholds at the same value collapse to the later (worse or final) colour.
    merged = {}
    for step in steps:
        merged[step["value"]] = step
    return list(merged.values())


def _column_properties(formatter):
    kind = formatter.get("formatter")
    props = []
    if kind == 13:  # Azure resource id: show the resource name, link to the portal
        props.append({"id": "mappings", "value": [{"type": "regex", "options": {
            "pattern": "^.*/([^/]+)$", "result": {"index": 0, "text": "$1"}}}]})
        props.append({"id": "links", "value": [{"title": "Open in the Azure portal", "targetBlank": True,
                                                "url": "https://portal.azure.com/#@/resource${__value.raw}"}]})
    elif kind == 7:  # plain URL
        props.append({"id": "links", "value": [{"title": "Open", "targetBlank": True, "url": "${__value.raw}"}]})
    elif kind == 5:
        props.append({"id": "custom.hidden", "value": True})
    elif kind == 18:
        grid = formatter["formatOptions"]["thresholdsGrid"]
        exact = [t for t in grid if t["operator"] == "=="]
        if exact:
            options = {t["thresholdValue"]: {"index": n, "text": t["thresholdValue"],
                                             "color": COLOURS.get(t["representation"], "text")}
                       for n, t in enumerate(exact) if t["representation"] in COLOURS}
            if options:
                props.append({"id": "mappings", "value": [{"type": "value", "options": options}]})
                props.append({"id": "custom.cellOptions", "value": {"type": "color-text"}})
        elif any(t["operator"] in (">=", "<") for t in grid):
            props.append({"id": "thresholds", "value": {"mode": "absolute", "steps": _threshold_steps(grid)}})
            props.append({"id": "custom.cellOptions", "value": {"type": "color-text"}})
    digits = formatter.get("numberFormat", {}).get("options", {}).get("maximumFractionDigits")
    if digits is not None:
        props.append({"id": "decimals", "value": digits})
    return props


def table_panel(item):
    content = item["content"]
    grid = content.get("gridSettings", {})
    by_column = {}
    for formatter in grid.get("formatters", []):
        by_column.setdefault(formatter["columnMatch"], []).extend(_column_properties(formatter))
    for label in grid.get("labelSettings", []):
        by_column.setdefault(label["columnId"], []).append({"id": "displayName", "value": label["label"]})
    overrides = [{"matcher": {"id": "byName", "options": column}, "properties": props}
                 for column, props in by_column.items() if props]
    panel = {
        "type": "table", "title": content.get("title") or "", "datasource": DATASOURCE, "targets": [target(content)],
        "options": {"showHeader": True, "cellHeight": "sm", "footer": {"show": False}},
        "fieldConfig": {"defaults": {"custom": {"filterable": True, "inspect": True},
                                     "noValue": content.get("noDataMessage", "No data")},
                        "overrides": overrides},
    }
    return panel, 9


def chart_panel(item):
    content = item["content"]
    bars = content["visualization"] == "barchart"
    panel = {
        "type": "timeseries", "title": content.get("title") or "", "datasource": DATASOURCE,
        "targets": [target(content, "time_series")],
        "options": {"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
                    "tooltip": {"mode": "multi", "sort": "desc"}},
        "fieldConfig": {"defaults": {
            "custom": {"drawStyle": "bars" if bars else "line", "fillOpacity": 60 if bars else 10,
                       "stacking": {"mode": "normal" if bars else "none", "group": "A"},
                       "showPoints": "never", "lineWidth": 1},
            "noValue": content.get("noDataMessage", "No data")}, "overrides": []},
    }
    if content["queryType"] == 1:
        # Resource Graph only returns tables; this turns time + label + value rows into one series per label.
        panel["transformations"] = [{"id": "prepareTimeSeries", "options": {"format": "multi"}}]
    return panel, 8


def query_panel(item):
    vis = item["content"].get("visualization", "table")
    if vis == "tiles":
        return stat_panel(item)
    if vis in ("timechart", "barchart"):
        return chart_panel(item)
    return table_panel(item)


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def width_of(item):
    px = item.get("styleSettings", {}).get("maxWidth", "")
    if px.endswith("px"):  # fixed tile slots in the workbook
        return 3 if int(px[:-2]) < 300 else 6
    pct = int(item.get("customWidth") or 0)
    return max(3, round(pct * COLUMNS / 100)) if pct else COLUMNS


class Layout:
    """Places panels left to right, wrapping at the grid edge, the way workbook items flow."""

    def __init__(self, ids, y=0):
        self.ids, self.x, self.y, self.row_height, self.panels = ids, 0, y, 0, []

    def newline(self):
        self.y += self.row_height
        self.x = self.row_height = 0

    def add(self, panel, width, height):
        if self.x + width > COLUMNS:
            self.newline()
        panel.update({"id": next(self.ids), "gridPos": {"h": height, "w": width, "x": self.x, "y": self.y}})
        self.panels.append(panel)
        self.x += width
        self.row_height = max(self.row_height, height)
        return panel


def hidden_without_workspace(item):
    return item.get("conditionalVisibility") == wb.WORKSPACE_UNSET


def tab_sections(group):
    """Split a tab into its own items and any load-on-demand groups nested in it (name, title, items)."""
    main, nested = [], []
    for item in group["content"]["items"]:
        if item["type"] == 12:
            nested.append((item["name"], item["content"].get("loadButtonText", item["name"]), item["content"]["items"]))
        else:
            main.append(item)
    return main, nested


def place(items, layout):
    """Translate workbook items into panels. Returns how many metric and Resource Manager items were left out."""
    metrics = resource_manager = 0
    for item in items:
        kind = item["type"]
        if kind == 1 and not hidden_without_workspace(item):
            panel, height = text_panel(item)
            layout.add(panel, COLUMNS, height)
        elif kind == 10:
            metrics += 1
        elif kind == 3 and item["content"]["queryType"] == 12:
            resource_manager += 1
        elif kind == 3:
            panel, height = query_panel(item)
            width = width_of(item)
            layout.add(panel, width, height or (4 if width <= 6 else 6))
    layout.newline()
    if metrics or resource_manager:
        parts = ([f"{metrics} metric chart{'s' if metrics != 1 else ''}"] if metrics else []) + \
                ([f"{resource_manager} Resource Manager panel{'s' if resource_manager != 1 else ''}"] if resource_manager else [])
        note = (f"**Not shown here:** {' and '.join(parts)} from this tab of the workbook. A Grafana metrics query "
                "covers one subscription and region, and the data source cannot call Resource Manager; open the "
                "workbook for these.")
        layout.add({"type": "text", "title": "", "transparent": True,
                    "options": {"mode": "markdown", "content": note}}, COLUMNS, 2)
        layout.newline()


def row(title, ids, y, collapsed, items):
    """A Grafana row and its panels. A collapsed row holds its panels and loads them only when opened."""
    header = {"type": "row", "title": title, "collapsed": collapsed, "id": next(ids),
              "gridPos": {"h": 1, "w": COLUMNS, "x": 0, "y": y}, "panels": []}
    layout = Layout(ids, y + 1)
    place(items, layout)
    if collapsed:
        header["panels"] = layout.panels
        return [header], y + 1
    return [header] + layout.panels, layout.y


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def variables(workbook):
    def query_variable(name, label, query, multi, include_all=False):
        return {"name": name, "label": label, "type": "query", "datasource": DATASOURCE, "query": query,
                "definition": query["queryType"], "multi": multi, "includeAll": include_all, "refresh": 1,
                "sort": 1, "current": {"text": "All", "value": "$__all"} if include_all else {}, "options": []}

    listed = [
        {"name": "ds", "label": "Data source", "type": "datasource", "query": "grafana-azure-monitor-datasource",
         "current": {}, "options": [], "refresh": 1},
        query_variable("Subscription", "Subscriptions", {"queryType": "Azure Subscriptions", "refId": "A"},
                       multi=True, include_all=True),
        # The data source lists workspaces one subscription at a time, so the workspace picker has its own.
        query_variable("WorkspaceSubscription", "Workspace subscription",
                       {"queryType": "Azure Subscriptions", "refId": "A"}, multi=False),
        query_variable("Workspace", "Log Analytics workspace",
                       {"queryType": "Azure Workspaces", "refId": "A", "subscription": "$WorkspaceSubscription"},
                       multi=True),
    ]
    params = next(i for i in workbook["items"] if i["name"] == "global-params")["content"]["parameters"]
    for p in params:
        if p["name"] in TEXT_PARAMS:
            listed.append({"name": p["name"], "label": p["label"], "type": "textbox", "query": p["value"],
                           "current": {"text": p["value"], "value": p["value"]},
                           "options": [{"text": p["value"], "value": p["value"], "selected": True}],
                           "description": p.get("description", "")})
    return listed


def dashboard(uid, title, description, only_tab=None):
    workbook = wb.workbook()
    labels = dict(wb.TABS)
    ids = iter(range(1, 100000))
    intro = Layout(ids)
    intro.add({"type": "text", "title": "", "transparent": True, "options": {"mode": "markdown", "content":
               f"# {title}\n{description} Generated from the Azure Monitor workbook in this repository by "
               "`src/build_grafana.py`: change it there, not here."}}, COLUMNS, 3)
    intro.newline()
    panels, y = intro.panels, intro.y

    for group in (i for i in workbook["items"] if i["type"] == 12):
        key = group["conditionalVisibility"]["value"]
        if only_tab and key != only_tab:
            continue
        main, nested = tab_sections(group)
        if only_tab:
            layout = Layout(ids, y)
            place(main, layout)
            panels, y = panels + layout.panels, layout.y
        else:
            added, y = row(labels[key], ids, y, key != "overview", main)
            panels += added
        for _, button, items in nested:
            # The workbook's button says "Show ..."; a row title just names what is in it.
            subject = button[5:] if button.startswith("Show ") else button
            title_ = subject[0].upper() + subject[1:] if only_tab else f"{labels[key]}: {subject}"
            added, y = row(title_, ids, y, True, items)
            panels += added

    return {
        "uid": uid, "title": title, "description": description, "tags": ["alz-platform-health"],
        "schemaVersion": 39, "version": 1, "editable": True, "graphTooltip": 1, "refresh": "", "timezone": "browser",
        "time": {"from": "now-24h", "to": "now"}, "annotations": {"list": []}, "links": [],
        "templating": {"list": variables(workbook)}, "panels": panels,
    }


DASHBOARDS = [
    ("alz-platform-health.dashboard.json", "alz-platform-health", "Enterprise Scale Platform Health",
     "Health and governance of the shared platform, one row per workbook tab.", None),
    ("alz-platform-overview.dashboard.json", "alz-platform-overview", "Enterprise Scale Platform Overview",
     "The Overview of the platform health workbook: issues, at-a-glance tiles and resources needing attention.",
     "overview"),
]


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for filename, uid, title, description, only_tab in DASHBOARDS:
        out = OUT_DIR / filename
        out.write_text(json.dumps(dashboard(uid, title, description, only_tab), indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8", newline="\n")
        print(f"Wrote {out}")


if __name__ == "__main__":
    main()
