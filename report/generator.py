"""HTML report generation."""
import os
from typing import Any, Dict, List, Optional


def _html_header(title: str) -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 40px; background: #f8f9fa; }}
h1 {{ color: #333; border-bottom: 2px solid #007bff; padding-bottom: 10px; }}
h2 {{ color: #555; margin-top: 30px; }}
table {{ border-collapse: collapse; width: 100%; margin: 15px 0; background: white; }}
th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: right; }}
th {{ background: #007bff; color: white; }}
tr:nth-child(even) {{ background: #f2f2f2; }}
.metric-good {{ color: #28a745; }}
.metric-warn {{ color: #ffc107; }}
.metric-bad {{ color: #dc3545; }}
img {{ max-width: 100%; margin: 10px 0; border: 1px solid #ddd; }}
.summary {{ background: white; padding: 20px; border-radius: 8px; border-left: 4px solid #007bff; margin: 20px 0; }}
</style>
</head>
<body>
"""


def _html_footer() -> str:
    return "</body></html>"


def _results_table(results: List[Dict]) -> str:
    """Generate HTML table from step-up results."""
    rows = ""
    for r in results:
        iperf = r.get("iperf_rows", [{}])
        avg_bps = sum(row.get("bits_per_second", 0) for row in iperf) / max(len(iperf), 1)
        avg_retrans = sum(row.get("retransmits", 0) for row in iperf) / max(len(iperf), 1)
        avg_loss = sum(row.get("lost_percent", 0) for row in iperf) / max(len(iperf), 1)

        rows += f"""<tr>
<td style="text-align:left">{r['label']}</td>
<td>{avg_bps/1e6:.1f}</td>
<td>{r.get('avg_rtt', 0):.1f}</td>
<td>{avg_retrans:.0f}</td>
<td>{avg_loss:.1f}</td>
<td>{r.get('ping_samples', 0)}</td>
</tr>"""

    return f"""<table>
<tr><th>Test</th><th>Throughput (Mbps)</th><th>Avg RTT (ms)</th><th>Retransmits</th><th>Loss %</th><th>Ping Samples</th></tr>
{rows}
</table>"""


def generate_step_up_report(
    results: List[Dict],
    output_dir: str,
    chart_paths: Optional[List[str]] = None,
) -> str:
    """Generate Phase 1 intermediate HTML report."""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "step_up_report.html")

    html = _html_header("Bandwidth Checker — Step-Up Report")
    html += "<h1>Phase 1: Step-Up Pressure Test Report</h1>\n"

    html += '<div class="summary">\n'
    html += "<h2>Test Summary</h2>\n"
    html += f"<p>Total tests run: {len(results)}</p>\n"
    html += "</div>\n"

    html += "<h2>Per-Test Results</h2>\n"
    html += _results_table(results)

    if chart_paths:
        html += "<h2>Charts</h2>\n"
        for cp in chart_paths:
            name = os.path.basename(cp)
            rel_path = os.path.relpath(cp, output_dir)
            html += f'<h3>{name.replace(".png", "").replace("_", " ").title()}</h3>\n'
            html += f'<img src="{rel_path}" alt="{name}">\n'

    html += _html_footer()

    with open(path, "w") as f:
        f.write(html)
    return path


def generate_final_report(
    step_up_results: List[Dict],
    sustained_results: Dict,
    throttled_results: Dict,
    output_dir: str,
    chart_paths: Optional[List[str]] = None,
) -> str:
    """Generate final comprehensive HTML report."""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "final_report.html")

    html = _html_header("Bandwidth Checker — Final Report")
    html += "<h1>AWS EC2 Bandwidth Test — Final Report</h1>\n"

    html += "<h2>Phase 1: Step-Up Pressure Test</h2>\n"
    html += _results_table(step_up_results)

    html += "<h2>Phase 2: Sustained Full-Load</h2>\n"
    html += '<div class="summary">\n'
    depl_time = sustained_results.get("depletion_time_sec")
    if depl_time:
        html += f"<p><strong>Credit depletion detected at:</strong> {depl_time:.0f} seconds</p>\n"
    else:
        html += "<p>Credit depletion was not detected during the test window.</p>\n"
    html += f"<p>Total elapsed: {sustained_results.get('total_elapsed_sec', 0):.0f} seconds</p>\n"
    html += "</div>\n"

    html += "<h2>Phase 3: Throttled State Observation</h2>\n"
    html += '<div class="summary">\n'
    html += f"<p>Steady-state TCP samples: {throttled_results.get('steady_tcp_rows', 0)}</p>\n"
    html += f"<p>Steady-state UDP samples: {throttled_results.get('steady_udp_rows', 0)}</p>\n"
    mini = throttled_results.get("mini_levels_tested", [])
    if mini:
        html += f"<p>Mini step-up levels tested: {', '.join(str(m) for m in mini)} Mbps</p>\n"
    html += "</div>\n"

    html += "<h2>Business Impact Assessment</h2>\n"
    html += '<div class="summary">\n'
    html += "<p><em>Based on test data — review with network and blockchain domain knowledge.</em></p>\n"
    if depl_time:
        html += f"<p>Network burst credits last approximately <strong>{depl_time/60:.0f} minutes</strong> under full load.</p>\n"
    html += "</div>\n"

    if chart_paths:
        html += "<h2>Charts</h2>\n"
        for cp in chart_paths:
            name = os.path.basename(cp)
            rel_path = os.path.relpath(cp, output_dir)
            html += f'<h3>{name.replace(".png", "").replace("_", " ").title()}</h3>\n'
            html += f'<img src="{rel_path}" alt="{name}">\n'

    html += _html_footer()

    with open(path, "w") as f:
        f.write(html)
    return path
