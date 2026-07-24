(function () {
  "use strict";

  function prep(canvas) {
    const dpr = devicePixelRatio || 1;
    const w = canvas.clientWidth || canvas.width;
    const h = canvas.clientHeight || canvas.height;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx, w, h };
  }

  function bounds(vals, pad) {
    let min = Infinity;
    let max = -Infinity;
    for (const v of vals) {
      if (v < min) min = v;
      if (v > max) max = v;
    }
    if (!Number.isFinite(min)) return { min: -1, max: 1 };
    if (min === max) return { min: min - 1, max: max + 1 };
    const p = (max - min) * (pad ?? 0.14);
    return { min: min - p, max: max + p };
  }

  function drawGlowTrace(canvas, opts) {
    const { ctx, w, h } = prep(canvas);
    ctx.clearRect(0, 0, w, h);

    // dark panel
    const g = ctx.createLinearGradient(0, 0, w, h);
    g.addColorStop(0, "rgba(4,10,18,0.95)");
    g.addColorStop(1, "rgba(10,8,20,0.95)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, w, h);

    const plot = { l: 48, t: 28, w: w - 70, h: h - 56 };
    const times = opts.times;
    const mean = opts.mean;
    const sem = opts.sem;
    const color = opts.color || "#00f5d4";
    const x0 = times[0];
    const x1 = times[times.length - 1];

    const ys = [];
    if (opts.individuals) {
      for (const row of opts.individuals) for (const v of row) ys.push(v);
    } else {
      for (let i = 0; i < mean.length; i += 1) {
        ys.push(mean[i]);
        if (sem) {
          ys.push(mean[i] + sem[i], mean[i] - sem[i]);
        }
      }
    }
    const yb = bounds(ys);

    const X = (t) => plot.l + ((t - x0) / (x1 - x0)) * plot.w;
    const Y = (v) => plot.t + ((yb.max - v) / (yb.max - yb.min)) * plot.h;

    // grid
    ctx.strokeStyle = "rgba(100,140,180,0.08)";
    for (let i = 0; i <= 4; i += 1) {
      const y = plot.t + (plot.h * i) / 4;
      ctx.beginPath();
      ctx.moveTo(plot.l, y);
      ctx.lineTo(plot.l + plot.w, y);
      ctx.stroke();
    }

    // baseline band
    if (opts.baseline) {
      const a = X(opts.baseline[0]);
      const b = X(opts.baseline[1]);
      ctx.fillStyle = "rgba(0,245,212,0.07)";
      ctx.fillRect(a, plot.t, Math.max(1, b - a), plot.h);
    }

    // zero
    if (x0 < 0 && x1 > 0) {
      const zx = X(0);
      ctx.strokeStyle = "rgba(255,45,149,0.55)";
      ctx.setLineDash([5, 5]);
      ctx.beginPath();
      ctx.moveTo(zx, plot.t);
      ctx.lineTo(zx, plot.t + plot.h);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    if (opts.individuals) {
      ctx.globalAlpha = Math.min(0.28, 10 / Math.max(opts.individuals.length, 1));
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      for (const row of opts.individuals) {
        ctx.beginPath();
        for (let i = 0; i < times.length; i += 1) {
          const x = X(times[i]);
          const y = Y(row[i]);
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }

    if (sem && !opts.individuals) {
      ctx.beginPath();
      for (let i = 0; i < times.length; i += 1) ctx.lineTo(X(times[i]), Y(mean[i] + sem[i]));
      for (let i = times.length - 1; i >= 0; i -= 1) ctx.lineTo(X(times[i]), Y(mean[i] - sem[i]));
      ctx.closePath();
      ctx.fillStyle = color + "33";
      ctx.fill();
    }

    // glow pass
    ctx.save();
    ctx.shadowColor = color;
    ctx.shadowBlur = 18;
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2.6;
    ctx.lineJoin = "round";
    for (let i = 0; i < times.length; i += 1) {
      const x = X(times[i]);
      const y = Y(mean[i]);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.restore();

    // crisp pass
    ctx.beginPath();
    ctx.strokeStyle = "#eafffb";
    ctx.globalAlpha = 0.35;
    ctx.lineWidth = 1;
    for (let i = 0; i < times.length; i += 1) {
      const x = X(times[i]);
      const y = Y(mean[i]);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.globalAlpha = 1;

    ctx.fillStyle = "rgba(139,163,184,0.85)";
    ctx.font = "11px JetBrains Mono, monospace";
    ctx.fillText(x0.toFixed(1) + "s", plot.l, plot.t + plot.h + 18);
    ctx.textAlign = "right";
    ctx.fillText(x1.toFixed(1) + "s", plot.l + plot.w, plot.t + plot.h + 18);
    ctx.textAlign = "left";
  }

  function heatColor(t) {
    // cyan -> violet -> magenta fire
    const stops = [
      [8, 12, 28],
      [0, 80, 90],
      [0, 245, 212],
      [139, 92, 255],
      [255, 45, 149],
      [255, 230, 120],
    ];
    const x = Math.min(1, Math.max(0, t)) * (stops.length - 1);
    const i = Math.floor(x);
    const f = x - i;
    const a = stops[i];
    const b = stops[Math.min(stops.length - 1, i + 1)];
    return `rgb(${Math.round(a[0] + (b[0] - a[0]) * f)},${Math.round(a[1] + (b[1] - a[1]) * f)},${Math.round(a[2] + (b[2] - a[2]) * f)})`;
  }

  function drawHeat(canvas, opts) {
    const { ctx, w, h } = prep(canvas);
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = "rgba(4,8,16,0.95)";
    ctx.fillRect(0, 0, w, h);
    const matrix = opts.matrix || [];
    if (!matrix.length) {
      ctx.fillStyle = "#8ba3b8";
      ctx.font = "12px JetBrains Mono, monospace";
      ctx.fillText("no trials selected", 16, 28);
      return;
    }
    const plot = { l: 10, t: 10, w: w - 20, h: h - 20 };
    let min = Infinity;
    let max = -Infinity;
    for (const row of matrix) for (const v of row) {
      if (v < min) min = v;
      if (v > max) max = v;
    }
    if (min === max) {
      min -= 1;
      max += 1;
    }
    const rows = matrix.length;
    const cols = matrix[0].length;
    const cw = plot.w / cols;
    const ch = plot.h / rows;
    for (let r = 0; r < rows; r += 1) {
      for (let c = 0; c < cols; c += 1) {
        const t = (matrix[r][c] - min) / (max - min);
        ctx.fillStyle = heatColor(t);
        ctx.fillRect(plot.l + c * cw, plot.t + r * ch, Math.ceil(cw), Math.ceil(ch));
      }
    }
    // zero marker
    const times = opts.times;
    if (times && times[0] < 0 && times[times.length - 1] > 0) {
      const zx = plot.l + ((0 - times[0]) / (times[times.length - 1] - times[0])) * plot.w;
      ctx.strokeStyle = "rgba(255,255,255,0.55)";
      ctx.beginPath();
      ctx.moveTo(zx, plot.t);
      ctx.lineTo(zx, plot.t + plot.h);
      ctx.stroke();
    }
  }

  function subset(channel, indices) {
    if (!indices.length) {
      const z = new Float64Array(channel.mean.length);
      return { mean: z, sem: z, rows: [] };
    }
    const rows = indices.map((i) => channel.trials[i]);
    const n = rows.length;
    const m = rows[0].length;
    const mean = new Float64Array(m);
    const sem = new Float64Array(m);
    for (let j = 0; j < m; j += 1) {
      let s = 0;
      for (let i = 0; i < n; i += 1) s += rows[i][j];
      mean[j] = s / n;
    }
    if (n > 1) {
      for (let j = 0; j < m; j += 1) {
        let ss = 0;
        for (let i = 0; i < n; i += 1) {
          const d = rows[i][j] - mean[j];
          ss += d * d;
        }
        sem[j] = Math.sqrt(ss / (n - 1)) / Math.sqrt(n);
      }
    }
    return { mean, sem, rows };
  }

  function peakLatency(times, mean) {
    let best = -Infinity;
    let idx = 0;
    for (let i = 0; i < mean.length; i += 1) {
      if (times[i] >= 0 && mean[i] > best) {
        best = mean[i];
        idx = i;
      }
    }
    return { peak: best, lat: times[idx] };
  }

  window.AuroraPlots = { drawGlowTrace, drawHeat, subset, peakLatency };
})();
