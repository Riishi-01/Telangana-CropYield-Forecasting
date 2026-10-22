/* =============================================================================
   Telangana kharif yield–weather explorer
   Vanilla JS + Leaflet (map) + Plotly (charts). No framework, no CDN.
   All data arrives in window.TA_DATA / window.TA_GEO (see src/10_build_dashboard.py).
   ============================================================================= */
(function () {
  "use strict";

  var D = window.TA_DATA;
  var G = window.TA_GEO;

  if (!D || !G) {
    document.body.innerHTML =
      '<p style="padding:2rem;font-family:sans-serif">The dashboard data bundle ' +
      "failed to load. Run <code>python src/10_build_dashboard.py</code> to rebuild it.</p>";
    return;
  }

  var META = D.meta;

  /* ---------------------------------------------------------------------- *
   * Colour ramps.
   * The project's colour system is fixed: RdYlBu (diverging, zero at the
   * exact midpoint) for yield anomaly, with blue = below normal and
   * red = above normal, and YlOrRd (sequential) for rainfall deficit.
   * Absolute yield uses a single-hue sequential ramp (Blues) so the red
   * ramp is never used to mean "good".
   * ---------------------------------------------------------------------- */
  var RAMPS = {
    anomaly: [
      "#313695", "#4575b4", "#74add1", "#abd9e9", "#e0f3f8", "#ffffbf",
      "#fee090", "#fdae61", "#f46d43", "#d73027", "#a50026"
    ],
    deficit: [
      "#ffffcc", "#ffeda0", "#fed976", "#feb24c", "#fd8d3c",
      "#fc4e2a", "#e31a1c", "#bd0026", "#800026"
    ],
    yield: [
      "#f7fbff", "#deebf7", "#c6dbef", "#9ecae1", "#6baed6",
      "#4292c6", "#2171b5", "#08519c", "#08306b"
    ]
  };

  function hex2rgb(h) {
    return [
      parseInt(h.slice(1, 3), 16),
      parseInt(h.slice(3, 5), 16),
      parseInt(h.slice(5, 7), 16)
    ];
  }

  function rgb2hex(c) {
    return (
      "#" +
      c
        .map(function (v) {
          return ("0" + Math.round(v).toString(16)).slice(-2);
        })
        .join("")
    );
  }

  function rampColor(name, t) {
    var stops = RAMPS[name];
    if (t === null || t === undefined || isNaN(t)) return "#e6e3dc";
    var x = Math.max(0, Math.min(1, t)) * (stops.length - 1);
    var i = Math.floor(x);
    var f = x - i;
    if (i >= stops.length - 1) return stops[stops.length - 1];
    var a = hex2rgb(stops[i]);
    var b = hex2rgb(stops[i + 1]);
    return rgb2hex([a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f]);
  }

  function inkOn(hex) {
    var c = hex2rgb(hex);
    var lum = (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) / 255;
    return lum > 0.62 ? "#16181d" : "#ffffff";
  }

  /* ---------------------------------------------------------------------- *
   * State
   * ---------------------------------------------------------------------- */
  var state = {
    crop: D.modelled_crops[0],
    season: D.seasons[D.seasons.length - 1],
    metric: "anomaly",
    pinned: null,
    sort: { key: "label", dir: 1 }
  };

  var els = {
    crop: document.getElementById("cropSelect"),
    season: document.getElementById("seasonSelect"),
    metric: document.getElementById("metricSelect"),
    reset: document.getElementById("resetBtn"),
    csv: document.getElementById("csvBtn"),
    map: document.getElementById("map"),
    legendScale: document.getElementById("legendScale"),
    legendCaption: document.getElementById("legendCaption"),
    mapNote: document.getElementById("mapNote"),
    readNote: document.getElementById("readNote"),
    rainChart: document.getElementById("rainChart"),
    yieldChart: document.getElementById("yieldChart"),
    rainTitle: document.getElementById("rainTitle"),
    yieldTitle: document.getElementById("yieldTitle"),
    modelFacts: document.getElementById("modelFacts"),
    curve: document.getElementById("curveChart"),
    curveNote: document.getElementById("curveNote"),
    curveFoot: document.getElementById("curveFoot"),
    markerDisclaimer: document.getElementById("markerDisclaimer"),
    tableBody: document.querySelector("#districtTable tbody"),
    tableSubtitle: document.getElementById("tableSubtitle"),
    stats: document.getElementById("statsChart"),
    statsFoot: document.getElementById("statsFoot"),
    disclosures: document.getElementById("disclosureList"),
    colophon: document.getElementById("colophonMeta"),
    dataVersion: document.getElementById("dataVersion")
  };

  var PLOT_CONFIG = {
    displaylogo: false,
    responsive: true,
    modeBarButtonsToRemove: ["select2d", "lasso2d", "autoScale2d", "toggleSpikelines"]
  };

  /* ---------------------------------------------------------------------- *
   * Data helpers
   * ---------------------------------------------------------------------- */
  function panelFor(crop, season) {
    if (!D.panel[crop]) return null;
    return D.panel[crop][season] || null;
  }

  function districtValue(crop, season, slug) {
    var rows = panelFor(crop, season);
    if (!rows) return null;
    var idx = D.districts.findIndex(function (d) { return d.s === slug; });
    if (idx < 0) return null;
    return rows[idx];
  }

  function modelFor(crop) {
    return D.models[crop] || null;
  }

  function isModelled(crop) {
    var m = modelFor(crop);
    return !!(m && m.modelled && m.stage1 && m.stage1.b1 !== undefined);
  }

  function unitOf(crop) {
    var m = modelFor(crop);
    if (m && m.unit) return m.unit;
    var rows = D.panel[crop] ? D.panel[crop][state.season] : null;
    for (var i = 0; i < (rows || []).length; i++) {
      if (rows[i]) return "t/ha";
    }
    return "t/ha";
  }

  function fmt(v, digits) {
    if (v === null || v === undefined || isNaN(v)) return "—";
    return Number(v).toLocaleString("en-IN", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits
    });
  }

  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  /* ---------------------------------------------------------------------- *
   * Map
   * ---------------------------------------------------------------------- */
  var map, geoLayer = {}, tileLayer = null, baseFallbackDone = false, hoverCard = null;

  function initMap() {
    hoverCard = document.createElement("div");
    hoverCard.className = "map-card";
    hoverCard.hidden = true;
    els.map.appendChild(hoverCard);

    map = L.map(els.map, {
      zoomControl: true,
      attributionControl: true,
      keyboard: true,
      scrollWheelZoom: false
    });

    tileLayer = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 12,
      minZoom: 5,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    });
    tileLayer.on("tileerror", function () {
      if (baseFallbackDone) return;
      baseFallbackDone = true;
      map.removeLayer(tileLayer);
      noteOffline();
    });
    tileLayer.addTo(map);

    var layer = L.geoJSON(G, {
      onEachFeature: function (feature, lyr) {
        var slug = feature.properties.slug;
        geoLayer[slug] = lyr;
        if (!slug) {
          lyr.setStyle({ fillColor: "#e6e3dc", fillOpacity: 0.7, color: "#c9c3b6" });
          return;
        }
        lyr.on("mouseover", function (e) {
          if (state.pinned) highlightPinned();
          lyr.setStyle({ weight: 2.2, color: "#16181d" });
          lyr.bringToFront();
          showHoverCard(slug, e);
        });
        lyr.on("mouseout", function () {
          styleDistrict(slug);
          if (state.pinned) highlightPinned();
          hideHoverCard();
        });
        lyr.on("click", function () {
          selectDistrict(slug);
        });
      }
    }).addTo(map);

    // The map lives in a CSS grid, so its size is not final at this point.
    // Fit the view after the container has been measured, and refit on resize.
    fitMap();
    window.addEventListener("resize", debounce(fitMap, 180));
  }

  var mapBounds = null;

  function fitMap() {
    if (!map) return;
    map.invalidateSize();
    if (!mapBounds) {
      mapBounds = L.geoJSON(G).getBounds();
    }
    if (mapBounds && mapBounds.isValid()) {
      map.fitBounds(mapBounds, { padding: [18, 18] });
    }
  }

  function debounce(fn, wait) {
    var t;
    return function () {
      clearTimeout(t);
      t = setTimeout(fn, wait);
    };
  }

  function noteOffline() {
    var note = document.getElementById("mapOffline");
    if (!note) {
      note = document.createElement("p");
      note.id = "mapOffline";
      note.className = "section-note";
      note.style.marginTop = "0.5rem";
      note.textContent =
        "Basemap tiles are unavailable (offline). District boundaries and values are unaffected.";
      els.map.parentNode.insertBefore(note, els.map.nextSibling);
    }
  }

  function valueForDistrict(slug) {
    var v = districtValue(state.crop, state.season, slug);
    if (!v) return null;
    return state.metric === "anomaly" ? v[1] : v[0];
  }

  function domainFor() {
    var dom = D.domains[state.crop] || { anomaly: [-50, 50], yield: [0, 1] };
    return state.metric === "anomaly" ? dom.anomaly : dom.yield;
  }

  function rampName() {
    return state.metric === "anomaly" ? "anomaly" : "yield";
  }

  function styleDistrict(slug) {
    var lyr = geoLayer[slug];
    if (!lyr) return;
    var value = valueForDistrict(slug);
    var dom = domainFor();
    var t = null;
    if (value !== null && dom[1] !== dom[0]) {
      t = (value - dom[0]) / (dom[1] - dom[0]);
    }
    var colour = rampColor(rampName(), t);
    var isPinned = state.pinned === slug;
    lyr.setStyle({
      fillColor: colour,
      fillOpacity: 0.88,
      color: isPinned ? "#16181d" : "#ffffff",
      weight: isPinned ? 2.4 : 0.9
    });

    // The value is written on the map as well as encoded in colour, so the
    // map never relies on colour alone.
    var label = value === null ? "n/a" :
      (state.metric === "anomaly" ? fmt(value, 0) : fmt(value, 1));

    if (lyr.getTooltip()) {
      lyr.setTooltipContent(label);
    } else {
      lyr.bindTooltip(label, {
        permanent: true,
        direction: "center",
        className: "district-label",
        opacity: 1
      });
    }
  }

  /* The permanent label on each polygon carries the value; the richer hover
     detail lives in a card so the map never depends on colour alone. */
  function showHoverCard(slug, evt) {
    var v = districtValue(state.crop, state.season, slug);
    if (!v) {
      hoverCard.innerHTML =
        "<strong>" + esc(districtLabel(slug)) + "</strong><br>No observation in " + state.season;
    } else {
      hoverCard.innerHTML =
        "<strong>" + esc(districtLabel(slug)) + "</strong><br>" +
        state.season + "<br>" +
        "rainfall " + fmt(v[2], 0) + " mm<br>" +
        "yield " + fmt(v[0], 2) + " " + unitOf(state.crop) + "<br>" +
        "anomaly " + fmt(v[1], 0) + "%<br>" +
        "longest dry run " + v[3] + " d · heat days " + v[5];
    }
    var rect = els.map.getBoundingClientRect();
    var x = evt.originalEvent.clientX - rect.left;
    var y = evt.originalEvent.clientY - rect.top;
    hoverCard.style.left = Math.min(x + 14, rect.width - 190) + "px";
    hoverCard.style.top = Math.max(8, y - 40) + "px";
    hoverCard.hidden = false;
  }

  function hideHoverCard() {
    hoverCard.hidden = true;
  }

  function districtLabel(slug) {
    var d = D.districts.find(function (x) { return x.s === slug; });
    return d ? d.l : slug;
  }

  function styleAll() {
    Object.keys(geoLayer).forEach(styleDistrict);
  }

  function highlightPinned() {
    if (!state.pinned || !geoLayer[state.pinned]) return;
    geoLayer[state.pinned].setStyle({ weight: 2.6, color: "#16181d", fillOpacity: 0.95 });
    geoLayer[state.pinned].bringToFront();
  }

  function renderLegend() {
    var dom = domainFor();
    var stops = [];
    for (var i = 0; i <= 10; i++) {
      stops.push(rampColor(rampName(), i / 10));
    }
    var gradient = "linear-gradient(90deg, " + stops.join(",") + ")";
    var lo = dom[0];
    var hi = dom[1];
    var name = state.metric === "anomaly" ? "RdYlBu (diverging)" : "Blues (sequential)";
    var unit = state.metric === "anomaly" ? "%" : unitOf(state.crop);
    var what = state.metric === "anomaly" ? "yield anomaly" : "yield";
    els.legendScale.innerHTML =
      "<span>" + fmt(lo, 1) + "</span>" +
      '<span class="legend__ramp" style="background:' + gradient + '"></span>' +
      "<span>" + fmt(hi, 1) + "</span>" +
      '<span style="color:var(--color-ink-muted)">· ' + what + " (" + unit + ")</span>";
    els.legendCaption.textContent =
      state.metric === "anomaly"
        ? "Colormap " + name + ", fixed domain across every season — the scale never rescales. " +
          "Blue is below normal, cream is normal, red is above normal. Districts with no observation are grey."
        : "Colormap " + name + ", fixed domain across every season. Absolute yield across Telangana is " +
          "dominated by soil and irrigation, so this view reads as a soil map, not a risk map; " +
          "the anomaly view is the risk view.";
  }

  /* ---------------------------------------------------------------------- *
   * Selection
   * ---------------------------------------------------------------------- */
  function selectDistrict(slug) {
    state.pinned = state.pinned === slug ? null : slug;
    styleAll();
    highlightPinned();
    renderTable();
    renderCurve();
    renderReadout();
  }

  /* ---------------------------------------------------------------------- *
   * Readout: rainfall and yield series
   * ---------------------------------------------------------------------- */
  function seriesTrace(crop, kind) {
    var out = [];
    D.seasons.forEach(function (s) {
      var row = (D.series[crop] || {})[s];
      if (!row) return;
      out.push({ season: s, values: row, n: row[6] });
    });
    return out;
  }

  function bandAndLine(el, crop, kind) {
    var rows = seriesTrace(crop, kind);
    var x = rows.map(function (r) { return r.season; });
    var lo = rows.map(function (r) { return kind === "rain" ? r.values[0] : r.values[3]; });
    var mid = rows.map(function (r) { return kind === "rain" ? r.values[1] : r.values[4]; });
    var hi = rows.map(function (r) { return kind === "rain" ? r.values[2] : r.values[5]; });

    var colour = kind === "rain" ? "#4c78a8" : "#e45756";
    var unit = kind === "rain" ? "mm" : unitOf(crop);

    var traces = [
      {
        x: x.concat(x.slice().reverse()),
        y: hi.concat(lo.slice().reverse()),
        type: "scatter",
        mode: "lines",
        line: { width: 0 },
        hoverinfo: "skip",
        showlegend: false,
        fill: "toself",
        fillcolor: colour + "2e",
        name: "p10–p90"
      },
      {
        x: x,
        y: mid,
        type: "scatter",
        mode: "lines+markers",
        line: { color: colour, width: 2 },
        marker: { color: colour, size: 6 },
        name: "state median",
        hovertemplate: "%{x}<br>median %{y:.1f} " + unit + "<extra></extra>"
      }
    ];

    if (state.pinned) {
      var pin = D.marker && D.marker.available ? null : null;
      var pv = null;
      D.seasons.forEach(function (s) {
        var v = districtValue(crop, s, state.pinned);
        if (v) pv = kind === "rain" ? v[2] : v[0];
      });
      if (pv !== null) {
        traces.push({
          x: [state.season],
          y: [pv],
          type: "scatter",
          mode: "markers",
          marker: { color: "#16181d", size: 9, symbol: "diamond" },
          name: districtLabel(state.pinned),
          hovertemplate: districtLabel(state.pinned) + "<br>%{x}<br>%{y:.1f} " + unit + "<extra></extra>"
        });
      }
    }

    Plotly.react(el, traces, {
      margin: { l: 46, r: 12, t: 8, b: 34 },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { family: "IBM Plex Sans, sans-serif", size: 11, color: "#454b55" },
      showlegend: false,
      hovermode: "x unified",
      xaxis: {
        tickangle: -45,
        gridcolor: "#e6e2d8",
        linecolor: "#d9d4c8",
        tickfont: { family: "IBM Plex Mono, monospace", size: 9, color: "#6d7481" }
      },
      yaxis: {
        title: { text: unit, font: { size: 10 } },
        gridcolor: "#e6e2d8",
        zeroline: false,
        tickfont: { family: "IBM Plex Mono, monospace", size: 9, color: "#6d7481" }
      }
    }, PLOT_CONFIG);
  }

  /* ---------------------------------------------------------------------- *
   * Model readout
   * ---------------------------------------------------------------------- */
  function fact(dl, dd, warn) {
    return "<dt>" + esc(dl) + "</dt><dd" + (warn ? ' class="is-warn"' : "") + ">" + dd + "</dd>";
  }

  function renderModelFacts() {
    var m = modelFor(state.crop);
    var out = "";
    if (!isModelled(state.crop)) {
      out += fact("Fitted model", "none for this crop", true);
      out += fact("District-season observations", fmt(countRows(), 0));
      out += fact("Yield unit", esc(unitOf(state.crop)));
      out += fact("Read", "descriptive only — no response curve is fitted for this crop");
      els.modelFacts.innerHTML = out;
      return;
    }
    var s1 = m.stage1;
    var s2 = m.stage2 || {};
    var va = m.validation || {};
    out += fact("Observations", fmt(s1.n_rows, 0) + " district-seasons");
    out += fact("Rainfall effect (b₁)", fmt(s1.b1, 5) + " per mm");
    out += fact("Curvature (b₂)", s1.b2.toExponential(2) + "  (p = " + fmt(s1.p2, 3) + ")");
    if (s1.vertex_reported) {
      out += fact("Rainfall optimum R*", fmt(s1.vertex_mm, 0) + " mm");
      var ci = s1.vertex_ci95_mm;
      if (ci) out += fact("95% CI", fmt(ci[0], 0) + " – " + fmt(ci[1], 0) + " mm");
    } else {
      out += fact("Rainfall optimum R*", "not supported", true);
    }
    out += fact("R² (Stage 1)", fmt(s1.r2, 3));
    if (s2.delta_r2 !== undefined) {
      out += fact("ΔR² (Stage 2)", fmt(s2.delta_r2, 4) +
        (s2.partial_f_p < 0.05 ? " (significant)" : " (not significant)"),
        !(s2.partial_f_p < 0.05));
    }
    if (va.skill_rmse !== undefined) {
      out += fact("Skill vs median", fmt(va.skill_rmse, 3), va.skill_rmse <= 0);
    }
    els.modelFacts.innerHTML = out;
  }

  function countRows() {
    var rows = panelFor(state.crop, state.season) || [];
    return rows.filter(function (r) { return !!r; }).length;
  }

  /* ---------------------------------------------------------------------- *
   * Response curve
   * ---------------------------------------------------------------------- */
  function renderCurve() {
    var crop = state.crop;
    var points = [];
    D.seasons.forEach(function (season) {
      (D.panel[crop] || {})[season] || [];
      var rows = panelFor(crop, season) || [];
      rows.forEach(function (v, i) {
        if (!v) return;
        points.push({
          rain: v[2],
          yield: v[0],
          anomaly: v[1],
          dry: v[3],
          heat: v[5],
          district: D.districts[i].l,
          slug: D.districts[i].s,
          season: season
        });
      });
    });

    var traces = [];
    var annotations = [];
    var shapes = [];

    // the axis always shows the 2026 band, so the reader can see how far
    // outside the fitted range the 2026 rainfall sits
    var axisRange = null;
    if (points.length) {
      var rains = points.map(function (p) { return p.rain; });
      var rMin = Math.min.apply(null, rains);
      var rMax = Math.max.apply(null, rains);
      if (D.marker && D.marker.available) {
        rMin = Math.min(rMin, D.marker.p10);
        rMax = Math.max(rMax, D.marker.p90);
      }
      var pad = (rMax - rMin) * 0.04;
      axisRange = [rMin - pad, rMax + pad];
    }

    if (isModelled(crop)) {
      var s1 = modelFor(crop).stage1;
      var y0 = s1.mean_fitted;
      var rbar = s1.rain_mean_mm;
      var r2bar = s1.rain_sq_mean;
      var xs = points.map(function (p) { return p.rain; });
      var xmin = Math.min.apply(null, xs);
      var xmax = Math.max.apply(null, xs);
      var grid = [];
      for (var g = 0; g <= 120; g++) grid.push(xmin + ((xmax - xmin) * g) / 120);
      var curve = grid.map(function (r) {
        return y0 + s1.b1 * (r - rbar) + s1.b2 * (r * r - r2bar);
      });
      traces.push({
        x: grid,
        y: curve,
        type: "scatter",
        mode: "lines",
        line: { color: "#1f77b4", width: 2.4 },
        name: "fitted quadratic (Stage 1)",
        hovertemplate: "rainfall %{x:.0f} mm<br>expected yield %{y:.3f}<extra></extra>"
      });

      if (s1.vertex_reported) {
        var vy = y0 + s1.b1 * (s1.vertex_mm - rbar) + s1.b2 * (Math.pow(s1.vertex_mm, 2) - r2bar);
        traces.push({
          x: [s1.vertex_mm],
          y: [vy],
          type: "scatter",
          mode: "markers",
          marker: { color: "#1f77b4", size: 13, line: { color: "#fffdf9", width: 2 } },
          name: "rainfall optimum R*",
          hovertemplate: "R* = %{x:.0f} mm<extra></extra>"
        });
        annotations.push({
          x: s1.vertex_mm,
          y: vy,
          text: "R* = " + fmt(s1.vertex_mm, 0) + " mm",
          showarrow: true,
          arrowhead: 0,
          ax: -30,
          ay: -34,
          bgcolor: "rgba(255,253,249,0.92)",
          bordercolor: "#b3ab9b",
          borderwidth: 1,
          font: { family: "IBM Plex Mono, monospace", size: 10, color: "#16181d" }
        });
      } else {
        annotations.push({
          x: 0.985,
          y: 0.97,
          xref: "paper",
          yref: "paper",
          xanchor: "right",
          text: "No significant inverted-U — the quadratic term is not supported (p = " + fmt(s1.p2, 3) + ")",
          showarrow: false,
          align: "right",
          bgcolor: "rgba(246,231,221,0.94)",
          bordercolor: "#a8471f",
          borderwidth: 1,
          font: { family: "IBM Plex Sans, sans-serif", size: 10, color: "#6d2f13" }
        });
      }
    }

    // observations: the selected season is emphasised, the rest are context
    var rest = points.filter(function (p) { return p.season !== state.season; });
    var focus = points.filter(function (p) { return p.season === state.season; });

    function pointTrace(list, name, colour, size) {
      return {
        x: list.map(function (p) { return p.rain; }),
        y: list.map(function (p) { return p.yield; }),
        customdata: list.map(function (p) {
          return [p.district, p.season, p.anomaly, p.dry, p.heat, p.slug];
        }),
        type: "scatter",
        mode: "markers",
        marker: { color: colour, size: size, opacity: 0.55, line: { width: 0 } },
        name: name,
        hovertemplate:
          "<b>%{customdata[0]}</b> · %{customdata[1]}<br>" +
          "rainfall %{x:.0f} mm · yield %{y:.3f} " + unitOf(crop) + "<br>" +
          "anomaly %{customdata[2]:+.0f}% · longest dry run %{customdata[3]} d<extra></extra>"
      };
    }

    traces.push(pointTrace(rest, "other seasons", "#9aa6b2", 6));
    traces.push(pointTrace(focus, state.season, "#1f77b4", 9));

    if (state.pinned) {
      var pin = points.filter(function (p) { return p.slug === state.pinned; });
      if (pin.length) {
        traces.push({
          x: pin.map(function (p) { return p.rain; }),
          y: pin.map(function (p) { return p.yield; }),
          customdata: pin.map(function (p) { return [p.district, p.season]; }),
          type: "scatter",
          mode: "markers",
          marker: {
            color: "rgba(0,0,0,0)",
            size: 15,
            line: { color: "#16181d", width: 1.6 }
          },
          name: districtLabel(state.pinned),
          hovertemplate: "<b>%{customdata[0]}</b> · %{customdata[1]}<br>rainfall %{x:.0f} mm · yield %{y:.3f}<extra></extra>"
        });
      }
    }

    // 2026 marker
    var markerBand = null;
    if (D.marker && D.marker.available) {
      var m26 = D.marker.state_mean;
      var lo26 = D.marker.p10;
      var hi26 = D.marker.p90;
      markerBand = { lo: lo26, hi: hi26, mean: m26 };
      shapes.push({
        type: "rect",
        x0: lo26, x1: hi26, y0: 0, y1: 1, yref: "paper",
        fillcolor: "rgba(17,17,17,0.06)",
        line: { width: 0 },
        layer: "below"
      });
      shapes.push({
        type: "line",
        x0: m26, x1: m26, y0: 0, y1: 1, yref: "paper",
        line: { color: "#111111", width: 1.4, dash: "dash" }
      });
      if (isModelled(crop)) {
        var s = modelFor(crop).stage1;
        var y26 = s.mean_fitted + s.b1 * (m26 - s.rain_mean_mm) +
          s.b2 * (Math.pow(m26, 2) - s.rain_sq_mean);
        traces.push({
          x: [m26],
          y: [y26],
          type: "scatter",
          mode: "markers",
          marker: { color: "rgba(0,0,0,0)", size: 13, line: { color: "#111111", width: 1.8 } },
          name: "2026 reading on the fitted curve",
          hovertemplate:
            "2026 rainfall " + fmt(m26, 0) + " mm (state mean)<br>" +
            "reading of the fitted curve: %{y:.3f} " + unitOf(crop) +
            "<br><i>not a forecast</i><extra></extra>"
        });
      }
    }

    Plotly.react(els.curve, traces, {
      margin: { l: 64, r: 24, t: 18, b: 52 },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { family: "IBM Plex Sans, sans-serif", size: 11, color: "#454b55" },
      shapes: shapes,
      annotations: annotations,
      hovermode: "closest",
      legend: {
        orientation: "h",
        y: -0.19,
        font: { size: 10 },
        bgcolor: "rgba(0,0,0,0)"
      },
      xaxis: {
        title: { text: "kharif rainfall, 1 Jun – 30 Sep (mm)", font: { size: 11 } },
        gridcolor: "#e6e2d8",
        linecolor: "#d9d4c8",
        tickfont: { family: "IBM Plex Mono, monospace", size: 9, color: "#6d7481" },
        zeroline: false,
        range: axisRange
      },
      yaxis: {
        title: { text: "yield (" + unitOf(crop) + ")", font: { size: 11 } },
        gridcolor: "#e6e2d8",
        linecolor: "#d9d4c8",
        tickfont: { family: "IBM Plex Mono, monospace", size: 9, color: "#6d7481" },
        zeroline: false
      }
    }, PLOT_CONFIG);

    els.curve.on("plotly_click", function (ev) {
      var cd = ev.points && ev.points[0] && ev.points[0].customdata;
      if (cd && cd[5]) selectDistrict(cd[5]);
    });
  }

  /* ---------------------------------------------------------------------- *
   * Table
   * ---------------------------------------------------------------------- */
  function tableRows() {
    var rows = panelFor(state.crop, state.season) || [];
    var out = [];
    rows.forEach(function (v, i) {
      if (!v) return;
      out.push({
        slug: D.districts[i].s,
        label: D.districts[i].l,
        rain: v[2],
        yield: v[0],
        anomaly: v[1],
        dry: v[3],
        heat: v[5]
      });
    });
    return out;
  }

  function renderTable() {
    var rows = tableRows();
    var key = state.sort.key;
    var dir = state.sort.dir;
    rows.sort(function (a, b) {
      var x = a[key];
      var y = b[key];
      if (typeof x === "string") return x.localeCompare(y) * dir;
      return ((x || 0) - (y || 0)) * dir;
    });

    var unit = unitOf(state.crop);
    var html = rows.map(function (r) {
      return (
        "<tr data-slug='" + r.slug + "'" + (state.pinned === r.slug ? ' class="is-pinned"' : "") +
        " tabindex='0'>" +
        "<td>" + esc(r.label) + "</td>" +
        "<td class='num'>" + fmt(r.rain, 0) + "</td>" +
        "<td class='num'>" + fmt(r.yield, 2) + "</td>" +
        "<td class='num'>" + fmt(r.anomaly, 0) + "</td>" +
        "<td class='num'>" + fmt(r.dry, 0) + "</td>" +
        "<td class='num'>" + fmt(r.heat, 0) + "</td>" +
        "</tr>"
      );
    }).join("");

    var missing = D.districts.filter(function (d) {
      return d.s && !rows.some(function (r) { return r.slug === d.s; });
    });
    if (missing.length) {
      html += "<tr class='is-empty'><td colspan='6'>No observation this season: " +
        missing.map(function (d) { return esc(d.l); }).join(", ") + "</td></tr>";
    }

    els.tableBody.innerHTML = html;

    Array.prototype.forEach.call(els.tableBody.querySelectorAll("tr[data-slug]"), function (tr) {
      tr.addEventListener("click", function () { selectDistrict(tr.getAttribute("data-slug")); });
      tr.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          selectDistrict(tr.getAttribute("data-slug"));
        }
      });
    });

    els.tableSubtitle.textContent =
      state.season + " · " + rows.length + " districts · " + unit;
  }

  Array.prototype.forEach.call(
    document.querySelectorAll("#districtTable th[data-sort]"),
    function (th) {
      th.addEventListener("click", function () {
        var key = th.getAttribute("data-sort");
        if (state.sort.key === key) {
          state.sort.dir = -state.sort.dir;
        } else {
          state.sort.key = key;
          state.sort.dir = 1;
        }
        Array.prototype.forEach.call(
          document.querySelectorAll("#districtTable th[data-sort]"),
          function (o) { o.removeAttribute("aria-sort"); }
        );
        th.setAttribute("aria-sort", state.sort.dir === 1 ? "ascending" : "descending");
        renderTable();
      });
    }
  );

  /* ---------------------------------------------------------------------- *
   * Model comparison chart
   * ---------------------------------------------------------------------- */
  function renderStats() {
    var crops = D.modelled_crops.filter(function (c) { return D.models[c] && D.models[c].stage2; });
    var shortNames = crops.map(function (c) {
      return { "Cotton(lint)": "Cotton", "Arhar/Tur": "Arhar", "Moong(Green Gram)": "Moong", "Rice": "Rice" }[c] || c;
    });
    if (!crops.length) {
      els.stats.innerHTML = "";
      return;
    }
    var dR2 = crops.map(function (c) { return D.models[c].stage2.delta_r2; });
    var skill = crops.map(function (c) {
      var v = D.models[c].validation;
      return v ? v.skill_rmse : null;
    });
    var pvals = crops.map(function (c) { return D.models[c].stage2.partial_f_p; });

    var trace1 = {
      x: shortNames,
      y: dR2,
      type: "bar",
      xaxis: "x",
      yaxis: "y",
      marker: {
        color: dR2.map(function (v, i) { return pvals[i] < 0.05 ? "#0b5f7a" : "#9bb3bd"; })
      },
      text: dR2.map(function (v, i) {
        return (v >= 0 ? "+" : "") + v.toFixed(3) + (pvals[i] < 0.05 ? " *" : "");
      }),
      textposition: "outside",
      textfont: { family: "IBM Plex Mono, monospace", size: 10 },
      hovertemplate: "%{x}<br>ΔR² = %{y:+.4f}<br>partial F p = %{customdata:.3f}<extra></extra>",
      customdata: pvals,
      name: "ΔR²"
    };
    var trace2 = {
      x: shortNames,
      y: skill,
      type: "bar",
      xaxis: "x2",
      yaxis: "y2",
      marker: { color: skill.map(function (v) { return v > 0 ? "#1f77b4" : "#a8471f"; }) },
      text: skill.map(function (v) { return (v >= 0 ? "+" : "") + v.toFixed(3); }),
      textposition: "outside",
      textfont: { family: "IBM Plex Mono, monospace", size: 10 },
      hovertemplate: "%{x}<br>skill = %{y:+.3f}<extra></extra>",
      name: "skill"
    };

    Plotly.react(els.stats, [trace1, trace2], {
      margin: { l: 54, r: 16, t: 40, b: 56 },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { family: "IBM Plex Sans, sans-serif", size: 10, color: "#454b55" },
      barmode: "group",
      showlegend: false,
      xaxis: {
        title: { text: "ΔR² (Stage 2 − Stage 1)", font: { size: 10 } },
        domain: [0, 0.44],
        anchor: "y",
        gridcolor: "#e6e2d8",
        tickfont: { family: "IBM Plex Mono, monospace", size: 9, color: "#6d7481" },
        zeroline: true,
        zerolinecolor: "#b3ab9b"
      },
      xaxis2: {
        title: { text: "skill vs median baseline", font: { size: 10 } },
        domain: [0.56, 1],
        anchor: "y2",
        gridcolor: "#e6e2d8",
        tickfont: { family: "IBM Plex Mono, monospace", size: 9, color: "#6d7481" },
        zeroline: true,
        zerolinecolor: "#b3ab9b"
      },
      yaxis: {
        title: { text: "ΔR²", font: { size: 10 } },
        domain: [0, 1],
        anchor: "x",
        gridcolor: "#e6e2d8",
        tickfont: { family: "IBM Plex Mono, monospace", size: 9, color: "#6d7481" }
      },
      yaxis2: {
        title: { text: "skill", font: { size: 10 } },
        domain: [0, 1],
        anchor: "x2",
        gridcolor: "#e6e2d8",
        tickfont: { family: "IBM Plex Mono, monospace", size: 9, color: "#6d7481" }
      }
    }, PLOT_CONFIG);

    els.statsFoot.textContent =
      "ΔR² is the change in explained variance when dry-spell, heat and VPD features are added " +
      "to the rainfall quadratic; * marks a partial F-test at p < 0.05. " +
      "A positive skill score means the weather-only model beats the district-crop median in the " +
      "test period; a negative score means it does not, and that is a reportable result rather than " +
      "a failure. The baseline median is computed on the training seasons only.";
  }

  /* ---------------------------------------------------------------------- *
   * CSV export
   * ---------------------------------------------------------------------- */
  function exportCsv() {
    var rows = tableRows();
    var head = [
      "crop", "season", "district_slug", "district", "rainfall_mm", "yield", "unit",
      "yield_anomaly_pct", "longest_dry_run_days", "heat_days"
    ];
    var lines = [head.join(",")];
    rows.forEach(function (r) {
      lines.push([
        '"' + state.crop + '"',
        '"' + state.season + '"',
        '"' + r.slug + '"',
        '"' + r.label + '"',
        r.rain, r.yield, '"' + unitOf(state.crop) + '"',
        r.anomaly, r.dry, r.heat
      ].join(","));
    });
    var blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = "telangana_" + state.crop.replace(/[^a-z0-9]+/gi, "_") + "_" + state.season + ".csv";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  /* ---------------------------------------------------------------------- *
   * Render
   * ---------------------------------------------------------------------- */
  function renderReadout() {
    var rows = panelFor(state.crop, state.season) || [];
    var vals = rows.filter(function (r) { return !!r; });
    var rain = vals.map(function (r) { return r[2]; });
    var yl = vals.map(function (r) { return r[0]; });
    var pinned = state.pinned ? districtValue(state.crop, state.season, state.pinned) : null;

    els.readNote.textContent =
      state.season + " · " + vals.length + " districts observed" +
      (pinned ? " · pinned: " + districtLabel(state.pinned) : "");

    els.yieldTitle.innerHTML =
      '<span class="icon icon--yield" aria-hidden="true"></span>' +
      esc(cropTitle(state.crop)) + " yield";

    bandAndLine(els.rainChart, state.crop, "rain");
    bandAndLine(els.yieldChart, state.crop, "yield");
    renderModelFacts();
  }

  function cropTitle(crop) {
    var map = {
      "Cotton(lint)": "Cotton (lint)",
      "Arhar/Tur": "Arhar / Tur",
      "Moong(Green Gram)": "Moong (green gram)",
      "Rice": "Rice"
    };
    return map[crop] || crop;
  }

  function renderAll() {
    styleAll();
    renderLegend();
    renderReadout();
    renderCurve();
    renderTable();

    var m = modelFor(state.crop);
    if (isModelled(state.crop)) {
      var s1 = m.stage1;
      els.curveNote.textContent =
        "District and season fixed effects; the curve is the mean-centred effect of rainfall, " +
        "with every other factor held at its average. " +
        (s1.vertex_reported
          ? "The rainfall optimum R* = " + fmt(s1.vertex_mm, 0) + " mm is statistically supported for this crop."
          : "No rainfall optimum is statistically supported for this crop: the quadratic term is not significant.");
    } else {
      els.curveNote.textContent =
        "This crop is mapped and described but not modelled — the response curve is not fitted for it.";
    }

    els.mapNote.textContent =
      state.season + " · " + cropTitle(state.crop) + " · " +
      (state.metric === "anomaly" ? "yield anomaly (%)" : "absolute yield (" + unitOf(state.crop) + ")");

    if (D.marker && D.marker.available) {
      els.markerDisclaimer.hidden = false;
      var extra = "";
      if (D.marker.districts_below_historical_min) {
        extra =
          " In this build the 2026 state-mean kharif rainfall is " +
          fmt(D.marker.state_mean, 0) + " mm, the " +
          fmt(D.marker.percentile_in_history, 1) + "th percentile of the " +
          fmt(D.marker.historical_min, 0) + "–" + fmt(D.marker.historical_max, 0) +
          " mm range observed in the fitting period; " +
          D.marker.districts_below_historical_min + " of " + D.marker.n_districts +
          " districts sit below that observed minimum, so the reading is an " +
          "extrapolation below the fitted range, not an interpolation.";
      }
      els.markerDisclaimer.textContent = META.disclosures.not_forecast + extra;
    } else {
      els.markerDisclaimer.hidden = true;
    }

    els.curveFoot.textContent =
      "Points are district-season observations. The band in the season panels is the p10–p90 " +
      "range across districts — descriptive, not inferential; no confidence intervals are claimed. " +
      "Rainfall is 1 Jun – 30 Sep, the official kharif sowing window, not the full growing season.";
  }

  /* ---------------------------------------------------------------------- *
   * Boot
   * ---------------------------------------------------------------------- */
  function populateControls() {
    D.crops.forEach(function (c) {
      var opt = document.createElement("option");
      opt.value = c;
      opt.textContent = cropTitle(c) + (isModelled(c) ? "" : "  (mapped, not modelled)");
      els.crop.appendChild(opt);
    });
    els.crop.value = state.crop;

    D.seasons.forEach(function (s) {
      var opt = document.createElement("option");
      opt.value = s;
      opt.textContent = s;
      els.season.appendChild(opt);
    });
    els.season.value = state.season;

    els.dataVersion.textContent = META.data_version;
  }

  function populateDisclosures() {
    var d = META.disclosures;
    var order = [
      d.reanalysis, d.convective, d.confound, d.aggregates, d.boundary, d.sowing,
      d.agency, d.cotton, d.sample, d.not_forecast, d.attribution, d.percentiles
    ];
    els.disclosures.innerHTML = order.map(function (t) { return "<li>" + esc(t) + "</li>"; }).join("");
    els.colophon.textContent =
      "DATA_VERSION " + META.data_version + " · panel built " + META.panel_created_utc +
      " · weather: " + META.weather_source + " (" + META.weather_licence + ")" +
      " · yield: " + META.yield_source + " · boundaries: " + META.geojson_source +
      " · district coordinates: " + META.centroid_method +
      " · split: " + META.split;
  }

  function init() {
    populateControls();
    populateDisclosures();
    initMap();
    renderStats();

    els.crop.addEventListener("change", function () {
      state.crop = els.crop.value;
      state.pinned = null;
      renderAll();
    });
    els.season.addEventListener("change", function () {
      state.season = els.season.value;
      renderAll();
    });
    els.metric.addEventListener("change", function () {
      state.metric = els.metric.value;
      renderAll();
    });
    els.reset.addEventListener("click", function () {
      state.pinned = null;
      renderAll();
    });
    els.csv.addEventListener("click", exportCsv);

    renderAll();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
