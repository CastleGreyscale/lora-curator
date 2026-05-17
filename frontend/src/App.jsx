import { useState, useEffect, useCallback, useRef } from "react";
import * as Recharts from "recharts";

// In dev, Vite proxies /api to :8042. In prod, same origin.
const API = "/api";

// ═══════════════════════════════════════════
// Theme & Style Constants
// ═══════════════════════════════════════════
const theme = {
  bg: "#0a0a0f",
  surface: "#12121a",
  surfaceAlt: "#1a1a26",
  border: "#2a2a3a",
  borderHover: "#3a3a5a",
  text: "#e8e8f0",
  textMuted: "#8888a0",
  textDim: "#555570",
  accent: "#c084fc",
  accentDim: "#7c3aed",
  accentGlow: "rgba(192, 132, 252, 0.15)",
  success: "#4ade80",
  successDim: "#166534",
  warning: "#fbbf24",
  danger: "#f87171",
  dangerDim: "#991b1b",
  selected: "#22c55e",
  selectedBg: "rgba(34,197,94,0.08)",
  selectedBorder: "rgba(34,197,94,0.3)",
  excludedBg: "rgba(248,113,113,0.06)",
  excludedBorder: "rgba(248,113,113,0.25)",
  chartColors: ["#c084fc", "#818cf8", "#38bdf8", "#34d399", "#fbbf24", "#f87171", "#fb923c", "#a78bfa"],
};

// ═══════════════════════════════════════════
// Utility Components
// ═══════════════════════════════════════════

function Badge({ children, color = theme.accent, count, onClick, active }) {
  return (
    <button
      onClick={onClick}
      style={{
        display: "inline-flex", alignItems: "center", gap: 6,
        padding: "4px 10px", borderRadius: 6,
        background: active ? `${color}22` : "transparent",
        border: `1px solid ${active ? color : theme.border}`,
        color: active ? color : theme.textMuted,
        fontSize: 12, cursor: "pointer", transition: "all 0.15s",
        fontFamily: "'DM Sans', sans-serif",
      }}
    >
      {children}
      {count != null && (
        <span style={{ fontSize: 10, opacity: 0.7 }}>{count}</span>
      )}
    </button>
  );
}

function StatCard({ label, value, sub, icon }) {
  return (
    <div style={{
      background: theme.surface, border: `1px solid ${theme.border}`,
      borderRadius: 10, padding: "16px 20px", flex: 1, minWidth: 140,
    }}>
      <div style={{ fontSize: 11, color: theme.textDim, letterSpacing: 1, textTransform: "uppercase", marginBottom: 6 }}>
        {icon && <span style={{ marginRight: 6 }}>{icon}</span>}{label}
      </div>
      <div style={{ fontSize: 28, fontWeight: 700, color: theme.text, fontFamily: "'Space Mono', monospace" }}>
        {typeof value === "number" ? value.toLocaleString() : value}
      </div>
      {sub && <div style={{ fontSize: 12, color: theme.textMuted, marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

function Section({ title, children, actions, collapsed, onToggle, style: containerStyle }) {
  return (
    <div style={{
      background: theme.surface, border: `1px solid ${theme.border}`,
      borderRadius: 12, overflow: "hidden", marginBottom: 16,
      ...containerStyle,
    }}>
      <div
        onClick={onToggle}
        style={{
          padding: "14px 20px", display: "flex", justifyContent: "space-between",
          alignItems: "center", cursor: onToggle ? "pointer" : "default",
          borderBottom: collapsed ? "none" : `1px solid ${theme.border}`,
          flexShrink: 0,
        }}
      >
        <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600, color: theme.text, letterSpacing: 0.3 }}>
          {onToggle && <span style={{ marginRight: 8, display: "inline-block", transform: collapsed ? "rotate(-90deg)" : "rotate(0)", transition: "transform 0.2s" }}>▾</span>}
          {title}
        </h3>
        {actions && <div style={{ display: "flex", gap: 8 }}>{actions}</div>}
      </div>
      {!collapsed && <div style={{ padding: 20, overflow: "auto", flex: 1, minHeight: 0 }}>{children}</div>}
    </div>
  );
}

function Checkbox({ checked, onChange, size = 18, color = theme.selected }) {
  return (
    <button
      onClick={(e) => { e.stopPropagation(); onChange(!checked); }}
      style={{
        width: size, height: size, borderRadius: 4, border: `2px solid ${checked ? color : theme.border}`,
        background: checked ? color : "transparent", cursor: "pointer", padding: 0,
        display: "flex", alignItems: "center", justifyContent: "center",
        transition: "all 0.15s ease", flexShrink: 0,
      }}
    >
      {checked && (
        <svg width={size - 6} height={size - 6} viewBox="0 0 12 12" fill="none">
          <path d="M2 6l3 3 5-5" stroke="#000" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      )}
    </button>
  );
}

// ═══════════════════════════════════════════
// Searchable Keyword Picker
// ═══════════════════════════════════════════

function KeywordPicker({ allKeywords, selected, onToggle, label }) {
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState(false);
  const inputRef = useRef(null);

  const filtered = search.trim()
    ? allKeywords.filter(k => k.keyword.toLowerCase().includes(search.toLowerCase()))
    : allKeywords.slice(0, 40);

  return (
    <div>
      <label style={{ fontSize: 11, color: theme.textDim, letterSpacing: 1, textTransform: "uppercase", display: "block", marginBottom: 6 }}>
        {label}
        {selected.length > 0 && (<span style={{ color: theme.accent, marginLeft: 6 }}>({selected.length})</span>)}
      </label>
      {selected.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 8 }}>
          {selected.map(kw => (
            <button key={kw} onClick={() => onToggle(kw)} style={{
              display: "inline-flex", alignItems: "center", gap: 4,
              padding: "3px 8px", borderRadius: 5,
              background: `${theme.accent}22`, border: `1px solid ${theme.accent}`,
              color: theme.accent, fontSize: 11, cursor: "pointer", fontFamily: "'DM Sans', sans-serif",
            }}>{kw} <span style={{ fontSize: 9, opacity: 0.7 }}>✕</span></button>
          ))}
        </div>
      )}
      <input ref={inputRef} type="text" value={search}
        onChange={e => { setSearch(e.target.value); setExpanded(true); }}
        onFocus={() => setExpanded(true)} placeholder="Type to search keywords..."
        style={{ width: "100%", padding: "6px 10px", borderRadius: 6, border: `1px solid ${theme.border}`, background: theme.bg, color: theme.text, fontSize: 12, fontFamily: "'DM Sans', sans-serif", boxSizing: "border-box" }}
      />
      {expanded && (
        <div style={{ maxHeight: 200, overflowY: "auto", marginTop: 4, borderRadius: 6, border: `1px solid ${theme.border}`, background: theme.surface }}>
          {filtered.length === 0 ? (
            <div style={{ padding: "8px 10px", fontSize: 11, color: theme.textDim }}>{search ? "No keywords match" : "Start typing to search"}</div>
          ) : filtered.map(({ keyword, count }) => {
            const isSelected = selected.includes(keyword);
            return (
              <button key={keyword} onClick={() => { onToggle(keyword); setSearch(""); inputRef.current?.focus(); }}
                style={{ display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%", padding: "6px 10px", border: "none", cursor: "pointer", background: isSelected ? `${theme.accent}15` : "transparent", color: isSelected ? theme.accent : theme.textMuted, fontSize: 12, textAlign: "left", fontFamily: "'DM Sans', sans-serif", borderBottom: `1px solid ${theme.border}08` }}
                onMouseOver={e => { if (!isSelected) e.currentTarget.style.background = theme.surfaceAlt; }}
                onMouseOut={e => { if (!isSelected) e.currentTarget.style.background = "transparent"; }}
              >
                <span>{keyword}</span>
                <span style={{ fontSize: 10, color: theme.textDim, fontFamily: "'Space Mono', monospace" }}>{count}</span>
              </button>
            );
          })}
          {!search && allKeywords.length > 40 && (
            <div style={{ padding: "6px 10px", fontSize: 10, color: theme.textDim, textAlign: "center" }}>{allKeywords.length.toLocaleString()} total keywords — type to search</div>
          )}
        </div>
      )}
      {expanded && (<div onClick={() => setExpanded(false)} style={{ position: "fixed", inset: 0, zIndex: -1 }} />)}
    </div>
  );
}

// ═══════════════════════════════════════════
// Filter Panel (for Browse tab sidebar)
// ═══════════════════════════════════════════

function FilterPanel({ filterOptions, filters, setFilters, onApply }) {
  if (!filterOptions) return null;
  const toggleArrayFilter = (key, value) => {
    setFilters(prev => {
      const arr = prev[key] || [];
      const next = arr.includes(value) ? arr.filter(v => v !== value) : [...arr, value];
      return { ...prev, [key]: next.length ? next : undefined };
    });
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: 16, paddingBottom: 16 }}>
        <div>
          <label style={{ fontSize: 11, color: theme.textDim, letterSpacing: 1, textTransform: "uppercase", display: "block", marginBottom: 6 }}>Search</label>
          <input type="text" value={filters.search || ""} onChange={e => setFilters(prev => ({ ...prev, search: e.target.value || undefined }))} placeholder="Search titles, descriptions..."
            style={{ width: "100%", padding: "8px 12px", borderRadius: 8, border: `1px solid ${theme.border}`, background: theme.bg, color: theme.text, fontSize: 13, fontFamily: "'DM Sans', sans-serif", outline: "none", boxSizing: "border-box" }} />
        </div>
        <div>
          <label style={{ fontSize: 11, color: theme.textDim, letterSpacing: 1, textTransform: "uppercase", display: "block", marginBottom: 6 }}>Year Range</label>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input type="number" value={filters.year_min || ""} onChange={e => setFilters(prev => ({ ...prev, year_min: e.target.value ? parseInt(e.target.value) : undefined }))} placeholder={filterOptions.year_range?.min || "min"}
              style={{ width: 80, padding: "6px 10px", borderRadius: 6, border: `1px solid ${theme.border}`, background: theme.bg, color: theme.text, fontSize: 13, fontFamily: "'Space Mono', monospace" }} />
            <span style={{ color: theme.textDim }}>–</span>
            <input type="number" value={filters.year_max || ""} onChange={e => setFilters(prev => ({ ...prev, year_max: e.target.value ? parseInt(e.target.value) : undefined }))} placeholder={filterOptions.year_range?.max || "max"}
              style={{ width: 80, padding: "6px 10px", borderRadius: 6, border: `1px solid ${theme.border}`, background: theme.bg, color: theme.text, fontSize: 13, fontFamily: "'Space Mono', monospace" }} />
          </div>
        </div>
        <div>
          <label style={{ fontSize: 11, color: theme.textDim, letterSpacing: 1, textTransform: "uppercase", display: "block", marginBottom: 6 }}>Language</label>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {(filterOptions.languages || []).map(lang => (<Badge key={lang} active={(filters.languages || []).includes(lang)} onClick={() => toggleArrayFilter("languages", lang)}>{lang}</Badge>))}
          </div>
        </div>
        <div>
          <label style={{ fontSize: 11, color: theme.textDim, letterSpacing: 1, textTransform: "uppercase", display: "block", marginBottom: 6 }}>Aspect Ratio</label>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {(filterOptions.aspect_groups || []).map(group => (<Badge key={group} active={(filters.aspect_groups || []).includes(group)} onClick={() => toggleArrayFilter("aspect_groups", group)}>{group}</Badge>))}
          </div>
        </div>
        <div>
          <label style={{ fontSize: 11, color: theme.textDim, letterSpacing: 1, textTransform: "uppercase", display: "block", marginBottom: 6 }}>Genres</label>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {(filterOptions.genres || []).map(genre => (<Badge key={genre} active={(filters.genres || []).includes(genre)} onClick={() => toggleArrayFilter("genres", genre)}>{genre}</Badge>))}
          </div>
        </div>
        <div>
          <label style={{ fontSize: 11, color: theme.textDim, letterSpacing: 1, textTransform: "uppercase", display: "block", marginBottom: 6 }}>Countries</label>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4, maxHeight: 120, overflowY: "auto" }}>
            {(filterOptions.countries || []).map(country => (<Badge key={country} active={(filters.countries || []).includes(country)} onClick={() => toggleArrayFilter("countries", country)}>{country}</Badge>))}
          </div>
        </div>
        <KeywordPicker allKeywords={filterOptions.keywords || []} selected={filters.keywords_include || []} onToggle={(kw) => toggleArrayFilter("keywords_include", kw)} label="Keywords (include)" />
        <KeywordPicker allKeywords={filterOptions.keywords || []} selected={filters.keywords_exclude || []} onToggle={(kw) => toggleArrayFilter("keywords_exclude", kw)} label="Keywords (exclude)" />
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════
// Image Grid (for Preview + Tags tabs)
// ═══════════════════════════════════════════

function ImageGrid({ images, loading }) {
  if (loading) {
    return (<div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 8 }}>
      {Array.from({ length: 12 }).map((_, i) => (<div key={i} style={{ aspectRatio: "16/9", borderRadius: 8, background: `linear-gradient(135deg, ${theme.surfaceAlt}, ${theme.bg})`, animation: "pulse 1.5s ease-in-out infinite" }} />))}
    </div>);
  }
  if (!images || images.length === 0) {
    return (<div style={{ textAlign: "center", padding: 40, color: theme.textDim }}>No images to display.</div>);
  }
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 8 }}>
      {images.map((img, i) => (
        <div key={img.id || i} style={{ position: "relative", borderRadius: 8, overflow: "hidden", background: theme.bg }}>
          <img src={`${API}/image/serve/${img.id}`} alt={img.filename} loading="lazy"
            style={{ width: "100%", aspectRatio: "16/10", objectFit: "cover", display: "block", transition: "transform 0.3s" }}
            onMouseOver={e => e.target.style.transform = "scale(1.05)"} onMouseOut={e => e.target.style.transform = "scale(1)"} />
          <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, background: "linear-gradient(transparent, rgba(0,0,0,0.85))", padding: "20px 10px 8px" }}>
            <div style={{ fontSize: 11, color: "#fff", fontWeight: 600, lineHeight: 1.3 }}>{img.movie_title}</div>
            <div style={{ fontSize: 10, color: "rgba(255,255,255,0.5)", marginTop: 2 }}>{img.movie_year} · {img.aspect_ratio_group}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

// ═══════════════════════════════════════════
// Charts
// ═══════════════════════════════════════════

function LossChart({ data }) {
  if (!data || data.length < 2) return null;
  const { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } = Recharts;
  const minLoss = Math.min(...data.map(d => d.loss));
  const maxLoss = Math.max(...data.map(d => d.loss));
  const pad = (maxLoss - minLoss) * 0.1 || 0.001;
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 11, color: theme.textDim, letterSpacing: 1, textTransform: "uppercase", marginBottom: 8 }}>
        Loss Curve <span style={{ color: theme.textMuted, fontFamily: "'Space Mono', monospace", letterSpacing: 0, textTransform: "none" }}>({data.length} steps)</span>
      </div>
      <ResponsiveContainer width="100%" height={180}>
        <LineChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={theme.border} />
          <XAxis dataKey="step" tick={{ fontSize: 10, fill: theme.textDim }} tickLine={false} axisLine={{ stroke: theme.border }} label={{ value: "step", position: "insideBottom", offset: -2, fontSize: 10, fill: theme.textDim }} />
          <YAxis domain={[minLoss - pad, maxLoss + pad]} tick={{ fontSize: 10, fill: theme.textDim }} tickLine={false} axisLine={{ stroke: theme.border }} tickFormatter={v => v.toFixed(4)} width={52} />
          <Tooltip
            contentStyle={{ background: theme.surface, border: `1px solid ${theme.border}`, borderRadius: 6, fontSize: 11, color: theme.text }}
            formatter={(v) => [v.toFixed(6), "avr_loss"]}
            labelFormatter={(l) => `step ${l}`}
          />
          <Line type="monotone" dataKey="loss" stroke={theme.accent} strokeWidth={1.5} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function AggregationCharts({ aggregations }) {
  if (!aggregations) return null;
  const { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } = Recharts;
  const decadeData = (aggregations.decades || []).map(([decade, count]) => ({ name: `${decade}s`, count }));
  const aspectData = (aggregations.aspect_groups || []).map(([group, count]) => ({ name: group.replace("_", " "), count }));
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
      {decadeData.length > 0 && (<div>
        <div style={{ fontSize: 11, color: theme.textDim, marginBottom: 8, letterSpacing: 1, textTransform: "uppercase" }}>Movies by Decade</div>
        <ResponsiveContainer width="100%" height={180}><BarChart data={decadeData}><XAxis dataKey="name" tick={{ fontSize: 10, fill: theme.textDim }} /><YAxis tick={{ fontSize: 10, fill: theme.textDim }} width={30} /><Tooltip contentStyle={{ background: theme.surface, border: `1px solid ${theme.border}`, borderRadius: 8, fontSize: 12 }} labelStyle={{ color: theme.text }} /><Bar dataKey="count" radius={[4, 4, 0, 0]}>{decadeData.map((_, i) => (<Cell key={i} fill={theme.chartColors[i % theme.chartColors.length]} />))}</Bar></BarChart></ResponsiveContainer>
      </div>)}
      {aspectData.length > 0 && (<div>
        <div style={{ fontSize: 11, color: theme.textDim, marginBottom: 8, letterSpacing: 1, textTransform: "uppercase" }}>Movies by Aspect Ratio</div>
        <ResponsiveContainer width="100%" height={180}><BarChart data={aspectData} layout="vertical"><XAxis type="number" tick={{ fontSize: 10, fill: theme.textDim }} /><YAxis type="category" dataKey="name" tick={{ fontSize: 9, fill: theme.textDim }} width={90} /><Tooltip contentStyle={{ background: theme.surface, border: `1px solid ${theme.border}`, borderRadius: 8, fontSize: 12 }} /><Bar dataKey="count" radius={[0, 4, 4, 0]}>{aspectData.map((_, i) => (<Cell key={i} fill={theme.chartColors[i % theme.chartColors.length]} />))}</Bar></BarChart></ResponsiveContainer>
      </div>)}
    </div>
  );
}

// ═══════════════════════════════════════════
// Scan Panel
// ═══════════════════════════════════════════

function ScanPanel({ onScanComplete }) {
  const [scanning, setScanning] = useState(false);
  const [progress, setProgress] = useState(null);
  const [scanPath, setScanPath] = useState("/home/brad/ai/training/main_datasets");
  const intervalRef = useRef(null);
  const startScan = async () => {
    setScanning(true);
    try {
      await fetch(`${API}/scan`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ root_path: scanPath }) });
      intervalRef.current = setInterval(async () => {
        const res = await fetch(`${API}/scan/status`); const data = await res.json(); setProgress(data);
        if (!data.running) { clearInterval(intervalRef.current); setScanning(false); if (onScanComplete) onScanComplete(); }
      }, 500);
    } catch (e) { setScanning(false); alert("Failed to start scan: " + e.message); }
  };
  return (
    <div>
      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        <input type="text" value={scanPath} onChange={e => setScanPath(e.target.value)}
          style={{ flex: 1, padding: "8px 12px", borderRadius: 8, border: `1px solid ${theme.border}`, background: theme.bg, color: theme.text, fontSize: 13, fontFamily: "'DM Sans', sans-serif" }} />
        <button onClick={startScan} disabled={scanning} style={{ padding: "8px 20px", borderRadius: 8, border: "none", background: scanning ? theme.surfaceAlt : `linear-gradient(135deg, ${theme.accentDim}, ${theme.accent})`, color: "white", fontSize: 13, fontWeight: 600, cursor: scanning ? "wait" : "pointer", fontFamily: "'DM Sans', sans-serif", opacity: scanning ? 0.6 : 1 }}>{scanning ? "Scanning..." : "Scan"}</button>
      </div>
      {scanning && progress && (<div>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: theme.textMuted, marginBottom: 4 }}><span>{progress.current}</span><span style={{ fontFamily: "'Space Mono', monospace" }}>{progress.progress}/{progress.total}</span></div>
        <div style={{ height: 4, borderRadius: 2, background: theme.bg, overflow: "hidden" }}><div style={{ height: "100%", borderRadius: 2, background: `linear-gradient(90deg, ${theme.accentDim}, ${theme.accent})`, width: progress.total ? `${(progress.progress / progress.total) * 100}%` : "0%", transition: "width 0.3s" }} /></div>
      </div>)}
      {!scanning && progress?.stats && (<div style={{ fontSize: 12, color: theme.textMuted, padding: 12, borderRadius: 8, background: theme.bg, marginTop: 8, fontFamily: "'Space Mono', monospace" }}>
        {progress.stats.error ? (<span style={{ color: theme.danger }}>Error: {progress.stats.error}</span>) : (<>Found {progress.stats.movies_found} movies ({progress.stats.movies_new} new) · {progress.stats.images_found?.toLocaleString()} images ({progress.stats.images_new?.toLocaleString()} new){progress.stats.errors?.length > 0 && (<div style={{ color: theme.warning, marginTop: 4 }}>{progress.stats.errors.length} errors</div>)}</>)}
      </div>)}
    </div>
  );
}

// ═══════════════════════════════════════════
// Movie Card (NEW — for browse grid)
// ═══════════════════════════════════════════

function MovieCard({ movie, onToggle, onClick }) {
  const [hovered, setHovered] = useState(false);
  const selected = !!movie.selected;
  const hasExclusions = movie.excluded_count > 0;
  return (
    <div onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)}
      style={{ borderRadius: 10, overflow: "hidden", cursor: "pointer", border: `1px solid ${selected ? theme.selectedBorder : hovered ? theme.borderHover : theme.border}`, background: selected ? theme.selectedBg : theme.surface, transition: "all 0.15s", position: "relative" }}>
      <div onClick={onClick} style={{ position: "relative", aspectRatio: "16/10", overflow: "hidden", background: theme.bg }}>
        {movie.thumbnail_id ? (
          <img src={`${API}/image/serve/${movie.thumbnail_id}`} alt={movie.title} loading="lazy" style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} />
        ) : (
          <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: theme.textDim, fontSize: 28 }}>🎬</div>
        )}
        <div style={{ position: "absolute", bottom: 6, right: 6, padding: "2px 7px", borderRadius: 4, fontSize: 11, background: "rgba(0,0,0,0.75)", color: "#fff", fontFamily: "'Space Mono', monospace", fontWeight: 600 }}>{movie.image_count}</div>
        {hasExclusions && selected && (<div style={{ position: "absolute", bottom: 6, left: 6, padding: "2px 7px", borderRadius: 4, fontSize: 10, background: "rgba(248,113,113,0.85)", color: "#fff", fontFamily: "'Space Mono', monospace" }}>-{movie.excluded_count}</div>)}
      </div>
      <div style={{ padding: "8px 10px", display: "flex", alignItems: "center", gap: 8 }}>
        <Checkbox checked={selected} onChange={onToggle} size={16} />
        <div style={{ flex: 1, minWidth: 0 }} onClick={onClick}>
          <div style={{ fontSize: 12, fontWeight: 600, color: theme.text, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", fontFamily: "'DM Sans', sans-serif" }}>{movie.title || movie.folder_name}</div>
          <div style={{ fontSize: 11, color: theme.textDim, fontFamily: "'Space Mono', monospace" }}>{movie.year || "?"} · {movie.aspect_ratio_group || "?"}</div>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════
// Movie Detail View (NEW — all frames)
// ═══════════════════════════════════════════

function MovieDetailView({ movieId, onBack, onSelectionChange, onDataUpdate }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const fetchImages = useCallback(async (p = 1) => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/browse/movies/${movieId}/images?page=${p}&per_page=200`);
      const j = await res.json();
      setData(j);
      if (onDataUpdate) onDataUpdate(j, p);
    } catch (e) { console.error(e); }
    setLoading(false);
  }, [movieId, onDataUpdate]);
  useEffect(() => { fetchImages(page); }, [page, fetchImages]);
  const toggleMovie = async () => {
    await fetch(`${API}/selection/toggle-movie`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ movie_id: movieId }) });
    fetchImages(page); if (onSelectionChange) onSelectionChange();
  };
  const toggleImage = async (imageId) => {
    await fetch(`${API}/selection/toggle-image`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ image_id: imageId }) });
    fetchImages(page); if (onSelectionChange) onSelectionChange();
  };
  // Expose controls for the unified footer
  useEffect(() => {
    window._detailControls = { setPage, toggleMovie, page, totalPages: data?.total_pages || 1, movieSelected: !!data?.movie?.selected };
    return () => { window._detailControls = null; };
  });
  if (loading && !data) return <div style={{ textAlign: "center", padding: 60, color: theme.textDim }}>Loading...</div>;
  if (!data) return null;
  const movie = data.movie;
  const movieSelected = !!movie.selected;
  return (
    <div>
      <div style={{ padding: "12px 20px", background: theme.surface, borderRadius: 10, border: `1px solid ${theme.border}`, marginBottom: 16 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: theme.text }}>{movie.title || movie.folder_name}</h2>
          {movie.year && <span style={{ padding: "2px 8px", borderRadius: 10, fontSize: 11, fontWeight: 600, background: `${theme.textMuted}22`, color: theme.textMuted, fontFamily: "'Space Mono', monospace" }}>{movie.year}</span>}
          {movie.aspect_ratio_group && <span style={{ padding: "2px 8px", borderRadius: 10, fontSize: 11, fontWeight: 600, background: `${theme.accent}22`, color: theme.accent, fontFamily: "'Space Mono', monospace" }}>{movie.aspect_ratio_group}</span>}
          <span style={{ fontSize: 12, color: movieSelected ? theme.selected : theme.textDim, fontWeight: 600, marginLeft: "auto" }}>{movieSelected ? "✓ Selected" : "Not selected"} · {data.total} frames</span>
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 8 }}>
        {data.images.map(img => {
          const included = img.included; const hasOverride = img.has_override;
          return (
            <div key={img.id} style={{ position: "relative", borderRadius: 8, overflow: "hidden", border: `1px solid ${included ? theme.selectedBorder : theme.border}`, transition: "all 0.15s" }}>
              <img src={`${API}/image/serve/${img.id}`} alt={img.filename} loading="lazy" style={{ width: "100%", aspectRatio: "16/10", objectFit: "cover", display: "block", cursor: "pointer" }} onClick={() => toggleImage(img.id)} />
              <div style={{ position: "absolute", top: 6, left: 6 }}><Checkbox checked={included} onChange={() => toggleImage(img.id)} size={18} color={included ? theme.selected : theme.danger} /></div>
              {hasOverride && (<div style={{ position: "absolute", top: 6, right: 6, width: 8, height: 8, borderRadius: "50%", background: included ? theme.selected : theme.danger }} />)}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════
// Unified Browse Footer (pinned)
// ═══════════════════════════════════════════

const footerBtn = (props) => ({
  padding: "7px 14px", borderRadius: 6, fontSize: 12, fontWeight: 600,
  cursor: "pointer", fontFamily: "'DM Sans', sans-serif", ...props,
});

function BrowseFooter({
  summary, inDetail, openMovieId,
  onApply, onBack,
  onSelectAllFiltered, onDeselectAllFiltered, onClear,
  browsePage, browseTotalPages, onBrowsePageChange,
}) {
  const hasSelection = summary && (summary.selected_movies > 0 || summary.force_included_images > 0);
  // Read detail controls from the component (exposed via window)
  const dc = window._detailControls;

  return (
    <div style={{
      position: "fixed", bottom: 0, left: 0, right: 0, padding: "8px 24px",
      display: "flex", alignItems: "center", gap: 12,
      background: theme.surface, borderTop: `1px solid ${theme.border}`, zIndex: 100,
    }}>
      {/* Left: context-specific buttons */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {inDetail ? (
          <>
            <button onClick={onBack} style={footerBtn({ border: `1px solid ${theme.border}`, background: "transparent", color: theme.textMuted })}>← Back</button>
            {dc && (
              <button onClick={() => dc.toggleMovie()} style={footerBtn({
                border: "none",
                background: dc.movieSelected ? theme.dangerDim : theme.successDim,
                color: dc.movieSelected ? theme.danger : theme.selected,
              })}>{dc.movieSelected ? "Deselect Movie" : "Select Movie"}</button>
            )}
          </>
        ) : (
          <button onClick={onApply} style={footerBtn({
            border: "none",
            background: `linear-gradient(135deg, ${theme.accentDim}, ${theme.accent})`,
            color: "#fff",
          })}>Apply Filters</button>
        )}
      </div>

      {/* Center: pagination */}
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        {inDetail && dc && dc.totalPages > 1 ? (
          <>
            <button onClick={() => dc.setPage(p => Math.max(1, p - 1))} disabled={dc.page <= 1}
              style={footerBtn({ border: `1px solid ${theme.border}`, background: "transparent", color: dc.page <= 1 ? theme.textDim : theme.textMuted, opacity: dc.page <= 1 ? 0.4 : 1 })}>◀</button>
            <span style={{ fontSize: 12, color: theme.textDim, fontFamily: "'Space Mono', monospace", minWidth: 50, textAlign: "center" }}>{dc.page}/{dc.totalPages}</span>
            <button onClick={() => dc.setPage(p => Math.min(dc.totalPages, p + 1))} disabled={dc.page >= dc.totalPages}
              style={footerBtn({ border: `1px solid ${theme.border}`, background: "transparent", color: dc.page >= dc.totalPages ? theme.textDim : theme.textMuted, opacity: dc.page >= dc.totalPages ? 0.4 : 1 })}>▶</button>
          </>
        ) : !inDetail && browseTotalPages > 1 ? (
          <>
            <button onClick={() => onBrowsePageChange(browsePage - 1)} disabled={browsePage <= 1}
              style={footerBtn({ border: `1px solid ${theme.border}`, background: "transparent", color: browsePage <= 1 ? theme.textDim : theme.textMuted, opacity: browsePage <= 1 ? 0.4 : 1 })}>◀</button>
            <span style={{ fontSize: 12, color: theme.textDim, fontFamily: "'Space Mono', monospace", minWidth: 50, textAlign: "center" }}>{browsePage}/{browseTotalPages}</span>
            <button onClick={() => onBrowsePageChange(browsePage + 1)} disabled={browsePage >= browseTotalPages}
              style={footerBtn({ border: `1px solid ${theme.border}`, background: "transparent", color: browsePage >= browseTotalPages ? theme.textDim : theme.textMuted, opacity: browsePage >= browseTotalPages ? 0.4 : 1 })}>▶</button>
          </>
        ) : null}
      </div>

      {/* Spacer */}
      <div style={{ flex: 1 }} />

      {/* Right: selection summary + bulk actions */}
      {summary && (
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <div style={{ width: 8, height: 8, borderRadius: "50%", background: hasSelection ? theme.selected : theme.textDim }} />
            <span style={{ fontSize: 12, color: theme.textMuted, fontFamily: "'Space Mono', monospace" }}>
              <span style={{ color: theme.selected, fontWeight: 600 }}>{summary.selected_movies}</span> movies
              <span style={{ margin: "0 6px", color: theme.textDim }}>·</span>
              <span style={{ color: theme.accent, fontWeight: 600 }}>{summary.total_images.toLocaleString()}</span> images
              {summary.excluded_images > 0 && <span style={{ color: theme.danger, marginLeft: 6 }}>(-{summary.excluded_images})</span>}
            </span>
          </div>
          {!inDetail && (
            <>
              <button onClick={onSelectAllFiltered} style={footerBtn({ border: `1px solid ${theme.selectedBorder}`, background: "transparent", color: theme.selected })}>Select All</button>
              <button onClick={onDeselectAllFiltered} style={footerBtn({ border: `1px solid ${theme.border}`, background: "transparent", color: theme.textMuted })}>Deselect All</button>
            </>
          )}
          {hasSelection && (
            <button onClick={onClear} style={footerBtn({ border: `1px solid ${theme.dangerDim}`, background: "transparent", color: theme.danger })}>Clear</button>
          )}
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════
// LoRA Training Presets
// ═══════════════════════════════════════════

const LORA_PRESETS = {
  style: {
    label: "Style",
    tagging_prompt: `Describe this image in 3-4 sentences focusing on the visual style and cinematographic qualities.\n\nThis is a cinematic image from an Italian Horror movie .\n\nEmphasize:\n- Lighting, color palette, and film grain characteristics\n- Composition and framing style\n- Mood and atmosphere\n- Brief subject description\n\nWrite naturally and descriptively`,
    learning_rate: "1e-5",
    network_dim: 32,
    network_alpha: 16,
    max_epochs: 12,
    save_every_n_epochs: 2,
  },
  character: {
    label: "Character",
    tagging_prompt: `Describe this image in 3-4 sentences focusing on the visual characteristics of the subject.\n\nThis is a cinematic image of [BRIEF CONTEXT HELPER].\n\nEmphasize:\n- Wardrobe, props, jewelry,  \n- Detailed description of face, hands, hair, eyes, nose\n\nWrite naturally and descriptively`,
    learning_rate: "5e-5",
    network_dim: 32,
    network_alpha: 16,
    max_epochs: 20,
    save_every_n_epochs: 2,
  },
  object: {
    label: "Object",
    tagging_prompt: `Describe this image in 3-4 sentences focusing on the visual characteristics of the object.\n\nEmphasize:\n- Shape, material, and surface texture\n- Color and any distinctive markings or features\n- Size relative to surroundings\n- Brief context or setting\n\nWrite naturally and descriptively`,
    learning_rate: "1e-4",
    network_dim: 16,
    network_alpha: 8,
    max_epochs: 12,
    save_every_n_epochs: 2,
  },
  environment: {
    label: "Environment",
    tagging_prompt: `Describe this image in 3-4 sentences focusing on the visual characteristics of the environment.\n\nEmphasize:\n- Architectural elements or landscape features\n- Lighting conditions, time of day, and weather\n- Color palette and film grain\n- Mood and atmosphere\n\nWrite naturally and descriptively`,
    learning_rate: "5e-5",
    network_dim: 32,
    network_alpha: 16,
    max_epochs: 16,
    save_every_n_epochs: 2,
  },
};

// ═══════════════════════════════════════════
// Main App
// ═══════════════════════════════════════════

export default function App() {
  const [stats, setStats] = useState(null);
  const [filterOptions, setFilterOptions] = useState(null);
  const [filters, setFilters] = useState({});
  const [results, setResults] = useState(null);
  const [sampleImages, setSampleImages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [loadingImages, setLoadingImages] = useState(false);
  const [sampleSize, setSampleSize] = useState(24);
  const [activeTab, setActiveTab] = useState("browse");
  const [scanCollapsed, setScanCollapsed] = useState(true);

  // Browse movie grid state
  const [browseMovies, setBrowseMovies] = useState([]);
  const [browseTotalMovies, setBrowseTotalMovies] = useState(0);
  const [browseTotalPages, setBrowseTotalPages] = useState(1);
  const [browseCurrentPage, setBrowseCurrentPage] = useState(1);
  const [browseLoading, setBrowseLoading] = useState(false);
  const [openMovieId, setOpenMovieId] = useState(null);
  const [selectionSummary, setSelectionSummary] = useState(null);
  const [browseSortBy, setBrowseSortBy] = useState("title");

  // Tag browser state
  const [topTags, setTopTags] = useState([]);
  const [tagSearch, setTagSearch] = useState("");
  const [tagSearchResults, setTagSearchResults] = useState([]);
  const [tagInclude, setTagInclude] = useState([]);
  const [tagExclude, setTagExclude] = useState([]);
  const [tagImages, setTagImages] = useState([]);
  const [tagImagesLoading, setTagImagesLoading] = useState(false);
  const [taggerStatus, setTaggerStatus] = useState(null);

  // Pipeline state
  const [pipelineStatus, setPipelineStatus] = useState(null);
  const [pipelineProjects, setPipelineProjects] = useState([]);
  const [pipelineForm, setPipelineForm] = useState({
    name: "", description: "", trigger_word: "",
    tagging_prompt: "Describe this image in detail for AI training. Include the subject, setting, lighting, mood, color palette, composition, and any notable visual elements.",
    tagging_model: "qwen2.5vl:32b",
    learning_rate: "5e-5", network_dim: 32, network_alpha: 16, max_epochs: 16,
    save_every_n_epochs: 2, resolution: 1024,
    enable_samples: false, sample_prompts: [],
    source_type: "selection", source_path: "",
    dit_model: "qwen_image_bf16.safetensors",
  });
  const [pipelineLog, setPipelineLog] = useState([]);
  const pipelineInterval = useRef(null);

  useEffect(() => { fetchStats(); fetchFilterOptions(); fetchSelectionSummary(); fetchBrowseMovies(1); }, []);
  useEffect(() => { if (activeTab === "tags") { fetchTopTags(); fetchTaggerStatus(); } }, [activeTab]);
  useEffect(() => {
    if (activeTab === "pipeline") {
      fetchPipelineStatus(); fetchPipelineProjects();
      pipelineInterval.current = setInterval(fetchPipelineStatus, 2000);
      return () => clearInterval(pipelineInterval.current);
    } else { if (pipelineInterval.current) clearInterval(pipelineInterval.current); }
  }, [activeTab]);

  const fetchStats = async () => { try { const r = await fetch(`${API}/stats`); setStats(await r.json()); } catch (e) { console.error(e); } };
  const fetchFilterOptions = async () => { try { const r = await fetch(`${API}/filters`); setFilterOptions(await r.json()); } catch (e) { console.error(e); } };
  const fetchSelectionSummary = async () => { try { const r = await fetch(`${API}/selection/summary`); setSelectionSummary(await r.json()); } catch (e) {} };

  const applyFilters = async (page = 1) => {
    setLoading(true);
    try { const r = await fetch(`${API}/movies/filter`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...filters, page, per_page: 50 }) }); setResults(await r.json()); } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  const buildBrowseParams = useCallback(() => {
    const p = new URLSearchParams();
    if (filters.year_min) p.set("year_min", filters.year_min);
    if (filters.year_max) p.set("year_max", filters.year_max);
    if (filters.languages?.length) p.set("languages", filters.languages.join(","));
    if (filters.genres?.length) p.set("genres", filters.genres.join(","));
    if (filters.countries?.length) p.set("countries", filters.countries.join(","));
    if (filters.aspect_groups?.length) p.set("aspects", filters.aspect_groups.join(","));
    if (filters.keywords_include?.length) p.set("keywords", filters.keywords_include.join(","));
    if (filters.keywords_exclude?.length) p.set("keywords_exclude", filters.keywords_exclude.join(","));
    if (filters.search) p.set("search", filters.search);
    return p;
  }, [filters]);

  const fetchBrowseMovies = useCallback(async (page = 1) => {
    setBrowseLoading(true);
    try {
      const p = buildBrowseParams(); p.set("page", page); p.set("per_page", 60); p.set("sort", browseSortBy);
      const r = await fetch(`${API}/browse/movies?${p}`); const j = await r.json();
      setBrowseMovies(j.movies); setBrowseTotalMovies(j.total); setBrowseTotalPages(j.total_pages); setBrowseCurrentPage(page);
    } catch (e) { console.error(e); }
    setBrowseLoading(false);
  }, [buildBrowseParams, browseSortBy]);

  const handleToggleMovieSelection = async (movieId) => {
    await fetch(`${API}/selection/toggle-movie`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ movie_id: movieId }) });
    setBrowseMovies(prev => prev.map(m => m.id === movieId ? { ...m, selected: m.selected ? 0 : 1 } : m));
    fetchSelectionSummary();
  };
  const handleSelectAllFiltered = async () => { await fetch(`${API}/selection/select-all-filtered?${buildBrowseParams()}`, { method: "POST" }); fetchBrowseMovies(browseCurrentPage); fetchSelectionSummary(); };
  const handleDeselectAllFiltered = async () => { await fetch(`${API}/selection/deselect-all-filtered?${buildBrowseParams()}`, { method: "POST" }); fetchBrowseMovies(browseCurrentPage); fetchSelectionSummary(); };
  const handleClearAll = async () => { await fetch(`${API}/selection/clear`, { method: "POST" }); fetchBrowseMovies(browseCurrentPage); fetchSelectionSummary(); };
  const handleApplyFilters = () => { setOpenMovieId(null); applyFilters(1); fetchBrowseMovies(1); };

  const fetchSampleImages = async (size) => {
    const count = size || sampleSize; setLoadingImages(true);
    try {
      const hasFilters = Object.values(filters).some(v => v !== undefined && v !== "" && (!Array.isArray(v) || v.length > 0));
      if (hasFilters) { const r = await fetch(`${API}/images/sample`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...filters, count }) }); setSampleImages(await r.json()); }
      else { const r = await fetch(`${API}/images/random?count=${count}`); setSampleImages(await r.json()); }
    } catch (e) { console.error(e); } finally { setLoadingImages(false); }
  };

  const clearFilters = () => { setFilters({}); setResults(null); setSampleImages([]); };
  const fetchTopTags = async () => { try { const r = await fetch(`${API}/tags/top?limit=150`); setTopTags(await r.json()); } catch (e) {} };
  const searchTags = async (query) => { setTagSearch(query); if (!query.trim()) { setTagSearchResults([]); return; } try { const r = await fetch(`${API}/tags/search?q=${encodeURIComponent(query)}&limit=30`); setTagSearchResults(await r.json()); } catch (e) {} };
  const fetchTagImages = async () => { if (tagInclude.length === 0 && tagExclude.length === 0) return; setTagImagesLoading(true); try { const r = await fetch(`${API}/images/filter-by-tags`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ include_tags: tagInclude, exclude_tags: tagExclude, count: 48 }) }); setTagImages(await r.json()); } catch (e) {} finally { setTagImagesLoading(false); } };
  const fetchTaggerStatus = async () => { try { const r = await fetch(`${API}/tagger/status`); setTaggerStatus(await r.json()); } catch (e) {} };
  const toggleTag = (list, setList, tag) => { setList(prev => prev.includes(tag) ? prev.filter(t => t !== tag) : [...prev, tag]); };

  // ── Pipeline functions ──
  const fetchPipelineStatus = async () => { try { const r = await fetch(`${API}/pipeline/status`); const j = await r.json(); setPipelineStatus(j); setPipelineLog(j.log_lines || []); } catch (e) {} };
  const fetchPipelineProjects = async () => { try { const r = await fetch(`${API}/pipeline/projects`); setPipelineProjects(await r.json()); } catch (e) {} };
  const createProject = async () => {
    try {
      const isFromPath = pipelineForm.source_type === "external_path";
      if (isFromPath && !pipelineForm.source_path.trim()) {
        alert("Please enter a source dataset path."); return;
      }
      const endpoint = isFromPath ? "/pipeline/create-from-path" : "/pipeline/create";
      const payload = isFromPath
        ? { ...pipelineForm, source_path: pipelineForm.source_path.trim() }
        : pipelineForm;
      const r = await fetch(`${API}${endpoint}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      if (!r.ok) {
        let msg = `Error ${r.status}`;
        try { const e = await r.json(); msg = e.detail || msg; } catch { msg = await r.text().catch(() => msg); }
        alert(msg); return;
      }
      fetchPipelineStatus(); fetchPipelineProjects();
    } catch (e) { alert("Error: " + e.message); }
  };
  const loadProject = async (dir) => {
    try {
      const r = await fetch(`${API}/pipeline/load`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project_dir: dir }) });
      if (!r.ok) { let msg = "Error"; try { msg = (await r.json()).detail; } catch {} alert(msg); return; }
      fetchPipelineStatus();
    } catch (e) { alert("Error: " + e.message); }
  };
  const runPipelineStep = async (step) => {
    const endpoints = { tag: "/pipeline/tag", cache: "/pipeline/cache?cache_type=both", train: "/pipeline/train" };
    try {
      const r = await fetch(`${API}${endpoints[step]}`, { method: "POST" });
      if (!r.ok) { let msg = "Error"; try { msg = (await r.json()).detail; } catch {} alert(msg); return; }
      fetchPipelineStatus();
    } catch (e) { alert("Error: " + e.message); }
  };
  const stopPipeline = async () => { try { await fetch(`${API}/pipeline/stop`, { method: "POST" }); fetchPipelineStatus(); } catch (e) {} };

  const activeFilterCount = Object.values(filters).filter(v => v !== undefined && v !== "" && (!Array.isArray(v) || v.length > 0)).length;

  return (
    <div style={{ minHeight: "100vh", background: theme.bg, color: theme.text, fontFamily: "'DM Sans', sans-serif" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Space+Mono:wght@400;700&display=swap');
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: ${theme.bg}; }
        ::-webkit-scrollbar { width: 8px; height: 8px; }
        ::-webkit-scrollbar-track { background: ${theme.bg}; }
        ::-webkit-scrollbar-thumb { background: ${theme.border}; border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: ${theme.borderHover}; }
        @keyframes pulse { 0%, 100% { opacity: 0.4; } 50% { opacity: 0.7; } }
        input:focus { border-color: ${theme.accent} !important; outline: none; }
        img { user-select: none; -webkit-user-drag: none; }
      `}</style>

      {/* Header */}
      <header style={{ borderBottom: `1px solid ${theme.border}`, padding: "16px 32px", display: "flex", justifyContent: "space-between", alignItems: "center", background: `linear-gradient(180deg, ${theme.surface}, ${theme.bg})` }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 700, letterSpacing: -0.5, background: `linear-gradient(135deg, ${theme.accent}, #818cf8)`, WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>LoRA Dataset Curator</h1>
          <div style={{ fontSize: 11, color: theme.textDim, marginTop: 2 }}>Filter · Select · Curate · Train</div>
        </div>
        {stats && (<div style={{ display: "flex", gap: 24, fontSize: 12 }}>
          <div><span style={{ color: theme.textDim }}>Movies</span> <span style={{ color: theme.accent, fontFamily: "'Space Mono', monospace", fontWeight: 700 }}>{stats.total_movies?.toLocaleString()}</span></div>
          <div><span style={{ color: theme.textDim }}>Images</span> <span style={{ color: theme.accent, fontFamily: "'Space Mono', monospace", fontWeight: 700 }}>{stats.total_images?.toLocaleString()}</span></div>
          <div><span style={{ color: theme.textDim }}>Tagged</span> <span style={{ color: theme.textMuted, fontFamily: "'Space Mono', monospace" }}>{stats.tagged_images?.toLocaleString()}</span></div>
        </div>)}
      </header>

      {/* Tab Bar */}
      <nav style={{ borderBottom: `1px solid ${theme.border}`, padding: "0 32px", display: "flex", gap: 0 }}>
        {[{ id: "browse", label: "Browse & Select" }, { id: "preview", label: "Image Preview" }, { id: "tags", label: "Tags" }, { id: "pipeline", label: "Pipeline" }, { id: "settings", label: "Settings" }].map(tab => (
          <button key={tab.id} onClick={() => { setActiveTab(tab.id); setOpenMovieId(null); }}
            style={{ padding: "12px 20px", fontSize: 13, fontWeight: 500, background: "transparent", border: "none", cursor: "pointer", color: activeTab === tab.id ? theme.accent : theme.textMuted, borderBottom: activeTab === tab.id ? `2px solid ${theme.accent}` : "2px solid transparent", transition: "all 0.15s", fontFamily: "'DM Sans', sans-serif" }}>{tab.label}</button>
        ))}
      </nav>

      {/* Main Content */}
      <main style={{ padding: 32, paddingBottom: activeTab === "browse" ? 80 : 32 }}>
        <Section title="Scan Dataset" collapsed={scanCollapsed} onToggle={() => setScanCollapsed(!scanCollapsed)}>
          <ScanPanel onScanComplete={() => { fetchStats(); fetchFilterOptions(); fetchBrowseMovies(1); }} />
        </Section>

        {/* ═══ BROWSE & SELECT TAB ═══ */}
        {activeTab === "browse" && (
          <div style={{ display: "grid", gridTemplateColumns: "320px 1fr", gap: 24 }}>
            <div style={{ position: "sticky", top: 16, alignSelf: "start", maxHeight: "calc(100vh - 140px)", display: "flex", flexDirection: "column" }}>
              <Section title="Filters" actions={activeFilterCount > 0 && (<button onClick={clearFilters} style={{ fontSize: 11, color: theme.textMuted, background: "transparent", border: "none", cursor: "pointer", textDecoration: "underline" }}>Clear ({activeFilterCount})</button>)} style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
                <FilterPanel filterOptions={filterOptions} filters={filters} setFilters={setFilters} onApply={handleApplyFilters} />
              </Section>
            </div>
            <div>
              {results && (<div style={{ display: "flex", gap: 12, marginBottom: 16 }}>
                <StatCard label="Matching Movies" value={results.total_movies} icon="🎬" />
                <StatCard label="Total Images" value={results.total_images} icon="🖼" />
                <StatCard label="Avg per Movie" value={results.total_movies ? Math.round(results.total_images / results.total_movies) : 0} icon="📊" />
              </div>)}
              {results?.aggregations && (<Section title="Distribution"><AggregationCharts aggregations={results.aggregations} /></Section>)}
              {!openMovieId && (<div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
                <div style={{ fontSize: 13, color: theme.textMuted }}><span style={{ color: theme.accent, fontWeight: 700, fontFamily: "'Space Mono', monospace" }}>{browseTotalMovies.toLocaleString()}</span> movies</div>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ fontSize: 11, color: theme.textDim }}>Sort:</span>
                  {[{ value: "title", label: "A-Z" }, { value: "year", label: "Year ↓" }, { value: "year_asc", label: "Year ↑" }, { value: "images", label: "Most" }].map(s => (
                    <button key={s.value} onClick={() => { setBrowseSortBy(s.value); setTimeout(() => fetchBrowseMovies(1), 0); }}
                      style={{ padding: "4px 8px", borderRadius: 4, fontSize: 11, border: `1px solid ${browseSortBy === s.value ? theme.accent : theme.border}`, background: browseSortBy === s.value ? `${theme.accent}18` : "transparent", color: browseSortBy === s.value ? theme.accent : theme.textMuted, cursor: "pointer" }}>{s.label}</button>
                  ))}
                </div>
              </div>)}
              {openMovieId ? (
                <MovieDetailView movieId={openMovieId}
                  onBack={() => { setOpenMovieId(null); fetchBrowseMovies(browseCurrentPage); fetchSelectionSummary(); }}
                  onSelectionChange={fetchSelectionSummary} />
              ) : (<>
                {browseLoading ? (<div style={{ textAlign: "center", padding: 60, color: theme.textDim }}>Loading...</div>) : browseMovies.length === 0 ? (<div style={{ textAlign: "center", padding: 60, color: theme.textDim }}>{results ? "No movies match your filters" : "Click Apply Filters to browse your dataset"}</div>) : (
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 12 }}>
                    {browseMovies.map(movie => (<MovieCard key={movie.id} movie={movie} onToggle={() => handleToggleMovieSelection(movie.id)} onClick={() => setOpenMovieId(movie.id)} />))}
                  </div>
                )}
              </>)}
            </div>
          </div>
        )}

        {/* ═══ PREVIEW TAB ═══ */}
        {activeTab === "preview" && (<div>
          <div style={{ display: "flex", gap: 12, marginBottom: 20, alignItems: "center", flexWrap: "wrap" }}>
            <button onClick={() => fetchSampleImages()} disabled={loadingImages} style={{ padding: "10px 24px", borderRadius: 8, border: "none", background: `linear-gradient(135deg, ${theme.accentDim}, ${theme.accent})`, color: "white", fontSize: 13, fontWeight: 600, cursor: loadingImages ? "wait" : "pointer", fontFamily: "'DM Sans', sans-serif", opacity: loadingImages ? 0.6 : 1 }}>
              {loadingImages ? "Loading..." : (Object.values(filters).some(v => v !== undefined && v !== "" && (!Array.isArray(v) || v.length > 0)) ? "Sample from Filtered Set" : "Random Sample (All)")}
            </button>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ fontSize: 12, color: theme.textDim }}>Count:</span>
              {[24, 48, 96, 200].map(size => (<button key={size} onClick={() => { setSampleSize(size); fetchSampleImages(size); }} style={{ padding: "5px 10px", borderRadius: 6, fontSize: 12, fontFamily: "'Space Mono', monospace", border: `1px solid ${sampleSize === size ? theme.accent : theme.border}`, background: sampleSize === size ? `${theme.accent}22` : "transparent", color: sampleSize === size ? theme.accent : theme.textMuted, cursor: "pointer" }}>{size}</button>))}
            </div>
            {sampleImages.length > 0 && (<div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: theme.textMuted, fontFamily: "'Space Mono', monospace" }}>{sampleImages.length} images<span style={{ color: theme.textDim }}>·</span><span style={{ color: theme.textDim }}>{new Set(sampleImages.map(i => i.movie_id)).size} movies</span></div>)}
          </div>
          <ImageGrid images={sampleImages} loading={loadingImages} />
        </div>)}

        {/* ═══ TAGS TAB ═══ */}
        {activeTab === "tags" && (<div>
          {taggerStatus && (taggerStatus.process_running || taggerStatus.processed > 0) && (
            <div style={{ background: theme.surface, border: `1px solid ${theme.border}`, borderRadius: 10, padding: "14px 20px", marginBottom: 16, display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
              <div style={{ width: 8, height: 8, borderRadius: "50%", background: taggerStatus.process_running ? theme.success : theme.textDim, boxShadow: taggerStatus.process_running ? `0 0 8px ${theme.success}` : "none" }} />
              <div style={{ fontSize: 13, color: theme.text }}>{taggerStatus.process_running ? "Tagger running" : "Tagger idle"}</div>
              {taggerStatus.processed > 0 && (<>
                <div style={{ fontSize: 12, color: theme.textMuted, fontFamily: "'Space Mono', monospace" }}>{taggerStatus.processed?.toLocaleString()}/{taggerStatus.total?.toLocaleString()} images</div>
                {taggerStatus.rate > 0 && (<div style={{ fontSize: 12, color: theme.textDim }}>{taggerStatus.rate} img/s</div>)}
                {taggerStatus.eta_seconds > 0 && taggerStatus.process_running && (<div style={{ fontSize: 12, color: theme.textDim }}>~{Math.floor(taggerStatus.eta_seconds / 3600)}h{Math.floor((taggerStatus.eta_seconds % 3600) / 60).toString().padStart(2, "0")}m remaining</div>)}
                {taggerStatus.current_movie && taggerStatus.process_running && (<div style={{ fontSize: 12, color: theme.textDim, marginLeft: "auto" }}>{taggerStatus.current_movie}</div>)}
              </>)}
              <button onClick={fetchTaggerStatus} style={{ marginLeft: "auto", padding: "4px 10px", borderRadius: 5, background: "transparent", border: `1px solid ${theme.border}`, color: theme.textMuted, fontSize: 11, cursor: "pointer" }}>Refresh</button>
            </div>
          )}
          <div style={{ display: "grid", gridTemplateColumns: "320px 1fr", gap: 24 }}>
            <div style={{ position: "sticky", top: 16, alignSelf: "start", maxHeight: "calc(100vh - 140px)", display: "flex", flexDirection: "column" }}>
              <Section title="Tag Filters" style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
                <div style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: 16, paddingBottom: 16 }}>
                  <div>
                    <label style={{ fontSize: 11, color: theme.textDim, letterSpacing: 1, textTransform: "uppercase", display: "block", marginBottom: 6 }}>Search Tags</label>
                    <input type="text" value={tagSearch} onChange={e => searchTags(e.target.value)} placeholder="Type to search tags..."
                      style={{ width: "100%", padding: "8px 12px", borderRadius: 8, border: `1px solid ${theme.border}`, background: theme.bg, color: theme.text, fontSize: 13, fontFamily: "'DM Sans', sans-serif", outline: "none", boxSizing: "border-box" }} />
                    {tagSearchResults.length > 0 && (<div style={{ marginTop: 6, display: "flex", flexWrap: "wrap", gap: 4 }}>
                      {tagSearchResults.map(({ tag, count }) => {
                        const included = tagInclude.includes(tag); const excluded = tagExclude.includes(tag);
                        return (<div key={tag} style={{ display: "flex", gap: 2 }}>
                          <button onClick={() => { toggleTag(tagInclude, setTagInclude, tag); if (tagExclude.includes(tag)) toggleTag(tagExclude, setTagExclude, tag); }}
                            style={{ padding: "3px 6px", borderRadius: "5px 0 0 5px", fontSize: 11, cursor: "pointer", background: included ? `${theme.success}22` : "transparent", border: `1px solid ${included ? theme.success : theme.border}`, borderRight: "none", color: included ? theme.success : theme.textMuted }}>+ {tag} <span style={{ fontSize: 9, opacity: 0.6 }}>{count}</span></button>
                          <button onClick={() => { toggleTag(tagExclude, setTagExclude, tag); if (tagInclude.includes(tag)) toggleTag(tagInclude, setTagInclude, tag); }}
                            style={{ padding: "3px 6px", borderRadius: "0 5px 5px 0", fontSize: 11, cursor: "pointer", background: excluded ? `${theme.danger}22` : "transparent", border: `1px solid ${excluded ? theme.danger : theme.border}`, color: excluded ? theme.danger : theme.textDim }}>−</button>
                        </div>);
                      })}
                    </div>)}
                  </div>
                  {tagInclude.length > 0 && (<div>
                    <label style={{ fontSize: 11, color: theme.textDim, letterSpacing: 1, textTransform: "uppercase", display: "block", marginBottom: 4 }}>Include ({tagInclude.length})</label>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                      {tagInclude.map(tag => (<button key={tag} onClick={() => toggleTag(tagInclude, setTagInclude, tag)} style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "3px 8px", borderRadius: 5, background: `${theme.success}22`, border: `1px solid ${theme.success}`, color: theme.success, fontSize: 11, cursor: "pointer" }}>{tag} <span style={{ fontSize: 9, opacity: 0.7 }}>✕</span></button>))}
                    </div>
                  </div>)}
                  {tagExclude.length > 0 && (<div>
                    <label style={{ fontSize: 11, color: theme.textDim, letterSpacing: 1, textTransform: "uppercase", display: "block", marginBottom: 4 }}>Exclude ({tagExclude.length})</label>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                      {tagExclude.map(tag => (<button key={tag} onClick={() => toggleTag(tagExclude, setTagExclude, tag)} style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "3px 8px", borderRadius: 5, background: `${theme.danger}22`, border: `1px solid ${theme.danger}`, color: theme.danger, fontSize: 11, cursor: "pointer" }}>{tag} <span style={{ fontSize: 9, opacity: 0.7 }}>✕</span></button>))}
                    </div>
                  </div>)}
                  <div>
                    <label style={{ fontSize: 11, color: theme.textDim, letterSpacing: 1, textTransform: "uppercase", display: "block", marginBottom: 6 }}>Top Tags {topTags.length > 0 && <span style={{ color: theme.textMuted, marginLeft: 6 }}>({topTags.length})</span>}</label>
                    {topTags.length === 0 ? (<div style={{ fontSize: 12, color: theme.textDim, padding: "8px 0" }}>No tags yet. Run the tagger first:<div style={{ fontFamily: "'Space Mono', monospace", fontSize: 11, marginTop: 4, color: theme.textMuted }}>python tagger.py --db curator.db --batch 100</div></div>) : (
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 4, maxHeight: 300, overflowY: "auto" }}>
                        {topTags.map(({ tag, count }) => {
                          const included = tagInclude.includes(tag); const excluded = tagExclude.includes(tag);
                          const maxCount = topTags[0]?.count || 1; const opacity = 0.4 + 0.6 * (count / maxCount);
                          return (<button key={tag} onClick={(e) => { if (e.shiftKey) { toggleTag(tagExclude, setTagExclude, tag); if (tagInclude.includes(tag)) toggleTag(tagInclude, setTagInclude, tag); } else { toggleTag(tagInclude, setTagInclude, tag); if (tagExclude.includes(tag)) toggleTag(tagExclude, setTagExclude, tag); } }}
                            title={`${count} images — click to include, shift+click to exclude`}
                            style={{ padding: "3px 8px", borderRadius: 5, fontSize: 11, cursor: "pointer", fontFamily: "'DM Sans', sans-serif", background: included ? `${theme.success}22` : excluded ? `${theme.danger}22` : "transparent", border: `1px solid ${included ? theme.success : excluded ? theme.danger : theme.border}`, color: included ? theme.success : excluded ? theme.danger : theme.textMuted, opacity: included || excluded ? 1 : opacity, transition: "all 0.15s" }}>
                            {tag}<span style={{ fontSize: 9, marginLeft: 4, opacity: 0.6 }}>{count}</span></button>);
                        })}
                      </div>
                    )}
                  </div>
                </div>
                <div style={{ position: "sticky", bottom: 0, paddingTop: 12, paddingBottom: 4, background: `linear-gradient(transparent, ${theme.surface} 20%)` }}>
                  <button onClick={fetchTagImages} disabled={tagInclude.length === 0 && tagExclude.length === 0}
                    style={{ width: "100%", padding: "10px 20px", borderRadius: 8, border: "none", background: (tagInclude.length > 0 || tagExclude.length > 0) ? `linear-gradient(135deg, ${theme.accentDim}, ${theme.accent})` : theme.surfaceAlt, color: (tagInclude.length > 0 || tagExclude.length > 0) ? "white" : theme.textDim, fontSize: 13, fontWeight: 600, cursor: (tagInclude.length > 0 || tagExclude.length > 0) ? "pointer" : "default", fontFamily: "'DM Sans', sans-serif", letterSpacing: 0.5 }}>Search by Tags</button>
                </div>
              </Section>
            </div>
            <div>
              {tagImages.length > 0 && (<div style={{ marginBottom: 12, fontSize: 12, color: theme.textMuted, fontFamily: "'Space Mono', monospace" }}>
                {tagImages.length} images<span style={{ color: theme.textDim, margin: "0 6px" }}>·</span>{new Set(tagImages.map(i => i.movie_id)).size} movies
                {tagInclude.length > 0 && (<span style={{ color: theme.success, marginLeft: 8 }}>+{tagInclude.join(", +")}</span>)}
                {tagExclude.length > 0 && (<span style={{ color: theme.danger, marginLeft: 8 }}>−{tagExclude.join(", −")}</span>)}
              </div>)}
              <ImageGrid images={tagImages} loading={tagImagesLoading} />
              {tagImages.length === 0 && !tagImagesLoading && (<div style={{ textAlign: "center", padding: 60, color: theme.textDim }}>
                <div style={{ fontSize: 36, marginBottom: 12, opacity: 0.3 }}>🏷</div>
                <div style={{ fontSize: 14, marginBottom: 8 }}>Select tags and click "Search by Tags"</div>
                <div style={{ fontSize: 12 }}>Click a tag to include it · Shift+click to exclude</div>
              </div>)}
            </div>
          </div>
        </div>)}

        {/* ═══ PIPELINE TAB ═══ */}
        {activeTab === "pipeline" && (<div>
          <div style={{ display: "grid", gridTemplateColumns: pipelineStatus?.project_name ? "360px 1fr" : "1fr", gap: 24 }}>
            {/* Left: Setup / Projects */}
            <div>
              {/* Create New Project */}
              <Section title="New Project">
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  <div>
                    <label style={{ fontSize: 11, color: theme.textDim, letterSpacing: 1, textTransform: "uppercase", display: "block", marginBottom: 4 }}>Source</label>
                    <div style={{ display: "flex", borderRadius: 8, border: `1px solid ${theme.border}`, overflow: "hidden" }}>
                      {[{ value: "selection", label: "From Browse Selection" }, { value: "external_path", label: "From External Path" }].map(opt => (
                        <button key={opt.value} onClick={() => setPipelineForm(p => ({ ...p, source_type: opt.value }))}
                          style={{
                            flex: 1, padding: "7px 10px", border: "none", fontSize: 12, fontWeight: 500, cursor: "pointer",
                            background: pipelineForm.source_type === opt.value ? `${theme.accent}22` : "transparent",
                            color: pipelineForm.source_type === opt.value ? theme.accent : theme.textMuted,
                            borderRight: opt.value === "selection" ? `1px solid ${theme.border}` : "none",
                            fontFamily: "'DM Sans', sans-serif", transition: "all 0.15s",
                          }}>
                          {opt.label}
                        </button>
                      ))}
                    </div>
                  </div>
                  {pipelineForm.source_type === "external_path" && (
                    <div>
                      <label style={{ fontSize: 11, color: theme.textDim, letterSpacing: 1, textTransform: "uppercase", display: "block", marginBottom: 4 }}>Dataset Path</label>
                      <input value={pipelineForm.source_path} onChange={e => setPipelineForm(p => ({ ...p, source_path: e.target.value }))}
                        placeholder="/path/to/character_dataset"
                        style={{ width: "100%", padding: "8px 12px", borderRadius: 8, border: `1px solid ${theme.border}`, background: theme.bg, color: theme.text, fontSize: 12, fontFamily: "'Space Mono', monospace", boxSizing: "border-box" }} />
                      <div style={{ fontSize: 11, color: theme.textDim, marginTop: 4 }}>
                        Images and any paired .txt captions will be copied. If captions exist for all images, the tagging step is skipped.
                      </div>
                    </div>
                  )}
                  <div>
                    <label style={{ fontSize: 11, color: theme.textDim, letterSpacing: 1, textTransform: "uppercase", display: "block", marginBottom: 4 }}>Preset</label>
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                      {Object.entries(LORA_PRESETS).map(([key, preset]) => (
                        <button key={key} onClick={() => { const { label: _, ...fields } = preset; setPipelineForm(p => ({ ...p, ...fields })); }}
                          style={{
                            padding: "5px 12px", borderRadius: 6, border: `1px solid ${theme.accentDim}`,
                            background: "transparent", color: theme.accent, fontSize: 11, fontWeight: 600,
                            cursor: "pointer", fontFamily: "'DM Sans', sans-serif", letterSpacing: 0.5,
                          }}>
                          {preset.label}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div>
                    <label style={{ fontSize: 11, color: theme.textDim, letterSpacing: 1, textTransform: "uppercase", display: "block", marginBottom: 4 }}>Model</label>
                    <select value={pipelineForm.dit_model} onChange={e => setPipelineForm(p => ({ ...p, dit_model: e.target.value }))}
                      style={{ width: "100%", padding: "6px 10px", borderRadius: 6, border: `1px solid ${theme.border}`, background: theme.bg, color: theme.text, fontSize: 12, fontFamily: "'Space Mono', monospace", boxSizing: "border-box" }}>
                      <option value="qwen_image_bf16.safetensors">Qwen-Image</option>
                      <option value="qwen_image_2512_bf16.safetensors">Qwen-Image-2512</option>
                    </select>
                  </div>
                  <div>
                    <label style={{ fontSize: 11, color: theme.textDim, letterSpacing: 1, textTransform: "uppercase", display: "block", marginBottom: 4 }}>Project Name *</label>
                    <input value={pipelineForm.name} onChange={e => setPipelineForm(p => ({ ...p, name: e.target.value.replace(/[^a-zA-Z0-9_-]/g, "_") }))}
                      placeholder="noir_style" style={{ width: "100%", padding: "8px 12px", borderRadius: 8, border: `1px solid ${theme.border}`, background: theme.bg, color: theme.text, fontSize: 13, fontFamily: "'Space Mono', monospace", boxSizing: "border-box" }} />
                  </div>
                  <div>
                    <label style={{ fontSize: 11, color: theme.textDim, letterSpacing: 1, textTransform: "uppercase", display: "block", marginBottom: 4 }}>Trigger Word</label>
                    <input value={pipelineForm.trigger_word} onChange={e => setPipelineForm(p => ({ ...p, trigger_word: e.target.value }))}
                      placeholder="noir_style" style={{ width: "100%", padding: "8px 12px", borderRadius: 8, border: `1px solid ${theme.border}`, background: theme.bg, color: theme.text, fontSize: 13, boxSizing: "border-box" }} />
                  </div>
                  <div>
                    <label style={{ fontSize: 11, color: theme.textDim, letterSpacing: 1, textTransform: "uppercase", display: "block", marginBottom: 4 }}>Tagging Prompt</label>
                    <textarea value={pipelineForm.tagging_prompt} onChange={e => setPipelineForm(p => ({ ...p, tagging_prompt: e.target.value }))} rows={4}
                      style={{ width: "100%", padding: "8px 12px", borderRadius: 8, border: `1px solid ${theme.border}`, background: theme.bg, color: theme.text, fontSize: 12, fontFamily: "'DM Sans', sans-serif", boxSizing: "border-box", resize: "vertical" }} />
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                    <div>
                      <label style={{ fontSize: 11, color: theme.textDim, textTransform: "uppercase", display: "block", marginBottom: 4 }}>Learning Rate</label>
                      <input value={pipelineForm.learning_rate} onChange={e => setPipelineForm(p => ({ ...p, learning_rate: e.target.value }))}
                        style={{ width: "100%", padding: "6px 10px", borderRadius: 6, border: `1px solid ${theme.border}`, background: theme.bg, color: theme.text, fontSize: 12, fontFamily: "'Space Mono', monospace", boxSizing: "border-box" }} />
                    </div>
                    <div>
                      <label style={{ fontSize: 11, color: theme.textDim, textTransform: "uppercase", display: "block", marginBottom: 4 }}>LoRA Rank</label>
                      <select value={pipelineForm.network_dim} onChange={e => setPipelineForm(p => ({ ...p, network_dim: parseInt(e.target.value) }))}
                        style={{ width: "100%", padding: "6px 10px", borderRadius: 6, border: `1px solid ${theme.border}`, background: theme.bg, color: theme.text, fontSize: 12, fontFamily: "'Space Mono', monospace", boxSizing: "border-box" }}>
                        {[16, 32, 64, 128].map(v => <option key={v} value={v}>{v}</option>)}
                      </select>
                    </div>
                    <div>
                      <label style={{ fontSize: 11, color: theme.textDim, textTransform: "uppercase", display: "block", marginBottom: 4 }}>
                        LoRA Alpha
                        <span style={{ marginLeft: 6, color: theme.accent, fontFamily: "'Space Mono', monospace", fontSize: 10 }}>
                          scale: {(pipelineForm.network_alpha / pipelineForm.network_dim).toFixed(2)}×
                        </span>
                      </label>
                      <select value={pipelineForm.network_alpha} onChange={e => setPipelineForm(p => ({ ...p, network_alpha: parseInt(e.target.value) }))}
                        style={{ width: "100%", padding: "6px 10px", borderRadius: 6, border: `1px solid ${theme.border}`, background: theme.bg, color: theme.text, fontSize: 12, fontFamily: "'Space Mono', monospace", boxSizing: "border-box" }}>
                        {[4, 8, 16, 32, 64].map(v => <option key={v} value={v}>{v}</option>)}
                      </select>
                    </div>
                    <div>
                      <label style={{ fontSize: 11, color: theme.textDim, textTransform: "uppercase", display: "block", marginBottom: 4 }}>Epochs</label>
                      <input type="number" value={pipelineForm.max_epochs} onChange={e => setPipelineForm(p => ({ ...p, max_epochs: parseInt(e.target.value) || 16 }))}
                        style={{ width: "100%", padding: "6px 10px", borderRadius: 6, border: `1px solid ${theme.border}`, background: theme.bg, color: theme.text, fontSize: 12, fontFamily: "'Space Mono', monospace", boxSizing: "border-box" }} />
                    </div>
                    <div>
                      <label style={{ fontSize: 11, color: theme.textDim, textTransform: "uppercase", display: "block", marginBottom: 4 }}>Save Every</label>
                      <input type="number" value={pipelineForm.save_every_n_epochs} onChange={e => setPipelineForm(p => ({ ...p, save_every_n_epochs: parseInt(e.target.value) || 2 }))}
                        style={{ width: "100%", padding: "6px 10px", borderRadius: 6, border: `1px solid ${theme.border}`, background: theme.bg, color: theme.text, fontSize: 12, fontFamily: "'Space Mono', monospace", boxSizing: "border-box" }} />
                    </div>
                  </div>
                  <button onClick={createProject}
                    disabled={!pipelineForm.name || pipelineStatus?.running || (pipelineForm.source_type === "external_path" && !pipelineForm.source_path.trim())}
                    style={{
                      padding: "10px 20px", borderRadius: 8, border: "none", fontSize: 13, fontWeight: 600,
                      cursor: (!pipelineForm.name || (pipelineForm.source_type === "external_path" && !pipelineForm.source_path.trim())) ? "default" : "pointer",
                      background: (pipelineForm.name && (pipelineForm.source_type === "selection" || pipelineForm.source_path.trim())) ? `linear-gradient(135deg, ${theme.accentDim}, ${theme.accent})` : theme.surfaceAlt,
                      color: (pipelineForm.name && (pipelineForm.source_type === "selection" || pipelineForm.source_path.trim())) ? "#fff" : theme.textDim,
                      fontFamily: "'DM Sans', sans-serif",
                    }}>
                    {pipelineForm.source_type === "external_path"
                      ? "Create Project from Path"
                      : (selectionSummary ? `Create Project (${selectionSummary.total_images.toLocaleString()} images)` : "Create Project")}
                  </button>
                </div>
              </Section>

              {/* Existing Projects */}
              {pipelineProjects.length > 0 && (
                <Section title={`Projects (${pipelineProjects.length})`}>
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    {pipelineProjects.map(p => (
                      <button key={p.path} onClick={() => loadProject(p.path)}
                        style={{
                          display: "flex", justifyContent: "space-between", alignItems: "center",
                          padding: "8px 12px", borderRadius: 6, border: `1px solid ${pipelineStatus?.project_dir === p.path ? theme.accent : theme.border}`,
                          background: pipelineStatus?.project_dir === p.path ? `${theme.accent}15` : "transparent",
                          color: theme.text, cursor: "pointer", textAlign: "left", fontSize: 12,
                        }}>
                        <div>
                          <div style={{ fontWeight: 600 }}>{p.name}</div>
                          <div style={{ fontSize: 11, color: theme.textDim, fontFamily: "'Space Mono', monospace", marginTop: 2 }}>{p.image_count} images · {p.caption_count} captions</div>
                        </div>
                        <span style={{ fontSize: 10, color: theme.textDim }}>Load</span>
                      </button>
                    ))}
                  </div>
                </Section>
              )}
            </div>

            {/* Right: Pipeline Steps + Log */}
            {pipelineStatus?.project_name && (
              <div>
                {/* Project header */}
                <div style={{ padding: "16px 20px", background: theme.surface, borderRadius: 10, border: `1px solid ${theme.border}`, marginBottom: 16, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div>
                    <div style={{ fontSize: 16, fontWeight: 700, color: theme.text }}>{pipelineStatus.project_name}</div>
                    <div style={{ fontSize: 12, color: theme.textDim, fontFamily: "'Space Mono', monospace", marginTop: 2 }}>{pipelineStatus.project_dir}</div>
                  </div>
                  {pipelineStatus.running && (
                    <button onClick={stopPipeline} style={{ padding: "6px 14px", borderRadius: 6, border: `1px solid ${theme.dangerDim}`, background: "transparent", color: theme.danger, fontSize: 12, fontWeight: 600, cursor: "pointer" }}>Stop</button>
                  )}
                </div>

                {/* Pipeline Steps */}
                <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 16 }}>
                  {[
                    { key: "export", label: "1. Export Images", desc: "Copy selected images to project", canRun: false },
                    { key: "tag", label: "2. Tag Images", desc: "Caption with qwen2.5vl:32b via Ollama", canRun: pipelineStatus.steps?.export?.status === "done" },
                    { key: "cache_vae", label: "3a. Cache VAE", desc: "Pre-compute VAE latents", canRun: pipelineStatus.steps?.tag?.status === "done", runKey: "cache" },
                    { key: "cache_te", label: "3b. Cache Text Encoder", desc: "Pre-compute text embeddings", canRun: false },
                    { key: "train", label: "4. Train LoRA", desc: "Run training with musubi-tuner", canRun: pipelineStatus.steps?.cache_te?.status === "done" },
                  ].map(step => {
                    const s = pipelineStatus.steps?.[step.key] || {};
                    const isRunning = s.status === "running";
                    const isDone = s.status === "done";
                    const isError = s.status === "error";
                    const statusColor = isDone ? theme.success : isError ? theme.danger : isRunning ? theme.accent : theme.textDim;
                    const statusIcon = isDone ? "✓" : isError ? "✗" : isRunning ? "●" : "○";

                    return (
                      <div key={step.key} style={{
                        display: "flex", alignItems: "center", gap: 12, padding: "12px 16px",
                        background: theme.surface, borderRadius: 8, border: `1px solid ${isRunning ? theme.accent + "44" : theme.border}`,
                      }}>
                        <span style={{ fontSize: 16, color: statusColor, fontWeight: 700, width: 20, textAlign: "center" }}>{statusIcon}</span>
                        <div style={{ flex: 1 }}>
                          <div style={{ fontSize: 13, fontWeight: 600, color: theme.text }}>{step.label}</div>
                          <div style={{ fontSize: 11, color: s.detail || theme.textDim }}>
                            {s.detail || step.desc}
                            {step.key === "tag" && s.progress > 0 && ` (${s.progress}/${s.total})`}
                          </div>
                          {step.key === "tag" && isRunning && s.total > 0 && (
                            <div style={{ height: 3, borderRadius: 2, background: theme.bg, marginTop: 6, overflow: "hidden" }}>
                              <div style={{ height: "100%", background: theme.accent, width: `${(s.progress / s.total) * 100}%`, transition: "width 1s", borderRadius: 2 }} />
                            </div>
                          )}
                        </div>
                        {step.canRun && !isRunning && !isDone && (
                          <button onClick={() => runPipelineStep(step.runKey || step.key)} disabled={pipelineStatus.running}
                            style={{
                              padding: "6px 14px", borderRadius: 6, border: "none", fontSize: 12, fontWeight: 600, cursor: pipelineStatus.running ? "default" : "pointer",
                              background: !pipelineStatus.running ? `linear-gradient(135deg, ${theme.accentDim}, ${theme.accent})` : theme.surfaceAlt,
                              color: !pipelineStatus.running ? "#fff" : theme.textDim,
                            }}>Run</button>
                        )}
                        {isDone && step.canRun && (
                          <button onClick={() => runPipelineStep(step.runKey || step.key)} disabled={pipelineStatus.running}
                            style={{ padding: "6px 14px", borderRadius: 6, border: `1px solid ${theme.border}`, background: "transparent", fontSize: 11, color: theme.textMuted, cursor: "pointer" }}>Re-run</button>
                        )}
                      </div>
                    );
                  })}
                </div>

                {/* Loss Chart */}
                <LossChart data={pipelineStatus.loss_data} />

                {/* Log Output */}
                <Section title="Log Output">
                  <div style={{
                    maxHeight: 300, overflowY: "auto", fontSize: 11, fontFamily: "'Space Mono', monospace",
                    color: theme.textMuted, lineHeight: 1.7, whiteSpace: "pre-wrap", wordBreak: "break-all",
                  }}>
                    {pipelineLog.length === 0 ? (
                      <span style={{ color: theme.textDim }}>No log output yet.</span>
                    ) : pipelineLog.map((line, i) => (
                      <div key={i} style={{ color: line.includes("error") || line.includes("Error") || line.includes("✗") ? theme.danger : line.includes("✓") || line.includes("complete") || line.includes("success") ? theme.success : theme.textMuted }}>{line}</div>
                    ))}
                  </div>
                </Section>
              </div>
            )}
          </div>
        </div>)}

        {/* ═══ SETTINGS TAB ═══ */}
        {activeTab === "settings" && (<div style={{ maxWidth: 600 }}>
          <Section title="Dataset Root">
            <div style={{ fontSize: 13, color: theme.textMuted, fontFamily: "'Space Mono', monospace" }}>{stats ? `/home/brad/ai/training/main_datasets` : "Loading..."}</div>
            <div style={{ fontSize: 12, color: theme.textDim, marginTop: 8 }}>Configure the DATASET_ROOT environment variable to change the scan path.</div>
          </Section>
          <Section title="Database">
            {stats && (<div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ fontSize: 13, color: theme.textMuted }}>DB Size: <span style={{ fontFamily: "'Space Mono', monospace" }}>{stats.db_size_mb} MB</span></div>
              <div style={{ fontSize: 13, color: theme.textMuted }}>Movies indexed: <span style={{ fontFamily: "'Space Mono', monospace" }}>{stats.total_movies?.toLocaleString()}</span></div>
              <div style={{ fontSize: 13, color: theme.textMuted }}>Images indexed: <span style={{ fontFamily: "'Space Mono', monospace" }}>{stats.total_images?.toLocaleString()}</span></div>
              <div style={{ fontSize: 13, color: theme.textMuted }}>Tagged: <span style={{ fontFamily: "'Space Mono', monospace" }}>{stats.tagged_images?.toLocaleString()}</span></div>
            </div>)}
          </Section>
          <Section title="Environment">
            <div style={{ fontSize: 12, color: theme.textDim }}>Required env vars (set in Fish config):</div>
            <div style={{ fontSize: 11, color: theme.textMuted, fontFamily: "'Space Mono', monospace", marginTop: 4, display: "flex", flexDirection: "column", gap: 2 }}>
              <div>LORA_PROJECTS_ROOT · COMFYUI_MODELS_ROOT · MUSUBI_TUNER_ROOT</div>
            </div>
          </Section>
        </div>)}
      </main>

      {activeTab === "browse" && (
        <BrowseFooter
          summary={selectionSummary}
          inDetail={!!openMovieId}
          openMovieId={openMovieId}
          onApply={handleApplyFilters}
          onBack={() => { setOpenMovieId(null); fetchBrowseMovies(browseCurrentPage); fetchSelectionSummary(); }}
          onSelectAllFiltered={handleSelectAllFiltered}
          onDeselectAllFiltered={handleDeselectAllFiltered}
          onClear={handleClearAll}
          browsePage={browseCurrentPage}
          browseTotalPages={browseTotalPages}
          onBrowsePageChange={fetchBrowseMovies}
        />
      )}
    </div>
  );
}