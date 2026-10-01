"""
report_gen.py — FilterGuardian Report Generator
================================================
Produces self-contained HTML reports from the collected database.
No external dependencies — all charts use inline CSS, no matplotlib.
"""

import csv
import io
import database
from datetime import datetime
from collections import defaultdict
from urllib.parse import urlparse


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now().strftime("%B %d, %Y")

def _period() -> str:
    return datetime.now().strftime("%B %d, %Y at %I:%M %p")

def _domain(url: str) -> str:
    try:
        return urlparse(url or "").netloc.lower()
    except Exception:
        return ""

def _css_bar(pct: float, color: str, height: int = 16) -> str:
    pct = max(0.0, min(100.0, pct))
    return (
        f'<div style="background:#e5e7eb;border-radius:3px;height:{height}px;'
        f'flex:1;min-width:80px">'
        f'<div style="background:{color};border-radius:3px;height:{height}px;'
        f'width:{pct:.1f}%"></div></div>'
    )

def _table_rows(items: list, total: int, color: str) -> str:
    if not items:
        return ('<tr><td colspan="3" style="padding:12px;color:#6b7280;'
                'font-style:italic">No data yet.</td></tr>')
    out = []
    for name, count in items:
        pct = (count / total * 100) if total else 0
        out.append(
            f'<tr>'
            f'<td style="padding:8px 12px;white-space:nowrap">{name}</td>'
            f'<td style="padding:8px 12px;text-align:right;font-weight:600">{count:,}</td>'
            f'<td style="padding:8px 12px;min-width:160px">'
            f'<div style="display:flex;align-items:center;gap:8px">'
            f'{_css_bar(pct, color)}'
            f'<span style="min-width:44px;text-align:right;color:#6b7280;font-size:12px">'
            f'{pct:.1f}%</span></div></td></tr>'
        )
    return "".join(out)


_BASE_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',Arial,sans-serif;background:#f3f4f6;color:#111827;font-size:14px;line-height:1.5}
@media print{body{background:white}.no-print{display:none!important}
  .card{box-shadow:none!important;border:1px solid #e5e7eb!important}
  .page-break{page-break-before:always}}
.header{background:#1e293b;color:white;padding:36px 56px}
.header h1{font-size:24px;font-weight:700;letter-spacing:-.3px;margin-top:8px}
.header .sub{color:#94a3b8;font-size:13px;margin-top:6px}
.badge{display:inline-block;padding:3px 12px;border-radius:4px;font-size:11px;
  font-weight:700;text-transform:uppercase;letter-spacing:1px}
.wrap{max-width:960px;margin:0 auto;padding:32px 40px 60px}
.section{margin-bottom:28px}
.sec-title{font-size:15px;font-weight:700;color:#1e293b;border-bottom:2px solid #e5e7eb;
  padding-bottom:8px;margin-bottom:14px}
.card{background:white;border-radius:10px;padding:20px 24px;box-shadow:0 1px 4px rgba(0,0,0,.08)}
.metric-grid{display:grid;gap:14px}
.metric{background:white;border-radius:10px;padding:20px;
  box-shadow:0 1px 4px rgba(0,0,0,.08);text-align:center}
.metric .val{font-size:40px;font-weight:800;line-height:1}
.metric .lbl{font-size:11px;color:#6b7280;margin-top:6px;text-transform:uppercase;letter-spacing:.5px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{background:#f9fafb;color:#6b7280;text-align:left;padding:8px 12px;font-size:11px;
  font-weight:700;text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid #e5e7eb}
td{border-bottom:1px solid #f3f4f6;vertical-align:middle}
tr:last-child td{border-bottom:none}
.timeline{display:flex;align-items:flex-end;gap:2px;height:72px;padding:0 2px}
.tbar{flex:1;border-radius:2px 2px 0 0;min-height:2px;background:#3b82f6}
.tbar:hover{opacity:.8}
.callout{border-left:5px solid;border-radius:0 8px 8px 0;padding:18px 22px;margin-bottom:0}
.para{line-height:1.75;color:#374151}
.footer{text-align:center;color:#9ca3af;font-size:11px;
  padding:24px 0;border-top:1px solid #e5e7eb;margin-top:32px}
ul li{margin-bottom:6px}
"""


# ── Executive Report ──────────────────────────────────────────────────────────

def generate_executive_report() -> str:
    stats       = database.get_stats()
    categories  = database.get_category_breakdown()
    platforms   = database.get_platform_breakdown()
    timeline    = database.get_timeline()
    top_sites   = database.get_top_site_names()
    proxy_techs = database.get_proxy_tech_breakdown()
    ft          = database.get_filter_summary()

    total    = stats["total"]
    analyzed = stats["analyzed"]
    pending  = stats["pending"]

    proxy_count  = next((c for n, c in categories if "proxy"  in n.lower()), 0)
    gaming_count = next((c for n, c in categories if "gaming" in n.lower()), 0)

    # Risk level
    bypass_pct   = (ft["allowed"] / ft["total"] * 100) if ft["total"] else 0
    risk_level   = "HIGH" if ft["allowed"] > 50 or bypass_pct > 50 else \
                   "MEDIUM" if ft["allowed"] > 10 or bypass_pct > 20 else "LOW"
    risk_color   = {"HIGH": "#dc2626", "MEDIUM": "#d97706", "LOW": "#16a34a"}[risk_level]

    # Unique proxy domains
    all_rows = database.get_all_urls()
    proxy_rows = [r for r in all_rows if (r[3] or "").lower().startswith("proxy")]
    unique_proxy_domains = len({_domain(r[6]) for r in proxy_rows if r[6]})

    # Timeline bars
    tl_max  = max((c for _, c in timeline), default=1)
    tl_bars = "".join(
        f'<div class="tbar" style="height:{max(2, int(c/tl_max*68))}px" '
        f'title="{d}: {c}"></div>'
        for d, c in timeline
    )
    tl_labels = ""
    if timeline:
        tl_labels = (
            f'<div style="display:flex;justify-content:space-between;'
            f'color:#9ca3af;font-size:10px;margin-top:4px">'
            f'<span>{timeline[0][0]}</span><span>{timeline[-1][0]}</span></div>'
        )

    cat_rows  = _table_rows(categories,  analyzed or 1, "#3b82f6")
    plat_rows = _table_rows(platforms,   analyzed or 1, "#8b5cf6")
    tech_rows = _table_rows(proxy_techs, analyzed or 1, "#ef4444")

    site_rows = "".join(
        f'<tr>'
        f'<td style="padding:7px 12px">{i+1}. {name}</td>'
        f'<td style="padding:7px 12px;text-align:right;font-weight:600">{count:,}</td>'
        f'</tr>'
        for i, (name, count) in enumerate(top_sites)
    )

    # Filter test callout
    if ft["total"] > 0:
        ft_last = f'Last tested: {ft["last_tested"][:16] if ft["last_tested"] else "unknown"}'
        ft_callout = f"""
<div class="section">
  <h2 class="sec-title">Network Filter Test Results</h2>
  <div class="callout" style="background:#fef2f2;border-color:#ef4444">
    <div style="display:flex;align-items:center;gap:32px;flex-wrap:wrap">
      <div style="text-align:center">
        <div style="font-size:52px;font-weight:800;color:#dc2626;line-height:1">{ft["allowed"]:,}</div>
        <div style="font-size:12px;color:#6b7280;text-transform:uppercase;letter-spacing:.5px;margin-top:4px">
          URLs Bypassed Filter</div>
      </div>
      <div style="flex:1;min-width:200px">
        <p class="para"><strong>{ft["allowed"]:,} of {ft["total"]:,} tested URLs
        ({bypass_pct:.0f}%) passed through Network Filter unblocked.</strong>
        {f"{ft['blocked']:,} were correctly blocked." if ft["blocked"] else ""}
        These sites are actively accessible to users on the network
        and represent the highest-priority targets for blocking.
        </p>
        <p style="color:#9ca3af;font-size:12px;margin-top:8px">
          {ft_last} &nbsp;·&nbsp; {ft["sessions"]} test session(s)</p>
      </div>
    </div>
  </div>
</div>"""
    else:
        ft_callout = """
<div class="section">
  <h2 class="sec-title">Network Filter Test Results</h2>
  <div class="card">
    <p class="para" style="color:#6b7280">
      No filter test data yet. Run a filter test from the Database page
      (requires the relay agent or a proxy address on the target network)
      to see which URLs are actively bypassing Network Filter.
    </p>
  </div>
</div>"""

    # Executive summary paragraph
    summary_para = (
        f'FilterGuardian has catalogued <strong>{total:,} URLs</strong> from monitored '
        f'Discord channels, of which <strong>{analyzed:,} have been fully analyzed</strong>. '
        f'The system identified <strong>{proxy_count:,} filter bypass proxies</strong> and '
        f'<strong>{gaming_count:,} unblocked gaming sites</strong> across '
        f'<strong>{unique_proxy_domains:,} unique domains</strong>. '
        + (f'A network filter test confirmed <strong style="color:#dc2626">{ft["allowed"]:,} '
           f'URLs ({bypass_pct:.0f}%) are currently bypassing Network Filter</strong>. '
           if ft["total"] > 0 else "")
        + f'Current bypass risk is rated '
        f'<strong style="color:{risk_color}">{risk_level}</strong>.'
    )

    top_sites_section = ""
    if top_sites:
        top_sites_section = f"""
<div class="section">
  <h2 class="sec-title">Most Frequently Shared Sites</h2>
  <div class="card">
    <table><thead><tr>
      <th>Site Name</th><th style="text-align:right">URLs Collected</th>
    </tr></thead><tbody>{site_rows}</tbody></table>
  </div>
</div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8">
<title>FilterGuardian Executive Report — {_now()}</title>
<style>{_BASE_CSS}</style>
</head>
<body>
<div class="header">
  <div class="badge" style="background:#3b82f6">Executive Report</div>
  <h1>FilterGuardian — Bypass Traffic Intelligence</h1>
  <div class="sub">Prepared {_period()} &nbsp;·&nbsp; Confidential — For Internal Distribution</div>
</div>

<div class="wrap">

<div class="section">
  <h2 class="sec-title">Executive Summary</h2>
  <div class="card"><p class="para">{summary_para}</p></div>
</div>

<div class="section">
  <h2 class="sec-title">Key Metrics</h2>
  <div class="metric-grid" style="grid-template-columns:repeat(4,1fr)">
    <div class="metric">
      <div class="val" style="color:#3b82f6">{total:,}</div>
      <div class="lbl">URLs Tracked</div>
    </div>
    <div class="metric">
      <div class="val" style="color:#16a34a">{analyzed:,}</div>
      <div class="lbl">Analyzed</div>
    </div>
    <div class="metric">
      <div class="val" style="color:#dc2626">{proxy_count:,}</div>
      <div class="lbl">Bypass Proxies Found</div>
    </div>
    <div class="metric">
      <div class="val" style="color:{risk_color}">{ft["allowed"] if ft["total"] else "—"}</div>
      <div class="lbl">Confirmed Bypassing</div>
    </div>
  </div>
</div>

{ft_callout}

<div class="section">
  <h2 class="sec-title">30-Day Discovery Timeline</h2>
  <div class="card">
    <div class="timeline">{tl_bars or '<span style="color:#6b7280;font-size:13px">No timeline data yet.</span>'}</div>
    {tl_labels}
  </div>
</div>

<div class="section">
  <h2 class="sec-title">Content Category Breakdown</h2>
  <div class="card">
    <table><thead><tr>
      <th>Category</th><th style="text-align:right">Count</th><th>Distribution</th>
    </tr></thead><tbody>{cat_rows}</tbody></table>
  </div>
</div>

<div class="section">
  <h2 class="sec-title">Proxy Technologies in Use</h2>
  <div class="card">
    <p class="para" style="margin-bottom:14px;font-size:13px;color:#6b7280">
      These bypass frameworks use service workers and WASM tunnels to route
      traffic past Network Filter. Each has distinct network signatures that
      Network Filter's engineering team can target for detection.
    </p>
    <table><thead><tr>
      <th>Framework</th><th style="text-align:right">Detections</th><th>Share</th>
    </tr></thead><tbody>{tech_rows}</tbody></table>
  </div>
</div>

<div class="section">
  <h2 class="sec-title">Hosting Platform Analysis</h2>
  <div class="card">
    <p class="para" style="margin-bottom:14px;font-size:13px;color:#6b7280">
      Bypass sites are predominantly hosted on free cloud platforms, making
      individual URL blocking ineffective — new instances spin up in minutes.
    </p>
    <table><thead><tr>
      <th>Platform</th><th style="text-align:right">Sites</th><th>Distribution</th>
    </tr></thead><tbody>{plat_rows}</tbody></table>
  </div>
</div>

{top_sites_section}

<div class="section">
  <h2 class="sec-title">Recommendations</h2>
  <div class="card">
    <ul style="padding-left:20px;line-height:1">
      <li>Submit the <strong>Network Filter Submission Report</strong> to your Network Filter
          account team — it contains domain lists and proxy tech data in their preferred format.</li>
      <li>Request Network Filter enable <strong>service worker interception</strong> and
          <strong>WASM execution blocking</strong> to neutralize Ultraviolet/Scramjet-class proxies.</li>
      <li>Consider blocking entire free-hosting platforms (Cloudflare Pages, Vercel, Netlify,
          Glitch, Render) by category rather than by individual URL.</li>
      <li>Re-run the <strong>Filter Test</strong> from inside the target network after each
          Network Filter update to verify the new blocking is effective.</li>
      <li>Monitor Discord channels continuously — new bypass links are shared within hours
          of existing ones being blocked.</li>
    </ul>
  </div>
</div>

<div class="footer no-print">
  Generated by FilterGuardian &nbsp;·&nbsp; {_now()} &nbsp;·&nbsp;
  Use browser <strong>Print → Save as PDF</strong> to create a shareable copy.
</div>

</div>
</body>
</html>"""


# ── Network Filter Submission Report ──────────────────────────────────────────

def generate_filter_report() -> tuple:
    """Returns (html_str, csv_str)."""

    all_rows    = database.get_all_urls()
    analyzed    = [r for r in all_rows if r[1] in ("analyzed", "reviewed")]
    proxy_rows  = [r for r in analyzed  if (r[3] or "").lower().startswith("proxy")]
    ft          = database.get_filter_summary()
    bypassing   = database.get_bypassing_urls()

    # Domain groupings from proxy rows
    domain_map: dict = defaultdict(list)
    for row in proxy_rows:
        d = _domain(row[6])
        if d:
            domain_map[d].append(row)

    # Also add bypassing URL domains even if not classified as proxy
    for url, site, method, ts in bypassing:
        d = _domain(url)
        if d and d not in domain_map:
            domain_map[d].append((None, "analyzed", site, "", "", "", url, "", ts))

    proxy_domains = sorted(domain_map.keys(), key=lambda d: -len(domain_map[d]))

    # Tech breakdown
    tech_counts: dict = defaultdict(int)
    for r in proxy_rows:
        if r[5]:
            tech_counts[r[5]] += 1

    bypass_pct = (ft["allowed"] / ft["total"] * 100) if ft["total"] else 0

    # ── CSV ──────────────────────────────────────────────────────────────────
    buf = io.StringIO()
    w   = csv.writer(buf)
    w.writerow(["Domain", "Example URL", "Site Name", "Category",
                "Proxy Technology", "Platform", "Bypasses Filter", "First Seen"])
    # Track which domains had a bypass
    bypassing_domains = {_domain(u) for u, *_ in bypassing}
    for domain in proxy_domains:
        rep   = domain_map[domain][0]
        w.writerow([
            domain,
            rep[6] or "",
            rep[2] or "",
            rep[3] or "",
            rep[5] or "",
            rep[4] or "",
            "YES" if domain in bypassing_domains else "Not tested",
            rep[8] or "",
        ])
    csv_str = buf.getvalue()

    # ── HTML sections ─────────────────────────────────────────────────────
    tech_rows_html = "".join(
        f'<tr>'
        f'<td style="padding:8px 12px;font-weight:600">{tech}</td>'
        f'<td style="padding:8px 12px;text-align:right">{cnt:,}</td>'
        f'<td style="padding:8px 12px;font-size:12px;color:#6b7280">'
        f'{_TECH_DESC.get(tech, "Custom/unknown proxy framework")}</td>'
        f'</tr>'
        for tech, cnt in sorted(tech_counts.items(), key=lambda x: -x[1])
    ) or ('<tr><td colspan="3" style="padding:12px;color:#6b7280;font-style:italic">'
          'No proxy technology detected yet.</td></tr>')

    domain_rows_html = "".join(
        f'<tr>'
        f'<td style="padding:6px 12px;font-family:monospace;font-size:12px">{d}</td>'
        f'<td style="padding:6px 12px;text-align:right">{len(domain_map[d])}</td>'
        f'<td style="padding:6px 12px;font-size:12px">'
        f'{"<span style=\'color:#dc2626;font-weight:600\'>⚠ Bypasses filter</span>" if d in bypassing_domains else "Not yet tested"}'
        f'</td></tr>'
        for d in proxy_domains[:120]
    ) or ('<tr><td colspan="3" style="padding:12px;color:#6b7280;font-style:italic">'
          'No proxy domains identified yet.</td></tr>')

    url_rows_html = "".join(
        f'<tr>'
        f'<td style="padding:5px 10px;font-family:monospace;font-size:11px;max-width:300px;'
        f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="{r[6]}">{r[6]}</td>'
        f'<td style="padding:5px 10px;font-size:12px">{r[2] or "—"}</td>'
        f'<td style="padding:5px 10px;font-size:12px">{r[5] or "—"}</td>'
        f'<td style="padding:5px 10px;font-size:12px">{r[8] or "—"}</td>'
        f'</tr>'
        for r in proxy_rows[:500]
    ) or ('<tr><td colspan="4" style="padding:12px;color:#6b7280;font-style:italic">'
          'No bypass proxy URLs in database yet.</td></tr>')

    more_note = (
        f'<tr><td colspan="4" style="padding:10px 12px;color:#6b7280;font-style:italic">'
        f'… and {len(proxy_rows)-500:,} more — see the exported CSV for the full list.</td></tr>'
        if len(proxy_rows) > 500 else ""
    )

    # Filter test section
    if ft["total"] > 0:
        bypass_rows_html = "".join(
            f'<tr>'
            f'<td style="padding:5px 10px;font-family:monospace;font-size:11px;'
            f'max-width:340px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" '
            f'title="{url}">{url}</td>'
            f'<td style="padding:5px 10px;font-size:12px">{site or "—"}</td>'
            f'<td style="padding:5px 10px;font-size:12px">{method}</td>'
            f'<td style="padding:5px 10px;font-size:12px">{(ts or "")[:16]}</td>'
            f'</tr>'
            for url, site, method, ts in bypassing[:300]
        ) or ('<tr><td colspan="4" style="padding:12px;color:#6b7280">None.</td></tr>')

        ft_section = f"""
<div class="section page-break">
  <h2 class="sec-title">Confirmed Bypass URLs (Filter Test Results)</h2>
  <div class="callout" style="background:#fef2f2;border-color:#ef4444;margin-bottom:16px">
    <strong style="color:#dc2626">{ft["allowed"]:,} of {ft["total"]:,} tested URLs
    ({bypass_pct:.0f}%) bypassed Network Filter</strong> as of
    {(ft["last_tested"] or "")[:16]}.
    These URLs were fetched from inside the target network via the relay agent
    and returned a 200 OK response without being intercepted by the filter.
    They are the highest-priority candidates for immediate blocking.
  </div>
  <div class="card" style="overflow-x:auto">
    <table><thead><tr>
      <th>URL</th><th>Site Name</th><th>Test Method</th><th>Tested At</th>
    </tr></thead><tbody>
    {bypass_rows_html}
    {'<tr><td colspan="4" style="padding:8px 12px;color:#6b7280;font-style:italic">'
     f'… and {len(bypassing)-300:,} more — see CSV export.</td></tr>'
     if len(bypassing) > 300 else ""}
    </tbody></table>
  </div>
</div>"""
    else:
        ft_section = """
<div class="section">
  <h2 class="sec-title">Confirmed Bypass URLs (Filter Test Results)</h2>
  <div class="card">
    <p class="para" style="color:#6b7280">
      No filter test data yet. Run a filter test from the FilterGuardian Database page
      using the relay agent on the target network to confirm which URLs pass through.
    </p>
  </div>
</div>"""

    ck_css = _BASE_CSS + ".header{background:#7f1d1d}.badge{background:#ef4444}"

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8">
<title>FilterGuardian — Network Filter Submission — {_now()}</title>
<style>{ck_css}</style>
</head>
<body>
<div class="header">
  <div class="badge">Network Filter Submission</div>
  <h1>FilterGuardian — Filter Bypass Intelligence Report</h1>
  <div class="sub">Prepared {_period()} &nbsp;·&nbsp;
  Submit to Network Filter support to improve category coverage and detection rules</div>
</div>

<div class="wrap">

<div class="section">
  <h2 class="sec-title">Purpose of This Report</h2>
  <div class="card">
    <p class="para">
      This report was generated by FilterGuardian, a tool that monitors Discord channels
      used by users to share filter bypass sites. The URLs and domains listed below were
      collected from active configured sources and confirmed to circumvent
      Network Filter filtering. This report is submitted to request:
    </p>
    <ul style="padding-left:20px;margin-top:12px">
      <li>Addition of identified domains to the <strong>Proxy / Anonymizer</strong> category</li>
      <li>Pattern-based detection rules for the proxy frameworks listed in Section 3</li>
      <li>Review of hosting platform sub-domain coverage (Cloudflare Pages, Vercel, Render, etc.)</li>
    </ul>
  </div>
</div>

<div class="section">
  <h2 class="sec-title">Summary</h2>
  <div class="metric-grid" style="grid-template-columns:repeat(3,1fr)">
    <div class="metric">
      <div class="val" style="color:#dc2626">{len(proxy_rows):,}</div>
      <div class="lbl">Bypass URLs Found</div>
    </div>
    <div class="metric">
      <div class="val" style="color:#d97706">{len(proxy_domains):,}</div>
      <div class="lbl">Unique Domains</div>
    </div>
    <div class="metric">
      <div class="val" style="color:#dc2626">{ft["allowed"] if ft["total"] else "—"}</div>
      <div class="lbl">Confirmed Bypassing</div>
    </div>
  </div>
</div>

{ft_section}

<div class="section">
  <h2 class="sec-title">Proxy Framework Breakdown</h2>
  <div class="card">
    <table><thead><tr>
      <th>Framework</th><th style="text-align:right">Count</th><th>Description</th>
    </tr></thead><tbody>{tech_rows_html}</tbody></table>
  </div>
</div>

<div class="section">
  <h2 class="sec-title">Domains Requiring Categorization</h2>
  <div class="card" style="overflow-x:auto">
    <p class="para" style="margin-bottom:14px;font-size:13px;color:#6b7280">
      The following domains host confirmed filter bypass proxies. The accompanying
      CSV export contains the complete list with proxy technology and platform metadata.
    </p>
    <table><thead><tr>
      <th>Domain</th><th style="text-align:right">URLs</th><th>Filter Test</th>
    </tr></thead><tbody>{domain_rows_html}</tbody></table>
  </div>
</div>

<div class="section page-break">
  <h2 class="sec-title">Bypass Proxy URL List</h2>
  <div class="card" style="overflow-x:auto">
    <table><thead><tr>
      <th>URL</th><th>Site Name</th><th>Proxy Tech</th><th>First Seen</th>
    </tr></thead><tbody>{url_rows_html}{more_note}</tbody></table>
  </div>
</div>

<div class="footer no-print">
  Generated by FilterGuardian &nbsp;·&nbsp; {_now()} &nbsp;·&nbsp;
  A CSV file was saved alongside this report for direct import.
  Use <strong>Print → Save as PDF</strong> to share with Network Filter support.
</div>

</div>
</body>
</html>""", csv_str


# ── Proxy technology descriptions (for Network Filter's engineering team) ──────

_TECH_DESC = {
    "Ultraviolet":       "Service-worker proxy; rewrites all URLs via a /uv/ path prefix",
    "Rammerhead":        "Browser-in-browser proxy using session ID obfuscation",
    "Scramjet":          "WASM-accelerated service-worker rewriter; successor to UV",
    "Bare Server":       "Transport layer used by UV/Scramjet to forward HTTPS requests",
    "Corrosion":         "Node.js HTTP proxy framework",
    "Interstellar":      "Ultraviolet-based bundle with custom themed UI",
    "Holy Unblocker":    "All-in-one proxy portal with UV and Rammerhead backends",
    "Epoxy":             "WASM TCP/TLS proxy — bypasses at transport layer, not HTTP",
    "Aero":              "Lightweight service-worker proxy framework",
    "Alloy":             "Simple JavaScript rewriting proxy",
    "NodeUnblocker":     "Server-side Node.js HTTP proxy (no service worker)",
    "Titanium Network":  "Organization maintaining Ultraviolet and related tools",
    "Meteor":            "Custom service-worker proxy framework",
    "Palladium":         "Lightweight proxy framework",
    "Womginx":           "nginx-based reverse web proxy",
    "Dynamic Intercept": "Custom dynamic request interception proxy",
    "Terbium":           "Custom service-worker proxy",
}
