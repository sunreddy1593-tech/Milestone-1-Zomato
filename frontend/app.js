/* GourmetAI frontend logic — talks to the FastAPI backend. */

const API_BASE = location.protocol === "file:" ? "http://localhost:8000" : "";

const state = {
  cuisines: [], // selected cuisine names
  maxPriceRange: null, // 1-4 or null
};

// ---------------------------------------------------------------------------
// Element helpers
// ---------------------------------------------------------------------------
const $ = (id) => document.getElementById(id);
const show = (el) => el && el.classList.remove("hidden-soft");
const hide = (el) => el && el.classList.add("hidden-soft");

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

function titleCase(s) {
  return String(s || "")
    .split(" ")
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
    .join(" ");
}

function priceSymbols(n) {
  const k = Math.max(1, Math.min(4, parseInt(n) || 1));
  return "₹".repeat(k);
}

function formatHours(oh) {
  if (!oh || typeof oh !== "object") return "Hours not available";
  const days = Object.keys(oh);
  if (!days.length) return "Hours not available";
  const fmt = (d) => `${oh[d].open}–${oh[d].close}`;
  const allSame = days.every((d) => fmt(d) === fmt(days[0]));
  if (allSame) return `${fmt(days[0])} daily`;
  return days.map((d) => `${titleCase(d)}: ${fmt(d)}`).join(", ");
}

function vegBadge(isVeg) {
  if (isVeg === "Veg")
    return `<span class="inline-flex items-center border border-[#4CAF50] rounded px-1.5 py-0.5"><span class="w-2 h-2 rounded-full bg-[#4CAF50] mr-1"></span><span class="font-semibold text-[10px] text-[#2E7D32] uppercase">Veg</span></span>`;
  if (isVeg === "Non-Veg")
    return `<span class="inline-flex items-center border border-[#C62828] rounded px-1.5 py-0.5"><span class="w-2 h-2 rounded-full bg-[#C62828] mr-1"></span><span class="font-semibold text-[10px] text-[#C62828] uppercase">Non-Veg</span></span>`;
  return `<span class="inline-flex items-center border border-[#4CAF50] rounded px-1.5 py-0.5"><span class="w-2 h-2 rounded-full bg-[#4CAF50] mr-1"></span><span class="font-semibold text-[10px] text-[#2E7D32] uppercase">Veg Options</span></span>`;
}

// ---------------------------------------------------------------------------
// Meta (dropdown options)
// ---------------------------------------------------------------------------
async function loadMeta() {
  try {
    const res = await fetch(`${API_BASE}/meta`);
    if (!res.ok) throw new Error("meta failed");
    const meta = await res.json();
    populateMeta(meta);
  } catch (e) {
    // Fallback minimal options so the UI still works.
    populateMeta({ cities: ["bengaluru"], localities: [], cuisines: [], default_city: "Bengaluru" });
  }
}

function populateMeta(meta) {
  const citySel = $("filter-city");
  citySel.innerHTML = "";
  (meta.cities || []).forEach((c) => {
    const o = document.createElement("option");
    o.value = c;
    o.textContent = titleCase(c);
    citySel.appendChild(o);
  });
  const defCity = (meta.default_city || "").toLowerCase();
  if (defCity && (meta.cities || []).includes(defCity)) citySel.value = defCity;

  const locSel = $("filter-locality");
  locSel.innerHTML = '<option value="">Any locality</option>';
  (meta.localities || []).forEach((l) => {
    const o = document.createElement("option");
    o.value = l;
    o.textContent = titleCase(l);
    locSel.appendChild(o);
  });

  const cuiSel = $("filter-cuisine-select");
  cuiSel.innerHTML = '<option value="">Add a cuisine…</option>';
  (meta.cuisines || []).forEach((c) => {
    const o = document.createElement("option");
    o.value = c;
    o.textContent = c;
    cuiSel.appendChild(o);
  });

  if (meta.restaurant_count) {
    $("header-city").textContent = `${titleCase(defCity || "Bengaluru")}`;
    $("footer-meta").textContent = `GourmetAI • ${meta.restaurant_count.toLocaleString()} restaurants indexed`;
  }
}

// ---------------------------------------------------------------------------
// Cuisine chips
// ---------------------------------------------------------------------------
function renderCuisineChips() {
  const wrap = $("cuisine-chips");
  wrap.innerHTML = "";
  state.cuisines.forEach((c) => {
    const chip = document.createElement("span");
    chip.className = "cuisine-chip";
    chip.innerHTML = `${esc(c)} <button aria-label="Remove ${esc(c)}"><span class="material-symbols-outlined text-[16px]">close</span></button>`;
    chip.querySelector("button").addEventListener("click", () => {
      state.cuisines = state.cuisines.filter((x) => x !== c);
      renderCuisineChips();
    });
    wrap.appendChild(chip);
  });
}

// ---------------------------------------------------------------------------
// Filter gathering
// ---------------------------------------------------------------------------
function gatherFilters() {
  const filters = {};
  const city = $("filter-city").value;
  const locality = $("filter-locality").value;
  if (city) filters.city = city;
  if (locality) filters.locality = locality;
  if ($("filter-veg").checked) filters.is_veg = true;
  if ($("filter-open").checked) filters.open_now = true;
  if ($("filter-booking").checked) filters.has_table_booking = true;
  if ($("filter-delivery").checked) filters.has_online_delivery = true;
  if (state.cuisines.length) filters.cuisines = [...state.cuisines];
  if (state.maxPriceRange) filters.max_price_range = state.maxPriceRange;
  const cost = parseInt($("filter-cost").value);
  if (cost && cost > 0) filters.max_cost_for_two = cost;
  const rating = $("filter-rating").value;
  if (rating) filters.min_rating = parseFloat(rating);
  return filters;
}

function resetFilters() {
  $("filter-locality").value = "";
  $("filter-veg").checked = false;
  $("filter-open").checked = false;
  $("filter-booking").checked = false;
  $("filter-delivery").checked = false;
  $("filter-rating").value = "";
  $("filter-cost").value = 0;
  $("cost-label").textContent = "Any";
  state.cuisines = [];
  state.maxPriceRange = null;
  renderCuisineChips();
  document.querySelectorAll(".price-btn").forEach((b) => b.classList.remove("active"));
}

// ---------------------------------------------------------------------------
// View switching
// ---------------------------------------------------------------------------
function showSearchView() {
  show($("search-view"));
  hide($("results-view"));
  hide($("compact-search"));
  hide($("edit-filters-btn"));
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function showResultsView() {
  hide($("search-view"));
  show($("results-view"));
  $("compact-search").classList.remove("hidden-soft");
  $("compact-search").classList.add("md:flex");
  $("edit-filters-btn").classList.remove("hidden-soft");
  $("edit-filters-btn").classList.add("md:flex");
}

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------
async function runSearch(query) {
  const topN = parseInt($("filter-topn").value) || 5;
  const filters = gatherFilters();
  const body = { top_n: topN };
  if (query && query.trim()) body.query = query.trim();
  if (Object.keys(filters).length) body.filters = filters;

  if (!body.query && !body.filters) {
    return; // nothing to search
  }

  $("compact-query").value = query || "";
  showResultsView();
  enterLoading();

  try {
    const res = await fetch(`${API_BASE}/recommend`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) {
      const msg =
        data.message ||
        (data.details && data.details[0] && data.details[0].msg) ||
        "The request could not be processed.";
      showError(msg);
      return;
    }
    renderResults(data, query);
  } catch (e) {
    showError("Could not reach the recommendation service. Is the backend running?");
  }
}

function enterLoading() {
  hide($("intent-banner"));
  hide($("empty-state"));
  hide($("error-state"));
  hide($("meta-strip"));
  $("results-grid").innerHTML = "";
  const sk = $("skeletons");
  sk.innerHTML = Array.from({ length: 3 })
    .map(
      () => `
    <div class="bg-surface-container-lowest rounded-2xl border border-outline-variant p-6">
      <div class="flex justify-between mb-4"><div class="skeleton h-6 w-20 rounded-full"></div><div class="skeleton h-12 w-12 rounded-full"></div></div>
      <div class="skeleton h-6 w-3/4 rounded mb-2"></div>
      <div class="skeleton h-4 w-1/2 rounded mb-4"></div>
      <div class="skeleton h-4 w-full rounded mb-2"></div>
      <div class="skeleton h-16 w-full rounded-lg mt-4"></div>
    </div>`
    )
    .join("");
  show($("loading-state"));
}

function showError(message) {
  hide($("loading-state"));
  hide($("empty-state"));
  hide($("intent-banner"));
  hide($("meta-strip"));
  $("results-grid").innerHTML = "";
  $("error-text").textContent = message;
  $("results-title").textContent = "Something went wrong";
  $("results-subtitle").textContent = "";
  show($("error-state"));
}

// ---------------------------------------------------------------------------
// Rendering results
// ---------------------------------------------------------------------------
function renderResults(data, query) {
  hide($("loading-state"));
  hide($("error-state"));

  const recs = data.recommendations || [];
  const count = (data.meta && data.meta.candidate_count) || 0;

  $("results-title").textContent = recs.length
    ? `${recs.length} place${recs.length === 1 ? "" : "s"} found`
    : "No matches";
  $("results-subtitle").textContent = query ? `Curated matches for "${query}"` : "Curated matches for your filters.";

  renderIntent(data.query_understood, data.notes);

  const grid = $("results-grid");
  grid.innerHTML = "";
  if (!recs.length) {
    show($("empty-state"));
  } else {
    hide($("empty-state"));
    recs.forEach((rec, i) => grid.appendChild(renderCard(rec, i)));
  }

  renderMeta(data.meta);
}

function renderIntent(qu, notes) {
  if (!qu) {
    hide($("intent-banner"));
    return;
  }
  const hc = qu.hard_constraints || {};
  const pills = [];
  const pill = (icon, label) =>
    `<span class="hard-pill"><span class="material-symbols-outlined text-secondary text-[16px]">${icon}</span>${esc(label)}</span>`;

  if (hc.city) pills.push(pill("location_city", titleCase(hc.city)));
  if (hc.locality) pills.push(pill("location_on", titleCase(hc.locality)));
  if (Array.isArray(hc.cuisines)) hc.cuisines.forEach((c) => pills.push(pill("restaurant_menu", c)));
  if (hc.is_veg === true) pills.push(pill("eco", "Vegetarian"));
  if (hc.is_veg === false) pills.push(pill("kebab_dining", "Non-veg"));
  if (hc.open_now) pills.push(pill("schedule", "Open now"));
  if (hc.has_table_booking) pills.push(pill("event_seat", "Table booking"));
  if (hc.has_online_delivery) pills.push(pill("delivery_dining", "Delivery"));
  if (hc.max_cost_for_two) pills.push(pill("payments", `≤ ₹${hc.max_cost_for_two}`));
  if (hc.max_price_range) pills.push(pill("sell", priceSymbols(hc.max_price_range)));
  if (hc.min_rating) pills.push(pill("star", `${hc.min_rating}+`));

  (qu.soft_preferences || []).forEach((p) =>
    pills.push(`<span class="soft-pill">${esc(p)}</span>`)
  );

  $("intent-pills").innerHTML = pills.join("") || `<span class="soft-pill">Popular picks</span>`;

  if (notes) {
    $("notes-text").textContent = notes;
    show($("notes-callout"));
  } else {
    hide($("notes-callout"));
  }
  show($("intent-banner"));
}

function matchRing(score, isTop) {
  if (score === null || score === undefined) return "";
  const pct = Math.round(Math.max(0, Math.min(1, score)) * 100);
  const color = isTop ? "#b7122a" : "#8b5cf6";
  return `
    <div class="relative w-14 h-14 flex-shrink-0">
      <svg class="ring-svg w-full h-full" viewBox="0 0 36 36">
        <path d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" fill="none" stroke="#e8e8e6" stroke-width="3"/>
        <path d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" fill="none" stroke="${color}" stroke-width="3" stroke-linecap="round" stroke-dasharray="${pct}, 100"/>
      </svg>
      <span class="absolute inset-0 flex items-center justify-center font-head font-bold text-sm">${pct}%</span>
    </div>`;
}

function renderCard(rec, idx) {
  const isTop = idx === 0;
  const art = document.createElement("article");
  art.className =
    "bg-surface-container-lowest rounded-2xl shadow-sm border border-outline-variant card-hover flex flex-col h-full p-6";

  const rankBadge = `
    <span class="inline-flex items-center gap-1 ${isTop ? "bg-on-surface text-surface" : "bg-surface-container-highest text-on-surface"} px-3 py-1 rounded-full font-semibold text-sm">
      ${isTop ? '<span class="material-symbols-outlined text-[16px] text-[#FFD700]">workspace_premium</span>' : ""}#${rec.rank} Match
    </span>`;

  const tags = (rec.ambiance_tags || rec.cuisines || [])
    .slice(0, 3)
    .map(
      (t) =>
        `<span class="px-2.5 py-1 bg-surface-container rounded-md text-xs text-on-surface-variant">${esc(titleCase(t))}</span>`
    )
    .join("");

  const actions = [];
  if (rec.has_table_booking)
    actions.push(`<span class="inline-flex items-center gap-1 text-xs text-secondary"><span class="material-symbols-outlined text-[16px]">event_seat</span>Booking</span>`);
  if (rec.has_online_delivery)
    actions.push(`<span class="inline-flex items-center gap-1 text-xs text-secondary"><span class="material-symbols-outlined text-[16px]">delivery_dining</span>Delivery</span>`);

  art.innerHTML = `
    <div class="flex items-start justify-between mb-3">
      ${rankBadge}
      ${matchRing(rec.match_score, isTop)}
    </div>
    <h2 class="font-head text-xl font-bold leading-tight">${esc(rec.name)}</h2>
    <p class="text-sm text-secondary mb-3">${esc(titleCase(rec.locality))}, ${esc(titleCase(rec.city))}</p>
    <div class="flex items-center flex-wrap gap-3 mb-4">
      <span class="inline-flex items-center"><span class="material-symbols-outlined text-primary text-base mr-1" style="font-variation-settings:'FILL' 1">star</span><span class="font-semibold text-sm">${rec.rating}</span><span class="text-xs text-secondary ml-1">(${(rec.votes || 0).toLocaleString()} votes)</span></span>
      <span class="w-1 h-1 rounded-full bg-outline-variant"></span>
      <span class="font-semibold text-sm">${priceSymbols(rec.price_range)}</span>
      <span class="w-1 h-1 rounded-full bg-outline-variant"></span>
      ${vegBadge(rec.is_veg)}
    </div>
    <div class="flex flex-wrap gap-2 mb-4">${tags}</div>
    <div class="mt-auto ai-gradient-bg border border-primary-fixed rounded-lg p-3">
      <div class="flex items-start gap-2">
        <span class="material-symbols-outlined text-primary text-[18px] mt-0.5">auto_awesome</span>
        <p class="text-sm text-on-surface-variant italic leading-snug">${esc(rec.reason)}</p>
      </div>
    </div>
    <div class="flex items-center justify-between mt-4 pt-3 border-t border-outline-variant/60">
      <div class="flex gap-3">${actions.join("")}</div>
      <button class="detail-btn inline-flex items-center gap-1 text-primary font-semibold text-sm hover:underline" data-id="${esc(rec.restaurant_id)}">
        View details<span class="material-symbols-outlined text-[18px]">chevron_right</span>
      </button>
    </div>`;

  art.querySelector(".detail-btn").addEventListener("click", () => openDetail(rec.restaurant_id));
  return art;
}

function renderMeta(meta) {
  if (!meta) {
    hide($("meta-strip"));
    return;
  }
  const rankerBadge =
    meta.ranker === "groq"
      ? `<span class="inline-flex items-center gap-1 bg-surface-container px-2.5 py-1 rounded-full"><span class="material-symbols-outlined text-[16px] text-ai-accent">auto_awesome</span>AI-Ranked</span>`
      : `<span class="inline-flex items-center gap-1 bg-surface-container px-2.5 py-1 rounded-full"><span class="material-symbols-outlined text-[16px]">bolt</span>Smart fallback</span>`;
  $("meta-strip").innerHTML = `
    ${rankerBadge}
    <span>${(meta.candidate_count || 0).toLocaleString()} candidates evaluated</span>
    <span>•</span>
    <span>${meta.latency_ms} ms</span>
    ${meta.groq_model ? `<span>•</span><span>${esc(meta.groq_model)}</span>` : ""}`;
  show($("meta-strip"));
}

// ---------------------------------------------------------------------------
// Detail modal
// ---------------------------------------------------------------------------
async function openDetail(id) {
  const modal = $("detail-modal");
  $("modal-content").innerHTML = `<div class="py-12 text-center"><span class="material-symbols-outlined text-primary text-3xl pulse-subtle rounded-full">auto_awesome</span><p class="text-secondary mt-2">Loading…</p></div>`;
  show(modal);
  try {
    const res = await fetch(`${API_BASE}/restaurants/${encodeURIComponent(id)}`);
    if (!res.ok) throw new Error("not found");
    const r = await res.json();
    $("modal-content").innerHTML = detailHtml(r);
    $("modal-close").addEventListener("click", () => hide(modal));
  } catch (e) {
    $("modal-content").innerHTML = `<div class="py-10 text-center"><span class="material-symbols-outlined text-error text-3xl">error</span><p class="mt-2">Could not load restaurant details.</p><button id="modal-close" class="mt-4 bg-primary text-on-primary px-5 py-2 rounded-xl font-semibold">Close</button></div>`;
    $("modal-close").addEventListener("click", () => hide(modal));
  }
}

function detailHtml(r) {
  const cuisines = (r.cuisines || []).map((c) => `<span class="px-2.5 py-1 bg-surface-container rounded-md text-xs">${esc(c)}</span>`).join("");
  const tags = (r.ambiance_tags || []).map((t) => `<span class="soft-pill">${esc(titleCase(t))}</span>`).join("");
  const dishes = (r.popular_dishes || []).slice(0, 8).map((d) => `<span class="px-2.5 py-1 bg-surface-container-low border border-outline-variant rounded-md text-xs">${esc(d)}</span>`).join("");
  const row = (icon, label, value) =>
    value
      ? `<div class="flex items-start gap-3 py-3 border-b border-outline-variant/50"><span class="material-symbols-outlined text-primary text-[20px]">${icon}</span><div><div class="font-semibold text-sm">${label}</div><div class="text-sm text-secondary">${value}</div></div></div>`
      : "";

  return `
    <div class="flex items-start justify-between gap-4 mb-4">
      <div>
        <h2 class="font-head text-2xl md:text-3xl font-extrabold">${esc(r.name)}</h2>
        <p class="text-secondary mt-1">${esc(titleCase(r.locality))}, ${esc(titleCase(r.city))}</p>
        <div class="flex items-center gap-3 mt-2">
          <span class="inline-flex items-center"><span class="material-symbols-outlined text-primary text-base mr-1" style="font-variation-settings:'FILL' 1">star</span><span class="font-semibold text-sm">${r.rating}</span><span class="text-xs text-secondary ml-1">(${(r.votes || 0).toLocaleString()} votes)</span></span>
          <span class="font-semibold text-sm">${priceSymbols(r.price_range)}</span>
          ${vegBadge(r.is_veg)}
        </div>
      </div>
      <button id="modal-close" class="text-secondary hover:text-primary p-1"><span class="material-symbols-outlined">close</span></button>
    </div>
    ${tags ? `<div class="flex flex-wrap gap-2 mb-4">${tags}</div>` : ""}
    ${r.description ? `<p class="text-sm text-on-surface-variant leading-relaxed mb-4">${esc(r.description)}</p>` : ""}
    <div class="rounded-xl border border-outline-variant overflow-hidden mb-4">
      ${row("restaurant_menu", "Cuisines", cuisines || "—")}
      ${row("payments", "Average cost for two", `₹${r.average_cost_for_two}`)}
      ${row("schedule", "Opening hours", esc(formatHours(r.opening_hours)))}
      ${row("call", "Phone", r.phone ? esc(r.phone) : "")}
      ${row("home_pin", "Address", r.address ? esc(r.address) : "")}
    </div>
    ${dishes ? `<div class="mb-4"><h3 class="font-head font-bold mb-2">Popular dishes</h3><div class="flex flex-wrap gap-2">${dishes}</div></div>` : ""}
    <div class="flex flex-wrap gap-3">
      ${r.has_table_booking ? `<span class="inline-flex items-center gap-1 bg-surface-container px-3 py-2 rounded-xl text-sm font-semibold"><span class="material-symbols-outlined text-[18px]">event_seat</span>Table booking</span>` : ""}
      ${r.has_online_delivery ? `<span class="inline-flex items-center gap-1 bg-surface-container px-3 py-2 rounded-xl text-sm font-semibold"><span class="material-symbols-outlined text-[18px]">delivery_dining</span>Online delivery</span>` : ""}
      ${r.url ? `<a href="${esc(r.url)}" target="_blank" rel="noopener" class="inline-flex items-center gap-1 bg-primary text-on-primary px-4 py-2 rounded-xl text-sm font-semibold hover:bg-surface-tint transition-colors">View listing<span class="material-symbols-outlined text-[18px]">open_in_new</span></a>` : ""}
    </div>`;
}

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------
function wire() {
  $("main-search-btn").addEventListener("click", () => runSearch($("main-query").value));
  $("main-query").addEventListener("keydown", (e) => {
    if (e.key === "Enter") runSearch($("main-query").value);
  });
  $("compact-query").addEventListener("keydown", (e) => {
    if (e.key === "Enter") runSearch($("compact-query").value);
  });

  document.querySelectorAll(".example-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const q = chip.getAttribute("data-q");
      $("main-query").value = q;
      runSearch(q);
    });
  });

  $("filter-cuisine-select").addEventListener("change", (e) => {
    const v = e.target.value;
    if (v && !state.cuisines.includes(v)) {
      state.cuisines.push(v);
      renderCuisineChips();
    }
    e.target.value = "";
  });

  document.querySelectorAll(".price-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const val = parseInt(btn.getAttribute("data-price"));
      if (state.maxPriceRange === val) {
        state.maxPriceRange = null;
        btn.classList.remove("active");
      } else {
        state.maxPriceRange = val;
        document.querySelectorAll(".price-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
      }
    });
  });

  $("filter-cost").addEventListener("input", (e) => {
    const v = parseInt(e.target.value);
    $("cost-label").textContent = v > 0 ? `₹${v}` : "Any";
  });

  $("reset-filters").addEventListener("click", resetFilters);
  $("edit-filters-btn").addEventListener("click", showSearchView);
  $("brand-link").addEventListener("click", (e) => {
    e.preventDefault();
    showSearchView();
  });
  $("empty-reset").addEventListener("click", showSearchView);
  $("error-retry").addEventListener("click", () => runSearch($("compact-query").value || $("main-query").value));

  // Modal close on backdrop click / Escape
  $("detail-modal").addEventListener("click", (e) => {
    if (e.target === $("detail-modal")) hide($("detail-modal"));
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") hide($("detail-modal"));
  });
}

loadMeta();
renderCuisineChips();
wire();
