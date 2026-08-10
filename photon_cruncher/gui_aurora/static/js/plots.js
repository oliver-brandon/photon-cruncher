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

  function formatTick(value) {
    const absolute = Math.abs(value);
    if (absolute >= 100) return value.toFixed(0);
    if (absolute >= 10) return value.toFixed(1);
    return value.toFixed(2).replace(/\.00$/, "");
  }

  function clippedText(ctx, value, maxWidth) {
    const text = String(value || "");
    if (ctx.measureText(text).width <= maxWidth) return text;
    let clipped = text;
    while (clipped.length > 1 && ctx.measureText(`${clipped}…`).width > maxWidth) {
      clipped = clipped.slice(0, -1);
    }
    return `${clipped}…`;
  }

  function fillPanel(ctx, w, h) {
    const gradient = ctx.createLinearGradient(0, 0, w, h);
    gradient.addColorStop(0, "rgba(4,10,18,0.95)");
    gradient.addColorStop(1, "rgba(10,8,20,0.95)");
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, w, h);
  }

  function drawTitle(ctx, title, w) {
    if (!title) return;
    ctx.fillStyle = "rgba(231,248,255,0.92)";
    ctx.font = "600 11px Inter, sans-serif";
    ctx.textAlign = "left";
    ctx.fillText(clippedText(ctx, title, Math.max(40, w - 24)), 12, 18);
  }

  function drawEmpty(ctx, w, h, message) {
    ctx.fillStyle = "rgba(139,163,184,0.9)";
    ctx.font = "12px JetBrains Mono, monospace";
    ctx.textAlign = "center";
    ctx.fillText(message || "no data", w / 2, h / 2);
    ctx.textAlign = "left";
  }

  function drawGlowTrace(canvas, opts) {
    const { ctx, w, h } = prep(canvas);
    ctx.clearRect(0, 0, w, h);
    fillPanel(ctx, w, h);
    drawTitle(ctx, opts.title, w);

    const times = Array.from(opts.times || []);
    const mean = Array.from(opts.mean || []);
    const sem = opts.sem;
    const color = opts.color || "#00f5d4";
    if (!times.length || !mean.length) {
      drawEmpty(ctx, w, h, opts.emptyMessage || "no signal available");
      return;
    }
    const plot = {
      l: 58,
      t: opts.title ? 34 : 18,
      w: Math.max(1, w - 76),
      h: Math.max(1, h - (opts.title ? 78 : 62)),
    };
    const x0 = times[0];
    const x1 = times[times.length - 1];
    const xSpan = x1 === x0 ? 1 : x1 - x0;

    const ys = [];
    if (opts.individuals) {
      for (const row of opts.individuals) {
        for (const v of row) if (Number.isFinite(v)) ys.push(v);
      }
    } else {
      for (let i = 0; i < mean.length; i += 1) {
        if (Number.isFinite(mean[i])) ys.push(mean[i]);
        if (sem) {
          if (Number.isFinite(sem[i])) {
            ys.push(mean[i] + sem[i], mean[i] - sem[i]);
          }
        }
      }
    }
    const yb = bounds(ys);

    const X = (t) => plot.l + ((t - x0) / xSpan) * plot.w;
    const Y = (v) => plot.t + ((yb.max - v) / (yb.max - yb.min)) * plot.h;

    ctx.font = "10px JetBrains Mono, monospace";
    ctx.fillStyle = "rgba(139,163,184,0.88)";
    ctx.strokeStyle = "rgba(100,140,180,0.08)";
    for (let i = 0; i <= 4; i += 1) {
      const y = plot.t + (plot.h * i) / 4;
      const value = yb.max - ((yb.max - yb.min) * i) / 4;
      ctx.beginPath();
      ctx.moveTo(plot.l, y);
      ctx.lineTo(plot.l + plot.w, y);
      ctx.stroke();
      ctx.textAlign = "right";
      ctx.fillText(formatTick(value), plot.l - 7, y + 3);
    }
    for (let i = 0; i <= 4; i += 1) {
      const x = plot.l + (plot.w * i) / 4;
      const value = x0 + (xSpan * i) / 4;
      ctx.textAlign = "center";
      ctx.fillText(formatTick(value), x, plot.t + plot.h + 16);
    }

    // baseline band
    if (opts.baseline) {
      const a = Math.max(plot.l, Math.min(plot.l + plot.w, X(opts.baseline[0])));
      const b = Math.max(plot.l, Math.min(plot.l + plot.w, X(opts.baseline[1])));
      ctx.fillStyle = "rgba(0,245,212,0.07)";
      ctx.fillRect(Math.min(a, b), plot.t, Math.max(1, Math.abs(b - a)), plot.h);
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
        for (let i = 0; i < Math.min(times.length, row.length); i += 1) {
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
      for (let i = 0; i < times.length; i += 1) {
        const x = X(times[i]);
        const y = Y(mean[i] + sem[i]);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      for (let i = times.length - 1; i >= 0; i -= 1) {
        ctx.lineTo(X(times[i]), Y(mean[i] - sem[i]));
      }
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

    ctx.fillStyle = "rgba(139,163,184,0.95)";
    ctx.font = "11px Inter, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("Time (s)", plot.l + plot.w / 2, h - 8);
    ctx.save();
    ctx.translate(13, plot.t + plot.h / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText("Z-score", 0, 0);
    ctx.restore();
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
    fillPanel(ctx, w, h);
    drawTitle(ctx, opts.title, w);
    const matrix = opts.matrix || [];
    if (!matrix.length || !matrix[0]?.length) {
      drawEmpty(ctx, w, h, opts.emptyMessage || "no trials selected");
      return;
    }
    const plot = {
      l: 46,
      t: opts.title ? 32 : 14,
      w: Math.max(1, w - 58),
      h: Math.max(1, h - (opts.title ? 72 : 54)),
    };
    let min = Infinity;
    let max = -Infinity;
    for (const row of matrix) {
      for (const v of row) {
        if (!Number.isFinite(v)) continue;
        if (v < min) min = v;
        if (v > max) max = v;
      }
    }
    if (!Number.isFinite(min) || !Number.isFinite(max)) {
      min = -1;
      max = 1;
    } else if (min === max) {
      min -= 1;
      max += 1;
    }
    const rows = matrix.length;
    const cols = matrix[0].length;
    const cw = plot.w / cols;
    const ch = plot.h / rows;
    for (let r = 0; r < rows; r += 1) {
      const drawRow = rows - 1 - r;
      for (let c = 0; c < cols; c += 1) {
        const value = matrix[r][c];
        const t = (value - min) / (max - min);
        ctx.fillStyle = Number.isFinite(value) ? heatColor(t) : "rgb(8,12,28)";
        ctx.fillRect(
          plot.l + c * cw,
          plot.t + drawRow * ch,
          Math.ceil(cw),
          Math.ceil(ch)
        );
      }
    }
    // zero marker
    const times = Array.from(opts.times || []);
    if (times && times[0] < 0 && times[times.length - 1] > 0) {
      const zx = plot.l + ((0 - times[0]) / (times[times.length - 1] - times[0])) * plot.w;
      ctx.strokeStyle = "rgba(255,255,255,0.55)";
      ctx.beginPath();
      ctx.moveTo(zx, plot.t);
      ctx.lineTo(zx, plot.t + plot.h);
      ctx.stroke();
    }

    ctx.fillStyle = "rgba(139,163,184,0.9)";
    ctx.font = "10px JetBrains Mono, monospace";
    if (times.length) {
      const x0 = times[0];
      const x1 = times[times.length - 1];
      for (let i = 0; i <= 2; i += 1) {
        const x = plot.l + (plot.w * i) / 2;
        const value = x0 + ((x1 - x0) * i) / 2;
        ctx.textAlign = "center";
        ctx.fillText(formatTick(value), x, plot.t + plot.h + 15);
      }
    }
    const trialNumbers = opts.trialNumbers || [];
    const maxTicks = Math.max(1, Math.min(rows, Math.floor(plot.h / 28)));
    const tickIndices = [];
    if (maxTicks === 1) {
      tickIndices.push(0);
    } else {
      for (let i = 0; i < maxTicks; i += 1) {
        tickIndices.push(Math.round((i * (rows - 1)) / (maxTicks - 1)));
      }
    }
    Array.from(new Set(tickIndices)).forEach((rowIndex) => {
      const raw = Number(trialNumbers[rowIndex] ?? rowIndex + 1);
      const label = Number.isFinite(raw) ? String(Math.round(raw)) : String(rowIndex + 1);
      const y = plot.t + (rows - rowIndex - 0.5) * ch;
      ctx.textAlign = "right";
      ctx.fillText(label, plot.l - 6, y + 3);
    });
    ctx.font = "11px Inter, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("Time (s)", plot.l + plot.w / 2, h - 8);
    ctx.save();
    ctx.translate(12, plot.t + plot.h / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText("Trial", 0, 0);
    ctx.restore();
    ctx.textAlign = "left";
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
