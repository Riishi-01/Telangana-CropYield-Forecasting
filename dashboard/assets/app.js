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
    // YlOrRd: the deficit value is positive for a shortfall, so the darkest
    // red sits at the high end of the domain - the worst case reads darkest.
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
    // the crops ticked in the forecast chart; null means "all of them"
    forecastCrops: null,
    forecastSort: { key: "diff", dir: 1 },
    forecastPoint: null
  };

  var els = {
    crop: document.getElementById("cropSelect"),
    cropStrip: document.getElementById("cropStrip"),
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
    markerDisclaimer: document.getElementById("markerDisclaimer"),
    stats: document.getElementById("statsChart"),
    statsFoot: document.getElementById("statsFoot"),
    forecastChart: document.getElementById("forecastChart"),
    forecastTicks: document.getElementById("forecastTicks"),
    forecastLegend: document.getElementById("forecastLegend"),
    forecastFoot: document.getElementById("forecastFoot"),
    forecastOffScale: 0,
    forecastDetail: document.getElementById("forecastDetail"),
    forecastDetailEmpty: document.getElementById("forecastDetailEmpty"),
    forecastDetailBody: document.getElementById("forecastDetailBody"),
    forecastTableBody: document.querySelector("#forecastTable tbody"),
    forecastTableSubtitle: document.getElementById("forecastTableSubtitle"),
    forecastTableFoot: document.getElementById("forecastTableFoot"),
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
    if (state.metric === "anomaly") return v[1];
    if (state.metric === "yield") return v[0];
    // rainfall deficit: this season's rain against this district's own median.
    // Positive = a shortfall, negative = a surplus, so the sign reads the way
    // a reader expects and the darkest red is the worst case.
    var ref = districtRefMedian(slug);
    if (ref === null || !v[2]) return null;
    return 100.0 * (1.0 - v[2] / ref);
  }

  function districtRefMedian(slug) {
    var d = D.districts.find(function (x) { return x.s === slug; });
    return d && d.rmed !== undefined && d.rmed !== null ? d.rmed : null;
  }

  function domainFor() {
    if (state.metric === "deficit") {
      return (D.domains && D.domains.deficit) || [-100, 100];
    }
    var dom = D.domains[state.crop] || { anomaly: [-50, 50], yield: [0, 1] };
    return state.metric === "anomaly" ? dom.anomaly : dom.yield;
  }

  function rampName() {
    if (state.metric === "deficit") return "deficit";
    return state.metric === "anomaly" ? "anomaly" : "yield";
  }

  function metricUnit() {
    if (state.metric === "anomaly") return "%";
    if (state.metric === "deficit") return "%";
    return unitOf(state.crop);
  }

  function metricLabel() {
    if (state.metric === "anomaly") return "yield anomaly";
    if (state.metric === "deficit") return "rainfall deficit";
    return "yield";
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
      (state.metric === "yield" ? fmt(value, 1) : fmt(value, 0));

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
        "rainfall " + fmt(v[2], 0) + " mm" +
        (districtRefMedian(slug) !== null
          ? "<br>vs own median " + fmt(districtRefMedian(slug), 0) + " mm (" +
            fmt(100 * (1 - v[2] / districtRefMedian(slug)), 0) + "% deficit)"
          : "") + "<br>" +
        "yield " + fmt(v[0], 2) + " " + unitOf(crop) + "<br>" +
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
    var unit = metricUnit();
    var what = metricLabel();
    var name = state.metric === "anomaly" ? "RdYlBu (diverging)"
            : state.metric === "deficit" ? "YlOrRd (sequential)"
            : "Blues (sequential)";
    els.legendScale.innerHTML =
      "<span>" + fmt(lo, 1) + "</span>" +
      '<span class="legend__ramp" style="background:' + gradient + '"></span>' +
      "<span>" + fmt(hi, 1) + "</span>" +
      '<span style="color:var(--color-ink-muted)">· ' + what + " (" + unit + ")</span>";
    els.legendCaption.textContent =
      state.metric === "anomaly"
        ? "Colormap " + name + ", fixed domain across every season — the scale never rescales. " +
          "Blue is below normal, cream is normal, red is above normal. Districts with no observation are grey."
        : state.metric === "deficit"
        ? "Colormap " + name + ", fixed domain across every season. " +
          "Rainfall this season against that district's own 2016-17–2022-23 median: " +
          "a positive value is a shortfall and dark red is a large one, so the scale reads as drought severity. " +
          "The reference is each district's own norm, so the map shows where a season was dry " +
          "for that district rather than for the state. Districts with no observation are grey."
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
   * The rows behind the CSV export.  The on-screen district table was
   * retired in v1.2.0, but the export still ships the same rows.
   * ---------------------------------------------------------------------- */
  function tableRows() {
    var rows = panelFor(state.crop, state.season) || [];
    var out = [];
    rows.forEach(function (v, i) {
      if (!v) return;
      var ref = districtRefMedian(D.districts[i].s);
      out.push({
        slug: D.districts[i].s,
        label: D.districts[i].l,
        rain: v[2],
        yield: v[0],
        anomaly: v[1],
        dry: v[3],
        heat: v[5],
        deficit: ref && v[2] ? 100 * (1 - v[2] / ref) : null
      });
    });
    return out;
  }

  // the table columns follow the map metric, so the numbers on screen always
  // match the colours on the map


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
   * Window sensitivity panel
   * ---------------------------------------------------------------------- */
  function renderWindowPanel() {
    var ws = D.window_sensitivity;
    var headRow = document.getElementById("windowHeadRow");
    var body = document.querySelector("#windowTable tbody");
    if (!ws || !ws.available) {
      headRow.innerHTML = "";
      body.innerHTML = "";
      document.getElementById("windowFoot").textContent =
        "The window sensitivity has not been computed in this build.";
      return;
    }
    var order = ws.window_order;
    headRow.innerHTML =
      "<th scope='col'>Crop</th>" +
      order.map(function (w) {
        return "<th scope='col' class='num'>" + esc(ws.windows[w]) + "</th>";
      }).join("");

    var html = Object.keys(ws.crops).map(function (crop) {
      var cells = order.map(function (w) {
        var r = ws.crops[crop][w];
        if (!r) return "<td class='num'>—</td>";
        var sig = r.p2 < 0.05;
        var txt = "p = " + (r.p2 < 0.001 ? "<0.001" : r.p2.toFixed(3));
        if (r.vertex_reported) {
          txt += "<br><strong>R* = " + fmt(r.vertex_mm, 0) + " mm</strong>";
        } else {
          txt += "<br>no vertex";
        }
        return "<td class='num' style='" +
          (sig ? "color:var(--color-accent);font-weight:600" : "color:var(--color-ink-muted)") +
          "'>" + txt + "</td>";
      }).join("");
      return "<tr><td>" + esc(cropTitle(crop)) + "</td>" + cells + "</tr>";
    }).join("");
    body.innerHTML = html;

    var stable = Object.keys(ws.crops).every(function (crop) {
      var flags = order.map(function (w) { return ws.crops[crop][w].vertex_reported; });
      return flags.every(function (f) { return f === flags[0]; });
    });
    document.getElementById("windowFoot").textContent =
      "p is the p-value of the quadratic rainfall term; a vertex is reported only when the term is " +
      "negative and significant at p < 0.05. " +
      (stable
        ? "The conclusion does not depend on the window: the same crops support an inverted-U " +
          "under all three windows, and the others support none."
        : "The conclusion depends on the window for at least one crop.") +
      " The Jun–Sep column reproduces the shipped Stage 1 fit exactly.";
  }

  /* ---------------------------------------------------------------------- *
   * The 2026 forecast
   * ---------------------------------------------------------------------- *
   * ONE chart, up to four crops.  Each crop is forecast by its OWN model -
   * the one that survived leave-one-season-out cross-validation inside the
   * fitting period and produced valid yields at 2026's rainfall.
   *
   * THE Y AXIS IS INDEXED.  Cotton is measured in bales per hectare and the
   * other three in tonnes, so four crops cannot share a raw axis.  Each crop
   * is indexed to its own Telangana average over the fitted period
   * (2016-17 - 2022-23 = 100), which is the same area-weighted reference the
   * forecast table uses.  The 2026 endpoint therefore reads directly as the
   * forecast difference: 100 + the per-cent change against that reference.
   *
   * THE STATE LINE IS AREA-WEIGHTED: sum(yield x area) / sum(area) over the
   * districts reporting in that season.  The unweighted median of district
   * yields is not used - it is not comparable across the 2016
   * reorganisation, whereas the state aggregate is a state total divided by
   * a state area and is the same quantity on both sides of the boundary.
   *
   * The x axis is CATEGORICAL: the nine observed seasons, then 2026 as its
   * own step.  A continuous axis would place 2026 (488 mm state mean, below
   * every fitted observation) to the LEFT of the record, which reads as
   * "before 2014" rather than "a prediction for a season that has not
   * happened yet".
   */

  // the crops the forecast covers, in the canonical order
  function forecastCrops() {
    var fc = D.forecast || {};
    return (D.crops || []).filter(function (c) { return fc[c]; });
  }

  // the crops currently ticked in the chart; null means every one of them
  function tickedCrops() {
    var all = forecastCrops();
    if (!state.forecastCrops) return all;
    var picked = all.filter(function (c) { return state.forecastCrops.indexOf(c) >= 0; });
    return picked.length ? picked : all;
  }

  function renderForecastTicks() {
    var box = els.forecastTicks;
    if (!box) return;
    var all = forecastCrops();
    var ticked = tickedCrops();
    var everyOne = ticked.length === all.length;
    box.innerHTML = "";

    var allBtn = document.createElement("button");
    allBtn.type = "button";
    allBtn.className = "forecast-tick forecast-tick--all" + (everyOne ? " forecast-tick--on" : "");
    allBtn.setAttribute("aria-pressed", everyOne ? "true" : "false");
    allBtn.textContent = "All crops";
    allBtn.addEventListener("click", function () {
      state.forecastCrops = null;
      renderForecast();
    });
    box.appendChild(allBtn);

    all.forEach(function (crop) {
      var on = ticked.indexOf(crop) >= 0;
      var b = document.createElement("button");
      b.type = "button";
      b.className = "forecast-tick" + (on ? " forecast-tick--on" : "");
      b.setAttribute("aria-pressed", on ? "true" : "false");
      b.setAttribute("data-crop", crop);
      var sw = document.createElement("span");
      sw.className = "forecast-tick__swatch";
      sw.style.background = cropColor(crop);
      var t = document.createElement("span");
      t.textContent = cropTitle(crop);
      b.appendChild(sw);
      b.appendChild(t);
      b.addEventListener("click", function () {
        var current = tickedCrops();
        // clicking the crop that is already alone returns to the full set;
        // clicking any other crop focuses on it
        if (current.length === 1 && current[0] === crop) {
          state.forecastCrops = null;
        } else {
          state.forecastCrops = [crop];
        }
        renderForecast();
      });
      box.appendChild(b);
    });
  }

  // One crop's series: the district observations, and the area-weighted state
  // yield per hectare for each season.
  function forecastSeries(crop) {
    var seasons = D.all_seasons || D.seasons;
    var points = [];
    var stateLine = [];

    seasons.forEach(function (season) {
      var rows = [];
      var pre = false;

      if (D.extended && D.extended[crop] && D.extended[crop][season]) {
        pre = true;
        D.extended[crop][season].forEach(function (r) {
          rows.push({
            slug: r.s, label: r.l, y: r.y, rain: r.r,
            dry: r.d, heat: r.h, area: r.a
          });
        });
      } else {
        var row = D.panel[crop] ? D.panel[crop][season] : null;
        if (row) {
          D.districts.forEach(function (d, i) {
            var v = row[i];
            if (!v) return;
            rows.push({
              slug: d.s, label: d.l, y: v[0], rain: v[2],
              dry: v[3], heat: v[5], area: v[8]
            });
          });
        }
      }

      rows.forEach(function (r) {
        points.push({
          season: season, slug: r.slug, label: r.label, y: r.y,
          rain: r.rain, dry: r.dry, heat: r.heat, area: r.area, pre: pre
        });
      });

      // the state figure: area-weighted, over the districts reporting
      var wsum = 0, wy = 0, n = 0;
      rows.forEach(function (r) {
        if (r.y === null || r.y === undefined) return;
        if (!r.area) return;
        wsum += r.area;
        wy += r.area * r.y;
        n++;
      });
      if (wsum > 0) {
        stateLine.push({
          season: season,
          y: wy / wsum,
          n: n,
          pre: pre
        });
      }
    });

    return { points: points, stateLine: stateLine };
  }

  function renderForecast() {
    if (!els.forecastChart) return;
    var fc = D.forecast || {};
    var all = forecastCrops();
    if (!all.length) {
      els.forecastChart.innerHTML = "";
      els.forecastFoot.textContent =
        "The 2026 forecast has not been computed in this build.";
      return;
    }

    renderForecastTicks();
    drawForecastChart();
    renderForecastLegend();
    renderForecastFoot();
    renderForecastTable();
  }

  function drawForecastChart() {
    var el = els.forecastChart;
    var fc = D.forecast || {};
    var seasons = D.all_seasons || D.seasons;
    var xAxis = seasons.concat(["2026"]);
    var boundaryAt = seasons.indexOf(D.primary_panel_start) - 0.5;
    var crops = tickedCrops();
    var one = crops.length === 1;

    var traces = [];
    var scaleVals = [];
    var pointVals = [];

    crops.forEach(function (crop) {
      var f = fc[crop];
      var series = forecastSeries(crop);
      var colour = cropColor(crop);
      var unit = f.unit;
      var ref = f.state.reference_yield_per_ha;
      var st = f.state;

      // the district observations, drawn only when a single crop is on the
      // chart: four crops would put more than a thousand points behind the
      // lines, which reads as noise rather than as spread
      if (one) {
        var pre = series.points.filter(function (p) { return p.pre; });
        var post = series.points.filter(function (p) { return !p.pre; });
        series.points.forEach(function (p) {
          if (p.y === null || p.y === undefined || !ref) return;
          pointVals.push(100 * p.y / ref);
        });
        traces.push(pointTrace(pre, "9 undivided parent districts (2014-15, 2015-16)",
          "#9aa1ab", 0.5, crop, unit, "pre", ref));
        traces.push(pointTrace(post, "32 post-reorganisation districts",
          colour, 0.45, crop, unit, "district", ref));
      }

      // the state line, indexed to the crop's own Telangana average
      var idx = series.stateLine.map(function (s) {
        return { season: s.season, index: ref ? 100 * s.y / ref : null, y: s.y, n: s.n };
      });
      traces.push({
        x: idx.map(function (p) { return p.season; }),
        y: idx.map(function (p) { return p.index; }),
        type: "scatter",
        mode: "lines+markers",
        line: { color: colour, width: 2.2 },
        marker: { color: colour, size: 5 },
        name: cropTitle(crop),
        customdata: idx.map(function (p) {
          return [crop, p.season, p.index, p.y, unit, p.n];
        }),
        hovertemplate:
          cropTitle(crop) + " · %{customdata[1]}<br>" +
          "state yield/area %{customdata[3]:.3f} " + "%{customdata[4]}" +
          "<br>index %{customdata[2]:.1f} (Telangana average = 100)" +
          "<br>%{customdata[5]} districts reporting<extra></extra>"
      });

      idx.forEach(function (p) {
        if (p.index !== null) scaleVals.push(p.index);
      });

      // the 2026 prediction: a DASHED segment from the last observed season
      // to the area-weighted state figure, with the point estimate marked as
      // a diamond.  The dashed segment is the forecast; the solid line before
      // it is history.
      var last = idx[idx.length - 1];
      var endIndex = ref ? 100 * st.yield_2026_per_ha / ref : null;
      if (last && endIndex !== null) {
        scaleVals.push(endIndex);
        traces.push({
          x: [last.season, "2026"],
          y: [last.index, endIndex],
          type: "scatter",
          mode: "lines",
          line: { color: colour, width: 2.2, dash: "dash" },
          name: cropTitle(crop) + " — 2026 prediction",
          showlegend: false,
          hoverinfo: "skip"
        });
        traces.push({
          x: ["2026"],
          y: [endIndex],
          type: "scatter",
          mode: "markers",
          marker: {
            color: colour, size: 11, symbol: "diamond",
            line: { color: "#fffdf9", width: 2 }
          },
          name: cropTitle(crop) + " — 2026 predicted yield/area",
          showlegend: false,
          customdata: [[crop, endIndex, st.yield_2026_per_ha, unit]],
          hovertemplate:
            cropTitle(crop) + " · 2026 predicted yield/area " +
            "%{customdata[2]:.3f} " + "%{customdata[3]}" +
            "<br>index %{customdata[1]:.1f}<extra></extra>"
        });
      }
    });

    function pointTrace(list, name, fill, opacity, crop, unit, kind, ref) {
      return {
        x: list.map(function (p) { return p.season; }),
        // the points are indexed too: the axis is an index, so a raw yield
        // would be plotted at the wrong place entirely
        y: list.map(function (p) {
          return (p.y === null || p.y === undefined || !ref) ? null : 100 * p.y / ref;
        }),
        type: "scatter",
        mode: "markers",
        marker: { color: fill, size: 5, opacity: opacity },
        name: name,
        showlegend: false,
        customdata: list.map(function (p) {
          return [kind, crop, p.slug, p.label, p.season, p.y, p.rain, p.dry, p.heat, p.area];
        }),
        hovertemplate:
          "%{customdata[3]} · %{customdata[4]}<br>" +
          "yield %{customdata[5]:.2f} " + unit + "<br>" +
          "rainfall %{customdata[6]:.0f} mm<br>" +
          "longest dry run %{customdata[7]:.0f} d · heat days %{customdata[8]:.0f}" +
          "<extra></extra>"
      };
    }

    // THE Y RANGE.  It is set from the state lines and the 2026 predictions,
    // and - when a single crop is on the chart - from the BULK of the
    // district observations, taken as the 2nd to 98th percentile.
    //
    // A percentile, not the extremes: one delivered observation (arhar,
    // Mulugu 2019-20) is 22.85 t/ha against a district norm of 0.62-0.91,
    // and letting it set the axis would flatten the whole chart to a line.
    // It is still a delivered value, so it is not deleted - it is reported in
    // the foot, and it is in the forecast table.
    var yLo = Math.min.apply(null, scaleVals);
    var yHi = Math.max.apply(null, scaleVals);
    if (pointVals.length) {
      var sortedPoints = pointVals.slice().sort(function (a, b) { return a - b; });
      yLo = Math.min(yLo, sortedPoints[Math.floor(sortedPoints.length * 0.02)]);
      yHi = Math.max(yHi, sortedPoints[Math.floor(sortedPoints.length * 0.98)]);
    }
    var yPad = (yHi - yLo) * 0.08 || 2;
    var yRange = [Math.max(0, yLo - yPad), yHi + yPad];

    // count the district observations that fall outside the plotted range, so
    // the reader is told rather than left to wonder where a point went
    var offScale = pointVals.filter(function (v) {
      return v < yRange[0] || v > yRange[1];
    }).length;

    var shapes = [
      {
        type: "line",
        x0: -0.5, x1: xAxis.length - 0.5, y0: 100, y1: 100,
        yref: "y", xref: "x",
        line: { color: "#b3ab9b", width: 1, dash: "dot" }
      }
    ];
    if (boundaryAt >= 0) {
      shapes.push({
        type: "line",
        x0: boundaryAt, x1: boundaryAt, y0: 0, y1: 1, yref: "paper",
        line: { color: "#b3ab9b", width: 1, dash: "dot" }
      });
    }

    var annotations = [
      {
        x: -0.4, y: 100,
        xref: "x", yref: "y",
        xanchor: "left", yanchor: "bottom",
        text: "Telangana average = 100",
        showarrow: false,
        font: { family: "IBM Plex Mono, monospace", size: 9, color: "#6d7481" }
      }
    ];

    Plotly.react(el, traces, {
      margin: { l: 54, r: 18, t: 10, b: 46 },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { family: "IBM Plex Sans, sans-serif", size: 10, color: "#454b55" },
      shapes: shapes,
      annotations: annotations,
      showlegend: false,
      hovermode: "closest",
      xaxis: {
        type: "category",
        categoryorder: "array",
        categoryarray: xAxis,
        tickangle: -45,
        gridcolor: "#e6e2d8",
        linecolor: "#d9d4c8",
        tickfont: { family: "IBM Plex Mono, monospace", size: 9, color: "#6d7481" }
      },
      yaxis: {
        title: {
          text: "state yield per hectare, indexed (Telangana average = 100)",
          font: { size: 10 }
        },
        range: yRange,
        gridcolor: "#e6e2d8",
        zeroline: false,
        tickfont: { family: "IBM Plex Mono, monospace", size: 9, color: "#6d7481" }
      }
    }, PLOT_CONFIG);

    // clicking a district point reads that district-season in the panel
    // below; clicking the 2026 diamond reads the crop's forecast
    el.on("plotly_click", function (ev) {
      var cd = ev && ev.points && ev.points[0] && ev.points[0].customdata;
      if (!cd || !cd.length) return;
      if (cd[0] === "pre" || cd[0] === "district") {
        showForecastPoint(cd[1], cd[2]);
      } else {
        showForecastCrop(cd[0]);
      }
    });

    els.forecastOffScale = offScale;
  }

  function renderForecastLegend() {
    var box = els.forecastLegend;
    if (!box) return;
    var crops = tickedCrops();
    var items = [];

    // the district observations are drawn only when the chart is focused on
    // one crop, so the legend does not claim marks that are not on screen
    if (crops.length === 1) {
      items.push(
        '<span class="forecast-legend__item"><span class="forecast-legend__swatch" style="background:#9aa1ab"></span>' +
        '9 undivided parent districts (2014-15, 2015-16)</span>'
      );
      items.push(
        '<span class="forecast-legend__item"><span class="forecast-legend__swatch forecast-legend__swatch--crop"></span>' +
        '32 post-reorganisation districts</span>'
      );
    }
    items.push(
      '<span class="forecast-legend__item"><span class="forecast-legend__line"></span>' +
      'state yield per hectare (area-weighted)</span>'
    );
    items.push(
      '<span class="forecast-legend__item"><span class="forecast-legend__dot"></span>' +
      'Telangana average = 100</span>'
    );
    items.push(
      '<span class="forecast-legend__item"><span class="forecast-legend__dash"></span>' +
      '2026 prediction (2022-23 area baseline)</span>'
    );
    items.push(
      '<span class="forecast-legend__item"><span class="forecast-legend__diamond"></span>' +
      '2026 predicted yield/area</span>'
    );

    var names = crops.map(function (c) { return cropTitle(c); }).join(", ");
    box.innerHTML =
      '<span class="forecast-legend__item forecast-legend__item--head">On the chart: ' +
      esc(names) + '</span>' + items.join("");
  }

  function renderForecastFoot() {
    var meta = D.forecast_meta || {};
    var crops = tickedCrops();
    var parts = [];

    parts.push(
      "Every crop is indexed to its own Telangana average over the fitted period " +
      "(2016-17 → 2022-23 = 100), so cotton in bales per hectare and the other " +
      "crops in tonnes per hectare can share one axis. The state line is " +
      "area-weighted — sum of area × yield ÷ sum of area over the districts " +
      "reporting in that season — not the unweighted mean of district yields."
    );

    parts.push(
      "The 2026 segment is a prediction from that crop's own model, not an " +
      "observation, and it is drawn dashed because nothing has been observed " +
      "for it. " +
      (meta.area_baseline_note || "")
    );

    var skills = crops.map(function (c) {
      var f = (D.forecast || {})[c];
      if (!f) return null;
      return cropTitle(c) + " " + (f.skill_rmse > 0 ? "+" : "") +
        f.skill_rmse.toFixed(3);
    }).filter(Boolean);
    if (skills.length) {
      parts.push(
        "Out-of-sample skill against the district-median baseline: " +
        skills.join(" · ") + ". A negative skill means the model does not beat " +
        "the baseline, so its prediction is read as no evidence of a change " +
        "rather than as a forecast."
      );
    }

    if (els.forecastOffScale) {
      parts.push(
        els.forecastOffScale + " district observation(s) fall outside the plotted " +
        "range and are not drawn. The scale is set by the state line, the 2026 " +
        "prediction and the 2nd-to-98th percentile of the district observations, " +
        "so that one delivered value cannot flatten the chart; every observation " +
        "is in the table below."
      );
    }

    els.forecastFoot.textContent = parts.join(" ");
  }

  /* ---------------------------------------------------------------------- *
   * The 2026 forecast table: every district against the state-wide mean
   * ---------------------------------------------------------------------- */
  function renderForecastTable() {
    var crop = state.crop;
    var f = (D.forecast || {})[crop];
    if (!f) {
      els.forecastTableBody.innerHTML = "";
      els.forecastTableSubtitle.textContent = "—";
      return;
    }
    var unit = f.unit;
    var rows = f.per_district.map(function (r) {
      return {
        label: r.label,
        slug: r.slug,
        pred: r.predicted_2026,
        state: f.state.reference_yield_per_ha,
        diff: r.pct_vs_state,
        rain: r.rain_2026_mm
      };
    });

    var key = state.forecastSort.key;
    var dir = state.forecastSort.dir;
    rows.sort(function (a, b) {
      var x = a[key], y = b[key];
      if (typeof x === "string") return x.localeCompare(y) * dir;
      if (x === null || x === undefined) return 1;
      if (y === null || y === undefined) return -1;
      return ((x || 0) - (y || 0)) * dir;
    });

    var cols = [
      { key: "label", title: "District" },
      { key: "pred", title: "2026 predicted", num: true },
      { key: "state", title: "State mean", num: true },
      { key: "diff", title: "Difference", num: true },
      { key: "rain", title: "2026 rainfall (mm)", num: true }
    ];
    var head = document.querySelector("#forecastTable thead tr");
    head.innerHTML = cols.map(function (c) {
      var aria = state.forecastSort.key === c.key
        ? ' aria-sort="' + (dir === 1 ? "ascending" : "descending") + '"' : "";
      return "<th scope='col' data-sort='" + c.key + "'" + aria +
        (c.num ? " class='num'" : "") + ">" + esc(c.title) + "</th>";
    }).join("");

    els.forecastTableBody.innerHTML = rows.map(function (r) {
      var diff = r.diff;
      var cls = "diff-cell";
      if (diff === null || diff === undefined) cls += " diff-cell--flat";
      else if (diff < 0) cls += " diff-cell--down";
      else if (diff > 0) cls += " diff-cell--up";
      else cls += " diff-cell--flat";
      var diffTxt = (diff === null || diff === undefined)
        ? "—"
        : (diff > 0 ? "+" : "") + diff.toFixed(1) + "%";
      return (
        "<tr data-slug='" + r.slug + "' tabindex='0'>" +
          "<td>" + esc(r.label) + "</td>" +
          "<td class='num'>" + fmt(r.pred, 2) + "</td>" +
          "<td class='num'>" + fmt(r.state, 2) + "</td>" +
          "<td class='num " + cls + "'>" + diffTxt + "</td>" +
          "<td class='num'>" + fmt(r.rain, 0) + "</td>" +
        "</tr>"
      );
    }).join("");

    Array.prototype.forEach.call(
      els.forecastTableBody.querySelectorAll("tr[data-slug]"),
      function (tr) {
        tr.addEventListener("click", function () {
          showForecastPoint(state.crop, tr.getAttribute("data-slug"));
        });
      }
    );
    Array.prototype.forEach.call(
      head.querySelectorAll("th[data-sort]"),
      function (th) {
        th.addEventListener("click", function () {
          var k = th.getAttribute("data-sort");
          if (state.forecastSort.key === k) {
            state.forecastSort.dir = -state.forecastSort.dir;
          } else {
            state.forecastSort.key = k;
            state.forecastSort.dir = 1;
          }
          renderForecastTable();
        });
      }
    );

    els.forecastTableSubtitle.textContent =
      "2026-27 · " + rows.length + " districts · " + unit;

    // the Mulugu footnote: a delivered data value that is retained as-is and
    // is visible in the table, so the reader can see why
    var mulugu = f.per_district.filter(function (r) {
      return r.slug === "mulugu" && unit === "t/ha";
    })[0];
    var extra = "";
    if (mulugu && mulugu.pct_vs_state !== null && mulugu.pct_vs_state > 200) {
      extra =
        " Mulugu's arhar record includes a 2019-20 cell reading 891 t on 39 ha " +
        "(22.85 t/ha against the district's 0.62–0.91 in other years). It is " +
        "retained exactly as delivered, and it inflates Mulugu's own mean and " +
        "therefore its 2026 prediction.";
    }
    els.forecastTableFoot.textContent =
      "Each district's predicted 2026 yield/area against the state-wide mean " +
      "yield/area for " + cropTitle(crop) + " — the area-weighted state figure " +
      "(sum of production ÷ sum of area over 2016-17 – 2022-23), not the " +
      "unweighted mean of district yields. Vermillion is below the state mean, " +
      "bluish-green is above, and the sign is always printed, so the colour is " +
      "never the only channel." + extra;
  }

  /* ---------------------------------------------------------------------- *
   * The point description: click a point, read that district-season
   * ---------------------------------------------------------------------- */
  function showForecastPoint(crop, slug) {
    var f = (D.forecast || {})[crop];
    if (!f) return;
    var row = f.per_district.filter(function (r) { return r.slug === slug; })[0];
    if (!row) return;
    state.forecastPoint = { crop: crop, slug: slug };

    els.forecastDetailEmpty.hidden = true;
    els.forecastDetailBody.hidden = false;

    // the district's own observed history, so the point can be read against
    // that district's own norm rather than the state's
    var own = [];
    var bySeason = D.panel[crop] || {};
    Object.keys(bySeason).forEach(function (season) {
      var rows = bySeason[season];
      D.districts.forEach(function (d, i) {
        if (d.s !== slug) return;
        var v = rows[i];
        if (v && v[0] !== null) own.push({ season: season, y: v[0], rain: v[2] });
      });
    });
    var ownMedian = null;
    if (own.length) {
      var s = own.map(function (o) { return o.y; }).sort(function (a, b) { return a - b; });
      var m = Math.floor(s.length / 2);
      ownMedian = s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
    }

    var fields = [
      ["Crop · season", cropTitle(crop) + " · 2026-27"],
      ["District", row.label],
      ["2026 predicted yield/area",
        row.predicted_2026 + " " + f.unit],
      ["Area baseline",
        "2022-23 kharif area (" + fmt(row.area_2022_23_ha, 0) + " ha)"],
      ["State average yield/area", fmt(f.state.reference_yield_per_ha, 3) + " " + f.unit],
      ["Difference vs state",
        (row.pct_vs_state > 0 ? "+" : "") + row.pct_vs_state + "%"],
      ["2026 kharif rainfall", fmt(row.rain_2026_mm, 0) + " mm"],
      ["Longest dry run", row.dry_run_max + " d"],
      ["Heat days", row.heat_days + " d"],
      ["This district's own mean yield",
        ownMedian === null ? "—" : fmt(ownMedian, 3) + " " + f.unit],
      ["Model out-of-sample skill",
        (f.skill_rmse > 0 ? "+" : "") + f.skill_rmse.toFixed(3) +
        (f.skill_rmse > 0 ? " (beats the median baseline)" : " (does not beat the median baseline)")]
    ];
    els.forecastDetailBody.innerHTML = fields.map(function (fld) {
      return "<div><dt>" + esc(fld[0]) + "</dt><dd>" + esc(String(fld[1])) + "</dd></div>";
    }).join("");
  }

  // the crop-level reading: click the 2026 diamond
  function showForecastCrop(crop) {
    var f = (D.forecast || {})[crop];
    if (!f) return;
    var st = f.state;
    state.forecastPoint = { crop: crop, slug: null };

    els.forecastDetailEmpty.hidden = true;
    els.forecastDetailBody.hidden = false;

    var rejected = (f.rejected_specs || []).length
      ? " The best-scoring specification was rejected for this crop: it returns " +
        "non-positive yields at 2026's rainfall, so a valid one is used instead."
      : "";

    var fields = [
      ["Crop · season", cropTitle(crop) + " · 2026-27"],
      ["2026 predicted yield/area",
        fmt(st.yield_2026_per_ha, 3) + " " + f.unit],
      ["Telangana average yield/area",
        fmt(st.reference_yield_per_ha, 3) + " " + f.unit],
      ["Difference vs the average",
        (st.diff_per_ha > 0 ? "+" : "") + fmt(st.diff_per_ha, 3) + " " + f.unit +
        "  (" + (st.pct_vs_reference > 0 ? "+" : "") + st.pct_vs_reference + "%)"],
      ["2026 total on the area baseline",
        fmt(st.total_2026, 0) + (st.total_unit_note ? " " + st.total_unit_note : "")],
      ["Area baseline", "2022-23 kharif area"],
      ["Model specification", f.selected_spec],
      ["Model out-of-sample skill",
        (f.skill_rmse > 0 ? "+" : "") + f.skill_rmse.toFixed(3) +
        (f.skill_rmse > 0
          ? " (beats the district-median baseline)"
          : " (does not beat the district-median baseline)") +
        rejected],
      ["2026 state-mean rainfall",
        fmt((D.marker || {}).state_mean, 0) + " mm — the " +
        fmt((D.marker || {}).percentile_in_history, 1) +
        "th percentile of the fitted range"]
    ];

    els.forecastDetailBody.innerHTML = fields.map(function (fld) {
      return "<div><dt>" + esc(fld[0]) + "</dt><dd>" + esc(String(fld[1])) + "</dd></div>";
    }).join("");
  }


  function exportCsv() {
    var rows = tableRows();
    var head = [
      "crop", "season", "district_slug", "district", "rainfall_mm",
      "yield", "yield_unit", "yield_anomaly_pct", "rain_deficit_pct",
      "longest_dry_run_days", "heat_days"
    ];
    var lines = [head.join(",")];
    rows.forEach(function (r) {
      lines.push([
        '"' + state.crop + '"',
        '"' + state.season + '"',
        '"' + r.slug + '"',
        '"' + r.label + '"',
        r.rain, r.yield, '"' + unitOf(state.crop) + '"',
        r.anomaly,
        r.deficit === null ? "" : r.deficit.toFixed(1),
        r.dry, r.heat
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
    // labels come from the bundle (src/10_build_dashboard.py -> common.CROP_LABELS)
    if (D.crop_labels && D.crop_labels[crop]) return D.crop_labels[crop];
    return crop;
  }

  // Crop identity colour (Okabe-Ito, SRS §7.1). A crop keeps the same colour
  // in every chart and in the selector strip, and switching crops never
  // repaints the others.
  function cropColor(crop) {
    if (D.crop_colors && D.crop_colors[crop]) return D.crop_colors[crop];
    return "#1f77b4";
  }

  function renderCropStrip() {
    if (!els.cropStrip) return;
    els.cropStrip.innerHTML = "";
    D.crops.forEach(function (c) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "cropchip" + (c === state.crop ? " cropchip--on" : "");
      b.setAttribute("aria-pressed", c === state.crop ? "true" : "false");
      var sw = document.createElement("span");
      sw.className = "cropchip__swatch";
      sw.style.background = cropColor(c);
      var t = document.createElement("span");
      t.textContent = cropTitle(c);
      b.appendChild(sw);
      b.appendChild(t);
      b.addEventListener("click", function () {
        state.crop = c;
        els.crop.value = c;
        state.pinned = null;
        renderAll();
      });
      els.cropStrip.appendChild(b);
    });
  }

  function renderAll() {
    renderCropStrip();
    styleAll();
    renderLegend();
    renderReadout();
    renderWindowPanel();
    renderForecast();

    els.mapNote.textContent =
      state.season + " · " + cropTitle(state.crop) + " · " +
      (state.metric === "anomaly" ? "yield anomaly (%)"
       : state.metric === "deficit" ? "rainfall deficit (%)"
       : "absolute yield (" + unitOf(state.crop) + ")");

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
          " districts sit below that observed minimum, so the prediction is an " +
          "extrapolation below the fitted range, not an interpolation.";
      }
      els.markerDisclaimer.textContent = META.disclosures.not_forecast + extra;
    } else {
      els.markerDisclaimer.hidden = true;
    }
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
      d.agency, d.cotton, d.sample, d.not_forecast,
      d.forecast_method, d.forecast_area, d.forecast_specimens,
      d.attribution, d.percentiles
    ].filter(function (t) { return !!t; });
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

    // --- font gate ---------------------------------------------------------
    // The webfonts are self-hosted with font-display: swap, so the browser
    // paints with a fallback face first and swaps in IBM Plex a moment
    // later.  Plotly measures an annotation's text at render time and sizes
    // the background box to that measurement, so a chart drawn before the
    // real font arrives gets a box sized for the FALLBACK metrics - and the
    // text then overflows its own box once the font swaps in.
    //
    // So: wait for the fonts, then render.  The timeout is a safety net so a
    // font that never arrives still produces a page, and a second pass
    // re-renders if the fonts settle after the first draw.
    var fontsReady = (document.fonts && document.fonts.ready)
      ? Promise.race([
          document.fonts.ready,
          new Promise(function (resolve) { setTimeout(resolve, 1500); })
        ])
      : Promise.resolve();
    fontsReady.then(function () {
      renderAll();
      if (document.fonts && document.fonts.ready) {
        document.fonts.ready.then(function () { renderAll(); });
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
