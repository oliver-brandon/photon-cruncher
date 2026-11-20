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

  function traceBounds(mean, sem, individuals) {
    let min = Infinity;
    let max = -Infinity;
    function include(value) {
      if (!Number.isFinite(value)) return;
      if (value < min) min = value;
      if (value > max) max = value;
    }
    if (individuals) {
      for (const row of individuals) for (const value of row) include(value);
    } else {
      for (let i = 0; i < mean.length; i++) {
        include(mean[i]);
        if (sem && Number.isFinite(sem[i])) {
          include(mean[i] + sem[i]);
          include(mean[i] - sem[i]);
        }
      }
    }
    if (!Number.isFinite(min)) return { min: -1, max: 1 };
    if (min === max) return { min: min - 1, max: max + 1 };
    const p = (max - min) * 0.14;
    return { min: min - p, max: max + p };
  }

  function formatTick(value) {
    const absolute = Math.abs(value);
    if (absolute < 1e-10) return "0";
    if (absolute >= 100) return value.toFixed(0);
    if (absolute >= 10) return value.toFixed(1);
    return value.toFixed(2).replace(/\.00$/, "");
  }

  function ticksIncludingZero(min, max, intervals, axisPixels, labelSpacing) {
    const span = max - min;
    if (!span) return [min];
    const hasZero = min <= 0 && max >= 0;
    const values = [];
    for (let i = 0; i <= intervals; i += 1) {
      const value = min + (span * i) / intervals;
      // Reserve room for the event/baseline label when a grid tick almost coincides with zero.
      if (!hasZero || Math.abs(value / span) * axisPixels >= labelSpacing) values.push(value);
    }
    if (hasZero) values.push(0);
    return values.sort((a, b) => a - b);
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
    ctx.fillStyle = "#111620";
    ctx.fillRect(0, 0, w, h);
  }

  function drawTitle(ctx, title, w) {
    if (!title) return;
    ctx.fillStyle = "rgba(231,248,255,0.92)";
    ctx.font = "600 11px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
    ctx.textAlign = "left";
    ctx.fillText(clippedText(ctx, title, Math.max(40, w - 24)), 12, 18);
  }

  function drawEmpty(ctx, w, h, message) {
    ctx.fillStyle = "rgba(139,163,184,0.9)";
    ctx.font = "12px 'SFMono-Regular', Consolas, monospace";
    ctx.textAlign = "center";
    ctx.fillText(message || "no data", w / 2, h / 2);
    ctx.textAlign = "left";
  }

  function drawGlowTrace(canvas, opts) {
    const { ctx, w, h } = prep(canvas);
    ctx.clearRect(0, 0, w, h);
    fillPanel(ctx, w, h);
    drawTitle(ctx, opts.title, w);

    const times = opts.times || [];
    const mean = opts.mean || [];
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

    const yb = traceBounds(mean, sem, opts.individuals);
    yb.min = Math.min(yb.min, 0);
    yb.max = Math.max(yb.max, 0);

    const X = (t) => plot.l + ((t - x0) / xSpan) * plot.w;
    const Y = (v) => plot.t + ((yb.max - v) / (yb.max - yb.min)) * plot.h;

    ctx.font = "10px 'SFMono-Regular', Consolas, monospace";
    ctx.fillStyle = "rgba(139,163,184,0.88)";
    ctx.strokeStyle = "rgba(100,140,180,0.08)";
    for (const value of ticksIncludingZero(yb.min, yb.max, 4, plot.h, 14)) {
      const y = Y(value);
      ctx.beginPath();
      ctx.moveTo(plot.l, y);
      ctx.lineTo(plot.l + plot.w, y);
      ctx.stroke();
      ctx.textAlign = "right";
      ctx.fillText(formatTick(value), plot.l - 7, y + 3);
    }
    for (const value of ticksIncludingZero(x0, x1, 4, plot.w, 28)) {
      const x = X(value);
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

    // zero references
    ctx.save();
    ctx.strokeStyle = "rgba(255,45,149,0.55)";
    ctx.lineWidth = 1;
    ctx.setLineDash([5, 5]);
    if (x0 <= 0 && x1 >= 0) {
      const zx = X(0);
      ctx.beginPath();
      ctx.moveTo(zx, plot.t);
      ctx.lineTo(zx, plot.t + plot.h);
      ctx.stroke();
    }
    if (yb.min <= 0 && yb.max >= 0) {
      const zy = Y(0);
      ctx.beginPath();
      ctx.moveTo(plot.l, zy);
      ctx.lineTo(plot.l + plot.w, zy);
      ctx.stroke();
    }
    ctx.restore();

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
    ctx.shadowBlur = 5;
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

    // Reuse the glow pass path for the crisp stroke.
    ctx.strokeStyle = "#eafffb";
    ctx.globalAlpha = 0.35;
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.globalAlpha = 1;

    ctx.fillStyle = "rgba(139,163,184,0.95)";
    ctx.font = "11px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("Time (s)", plot.l + plot.w / 2, h - 8);
    ctx.save();
    ctx.translate(13, plot.t + plot.h / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText("Z-score", 0, 0);
    ctx.restore();
    ctx.textAlign = "left";
  }

  // Zero-centered blue-dark-red scale for signed z-scores.
  const heatStops = [[44, 91, 160], [73, 154, 181], [20, 27, 42], [214, 104, 82], [178, 24, 43]];

  function paintHeatmap(ctx, plot, matrix, limit) {
    const rows = matrix.length;
    const cols = matrix[0].length;
    // Draw at most one colour per visible device pixel. Nearest-neighbour
    // sampling keeps trial rows distinct when scaling to the plot rectangle.
    const raster = document.createElement("canvas");
    const dpr = devicePixelRatio || 1;
    raster.width = Math.min(cols, Math.ceil(plot.w * dpr));
    raster.height = Math.min(rows, Math.ceil(plot.h * dpr));
    const surface = raster.getContext("2d");
    const image = surface.createImageData(raster.width, raster.height);
    const pixels = image.data;
    let offset = 0;
    for (let y = 0; y < raster.height; y++) {
      const row = matrix[rows - 1 - Math.floor((y + 0.5) * rows / raster.height)];
      for (let x = 0; x < raster.width; x++) {
        const value = row[Math.floor((x + 0.5) * cols / raster.width)];
        if (Number.isFinite(value)) {
          const t = Math.max(0, Math.min(1, (value + limit) / (2 * limit))) * (heatStops.length - 1);
          const i = Math.min(Math.floor(t), heatStops.length - 2);
          const a = heatStops[i];
          const b = heatStops[i + 1];
          const fraction = t - i;
          for (let c = 0; c < 3; c++) {
            pixels[offset++] = Math.round(a[c] + (b[c] - a[c]) * fraction);
          }
        } else {
          pixels[offset++] = 8;
          pixels[offset++] = 12;
          pixels[offset++] = 28;
        }
        pixels[offset++] = 255;
      }
    }
    surface.putImageData(image, 0, 0);
    ctx.save();
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(raster, plot.l, plot.t, plot.w, plot.h);
    ctx.restore();
  }

  function drawHeat(canvas, opts) {
    const { ctx, w, h } = prep(canvas);
    ctx.clearRect(0, 0, w, h);
    fillPanel(ctx, w, h);
    drawTitle(ctx, opts.title, w);
    const matrix = opts.matrix || [];
    if (!matrix.length || !matrix[0]?.length) {
      drawEmpty(ctx, w, h, opts.emptyMessage || "no trials selected");
      return {
        limit:
          opts.scaleMode === "locked" && Number(opts.colorLimit) > 0
            ? Number(opts.colorLimit)
            : null,
        mode: opts.scaleMode === "locked" ? "locked" : "auto",
      };
    }
    const plot = {
      l: 46,
      t: opts.title ? 32 : 14,
      w: Math.max(1, w - 58),
      h: Math.max(1, h - (opts.title ? 104 : 86)),
    };
    let limit = Number(opts.colorLimit);
    if (opts.scaleMode !== "locked" || !Number.isFinite(limit) || limit <= 0) {
      let magnitude = -Infinity;
      for (const row of matrix) {
        for (const value of row) {
          if (Number.isFinite(value)) magnitude = Math.max(magnitude, Math.abs(value));
        }
      }
      limit = Number.isFinite(magnitude) ? Math.max(magnitude, Number.EPSILON) : 1;
    }
    const min = -limit;
    const max = limit;
    const rows = matrix.length;
    const ch = plot.h / rows;
    paintHeatmap(ctx, plot, matrix, limit);
    // zero marker
    const times = opts.times || [];
    if (
      times.length &&
      times[0] <= 0 &&
      times[times.length - 1] >= 0 &&
      times[times.length - 1] !== times[0]
    ) {
      const zx = plot.l + ((0 - times[0]) / (times[times.length - 1] - times[0])) * plot.w;
      ctx.save();
      ctx.strokeStyle = "rgba(3,7,15,0.92)";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(zx, plot.t);
      ctx.lineTo(zx, plot.t + plot.h);
      ctx.stroke();
      ctx.restore();
    }

    ctx.fillStyle = "rgba(139,163,184,0.9)";
    ctx.font = "10px 'SFMono-Regular', Consolas, monospace";
    if (times.length) {
      const x0 = times[0];
      const x1 = times[times.length - 1];
      const xSpan = x1 === x0 ? 1 : x1 - x0;
      for (const value of ticksIncludingZero(x0, x1, 2, plot.w, 28)) {
        const x = plot.l + ((value - x0) / xSpan) * plot.w;
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
    const plotBottom = plot.t + plot.h;
    ctx.font = "11px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("Time (s)", plot.l + plot.w / 2, plotBottom + 30);
    const barY = plotBottom + 38;
    const barHeight = 7;
    const gradient = ctx.createLinearGradient(plot.l, 0, plot.l + plot.w, 0);
    heatStops.forEach((rgb, index) => {
      gradient.addColorStop(index / (heatStops.length - 1), `rgb(${rgb.join(",")})`);
    });
    ctx.fillStyle = gradient;
    ctx.fillRect(plot.l, barY, plot.w, barHeight);
    ctx.strokeStyle = "rgba(255,255,255,0.24)";
    ctx.strokeRect(plot.l, barY, plot.w, barHeight);
    ctx.fillStyle = "rgba(139,163,184,0.95)";
    ctx.font = "9px 'SFMono-Regular', Consolas, monospace";
    ctx.textAlign = "left";
    ctx.fillText(formatTick(-limit), plot.l, barY + 18);
    ctx.textAlign = "center";
    ctx.fillText("0 z", plot.l + plot.w / 2, barY + 18);
    ctx.textAlign = "right";
    ctx.fillText(formatTick(limit), plot.l + plot.w, barY + 18);
    ctx.save();
    ctx.translate(12, plot.t + plot.h / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText("Trial", 0, 0);
    ctx.restore();
    ctx.textAlign = "left";
    return {
      min,
      max,
      limit,
      mode: opts.scaleMode === "locked" ? "locked" : "auto",
    };
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

  window.AuroraPlots = { drawGlowTrace, drawHeat, peakLatency };
})();
