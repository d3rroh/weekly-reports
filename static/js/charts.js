/* Performance charts built only from server-supplied saved values. */
(function () {
  "use strict";
  var source = document.getElementById("chart-data");
  if (!source || typeof Chart === "undefined") { return; }
  var payload = JSON.parse(source.textContent);
  var points = payload.points || [];
  var metrics = payload.metrics || [];

  var css = getComputedStyle(document.documentElement);
  var accent = css.getPropertyValue("--accent").trim() || "#2856c7";
  var muted = css.getPropertyValue("--muted").trim() || "#5c6575";
  var grid = css.getPropertyValue("--border").trim() || "#dfe3ea";
  var navy = css.getPropertyValue("--navy-500").trim() || "#4a5d7c";

  Chart.defaults.font.family = css.getPropertyValue("--font");
  Chart.defaults.font.size = 11;
  Chart.defaults.color = muted;

  function fmt(v, unit) {
    if (v === null || v === undefined) { return "Not available"; }
    if (unit === "%") { return v.toFixed(1) + "%"; }
    if (unit === "min") { return v.toFixed(1) + " min"; }
    return Math.round(v).toLocaleString();
  }

  // Index of the latest and previous periods that have values (to distinguish them).
  function lastTwo(values) {
    var idx = [];
    for (var i = values.length - 1; i >= 0 && idx.length < 2; i--) {
      if (values[i] !== null) { idx.push(i); }
    }
    return { current: idx[0], previous: idx[1] };
  }

  function yScale(metric, values) {
    var present = values.filter(function (v) { return v !== null; });
    var scale = { grid: { color: grid }, title: { display: true, text: metric.unit === "calls" ? "calls" : metric.unit } };
    if (metric.unit === "%") {
      var lo = present.length ? Math.min.apply(null, present) : 0;
      // Bounded percentage axis: never above 100, lower bound rounded down
      // to a multiple of 10 with headroom so small changes are not exaggerated.
      scale.min = Math.max(0, Math.floor((lo - 10) / 10) * 10);
      scale.max = 100;
    } else {
      scale.beginAtZero = true;
    }
    return scale;
  }

  document.querySelectorAll("canvas[data-metric]").forEach(function (canvas) {
    var key = canvas.getAttribute("data-metric");
    var metric = metrics.filter(function (m) { return m.key === key; })[0];
    if (!metric) { return; }
    var values = points.map(function (p) { return p.values[key]; });
    var marks = lastTwo(values);
    var compact = canvas.hasAttribute("data-compact");

    new Chart(canvas, {
      type: metric.unit === "calls" ? "bar" : "line",
      data: {
        labels: points.map(function (p) { return p.label; }),
        datasets: [{
          label: metric.label,
          data: values,
          spanGaps: false,
          borderColor: accent,
          backgroundColor: values.map(function (_, i) {
            return i === marks.current ? accent : (i === marks.previous ? navy : "rgba(40,86,199,.35)");
          }),
          pointBackgroundColor: values.map(function (_, i) {
            return i === marks.current ? accent : "#fff";
          }),
          pointBorderColor: values.map(function (_, i) { return i === marks.previous ? navy : accent; }),
          pointRadius: values.map(function (_, i) {
            return i === marks.current ? 5 : (i === marks.previous ? 4 : (compact ? 2 : 3));
          }),
          pointBorderWidth: 2,
          borderWidth: 2,
          tension: 0
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: function (items) { return points[items[0].dataIndex].range; },
              label: function (item) {
                var p = points[item.dataIndex];
                if (!p.has_report) { return "No report for this period"; }
                var v = p.values[key];
                var tag = item.dataIndex === marks.current ? " (latest)" : (item.dataIndex === marks.previous ? " (previous)" : "");
                return metric.label + ": " + (v === null ? "Not entered" : fmt(v, metric.unit)) + tag;
              },
              afterLabel: function (item) {
                var p = points[item.dataIndex];
                return p.status ? "Status: " + p.status : "";
              }
            }
          }
        },
        scales: {
          x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: compact ? 6 : 13 } },
          y: yScale(metric, values)
        }
      }
    });
  });
})();
