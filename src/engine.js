// Browser/Node port of src/cohort.py (same rule IDs). Days are integers from DATA_START.
// patients: [[pid, [[day, supply], ...brand fills sorted], [[start, end], ...enrolment]], ...]
(function (root) {
  function mergeSegs(segs) {
    const s = segs.slice().sort((a, b) => a[0] - b[0]);
    const out = [];
    for (const [a, b] of s) {
      if (out.length && a <= out[out.length - 1][1] + 1) out[out.length - 1][1] = Math.max(out[out.length - 1][1], b);
      else out.push([a, b]);
    }
    return out;
  }
  function covering(segs, d) {
    for (const s of mergeSegs(segs)) if (s[0] <= d && d <= s[1]) return s;
    return null;
  }
  function timeToDisc(rel, followEnd, maxGap) { // R5, R6
    let cov = rel[0][0] + rel[0][1];
    for (let i = 1; i < rel.length; i++) {
      const [d, s] = rel[i];
      if (d > followEnd) break;
      if (d - cov > maxGap) return [cov, 1];
      cov = Math.max(cov, d) + s;
    }
    if (followEnd - cov > maxGap) return [cov, 1];
    return [followEnd, 0];
  }
  function buildCohort(patients, p, C) {
    const need = Math.max(p.lookforward, p.persistenceDay);
    const intakeEnd = C.DATA_END - need;
    const counts = { R2: 0, R3: 0, R4: 0, included: 0 };
    const rows = [];
    for (const [pid, fills, segs] of patients) {
      let idx;
      if (p.indexRule === "first_ever") idx = fills[0][0];               // R1
      else { const f = fills.find(x => x[0] >= C.INTAKE_START); idx = f ? f[0] : null; }
      if (idx === null || idx < C.INTAKE_START || idx > intakeEnd) { counts.R2++; continue; }  // R2
      const back = covering(segs, idx - p.lookback);
      if (!back || back[1] < idx) { counts.R3++; continue; }             // R3
      const seg = covering(segs, idx);
      const followEnd = Math.min(seg[1], C.DATA_END);
      if (followEnd < idx + p.lookforward) { counts.R4++; continue; }    // R4
      const rel = fills.filter(x => x[0] >= idx).map(x => [x[0] - idx, x[1]]);
      const [t, e] = timeToDisc(rel, followEnd - idx, p.maxGap);
      rows.push([t, e]); counts.included++;
    }
    return { rows, counts };
  }
  function kaplanMeier(rows) {                                          // R8
    const r = rows.slice().sort((a, b) => a[0] - b[0]);
    let atRisk = r.length, s = 1; const ts = [0], ss = [1];
    let i = 0;
    while (i < r.length) {
      const t = r[i][0]; let d = 0, n = 0;
      while (i < r.length && r[i][0] === t) { d += r[i][1]; n++; i++; }
      if (d) { s *= 1 - d / atRisk; ts.push(t); ss.push(s); }
      atRisk -= n;
    }
    return { t: ts, s: ss };
  }
  function survAt(km, day) {
    let lo = 0;
    for (let i = 0; i < km.t.length; i++) if (km.t[i] <= day) lo = i; else break;
    return km.s[lo];
  }
  function summarise(res, p) {                                          // R7
    const P = p.persistenceDay, rows = res.rows;
    const known = rows.filter(([t, e]) => e === 1 || t >= P);
    const pers = known.filter(([t, e]) => e === 0 || t >= P).length;
    const km = kaplanMeier(rows);
    return {
      cohort_n: rows.length,
      pct_persistent_6m: known.length ? Math.round(1000 * pers / known.length) / 10 : NaN,
      km_6m: Math.round(1000 * survAt(km, P - 0.5)) / 10,
      worst_case_6m: rows.length ? Math.round(1000 * pers / rows.length) / 10 : NaN,
      censored_before_6m: rows.filter(([t, e]) => e === 0 && t < P).length,
      km
    };
  }
  const api = { mergeSegs, timeToDisc, buildCohort, kaplanMeier, survAt, summarise };
  if (typeof module !== "undefined") module.exports = api; else root.Engine = api;
})(this);
