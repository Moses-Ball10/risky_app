// Shared by the map app (static/index.html) and the sandbox (sandbox/index.html).
// Turns model outputs into driver words. Nothing here changes a score.

// Features that describe the moment, not the place (shown once for the whole route).
const TIME_F = new Set(["hour", "is_dark", "weekday", "is_weekend", "month", "is_holiday"]);

// Name of the risky spot, from that segment's own road features (BAAC codes).
function hazard(f) {
  return { 2: "Crossroads", 3: "T junction", 4: "Y junction", 5: "Big junction", 6: "Roundabout", 8: "Rail crossing" }[f.int]
      || { 2: "Left curve", 3: "Right curve", 4: "Bends" }[f.plan]
      || { 1: "Tunnel", 2: "Bridge", 8: "Road works" }[f.infra]
      || { 2: "Slope", 3: "Hilltop", 4: "Dip" }[f.prof] || "Risky stretch";
}

// A factor the model blames -> [short words, what the driver can do] (or null).
// t = {feature, value?}; row = that segment's model inputs.
function factor(t, row) {
  const v = t.value ?? row[t.feature];
  switch (t.feature) {
    case "hour": return v >= 21 || v <= 5 ? ["late at night", "Stay alert, rest if tired"] : ["busy hour", "Keep your distance"];
    case "is_dark": return v ? ["darkness", "Headlights on"] : null;
    case "weekday": case "is_weekend": return [row.weekday >= 5 ? "weekend traffic" : "this day", "Watch other drivers"];
    case "month": return ["season", null];
    case "plan": return v > 1 ? ["the curve", "Slow down before the curve"] : null;
    case "int": return v > 1 ? [v == 6 ? "the roundabout" : v == 8 ? "the rail crossing" : "the junction",
                                v == 8 ? "Stop and look both ways" : "Be ready to give way"] : null;
    case "prof": return v > 1 ? [v == 3 ? "the hilltop" : "the slope", v == 3 ? "No overtaking" : "Use engine braking"] : null;
    case "infra": return v > 0 ? [v == 1 ? "the tunnel" : "the bridge", "Keep your lane"] : null;
    case "vma": return ["high speed limit", "Stay under the limit"];
    case "agg": return [v == 2 ? "town traffic" : "open road", v == 2 ? "Watch for pedestrians" : null];
    default: return null;
  }
}

// Level index from x using config levels [{max}, ...].
function levelOf(x, levels) { const i = levels.findIndex(l => l.max === null || x < l.max); return i < 0 ? levels.length - 1 : i; }

// Continuous colour from x (log scale), so small changes such as the weather are visible.
const RAMP = [[0.4, [46, 204, 113]], [1.0, [241, 196, 15]], [2.1, [230, 126, 34]], [3.5, [231, 76, 60]], [6, [150, 20, 40]]];
function riskColor(x) {
  const lx = Math.log(Math.max(RAMP[0][0], Math.min(RAMP[RAMP.length - 1][0], x)));
  for (let k = 1; k < RAMP.length; k++) {
    const [x1, c1] = RAMP[k], [x0, c0] = RAMP[k - 1];
    if (lx <= Math.log(x1)) {
      const t = (lx - Math.log(x0)) / (Math.log(x1) - Math.log(x0));
      return `rgb(${c0.map((c, j) => Math.round(c + t * (c1[j] - c))).join(",")})`;
    }
  }
  return "rgb(150,20,40)";
}

// Weather rule from /weather: x × factor (factor_hard on curves and slopes), at most one level up.
function weatherOn(modelX, modelLevel, f, wx, levels) {
  const hard = f.plan !== 1 || f.prof === 2 || f.prof === 3;
  const k = wx ? (hard ? wx.factor_hard : wx.factor) : 1, x = modelX * k;
  return { wx: k, x, level: Math.min(modelLevel + 1, levelOf(x, levels)) };
}
