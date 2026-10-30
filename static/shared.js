// Shared by the map app (static/index.html) and the sandbox (sandbox/index.html).
// Turns model outputs into short driver messages in Arabic, French or English. Nothing here changes a score.

// Features that describe the moment, not the place (shown once for the whole route).
const TIME_F = new Set(["hour", "is_dark", "weekday", "is_weekend", "month", "is_holiday"]);

const I18N = {
  en: {
    dir: "ltr", voice: "en-US",
    spot: { crossroads: "Crossroads", t: "T junction", y: "Y junction", big: "Big junction", roundabout: "Roundabout",
            rail: "Rail crossing", left: "Left curve", right: "Right curve", bends: "Bends", tunnel: "Tunnel", bridge: "Bridge",
            works: "Road works", slope: "Slope", hilltop: "Hilltop", dip: "Dip", risky: "Risky spot", speeding: "Speeding" },
    // key -> [short words, one action]
    f: { night: ["late at night", "Stay alert"], busy: ["busy hour", "Keep your distance"], dark: ["darkness", "Lights on"],
         weekend: ["weekend traffic", "Watch other drivers"], day: ["this day", "Watch other drivers"], season: ["season", null],
         curve: ["the curve", "Brake before the curve"], junction: ["the junction", "Be ready to give way"],
         roundabout: ["the roundabout", "Give way"], rail: ["the rail crossing", "Stop and look"],
         hilltop: ["the hilltop", "No overtaking"], slope: ["the slope", "Use engine braking"],
         tunnel: ["the tunnel", "Keep your lane"], bridge: ["the bridge", "Keep your lane"],
         speedlim: ["high speed limit", "Stay under the limit"], town: ["town traffic", "Watch for pedestrians"], open: ["open road", null],
         rain: ["wet road", "Keep double distance"], heavy: ["heavy rain", "Keep double distance"], first_rain: ["slippery road", "Keep double distance"],
         still_wet: ["wet road", "Keep double distance"], fog: ["fog", "Lights on"], snow: ["snow", "Brake gently"], wind: ["strong wind", "Hold the wheel"] },
    nowWord: "now", m: "m",
    in: (n, d) => `${n} in ${d} m`, now: n => `${n} — now`, slow: v => `Slow to ${v}`,
    whole: (x, w) => `Whole route ×${x}${w ? ": " + w : ""}`, normal: "✓ Road ahead looks normal", limit: "limit",
    noWx: "no weather effect", wxOff: "⚠ Weather unavailable",
  },
  fr: {
    dir: "ltr", voice: "fr-FR",
    spot: { crossroads: "Carrefour", t: "Intersection en T", y: "Intersection en Y", big: "Grand carrefour", roundabout: "Rond-point",
            rail: "Passage à niveau", left: "Virage à gauche", right: "Virage à droite", bends: "Virages", tunnel: "Tunnel", bridge: "Pont",
            works: "Travaux", slope: "Pente", hilltop: "Sommet", dip: "Creux", risky: "Zone à risque", speeding: "Excès de vitesse" },
    f: { night: ["tard la nuit", "Restez vigilant"], busy: ["heure chargée", "Gardez vos distances"], dark: ["obscurité", "Allumez les feux"],
         weekend: ["trafic du week-end", "Attention aux autres"], day: ["ce jour", "Attention aux autres"], season: ["saison", null],
         curve: ["le virage", "Freinez avant le virage"], junction: ["le carrefour", "Préparez-vous à céder"],
         roundabout: ["le rond-point", "Cédez le passage"], rail: ["le passage à niveau", "Arrêtez-vous et regardez"],
         hilltop: ["le sommet", "Ne doublez pas"], slope: ["la pente", "Utilisez le frein moteur"],
         tunnel: ["le tunnel", "Restez dans votre voie"], bridge: ["le pont", "Restez dans votre voie"],
         speedlim: ["vitesse élevée", "Respectez la limite"], town: ["circulation urbaine", "Attention aux piétons"], open: ["route ouverte", null],
         rain: ["route mouillée", "Doublez la distance"], heavy: ["forte pluie", "Doublez la distance"], first_rain: ["route glissante", "Doublez la distance"],
         still_wet: ["route mouillée", "Doublez la distance"], fog: ["brouillard", "Allumez les feux"], snow: ["neige", "Freinez doucement"], wind: ["vent fort", "Tenez bien le volant"] },
    nowWord: "maintenant", m: "m",
    in: (n, d) => `${n} dans ${d} m`, now: n => `${n} — maintenant`, slow: v => `Ralentir à ${v}`,
    whole: (x, w) => `Tout le trajet ×${x}${w ? " : " + w : ""}`, normal: "✓ Route normale devant", limit: "limite",
    noWx: "sans effet météo", wxOff: "⚠ Météo indisponible",
  },
  ar: {
    dir: "rtl", voice: "ar-SA",
    spot: { crossroads: "تقاطع", t: "تقاطع على شكل T", y: "تقاطع على شكل Y", big: "تقاطع كبير", roundabout: "دوار",
            rail: "ممر سكة حديد", left: "منعطف يساراً", right: "منعطف يميناً", bends: "منعطفات", tunnel: "نفق", bridge: "جسر",
            works: "أشغال", slope: "منحدر", hilltop: "قمة مرتفع", dip: "منخفض", risky: "منطقة خطرة", speeding: "سرعة زائدة" },
    f: { night: ["وقت متأخر من الليل", "ابقَ يقظاً"], busy: ["ساعة ازدحام", "حافظ على المسافة"], dark: ["الظلام", "شغّل الأضواء"],
         weekend: ["حركة نهاية الأسبوع", "انتبه للسائقين"], day: ["هذا اليوم", "انتبه للسائقين"], season: ["الموسم", null],
         curve: ["المنعطف", "فرمل قبل المنعطف"], junction: ["التقاطع", "استعد لإعطاء الأولوية"],
         roundabout: ["الدوار", "أعطِ الأولوية"], rail: ["ممر السكة", "توقف وانظر"],
         hilltop: ["قمة المرتفع", "لا تتجاوز"], slope: ["المنحدر", "استعمل فرامل المحرك"],
         tunnel: ["النفق", "التزم بمسارك"], bridge: ["الجسر", "التزم بمسارك"],
         speedlim: ["سرعة عالية", "التزم بالحد"], town: ["حركة المدينة", "انتبه للمشاة"], open: ["طريق مفتوح", null],
         rain: ["طريق مبلل", "ضاعف المسافة"], heavy: ["أمطار غزيرة", "ضاعف المسافة"], first_rain: ["طريق زلق", "ضاعف المسافة"],
         still_wet: ["طريق مبلل", "ضاعف المسافة"], fog: ["ضباب", "شغّل الأضواء"], snow: ["ثلج", "فرمل بلطف"], wind: ["رياح قوية", "أمسك المقود جيداً"] },
    nowWord: "الآن", m: "م",
    in: (n, d) => `${n} بعد ${d} م`, now: n => `${n} — الآن`, slow: v => `خفّف إلى ${v}`,
    whole: (x, w) => `كامل الطريق ×${x}${w ? ": " + w : ""}`, normal: "✓ الطريق أمامك عادي", limit: "الحد",
    noWx: "بدون تأثير الطقس", wxOff: "⚠ الطقس غير متوفر",
  },
};
const tr = lang => I18N[lang] || I18N.en;

// Spot from that segment's own road features (BAAC codes) -> key, or null for a plain stretch.
function hazardKey(f) {
  return { 2: "crossroads", 3: "t", 4: "y", 5: "big", 6: "roundabout", 8: "rail" }[f.int]
      || { 2: "left", 3: "right", 4: "bends" }[f.plan]
      || { 1: "tunnel", 2: "bridge", 8: "works" }[f.infra]
      || { 2: "slope", 3: "hilltop", 4: "dip" }[f.prof] || null;
}
const hazard = (f, lang = "en") => tr(lang).spot[hazardKey(f) || "risky"];
const HAZARD_ICON = { crossroads: "✚", t: "✚", y: "✚", big: "✚", roundabout: "⟳", rail: "🚆", left: "↰", right: "↱", bends: "〰",
                      tunnel: "◠", bridge: "🌉", works: "🚧", slope: "⛰", hilltop: "⛰", dip: "⌄", risky: "!", speeding: "⚡" };

// A factor the model blames -> key (or null). t = {feature, value?}; row = that segment's model inputs.
function factorKey(t, row) {
  const v = t.value ?? row[t.feature];
  switch (t.feature) {
    case "hour": return v >= 21 || v <= 5 ? "night" : "busy";
    case "is_dark": return v ? "dark" : null;
    case "weekday": case "is_weekend": return row.weekday >= 5 ? "weekend" : "day";
    case "month": return "season";
    case "plan": return v > 1 ? "curve" : null;
    case "int": return v > 1 ? (v == 6 ? "roundabout" : v == 8 ? "rail" : "junction") : null;
    case "prof": return v > 1 ? (v == 3 ? "hilltop" : "slope") : null;
    case "infra": return v > 0 ? (v == 1 ? "tunnel" : "bridge") : null;
    case "vma": return "speedlim";
    case "agg": return v == 2 ? "town" : "open";
    default: return null;
  }
}
// -> [short words, one action] in the chosen language, or null
function factor(t, row, lang = "en") { const k = factorKey(t, row); return k ? tr(lang).f[k] : null; }

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
