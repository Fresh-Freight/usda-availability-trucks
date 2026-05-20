"""
Builds Q3_Availability_Graph.html from a DataFrame.

This reproduces EXACTLY the chart design you approved (Q2-faithful single
trend line, Year + Region dropdowns, Q2-style single-track slider with
round knobs, 0-5 y-axis, Montserrat/Open Sans, green line, Mango accents).

The only difference from the static version is that the embedded data is
computed fresh from fetch_data() instead of being hardcoded.
"""
from __future__ import annotations
import json
import sys
import pandas as pd

from fetch_data import fetch_data

# Q3 core weeks — matches the Q2 reference's week-number axis style.
WEEKS = list(range(27, 40))
# "4-year average" = most recent 4 complete years (matches Q2 framing).
RECENT4 = [2022, 2023, 2024, 2025]
# Minimum year to expose in the Year dropdown.
MIN_DROPDOWN_YEAR = 2010


def compute_series(df: pd.DataFrame) -> dict:
    """Build the {key: [13 weekly values]} structure the HTML expects.
    Keys are 'YEARorAll|REGIONorAll'. None where a week has no data."""
    q3 = df[(df.Quarter == 3) & (df.Week.isin(WEEKS))].copy()
    if q3.empty:
        raise ValueError("No Q3 (weeks 27-39) rows in the data.")

    regions = sorted(q3.Region.unique())
    years = sorted(int(y) for y in q3.Year.unique() if int(y) >= MIN_DROPDOWN_YEAR)

    def series_for(sub: pd.DataFrame) -> list:
        g = sub.groupby("Week").Availability.mean()
        return [round(float(g[w]), 3) if w in g.index else None for w in WEEKS]

    series: dict[str, list] = {}

    recent = q3[q3.Year.isin(RECENT4)]
    series["all|all"] = series_for(recent)
    for r in regions:
        series[f"all|{r}"] = series_for(recent[recent.Region == r])

    for y in years:
        yr = q3[q3.Year == y]
        series[f"{y}|all"] = series_for(yr)
        for r in regions:
            s = series_for(yr[yr.Region == r])
            if any(v is not None for v in s):
                series[f"{y}|{r}"] = s

    return {"weeks": WEEKS, "regions": regions, "recent4": RECENT4,
            "years": years, "series": series}


def region_display(r: str) -> str:
    return "–".join(p[:1] + p[1:].lower() for p in r.split("-")).replace("Pnw", "PNW")


def build_html(data: dict) -> str:
    data_js = json.dumps(data, separators=(",", ":"))
    years_desc = sorted(data["years"], reverse=True)
    year_opts = "\n".join(
        f'          <option value="{y}">{y}</option>' for y in years_desc)
    region_opts = "\n".join(
        f'          <option value="{r}">{region_display(r)}</option>'
        for r in data["regions"])

    # NOTE: braces in the CSS/JS are escaped as {{ }} because this is one
    # big .format() string. The DATA payload is injected as %s via %.
    tpl = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Q3 Reefer Truck Availability by Week</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@500;600;700&family=Open+Sans:wght@400;600&display=swap" rel="stylesheet">
<script src="https://cdn.plot.ly/plotly-2.35.0.min.js"></script>
<style>
  :root{{
    --bg:#fafafa;--panel:#ffffff;
    --n-fill:#f4f4f4;--n-border:#e5e5e5;--n-text:#9a9a9a;
    --ink:#1a1a1a;--mut:#5f5f5f;
    --g-mid:#4a8b2c;--g-dark:#1d3711;
    --mango:#ec7700;
  }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--ink);
    font-family:'Open Sans',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
    padding:34px 28px;line-height:1.5;font-size:14px;font-weight:400}}
  .wrap{{max-width:1080px;margin:0 auto}}
  .eyebrow{{font-family:'Montserrat',sans-serif;font-size:11.5px;
    letter-spacing:.13em;text-transform:uppercase;color:var(--g-mid);
    font-weight:600;margin-bottom:7px}}
  h1{{font-family:'Montserrat',sans-serif;font-size:22px;font-weight:700;
    letter-spacing:-.01em;margin-bottom:4px;color:var(--ink)}}
  .sub{{color:var(--mut);font-size:13px;margin-bottom:20px}}
  .card{{background:var(--panel);border:1px solid var(--n-border);
    border-radius:12px;padding:22px 24px}}
  .filters{{display:flex;gap:26px;margin-bottom:6px;flex-wrap:wrap}}
  .fg{{display:flex;flex-direction:column;gap:6px}}
  .fg label{{font-family:'Montserrat',sans-serif;font-size:10.5px;
    letter-spacing:.06em;text-transform:uppercase;color:var(--n-text);
    font-weight:500}}
  select{{font-family:'Open Sans',sans-serif;font-size:13px;font-weight:600;
    padding:7px 30px 7px 12px;border:1px solid var(--n-border);border-radius:7px;
    background:#fff;color:var(--ink);cursor:pointer;min-width:170px;
    appearance:none;
    background-image:url("data:image/svg+xml;charset=US-ASCII,%%3Csvg%%20width%%3D%%2210%%22%%20height%%3D%%226%%22%%20viewBox%%3D%%220%%200%%2010%%206%%22%%20xmlns%%3D%%22http%%3A%%2F%%2Fwww.w3.org%%2F2000%%2Fsvg%%22%%3E%%3Cpath%%20d%%3D%%22M1%%201l4%%204%%204-4%%22%%20stroke%%3D%%22%%239a9a9a%%22%%20stroke-width%%3D%%221.5%%22%%20fill%%3D%%22none%%22%%20stroke-linecap%%3D%%22round%%22%%2F%%3E%%3C%%2Fsvg%%3E");
    background-repeat:no-repeat;background-position:right 11px center}}
  select:hover{{border-color:var(--mango)}}
  select:focus{{outline:none;border-color:var(--mango);
    box-shadow:0 0 0 3px rgba(236,119,0,.12)}}
  .ctitle{{font-family:'Montserrat',sans-serif;text-align:center;
    font-size:18px;font-weight:700;color:var(--ink);margin:18px 0 2px}}
  .csub{{text-align:center;font-size:12.5px;font-weight:600;
    color:var(--mut);margin-bottom:6px}}
  #chart{{height:380px}}
  .wkslider{{margin:6px 64px 0 64px}}
  .track{{position:relative;height:4px;background:#3a3a3a;border-radius:2px;
    margin:14px 10px 0 10px;cursor:pointer}}
  .track-fill{{position:absolute;height:100%;background:#3a3a3a;border-radius:2px}}
  .knob{{position:absolute;top:50%;width:16px;height:16px;border-radius:50%;
    background:#fff;border:2px solid #3a3a3a;transform:translate(-50%,-50%);
    cursor:grab;transition:box-shadow .12s}}
  .knob:hover{{box-shadow:0 0 0 5px rgba(236,119,0,.16);border-color:var(--mango)}}
  .knob:active{{cursor:grabbing;border-color:var(--mango)}}
  .wkaxis{{position:relative;height:18px;margin:9px 10px 0 10px}}
  .wkaxis span{{position:absolute;transform:translateX(-50%);
    font-size:11px;color:var(--mut);font-family:'Open Sans',sans-serif}}
  .wklabel{{text-align:center;font-family:'Montserrat',sans-serif;
    font-weight:700;font-size:13px;color:var(--ink);margin-top:6px}}
</style>
</head>
<body>
<div class="wrap">
  <div class="eyebrow">Q3 Reefer &amp; Perishable Forecast 2026</div>
  <h1>Reefer truck availability by week</h1>
  <div class="sub">Built on USDA AMS refrigerated-truck data. Drag the slider to zoom a week range; use Year and Region to refine.</div>

  <div class="card">
    <div class="filters">
      <div class="fg">
        <label for="yearSel">Year</label>
        <select id="yearSel">
          <option value="all">All (4-year avg.)</option>
{year_opts}
        </select>
      </div>
      <div class="fg">
        <label for="regSel">Region</label>
        <select id="regSel">
          <option value="all">All</option>
{region_opts}
        </select>
      </div>
    </div>

    <div class="ctitle" id="ctitle">Q3 Reefer Truck Availability by Week (4-year Avg.)</div>
    <div class="csub">(5 = Shortage of Capacity, 1 = Surplus of Capacity)</div>
    <div id="chart"></div>
    <div class="wkslider">
      <div class="track" id="track">
        <div class="track-fill" id="trackFill"></div>
        <div class="knob" id="knobLo"></div>
        <div class="knob" id="knobHi"></div>
      </div>
      <div class="wkaxis" id="wkaxis"></div>
      <div class="wklabel">Week</div>
    </div>
  </div>
</div>

<script>
const DATA = {data_js};
const WK = DATA.weeks;
const BASE=3, GREEN="#4a8b2c", MANGO="#ec7700", FONT="Open Sans, sans-serif";
let curLo=WK[0], curHi=WK[WK.length-1];

function dispRegion(r){{
  return r.split('-').map(p=>p.charAt(0)+p.slice(1).toLowerCase()).join('\\u2013')
          .replace('Pnw','PNW');
}}

const yearSel=document.getElementById("yearSel");
const regSel=document.getElementById("regSel");
const ctitle=document.getElementById("ctitle");
yearSel.onchange=draw; regSel.onchange=draw;

function getSeries(yr,rg){{
  const key=(yr==="all"?"all":yr)+"|"+(rg==="all"?"all":rg);
  return DATA.series[key] || null;
}}

function draw(){{
  const yr=yearSel.value, rg=regSel.value;
  let y=getSeries(yr,rg);
  const missing = !y;
  if(missing) y = WK.map(()=>null);

  const yrLabel = yr==="all" ? "4-year Avg." : yr;
  const rgLabel = rg==="all" ? "" : " \\u2014 "+dispRegion(rg);
  ctitle.textContent="Q3 Reefer Truck Availability by Week ("+yrLabel+")"+rgLabel;

  const trace={{
    x:WK,y:y,mode:"lines+markers",
    connectgaps:false,
    line:{{color:GREEN,width:3,shape:"linear"}},
    marker:{{size:7,color:GREEN}},
    hovertemplate:"Week %{{x}}<br>Avg. availability %{{y:.2f}} / 5<extra></extra>"
  }};
  const layout={{
    paper_bgcolor:"rgba(0,0,0,0)",plot_bgcolor:"rgba(0,0,0,0)",
    font:{{color:"#5f5f5f",size:12,family:FONT}},
    hovermode:"closest",
    hoverlabel:{{bgcolor:"#1a1a1a",bordercolor:"#1a1a1a",
      font:{{color:"#fff",family:FONT,size:12.5}}}},
    margin:{{l:70,r:30,t:8,b:20}},
    xaxis:{{showticklabels:false,
      tickmode:"array",tickvals:WK,
      showgrid:false,zeroline:false,
      range:[curLo-0.4,curHi+0.4]}},
    yaxis:{{title:{{text:"Average of Availability",
        font:{{family:'Montserrat',size:14,color:"#1a1a1a"}}}},
      range:[1,5],tickmode:"array",tickvals:[1,2,3,4,5],
      gridcolor:"#eeeeee",zeroline:false,
      tickfont:{{size:12,family:FONT,color:"#5f5f5f"}}}},
    shapes:[{{type:"line",xref:"paper",x0:0,x1:1,yref:"y",y0:BASE,y1:BASE,
      line:{{color:MANGO,width:2,dash:"dot"}}}}],
    annotations:[]
  }};
  if(missing){{
    layout.annotations.push({{xref:"paper",yref:"paper",x:0.5,y:0.5,
      xanchor:"center",text:"No reported data for this Year + Region",
      showarrow:false,font:{{color:"#9a9a9a",size:13,family:FONT}}}});
  }}
  Plotly.react("chart",[trace],layout,{{displayModeBar:false,responsive:true}});
}}

const track=document.getElementById("track");
const fill=document.getElementById("trackFill");
const knobLo=document.getElementById("knobLo");
const knobHi=document.getElementById("knobHi");
const wkaxis=document.getElementById("wkaxis");
const N=WK.length;

WK.forEach((w,i)=>{{
  if(i===0||i===N-1||w%2===0){{
    const s=document.createElement("span");
    s.textContent=w;
    s.style.left=(i/(N-1)*100)+"%";
    wkaxis.appendChild(s);
  }}
}});

let loIdx=0, hiIdx=N-1;
function pct(i){{ return (i/(N-1))*100; }}
function renderSlider(){{
  knobLo.style.left=pct(loIdx)+"%";
  knobHi.style.left=pct(hiIdx)+"%";
  fill.style.left=pct(loIdx)+"%";
  fill.style.width=(pct(hiIdx)-pct(loIdx))+"%";
  curLo=WK[loIdx]; curHi=WK[hiIdx];
}}
function idxFromEvent(e){{
  const r=track.getBoundingClientRect();
  const x=( (e.touches?e.touches[0].clientX:e.clientX) - r.left)/r.width;
  return Math.max(0,Math.min(N-1,Math.round(x*(N-1))));
}}
let dragging=null;
function startDrag(which){{return e=>{{dragging=which;e.preventDefault();}};}}
knobLo.addEventListener("mousedown",startDrag("lo"));
knobHi.addEventListener("mousedown",startDrag("hi"));
knobLo.addEventListener("touchstart",startDrag("lo"),{{passive:false}});
knobHi.addEventListener("touchstart",startDrag("hi"),{{passive:false}});
function onMove(e){{
  if(!dragging)return;
  const i=idxFromEvent(e);
  if(dragging==="lo") loIdx=Math.min(i,hiIdx-1<0?0:hiIdx-1);
  else hiIdx=Math.max(i,loIdx+1>N-1?N-1:loIdx+1);
  if(loIdx<0)loIdx=0; if(hiIdx>N-1)hiIdx=N-1;
  renderSlider(); draw();
}}
document.addEventListener("mousemove",onMove);
document.addEventListener("touchmove",onMove,{{passive:false}});
document.addEventListener("mouseup",()=>dragging=null);
document.addEventListener("touchend",()=>dragging=null);

renderSlider();
draw();
</script>
</body>
</html>'''

    return tpl.format(data_js=data_js, year_opts=year_opts,
                      region_opts=region_opts)


def main(out_path: str = "dist/Q3_Availability_Graph.html") -> None:
    import os
    df = fetch_data()
    data = compute_series(df)
    html = build_html(data)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[build_chart] wrote {out_path} "
          f"({len(html):,} bytes, {len(data['series'])} series, "
          f"{len(data['regions'])} regions, {len(data['years'])} years)",
          file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "dist/Q3_Availability_Graph.html")
