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
   * Colour ramps, fixed by the project colour system: RdYlBu (diverging,
   * zero at the midpoint) for anomaly, YlOrRd for a rainfall shortfall, and
   * Blues for absolute yield - never the red ramp, which must not be able to
   * mean "good".
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
  // not a DES season: nothing has been observed for it, so it is labelled a
  // prediction wherever it appears
  var SEASON_2026 = "2026-27";

  var state = {
    crop: D.modelled_crops[0],
    season: SEASON_2026,
    metric: "yield",
    pinned: null,
    // the crops ticked in the forecast chart; null means "all of them"
    forecastCrops: null,
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
    forecastChart: document.getElementById("forecastChart"),
    forecastTicks: document.getElementById("forecastTicks"),
    forecastLegend: document.getElementById("forecastLegend"),
    forecastFoot: document.getElementById("forecastFoot"),
    forecastOffScale: 0,
    forecastDetail: document.getElementById("forecastDetail"),
    forecastDetailTitle: document.getElementById("forecastDetailTitle"),
    forecastReadout: document.getElementById("forecastReadout"),
    forecastDetailBody: document.getElementById("forecastDetailBody"),
    stateSummaryBody: document.querySelector("#stateSummary tbody"),
    stateSummaryNote: document.getElementById("stateSummaryNote"),
    dataVersion: document.getElementById("dataVersion")
  };

  var PLOT_CONFIG = {
    displaylogo: false,
    responsive: true,
    modeBarButtonsToRemove: ["select2d", "lasso2d", "autoScale2d", "toggleSpikelines"]
  };

  // One hover label for every chart.  Plotly reads hoverlabel from the
  // LAYOUT; in the config it is ignored.  Opaque surface plus a shadow, so a
  // label over the plotted lines still reads as a label and not a hole.
  var HOVER_LABEL = {
    bgcolor: "#fffdf9",
    bordercolor: "#b3ab9b",
    borderwidth: 1,
    font: {
      family: "'IBM Plex Sans', sans-serif",
      size: 11,
      color: "#16181d"
    }
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
    if (isForecastSeason()) return forecastValueForDistrict(slug);
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

  /* ---------------------------------------------------------------------- *
   * The 2026 layer.  There are no 2026 yield observations, so every value
   * under the 2026-27 season is a prediction, and the layer is labelled as
   * one wherever it appears.
   * ---------------------------------------------------------------------- */
  function isForecastSeason() {
    return state.season === SEASON_2026;
  }

  function forecastFor(crop) {
    return (D.forecast || {})[crop] || null;
  }

  function forecastRow(crop, slug) {
    var f = forecastFor(crop);
    if (!f) return null;
    var hit = null;
    f.per_district.forEach(function (r) {
      if (r.slug === slug) hit = r;
    });
    return hit;
  }

  // the district's own mean observed yield, the reference its prediction is
  // read against
  function districtOwnMeanYield(crop, slug) {
    var bySeason = D.panel[crop] || {};
    var vals = [];
    D.districts.forEach(function (d, i) {
      if (d.s !== slug) return;
      Object.keys(bySeason).forEach(function (season) {
        var v = bySeason[season][i];
        if (v && v[0] !== null && v[0] !== undefined) vals.push(v[0]);
      });
    });
    if (!vals.length) return null;
    var sum = vals.reduce(function (a, b) { return a + b; }, 0);
    return sum / vals.length;
  }

  function forecastValueForDistrict(slug) {
    var row = forecastRow(state.crop, slug);
    if (!row) return null;
    if (state.metric === "yield") return row.predicted_2026;
    if (state.metric === "anomaly") {
      // the prediction against that district's OWN observed mean yield
      var own = districtOwnMeanYield(state.crop, slug);
      if (!own) return null;
      return 100.0 * (row.predicted_2026 / own - 1.0);
    }
    // rainfall deficit: the 2026 rainfall against this district's own median
    var ref = districtRefMedian(slug);
    var rain = (D.marker || {}).per_district
      ? D.marker.per_district[slug] : null;
    if (ref === null || !rain) return null;
    return 100.0 * (1.0 - rain / ref);
  }

  function districtRefMedian(slug) {
    var d = D.districts.find(function (x) { return x.s === slug; });
    return d && d.rmed !== undefined && d.rmed !== null ? d.rmed : null;
  }

  function domainFor() {
    // The prediction layer has its own fixed domain, so that the 2026
    // predictions - which occupy the middle of the observed range - are not
    // all compressed into one pale band of the observed scale.  It is still
    // fixed: it does not move with the selection.
    var d26 = D.domains_2026 || null;
    if (isForecastSeason() && d26) {
      if (state.metric === "deficit") return d26.deficit || [-100, 100];
      var crop26 = d26[state.crop] || null;
      if (crop26) {
        if (state.metric === "anomaly" && crop26.anomaly) return crop26.anomaly;
        if (state.metric === "yield") return crop26.yield;
      }
    }
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
    if (isForecastSeason()) {
      var fr = forecastRow(state.crop, slug);
      if (!fr) {
        hoverCard.innerHTML =
          "<strong>" + esc(districtLabel(slug)) + "</strong><br>No prediction for 2026";
      } else {
        var f = forecastFor(state.crop);
        hoverCard.innerHTML =
          "<strong>" + esc(districtLabel(slug)) + "</strong><br>" +
          "2026-27 · prediction<br>" +
          "predicted yield/area " + fmt(fr.predicted_2026, 2) + " " + f.unit + "<br>" +
          "state average " + fmt(f.state.reference_yield_per_ha, 2) + " " + f.unit +
          " (" + (fr.pct_vs_state > 0 ? "+" : "") + fr.pct_vs_state + "% vs the state)<br>" +
          "2026 kharif rainfall " + fmt(fr.rain_2026_mm, 0) + " mm" +
          (districtRefMedian(slug) !== null
            ? "<br>vs own median " + fmt(districtRefMedian(slug), 0) + " mm (" +
              fmt(100 * (1 - fr.rain_2026_mm / districtRefMedian(slug)), 0) + "% deficit)"
            : "") + "<br>" +
          "area baseline " + fmt(fr.area_2022_23_ha, 0) + " ha (2022-23)";
      }
      positionHoverCard(evt);
      return;
    }
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
    positionHoverCard(evt);
  }

  function positionHoverCard(evt) {
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
    // the 2026 layer has its own fixed domain, so the caption says so rather
    // than claiming the scale is the observed one
    var scope = isForecastSeason()
      ? "the fixed domain of the 2026 prediction for this crop, not the observed range — " +
        "the predictions occupy the middle of the observed range and would otherwise all land in one pale band"
      : "fixed domain across every season — the scale never rescales";
    els.legendCaption.textContent =
      state.metric === "anomaly"
        ? "Colormap " + name + ", " + scope + ". " +
          "Blue is below normal, cream is normal, red is above normal. Districts with no observation are grey."
        : state.metric === "deficit"
        ? "Colormap " + name + ", " + scope + ". " +
          "Rainfall this season against that district's own 2016-17–2022-23 median: " +
          "a positive value is a shortfall and dark red is a large one, so the scale reads as drought severity. " +
          "The reference is each district's own norm, so the map shows where a season was dry " +
          "for that district rather than for the state. Districts with no observation are grey."
        : "Colormap " + name + ", " + scope + ". Absolute yield across Telangana is " +
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

    /* The 2026 point, on the same chart and the same axis.  It is drawn
     * DASHED, exactly as on the forecast chart, because nothing has been
     * observed for it: the rainfall is ERA5 reanalysis for a season that has
     * not happened, and the yield is a model prediction.  The band keeps the
     * same meaning - the p10-p90 range across the districts. */
    var f26 = forecastFor(crop);
    if (f26) {
      var vals26 = [];
      if (kind === "rain") {
        var pd26 = (D.marker || {}).per_district || {};
        Object.keys(pd26).forEach(function (k) { vals26.push(pd26[k]); });
      } else {
        f26.per_district.forEach(function (r) {
          if (r.predicted_2026 !== null && r.predicted_2026 !== undefined) {
            vals26.push(r.predicted_2026);
          }
        });
      }
      if (vals26.length) {
        vals26.sort(function (a, b) { return a - b; });
        function quantile(q) {
          var pos = (vals26.length - 1) * q;
          var lo = Math.floor(pos), hi = Math.ceil(pos);
          return vals26[lo] + (vals26[hi] - vals26[lo]) * (pos - lo);
        }
        var p10 = quantile(0.1), p50 = quantile(0.5), p90 = quantile(0.9);
        var lastX = x[x.length - 1];
        var lastMid = mid[mid.length - 1];

        // the band polygon is rebuilt with the 2026 category added, so the
        // band keeps its meaning: the p10-p90 range across the districts
        traces[0].x = x.concat([SEASON_2026], x.slice().reverse());
        traces[0].y = hi.concat([p90], lo.slice().reverse());

        traces.push({
          x: [lastX, SEASON_2026],
          y: [lastMid, p50],
          type: "scatter",
          mode: "lines",
          line: { color: colour, width: 2, dash: "dash" },
          showlegend: false,
          hoverinfo: "skip"
        });
        traces.push({
          x: [SEASON_2026],
          y: [p50],
          type: "scatter",
          mode: "markers",
          marker: {
            color: colour, size: 9, symbol: "diamond",
            line: { color: "#fffdf9", width: 2 }
          },
          name: "2026 prediction",
          showlegend: false,
          hovertemplate:
            "2026-27 · prediction<br>median %{y:.1f} " + unit +
            "<br>p10–p90 " + p10.toFixed(1) + "–" + p90.toFixed(1) + " " + unit +
            "<extra></extra>"
        });
      }
    }

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
      hoverlabel: HOVER_LABEL,
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
  function countRows() {
    var rows = panelFor(state.crop, state.season) || [];
    return rows.filter(function (r) { return !!r; }).length;
  }


  /* ---------------------------------------------------------------------- *
   * The rows behind the CSV export.  The on-screen district table was
   * retired in v1.2.0, but the export still ships the same rows.
   * ---------------------------------------------------------------------- */
  function tableRows() {
    var out = [];

    // the 2026 layer: the predictions, not observations
    if (isForecastSeason()) {
      var f = forecastFor(state.crop);
      if (f) {
        f.per_district.forEach(function (r) {
          var ref = districtRefMedian(r.slug);
          out.push({
            slug: r.slug,
            label: r.label,
            rain: r.rain_2026_mm,
            yield: r.predicted_2026,
            anomaly: r.pct_vs_state,
            dry: r.dry_run_max,
            heat: r.heat_days,
            deficit: ref && r.rain_2026_mm
              ? 100 * (1 - r.rain_2026_mm / ref) : null
          });
        });
      }
      return out;
    }

    var rows = panelFor(state.crop, state.season) || [];
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
   * The 2026 forecast.
   *
   * Three rules decide how this chart is drawn, and each is stated once here
   * and once in the foot the reader can see.
   *
   * The y axis is INDEXED: cotton is in bales per hectare and the rest in
   * tonnes, so each crop is indexed to its own state average (2016-17 to
   * 2022-23 = 100).
   *
   * The state line is AREA-WEIGHTED, sum(yield x area) / sum(area).  The
   * unweighted mean of district yields is not comparable across the 2016
   * reorganisation; a state total over a state area is the same quantity on
   * both sides of it.
   *
   * The x axis is CATEGORICAL, nine observed seasons and then 2026 as its own
   * step: on a continuous axis 2026 would fall to the LEFT of the record,
   * which reads as "before 2014" rather than as a season yet to happen.
   * ---------------------------------------------------------------------- */

  // The reading shown before anything is clicked.  Rice, because it is the
  // one crop whose model beats its own baseline out of sample, so the panel
  // opens on a prediction that earned the right to be quoted; cotton and
  // moong are still one click away, and their diamonds carry the negative
  // skill.
  var DEFAULT_READING_CROP = "Rice";

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
      els.forecastFoot.innerHTML =
        '<p class="forecast-foot__item">The 2026 forecast has not been ' +
        'computed in this build.</p>';
      setForecastSplit(false);
      return;
    }

    renderForecastTicks();
    drawForecastChart();
    renderForecastLegend();
    renderForecastFoot();

    // keep whatever is being read across a re-render (a crop tick changes
    // the chart, not the reading); on the first render, show the default
    if (!state.forecastPoint) {
      if (fc[DEFAULT_READING_CROP]) showForecastCrop(DEFAULT_READING_CROP);
      else showForecastCrop(all[0]);
    } else if (state.forecastPoint.slug) {
      showForecastPoint(state.forecastPoint.crop, state.forecastPoint.slug);
    } else {
      showForecastCrop(state.forecastPoint.crop);
    }

    renderStateSummary();
  }

  function drawForecastChart() {
    var el = els.forecastChart;
    var fc = D.forecast || {};
    var seasons = D.all_seasons || D.seasons;
    var xAxis = seasons.concat([SEASON_2026]);
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
          x: [last.season, SEASON_2026],
          y: [last.index, endIndex],
          type: "scatter",
          mode: "lines",
          line: { color: colour, width: 2.2, dash: "dash" },
          name: cropTitle(crop) + " — 2026 prediction",
          showlegend: false,
          hoverinfo: "skip"
        });
        traces.push({
          x: [SEASON_2026],
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
            cropTitle(crop) + " · 2026-27 predicted yield/area " +
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
      hoverlabel: HOVER_LABEL,
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
      'Telangana yield per hectare</span>'
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

  // The explanation under the chart.  Four headed items rather than one
  // paragraph: a reader who wants the axis rule should not have to read the
  // skill scores to find it.
  function renderForecastFoot() {
    var meta = D.forecast_meta || {};
    var crops = tickedCrops();
    var items = [];

    items.push(
      footItem("How to read the axis",
        "Each crop is indexed to its own Telangana average over the fitted " +
        "period (2016-17 → 2022-23 = 100). Cotton is measured in bales per " +
        "hectare and the other three in tonnes, which is how four crops " +
        "share one axis. The dotted line is 100; the vertical dotted rule " +
        "marks the 2016 reorganisation, after which the districts are not " +
        "the same units as before it.")
    );

    items.push(
      footItem("The state line",
        "Area-weighted — total yield ÷ total area over the districts " +
        "reporting that season — not the unweighted mean of district yields, " +
        "which would weigh a 720 ha district like a 129,633 ha one.")
    );

    items.push(
      footItemWide("The 2026 segment",
        "A prediction from that crop's own model, drawn dashed because " +
        "nothing has been observed for it. " + (meta.area_baseline_note || ""))
    );

    var skills = crops.map(function (c) {
      var f = (D.forecast || {})[c];
      if (!f) return "";
      var cls = f.skill_rmse < 0 ? " forecast-foot__skill--down"
                                 : " forecast-foot__skill--up";
      return '<div class="forecast-foot__skill' + cls + '"><span>' +
        esc(cropTitle(c)) + "</span><span>" +
        (f.skill_rmse > 0 ? "+" : "") + f.skill_rmse.toFixed(3) +
        "</span></div>";
    }).filter(Boolean);

    if (skills.length) {
      items.push(
        footItem("How well the model does",
          '<dl>' + skills.join("") + "</dl>" +
          "<p>Out of sample, against the district's own median. A negative " +
          "score means the model loses to that median, so read the prediction " +
          "as no evidence of a change.</p>")
      );
    }

    if (els.forecastOffScale) {
      items.push(
        footItem("Not drawn",
          els.forecastOffScale + " district observation(s) fall outside the " +
          "plotted range and are not shown here. The scale is set by the " +
          "state line, the 2026 prediction and the 2nd-to-98th percentile of " +
          "the district observations, so that one delivered value cannot " +
          "flatten the chart. Every observation is in the CSV export.")
      );
    }

    els.forecastFoot.innerHTML = items.join("");
  }

  function footItem(title, body) {
    return footItemEl("", title, body);
  }

  function footItemWide(title, body) {
    return footItemEl(" forecast-foot__item--wide", title, body);
  }

  function footItemEl(mod, title, body) {
    return '<div class="forecast-foot__item' + mod + '">' +
      '<h3 class="forecast-foot__title">' + esc(title) + "</h3>" + body + "</div>";
  }

  // The row is one column until the reading has something to say, so an empty
  // panel does not leave a blank column beside the explanation.
  function setForecastSplit(on) {
    if (!els.forecastReadout) return;
    els.forecastReadout.classList.toggle("forecast-readout--split", !!on);
  }

  /* ---------------------------------------------------------------------- *
   * The 2026 forecast table: every district against the state-wide mean
   * ---------------------------------------------------------------------- */
  /* ---------------------------------------------------------------------- *
   * The state in one table: the 2026 totals for the four crops and the
   * kharif rainfall, against the Telangana average.  The crop name is the
   * parent header; 2026 and the state average are the two columns under it.
   * ---------------------------------------------------------------------- */
  function millions(value) {
    // everything is in millions, with enough decimals to stay meaningful:
    // moong is 20 thousand tonnes, which two decimals would round to
    // nothing
    var m = value / 1e6;
    var digits = Math.abs(m) >= 1 ? 2 : 3;
    return m.toFixed(digits);
  }

  function renderStateSummary() {
    var body = els.stateSummaryBody;
    if (!body) return;
    var fc = D.forecast || {};
    var crops = forecastCrops();
    if (!crops.length) {
      body.innerHTML = "";
      els.stateSummaryNote.textContent = "The 2026 forecast has not been computed in this build.";
      return;
    }

    var rows = crops.map(function (crop) {
      var f = fc[crop];
      var st = f.state;
      var unit = f.unit;
      var isBales = unit === "bales/ha";
      var unitLabel = isBales ? "M bales" : "M t";
      var pct = st.pct_vs_reference;
      var cls = pct < 0 ? "diff-cell--down" : (pct > 0 ? "diff-cell--up" : "diff-cell--flat");
      return {
        label: cropTitle(crop),
        value: millions(st.total_2026) + " " + unitLabel,
        avg: millions(st.reference_total_same_area) + " " + unitLabel,
        delta: (pct > 0 ? "\u2191" : pct < 0 ? "\u2193" : "") + Math.abs(pct).toFixed(1) + "%",
        cls: cls
      };
    });

    // the kharif rainfall: the state mean for 2026 against the state-wise
    // average over the nine observed seasons
    var rs = D.rain_state || null;
    var mk = D.marker || null;
    if (rs && mk && mk.available) {
      var base = rs.avg_9season;
      var now = mk.state_mean;
      var pctR = 100.0 * (now / base - 1.0);
      rows.push({
        label: "Kharif rainfall",
        value: fmt(now, 0) + " mm",
        avg: fmt(base, 0) + " mm",
        delta: (pctR > 0 ? "\u2191" : "\u2193") + Math.abs(pctR).toFixed(1) + "%",
        cls: pctR < 0 ? "diff-cell--down" : "diff-cell--up"
      });
    }

    body.innerHTML = rows.map(function (r) {
      return (
        "<tr>" +
          "<th scope='row' class='state-summary__crop'>" + esc(r.label) + "</th>" +
          "<td class='num'>" + esc(r.value) +
            "<span class='state-summary__delta " + r.cls + "'>" + esc(r.delta) + "</span>" +
          "</td>" +
          "<td class='num'>" + esc(r.avg) + "</td>" +
        "</tr>"
      );
    }).join("");

    els.stateSummaryNote.textContent =
      "Totals are for the whole state: the 2026 prediction is the area-weighted " +
      "yield per hectare applied to each district's 2022-23 kharif area, and the " +
      "average is the Telangana average on that same area, so the two columns " +
      "differ only by the model's skill. Rainfall is the state mean; the average " +
      "is the mean of the nine seasonal state means, 2014-15 to 2022-23 (" +
      fmt(rs ? rs.avg_9season : 0, 0) + " mm).";
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

    if (els.forecastDetailTitle) {
      els.forecastDetailTitle.textContent =
        cropTitle(crop) + " · " + districtLabel(slug);
    }
    setForecastSplit(true);

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

    if (els.forecastDetailTitle) {
      els.forecastDetailTitle.textContent = cropTitle(crop) + " · 2026-27 prediction";
    }
    setForecastSplit(true);

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
    var nDistricts = vals.length;
    if (isForecastSeason()) {
      var f = forecastFor(state.crop);
      nDistricts = f ? f.per_district.length : 0;
    }
    var pinned = state.pinned ? districtValue(state.crop, state.season, state.pinned) : null;

    els.readNote.textContent =
      (isForecastSeason() ? state.season + " (prediction)" : state.season) +
      " · " + nDistricts + " districts" +
      (isForecastSeason() ? " predicted" : " observed") +
      (pinned ? " · pinned: " + districtLabel(state.pinned) : "");

    els.yieldTitle.innerHTML =
      '<span class="icon icon--yield" aria-hidden="true"></span>' +
      esc(cropTitle(state.crop)) + " yield";

    bandAndLine(els.rainChart, state.crop, "rain");
    bandAndLine(els.yieldChart, state.crop, "yield");
  }

  function cropTitle(crop) {
    // labels come from the bundle (src/10_build_dashboard.py -> common.CROP_LABELS)
    if (D.crop_labels && D.crop_labels[crop]) return D.crop_labels[crop];
    return crop;
  }

  // Crop identity colour (Okabe-Ito). A crop keeps the same colour
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
    renderForecast();

    els.mapNote.textContent =
      (isForecastSeason() ? state.season + " (prediction)" : state.season) +
      " · " + cropTitle(state.crop) + " · " +
      (state.metric === "anomaly" ? "yield anomaly (%)"
       : state.metric === "deficit" ? "rainfall deficit (%)"
       : "absolute yield (" + unitOf(state.crop) + ")");
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
    // the 2026 prediction is not a DES season: there are no 2026 yield
    // observations, so it is offered as a separate, labelled option
    if (D.forecast && Object.keys(D.forecast).length) {
      var opt26 = document.createElement("option");
      opt26.value = SEASON_2026;
      opt26.textContent = "2026-27 (prediction)";
      els.season.appendChild(opt26);
    }
    els.season.value = state.season;
    els.metric.value = state.metric;

    els.dataVersion.textContent = META.data_version;
  }

  function init() {
    populateControls();
    initMap();

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

    // Plotly sizes a label's box to the face it measures with, so drawing
    // before the webfont arrives boxes the text for a fallback face.  Wait
    // for the fonts; the timeout is only a safety net.
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
