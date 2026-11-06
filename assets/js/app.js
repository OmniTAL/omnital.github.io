/* OmniTAL — application front (sans build JS, sans dépendance hors Leaflet/MapLibre).
 * Données : data/radar.json   (généré chaque jour par scripts/agent_veille_nlp.py)
 *           data/i18n.json    (traductions FR / EN / Taqbaylit)
 *           data/langues.json (langues suivies : codes, mots-clés, région, groupe)
 *           data/pays.json    (pays : noms FR/EN et centroïdes — filtre « Pays », recherche web)
 *
 * v4 (refonte) : carte réduite au centre-gauche, barre de recherche unique (site / web),
 * filtres regroupés dans un panneau (tiroir sur mobile) avec puces des filtres actifs,
 * état des filtres dans l'URL (liens partageables), filtre par pays des opportunités,
 * indicateurs animés, cartes animées, pied de page.
 */
(() => {
  'use strict';

  /* ═══════════════ Constantes ═══════════════ */
  const PAGE_SIZE = 40;
  const CAT_PAGE = 48;
  const TYPES = ['Paper', 'Corpus', 'Model', 'Tool', 'Event', 'Journal'];
  // Palette des marqueurs : distincte, lisible sur fond clair et sombre (ne jamais coder l'info par la seule couleur :
  // chaque fiche porte aussi son type en toutes lettres)
  const TYPE_COLOR = { Corpus: '#3F8A2C', Paper: '#1E6FD9', Model: '#C27C0E', Tool: '#B4447A', Event: '#6D4BC4',
                       Journal: '#8A5A1C', Opportunity: '#0F8A80' };
  const TYPE_CHIP = { Corpus: 'chip-corpus', Paper: 'chip-paper', Model: 'chip-model', Tool: 'chip-tool',
                      Event: 'chip-event', Journal: 'chip-journal', Opportunity: 'chip-opp' };
  const CAT_TO_TYPE = { cat_Dataset: 'Corpus', cat_Model: 'Model', cat_Tool: 'Tool', cat_Event: 'Event', cat_Journal: 'Journal', cat_Job: 'Opportunity' };
  const SRC_CLASS = { general: 'src-general', berbere: 'src-berbere', ecosysteme: 'src-ecosysteme', veille: 'src-veille',
                      local: 'src-local', mediterranee: 'src-mediterranee' };
  const SOURCES = { arxiv: 'arXiv', hal: 'HAL', huggingface: 'Hugging Face', github: 'GitHub', wikicfp: 'WikiCFP',
                    confdeadlines: 'Conf. deadlines (ccfddl)', zenodo: 'Zenodo', elg: 'European Language Grid', doaj: 'DOAJ',
                    nlppeople: 'NLP People', jobboards: 'Greenhouse · Ashby · Lever', greenhouse: 'Greenhouse', ashby: 'Ashby',
                    lever: 'Lever', remote: 'Remotive · Arbeitnow', remotive: 'Remotive', arbeitnow: 'Arbeitnow', jobicy: 'Jobicy',
                    himalayas: 'Himalayas', weworkremotely: 'We Work Remotely', hnhiring: 'HN « Who is hiring? »',
                    theses: 'theses.fr', formations: 'Formations (liste OmniTAL)', requetes: 'Requêtes suivies' };
  const OPP_KINDS = ['job', 'internship', 'phd', 'postdoc', 'thesis', 'master', 'bachelor', 'school'];
  const OPP_COLOR = { job: '#0F8A80', internship: '#0E7490', phd: '#6D28D9', postdoc: '#7E22CE', thesis: '#4F46E5',
                      master: '#BE185D', bachelor: '#BE123C', school: '#C2410C' };
  const GROUPS = ['berbere', 'mediterranee', 'arabe', 'nationales'];
  // Filtres sérialisés dans l'URL (#veille?type=Paper&lang=kab) : id de l'élément → clé courte
  const URL_KEYS = {
    veille: { 'type-filter': 'type', 'lang-filter': 'lang', 'vsource-filter': 'src', 'region-filter': 'reg', 'query-filter': 'rq' },
    catalogue: { 'cat-filter': 'cat', 'langue-filter': 'lang', 'source-filter': 'col', 'oa-filter': 'oa', 'cat-sort': 'sort' },
    opps: { 'opp-kind': 'kind', 'opp-country': 'country', 'opp-source': 'src', 'opp-sort': 'sort' },
  };
  const CHECKS = { veille: { 'catalogue-layer': ['layer', true] }, catalogue: { 'deadline-filter': ['dl', false] }, opps: { 'opp-remote': ['remote', false] } };
  const DEFAULTS = { 'cat-sort': 'relevance', 'opp-sort': 'relevance' };

  const state = {
    tab: 'veille', lang: 'fr', period: 0, mode: 'site', view: 'list',
    i18n: {}, notices: [], opps: [], ressources: [], requetes: [], repo: null,
    langs: [], groups: {}, pays: {}, today: null, agent: {}, stats: {}, lastUpdated: null,
    web: null, // { q, results, loading, errors }
    deadlines: [], catTotal: 0, catalogueLoaded: false, loaded: false,
  };
  let map = null, baseLayer = null, cluster = null, tempMarker = null;
  const markers = new Map();
  const $ = (id) => document.getElementById(id);
  const store = {
    get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* navigation privée / quota */ } },
  };
  const reduceMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ═══════════════ Utilitaires ═══════════════ */
  const esc = (s) => s == null ? '' : String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  /** N'autorise que http(s) : protège contre les liens javascript: injectés dans les données. */
  const safeUrl = (u) => (/^https?:\/\//i.test(String(u || '').trim()) ? String(u).trim() : '#');
  const ico = (name, cls = 'ico ico-sm') => `<svg class="${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
  const t = (key) => {
    const d = state.i18n[state.lang] || {};
    return d[key] ?? state.i18n.fr?.[key] ?? key;
  };
  const tf = (key, vars) => t(key).replace(/\{(\w+)\}/g, (_, k) => vars[k] ?? '');
  const locale = () => (state.lang === 'en' ? 'en-GB' : 'fr-FR');
  const daysAgo = (iso) => Math.round((Date.parse(state.today) - Date.parse(iso)) / 864e5);
  const addDays = (iso, n) => new Date(Date.parse(iso) + n * 864e5).toISOString().slice(0, 10);
  const fmtDate = (iso) => {
    if (!iso) return '';
    const d = new Date(iso.slice(0, 10) + 'T00:00:00Z');
    return isNaN(d) ? iso : d.toLocaleDateString(locale(), { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'UTC' });
  };
  const fmtNum = (n) => Number(n || 0).toLocaleString(locale());
  const debounce = (fn, ms) => { let id; return (...a) => { clearTimeout(id); id = setTimeout(() => fn(...a), ms); }; };
  const isDesktop = () => window.matchMedia('(min-width: 1024px)').matches;
  const srcName = (s) => SOURCES[s] || s;
  const langName = (code) => { const l = state.langs.find((x) => x.code === code); return l ? (state.lang === 'en' ? l.en : l.fr) : code; };
  const groupName = (g) => t('group_' + g);
  const countryName = (iso) => { const c = state.pays[iso]; return c ? (state.lang === 'en' ? c.en : c.fr) : iso; };

  /** Code pays d'une opportunité : champ `country` (ISO) fourni par l'agent, sinon déduit du lieu. */
  let countryIndex = null;
  let lastHash = '';
  function countryOf(o) {
    if (o._country !== undefined) return o._country;
    let iso = (o.country && String(o.country).length === 2 && state.pays[String(o.country).toUpperCase()]) ? String(o.country).toUpperCase() : null;
    if (!iso) {
      if (!countryIndex) {
        countryIndex = [];
        Object.entries(state.pays).forEach(([code, c]) => [c.fr, c.en].forEach((n) => {
          if (n && n.length > 3) countryIndex.push([new RegExp(`(?<![\\p{L}])${n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?![\\p{L}])`, 'iu'), code]);
        }));
      }
      const txt = `${o.country || ''} ${o.location || ''} ${o.region || ''} ${o.city || ''}`;
      iso = countryIndex.find(([rx]) => rx.test(txt))?.[1] || null;
    }
    o._country = iso;
    return iso;
  }

  /* ═══════════════ i18n ═══════════════ */
  function applyI18n() {
    document.querySelectorAll('[data-i18n]').forEach((el) => { el.textContent = t(el.dataset.i18n); });
    document.querySelectorAll('[data-i18n-placeholder]').forEach((el) => { el.placeholder = t(el.dataset.i18nPlaceholder); });
    document.querySelectorAll('[data-i18n-title]').forEach((el) => { el.title = t(el.dataset.i18nTitle); });
    document.documentElement.lang = state.lang === 'kab' ? 'kab' : state.lang;
    document.title = `${t('site_title')} — ${t('site_subtitle')}`;
    $('theme-toggle').setAttribute('aria-label', t('theme_toggle'));
    updateSearchMode();
  }
  function setLanguage(lang) {
    state.lang = state.i18n[lang] ? lang : 'fr';
    store.set('lang', state.lang);
    document.querySelectorAll('.lang-btn').forEach((b) => {
      const on = b.dataset.lang === state.lang;
      b.classList.toggle('lang-active', on);
      b.setAttribute('aria-pressed', on);
    });
    applyI18n();
    if (state.today) { populateFilters(); renderLegend(); renderAgentStatus(); renderWebHistory(); renderFooter(); updateHeader(); }
    refreshAll();
  }

  /* ═══════════════ Thème & carte ═══════════════ */
  const isDark = () => document.documentElement.classList.contains('dark');
  function setTheme(theme) {
    const dark = theme === 'dark';
    document.documentElement.classList.toggle('dark', dark);
    $('theme-toggle').setAttribute('aria-pressed', String(dark));
    store.set('theme', theme);
    if (map) setBaseLayer();
  }
  function setBaseLayer() {
    if (baseLayer) map.removeLayer(baseLayer);
    const attribution = '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · <a href="https://openfreemap.org">OpenFreeMap</a>';
    const canGL = typeof L.maplibreGL === 'function' && window.maplibregl?.supported?.();
    baseLayer = canGL
      ? L.maplibreGL({ style: `https://tiles.openfreemap.org/styles/${isDark() ? 'dark' : 'positron'}`, attribution })
      : L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution });
    baseLayer.addTo(map);
  }
  function initMap() {
    if (typeof L === 'undefined') { $('map').innerHTML = `<div class="empty-state">${esc(t('err_map'))}</div>`; return; }
    // vue centrée sur la Méditerranée (cœur du projet), le monde reste accessible
    map = L.map('map', { zoomControl: true, worldCopyJump: true, minZoom: 1, scrollWheelZoom: false }).setView([36, 12], 3);
    map.on('focus click', () => map.scrollWheelZoom.enable());
    map.on('blur mouseout', () => map.scrollWheelZoom.disable());
    setBaseLayer();
    cluster = L.markerClusterGroup({
      showCoverageOnHover: false, maxClusterRadius: 45, spiderfyOnMaxZoom: true, chunkedLoading: true,
      iconCreateFunction: (c) => {
        const n = c.getChildCount();
        const size = n < 10 ? 32 : n < 100 ? 40 : 50;
        return L.divIcon({ html: `<div class="cluster-icon" style="width:${size}px;height:${size}px">${n}</div>`,
                           className: '', iconSize: [size, size] });
      },
    });
    map.addLayer(cluster);
  }

  /** Disperse les éléments partageant exactement les mêmes coordonnées (spirale de Fermat). */
  function spread(items) {
    const groups = new Map();
    items.forEach((it) => {
      if (it.lat == null || it.lng == null) return;
      const k = `${(+it.lat).toFixed(3)},${(+it.lng).toFixed(3)}`;
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k).push(it);
    });
    const GOLDEN = 2.399963229728653;
    groups.forEach((g) => {
      const R_KM = Math.min(60, 6 + Math.sqrt(g.length) * 2.2);
      const cos = Math.cos((+g[0].lat * Math.PI) / 180);
      g.sort((a, b) => String(a.id).localeCompare(String(b.id))).forEach((it, i) => {
        const r = g.length === 1 ? 0 : (R_KM * Math.sqrt(i)) / Math.sqrt(g.length);
        it._lat = +it.lat + (r / 111) * Math.cos(i * GOLDEN);
        it._lng = +it.lng + (r / (111 * cos)) * Math.sin(i * GOLDEN);
      });
    });
    return items;
  }

  /** kind : 'notice' | 'catalogue' | 'opp' | 'web' — forme et couleur du marqueur. */
  function markerFor(item, kind = 'notice') {
    const type = kind === 'catalogue' ? CAT_TO_TYPE[item.categorie_key] || 'Tool' : item.type;
    const color = kind === 'opp' ? OPP_COLOR[item.opp_kind] || TYPE_COLOR.Opportunity : TYPE_COLOR[type] || '#1E4E8C';
    const cls = ['marker-pin', item.focus ? 'is-focus' : '', `is-${kind}`].join(' ');
    const icon = L.divIcon({
      className: '', iconSize: [16, 16], iconAnchor: [8, 8],
      html: `<div class="${cls}" style="background:${color};width:16px;height:16px;box-shadow:0 0 6px ${color}80"></div>`,
    });
    const m = L.marker([item._lat ?? item.lat, item._lng ?? item.lng], { icon, title: item.title || item.nom, keyboard: true });
    m.bindPopup(() => (kind === 'catalogue' ? popupCatalogue(item) : kind === 'opp' ? popupOpp(item) : popupNotice(item)), { maxWidth: 330 });
    m.on('click', () => highlightCard(item.id));
    return m;
  }
  function geoLine(it) {
    const place = it.location || it.city || it.region || '';
    if (!place && it.lat == null) return '';
    const prec = it.geo_precision ? ` <span class="geo-prec" title="${esc(it.geo_source || '')}">${esc(t('geo_' + it.geo_precision))}</span>` : '';
    return `<div class="popup-meta">${ico('pin')} ${esc(place)}${prec}</div>`;
  }
  function langTags(it) {
    return (it.lang_codes || []).slice(0, 3).map((c) => `<span class="tag tag-focus">${ico('lang')}${esc(langName(c))}</span>`).join('');
  }
  function popupNotice(it) {
    return `<div>
      <span class="chip ${TYPE_CHIP[it.type] || ''}">${esc(t('type_' + it.type))}</span>
      ${it.web ? `<span class="tag tag-web">${esc(t('web_result'))}</span>` : ''}
      <h3>${esc(it.title)}</h3>
      ${it.summary ? `<p>${esc(it.summary)}</p>` : ''}
      <div class="popup-meta">${esc(srcName(it.source))} · ${esc(fmtDate(it.date))}${it.date_end && it.date_end !== it.date ? ' → ' + esc(fmtDate(it.date_end)) : ''}</div>
      ${geoLine(it)}
      ${it.event ? deadlineRows(it.event, true) : ''}
      <a href="${esc(safeUrl(it.url))}" target="_blank" rel="noopener">${esc(t('consult'))} →</a>
    </div>`;
  }
  function popupCatalogue(r) {
    return `<div>
      <span class="src-pill ${SRC_CLASS[r.source] || 'src-general'}">${esc(t('source_' + r.source))}</span>
      <h3>${esc(r.nom)}</h3>
      <p>${esc(descOf(r).slice(0, 260))}</p>
      ${r.event ? deadlineRows(r.event, true) : ''}
      <div class="popup-meta">${esc(t(r.categorie_key))}${r.langue ? ' · ' + esc(r.langue) : ''}</div>
      ${geoLine(r)}
      <a href="${esc(safeUrl(r.lien))}" target="_blank" rel="noopener">${esc(t('open'))} →</a>
    </div>`;
  }
  function popupOpp(o) {
    const iso = countryOf(o);
    return `<div>
      <span class="chip chip-opp" style="--opp:${OPP_COLOR[o.opp_kind] || '#0F8A80'}">${esc(t('opp_' + o.opp_kind))}</span>
      <h3>${esc(o.title)}</h3>
      ${o.author ? `<p><b>${esc(o.author)}</b></p>` : ''}
      ${o.summary ? `<p>${esc(o.summary.slice(0, 220))}${o.summary.length > 220 ? '…' : ''}</p>` : ''}
      ${geoLine(o)}
      ${iso ? `<div class="popup-meta">${ico('globe')} ${esc(countryName(iso))}</div>` : ''}
      ${o.event ? deadlineRows(o.event, true) : ''}
      <a href="${esc(safeUrl(o.url))}" target="_blank" rel="noopener">${esc(t('open'))} →</a>
    </div>`;
  }

  function renderMap(points) {
    if (!map) return;
    cluster.clearLayers();
    markers.clear();
    if (tempMarker) { map.removeLayer(tempMarker); tempMarker = null; }
    const layers = [];
    let unlocated = 0;
    points.forEach(([it, kind]) => {
      if (it.lat == null) { unlocated++; return; }
      const m = markerFor(it, kind);
      markers.set(it.id, m);
      layers.push(m);
    });
    cluster.addLayers(layers);
    $('map-counter-num').textContent = fmtNum(layers.length);
    $('map-unlocated').textContent = unlocated ? ' · ' + tf('unlocated', { n: fmtNum(unlocated) }) : '';
  }

  /** Centre la carte sur un élément (veille, catalogue, opportunité ou résultat web), même filtré. */
  function viewOnMap(id) {
    const pools = [['notice', state.notices], ['opp', state.opps], ['catalogue', state.ressources],
                   ['web', state.web?.results || []]];
    let target = null, kind = 'notice';
    for (const [k, arr] of pools) {
      target = arr.find((x) => x.id === id);
      if (target) { kind = k; break; }
    }
    if (!target || target.lat == null || !map) return;
    setMapCollapsed(false);
    if (!isDesktop()) document.querySelector('.map-card').scrollIntoView({ behavior: reduceMotion() ? 'auto' : 'smooth', block: 'start' });
    setTimeout(() => {
      map.invalidateSize();
      let m = markers.get(id);
      if (!m) { m = tempMarker = markerFor(target, kind).addTo(map); }
      if (cluster.hasLayer(m)) cluster.zoomToShowLayer(m, () => m.openPopup());
      else { map.flyTo(m.getLatLng(), 8, { duration: reduceMotion() ? 0 : 1.1 }); setTimeout(() => m.openPopup(), reduceMotion() ? 50 : 1200); }
    }, 120);
  }
  /** Survol d'une fiche → le marqueur correspondant pulse (s'il est visible hors groupe). */
  function pulseMarker(id) {
    const m = markers.get(id);
    if (!m || !map || !cluster) return;
    const parent = cluster.getVisibleParent(m);
    const el = parent?.getElement?.()?.firstElementChild;
    if (!el) return;
    el.classList.remove('marker-pulse'); void el.offsetWidth; el.classList.add('marker-pulse');
  }
  function highlightCard(id) {
    document.querySelectorAll('.card.is-active').forEach((c) => c.classList.remove('is-active'));
    const c = document.querySelector(`.card[data-id="${CSS.escape(id)}"], .card[data-opp-id="${CSS.escape(id)}"]`);
    if (c) { c.classList.add('is-active'); if (isDesktop()) c.scrollIntoView({ behavior: reduceMotion() ? 'auto' : 'smooth', block: 'nearest' }); }
  }
  function setMapCollapsed(collapsed) {
    $('map-toggle').setAttribute('aria-expanded', String(!collapsed));
    document.querySelector('.map-frame').classList.toggle('is-collapsed', collapsed);
    if (!collapsed && map) setTimeout(() => map.invalidateSize(), 320);
  }

  /* ═══════════════ Données ═══════════════ */
  async function getJSON(url) {
    const r = await fetch(url, { cache: 'no-cache' });
    if (!r.ok) throw new Error(`${url} : HTTP ${r.status}`);
    return r.json();
  }
  async function loadStatic() {
    const [i18n, langues, pays] = await Promise.allSettled([getJSON('data/i18n.json'), getJSON('data/langues.json'), getJSON('data/pays.json')]);
    state.i18n = i18n.value || {};
    state.i18n.fr ||= {};
    state.pays = pays.value || {};
    if (langues.value) {
      state.langs = langues.value.languages || [];
      state.groups = langues.value.groups || {};
      // mots-clés → expressions régulières (géolocalisation des résultats de recherche web)
      state.langs.forEach((l) => {
        l._rx = (l.keywords || []).map((k) => new RegExp(`(?<![\\w-])${k.trim().replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?![\\w-])`, 'i'));
      });
    }
  }
  async function loadData({ silent = false } = {}) {
    if (!silent) { showLoading(true); if (!state.loaded) renderSkeleton(); }
    try {
      const data = await getJSON('data/radar.json');
      state.today = data.today || new Date().toISOString().slice(0, 10);
      state.repo = data.repo || 'OmniTAL/omnital.github.io';
      state.notices = spread(data.notices?.items || []);
      state.opps = spread(data.opportunites?.items || []);
      // radar.json n'embarque que le catalogue éditorial ; le catalogue complet (data/catalogue.json)
      // est chargé à la première ouverture de l'onglet Catalogue
      state.catTotal = data.ressources?.total || 0;
      if (!state.catalogueLoaded) state.ressources = spread([...(data.ressources?.items || []), ...localCatalogue()]);
      state.deadlines = data.deadlines || [];
      state.requetes = data.requetes || [];
      state.agent = data.agent || {};
      state.stats = data.stats || {};
      state.lastUpdated = data.last_updated;
      state.loaded = true;
      updateHeader();
      populateFilters();
      readUrlState();
      renderLegend();
      renderAgentStatus();
      renderWebHistory();
      renderFooter();
      renderKpis();
      refreshAll();
    } catch (err) {
      console.error('[data]', err);
      showError(t('err_loading'));
    } finally { showLoading(false); }
  }

  async function ensureCatalogue() {
    if (state.catalogueLoaded) return;
    showLoading(true);
    try {
      const cat = await getJSON('data/catalogue.json');
      state.ressources = spread([...(cat.items || []), ...localCatalogue()]);
      state.catalogueLoaded = true;
      populateFilters();
      readUrlState();
      refreshAll();
    } catch (e) { console.warn('[catalogue]', e); } finally { showLoading(false); }
  }

  /* ═══════════════ Filtres ═══════════════ */
  function populateSelect(id, values, allKey, labelFn = (v) => v, extra = '') {
    const sel = $(id);
    const cur = sel.dataset.pending ?? sel.value;
    sel.innerHTML = `<option value="ALL">${esc(t(allKey))}</option>${extra}` +
      values.map(([v, n]) => `<option value="${esc(v)}">${esc(labelFn(v))}${n != null ? ` (${fmtNum(n)})` : ''}</option>`).join('');
    sel.value = [...sel.options].some((o) => o.value === cur) ? cur : 'ALL';
  }
  const countBy = (arr, key) => {
    const c = new Map();
    arr.forEach((x) => {
      const vals = typeof key === 'function' ? key(x) : x[key];
      (Array.isArray(vals) ? vals : [vals]).forEach((v) => { if (v) c.set(v, (c.get(v) || 0) + 1); });
    });
    return c;
  };
  const byCount = (m) => [...m].sort((a, b) => b[1] - a[1]);

  /** Sélecteur « Langue » unique : groupes (berbère, Méditerranée…) puis langues de chaque groupe. */
  function populateLangSelect(id, items) {
    const sel = $(id);
    const cur = sel.dataset.pending ?? sel.value;
    const codes = countBy(items, 'lang_codes');
    const groups = countBy(items, 'lang_groups');
    const anyN = items.filter((i) => (i.lang_groups || []).some((g) => g !== 'nationales') || i.focus).length;
    let html = `<option value="ALL">${esc(t('language_all'))}</option>`;
    html += `<option value="ANY">${esc(t('lowres_any'))} (${fmtNum(anyN)})</option>`;
    GROUPS.forEach((g) => {
      const inGroup = state.langs.filter((l) => l.group === g && codes.has(l.code))
        .sort((a, b) => codes.get(b.code) - codes.get(a.code));
      if (!groups.has(g)) return;
      html += `<optgroup label="${esc(groupName(g))}">`;
      html += `<option value="g:${g}">${esc(tf('lang_group_all', { g: groupName(g) }))} (${fmtNum(groups.get(g))})</option>`;
      html += inGroup.map((l) => `<option value="${esc(l.code)}">${esc(langName(l.code))} (${fmtNum(codes.get(l.code))})</option>`).join('');
      html += '</optgroup>';
    });
    sel.innerHTML = html;
    sel.value = [...sel.options].some((o) => o.value === cur) ? cur : 'ALL';
  }
  function populateFilters() {
    const N = state.notices;
    populateSelect('vsource-filter', byCount(countBy(N, 'source')), 'source_all', srcName);
    const types = countBy(N, 'type');
    populateSelect('type-filter', TYPES.filter((x) => types.has(x)).map((x) => [x, types.get(x)]), 'type_all', (v) => t('type_' + v));
    populateSelect('region-filter', byCount(countBy(N, 'region')).filter(([r]) => r !== 'International'), 'region_all');
    populateLangSelect('lang-filter', N);
    if (state.requetes.length) {
      $('query-filter-wrap').classList.remove('hidden');
      populateSelect('query-filter', state.requetes.map((r) => [r.q, r.results]), 'tracked_all');
    }

    const O = state.opps;
    const kinds = countBy(O, 'opp_kind');
    populateSelect('opp-kind', OPP_KINDS.filter((k) => kinds.has(k)).map((k) => [k, kinds.get(k)]), 'opp_all', (k) => t('opp_' + k));
    const countries = [...countBy(O, (o) => countryOf(o))].sort((a, b) => countryName(a[0]).localeCompare(countryName(b[0]), locale()));
    const remoteN = O.filter(isRemote).length;
    populateSelect('opp-country', countries, 'country_all', countryName,
      remoteN ? `<option value="REMOTE">${esc(t('country_remote'))} (${fmtNum(remoteN)})</option>` : '');
    populateSelect('opp-source', byCount(countBy(O, 'source')), 'source_all', srcName);

    const R = state.ressources;
    populateSelect('source-filter', [...countBy(R, 'source')], 'source_all', (v) => t('source_' + v));
    populateSelect('cat-filter', [...countBy(R, 'categorie_key')].sort((a, b) => t(a[0]).localeCompare(t(b[0]))), 'category_all', t);
    populateLangSelect('langue-filter', R);
    document.querySelectorAll('.filters-grid select').forEach((s) => { delete s.dataset.pending; });
    markFields();
  }
  const query = () => (state.mode === 'site' ? $('search-input').value.toLowerCase().trim() : '');
  function matchLangValue(it, v) {
    if (v === 'ALL') return true;
    if (v === 'ANY') return (it.lang_groups || []).some((g) => g !== 'nationales') || !!it.focus;
    if (v.startsWith('g:')) return (it.lang_groups || []).includes(v.slice(2));
    return (it.lang_codes || []).includes(v);
  }
  const isRemote = (o) => /remote|télétravail|teletravail|anywhere|worldwide/i.test(`${o.location || ''} ${o.employment || ''}`);

  function filterNotices() {
    const q = query(), src = $('vsource-filter').value, typ = $('type-filter').value, reg = $('region-filter').value;
    const rq = $('query-filter').value, lang = $('lang-filter').value, p = state.period;
    return state.notices.filter((i) => {
      if (src !== 'ALL' && i.source !== src) return false;
      if (typ !== 'ALL' && i.type !== typ) return false;
      if (reg !== 'ALL' && i.region !== reg) return false;
      if (rq !== 'ALL' && !(i.queries || []).includes(rq)) return false;
      if (!matchLangValue(i, lang)) return false;
      if (p && daysAgo(i.first_seen) >= p) return false;
      if (q) {
        const hay = `${i.title} ${i.summary} ${i.author} ${i.city || ''} ${i.region || ''} ${i.location || ''} ${(i.lang_codes || []).map(langName).join(' ')}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }
  // offres ouvertes d'abord (emplois, stages, thèses, postdocs), puis thèses en cours, puis formations
  const kindRank = (o) => (o.opp_kind === 'thesis' ? 1 : ['master', 'bachelor', 'school'].includes(o.opp_kind) ? 2 : 0);
  function filterOpps() {
    const q = query(), kind = $('opp-kind').value, ctry = $('opp-country').value, src = $('opp-source').value;
    const remote = $('opp-remote').checked, p = state.period, sort = $('opp-sort').value;
    const out = state.opps.filter((o) => {
      if (kind !== 'ALL' && o.opp_kind !== kind) return false;
      if (ctry === 'REMOTE' ? !isRemote(o) : ctry !== 'ALL' && countryOf(o) !== ctry) return false;
      if (src !== 'ALL' && o.source !== src) return false;
      if (remote && !isRemote(o) && !/hybrid/i.test(o.location || '')) return false;
      if (p && daysAgo(o.first_seen) >= p) return false;
      if (q && !`${o.title} ${o.summary || ''} ${o.author || ''} ${o.location || ''} ${o.region || ''} ${countryName(countryOf(o) || '')}`.toLowerCase().includes(q)) return false;
      return true;
    });
    if (sort === 'recent') return out.sort((a, b) => (b.first_seen || '').localeCompare(a.first_seen || '') || (b.date || '').localeCompare(a.date || ''));
    if (sort === 'country') return out.sort((a, b) => countryName(countryOf(a) || 'ZZ').localeCompare(countryName(countryOf(b) || 'ZZ'), locale()));
    return out.sort((a, b) => kindRank(a) - kindRank(b) || (b.date || '').localeCompare(a.date || ''));
  }

  /** Notice rédigée par l'agent en priorité, sinon description du classeur. */
  const descOf = (r) => r.notice?.[state.lang] || r.notice?.fr
    || r.description?.[state.lang] || r.description?.fr || r.type || '';
  function filterRessources(forMap = false) {
    const q = query();
    const src = $('source-filter').value, cat = $('cat-filter').value, langue = $('langue-filter').value, oa = $('oa-filter').value;
    const inCat = state.tab === 'catalogue';
    return state.ressources.filter((r) => {
      if (!forMap || inCat) {
        if (src !== 'ALL' && r.source !== src) return false;
        if (cat !== 'ALL' && r.categorie_key !== cat) return false;
        if (!matchLangValue(r, langue)) return false;
        if (oa !== 'ALL' && r.licence_class !== oa) return false;
        if ($('deadline-filter').checked && !r.deadline_next) return false;
      }
      if (forMap && !inCat && !matchLangValue(r, $('lang-filter').value)) return false;
      if (q) {
        const hay = `${r.nom} ${r.type || ''} ${descOf(r)} ${r.langue || ''} ${r.region || ''} ${r.city || ''}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }

  /* Filtres actifs → puces (retrait en un clic), compteurs, champs surlignés */
  function activeFilters() {
    const out = [];
    const ids = URL_KEYS[state.tab];
    Object.keys(ids).forEach((id) => {
      const el = $(id);
      if (!el || el.value === 'ALL' || el.value === (DEFAULTS[id] ?? 'ALL')) return;
      const label = document.querySelector(`label[for="${id}"]`)?.textContent || '';
      out.push({ id, label, value: el.options[el.selectedIndex]?.text.replace(/\s\(\d[\d\s.,  ]*\)$/, '') || el.value });
    });
    Object.entries(CHECKS[state.tab]).forEach(([id, [, def]]) => {
      const el = $(id);
      if (el.checked !== def) out.push({ id, label: '', value: el.checked ? el.nextElementSibling.textContent : `${t('hidden')} : ${el.nextElementSibling.textContent}` });
    });
    if (state.period && state.tab !== 'catalogue') out.push({ id: 'period', label: t('period'), value: t('period_' + state.period) });
    if (query()) out.push({ id: 'q', label: t('search_title'), value: `« ${$('search-input').value.trim()} »` });
    return out;
  }
  function renderActiveFilters() {
    const list = activeFilters();
    const box = $('active-filters');
    box.innerHTML = list.map((f) => `<span class="filter-chip">${f.label ? `<span>${esc(f.label)} : <b>${esc(f.value)}</b></span>` : `<span><b>${esc(f.value)}</b></span>`}
        <button type="button" data-clear="${esc(f.id)}" aria-label="${esc(t('remove_filter'))} ${esc(f.label)} ${esc(f.value)}">${ico('x')}</button></span>`).join('')
      + (list.length > 1 ? `<button type="button" class="filter-chip filter-chip-clear" data-clear="ALL">${esc(t('clear_all'))}</button>` : '');
    const n = list.filter((f) => f.id !== 'q').length;
    ['filters-count', 'fab-count'].forEach((id) => { $(id).textContent = n; $(id).classList.toggle('hidden', !n); });
    markFields();
  }
  function markFields() {
    document.querySelectorAll('.filters-grid select').forEach((s) => s.classList.toggle('is-set', s.value !== (DEFAULTS[s.id] ?? 'ALL')));
  }
  function clearFilter(id) {
    if (id === 'ALL') return resetFilters();
    if (id === 'period') return setPeriod(0);
    if (id === 'q') { $('search-input').value = ''; return refreshAll(); }
    const el = $(id);
    if (el.type === 'checkbox') el.checked = CHECKS[state.tab][id][1];
    else el.value = DEFAULTS[id] ?? 'ALL';
    refreshAll();
  }
  function resetFilters() {
    Object.values(URL_KEYS).forEach((ids) => Object.keys(ids).forEach((id) => { $(id).value = DEFAULTS[id] ?? 'ALL'; }));
    Object.values(CHECKS).forEach((c) => Object.entries(c).forEach(([id, [, def]]) => { $(id).checked = def; }));
    $('search-input').value = '';
    setPeriod(0);
  }
  function setPeriod(p) {
    state.period = p;
    document.querySelectorAll('#period-filter [data-period]').forEach((b) => {
      const on = +b.dataset.period === p;
      b.classList.toggle('seg-active', on);
      b.setAttribute('aria-checked', String(on));
    });
    refreshAll();
  }

  /* ═══════════════ État dans l'URL (liens partageables) ═══════════════ */
  function writeUrlState() {
    if (state.web) return;
    const params = new URLSearchParams();
    Object.entries(URL_KEYS[state.tab]).forEach(([id, key]) => {
      const v = $(id).value;
      if (v && v !== (DEFAULTS[id] ?? 'ALL')) params.set(key, v);
    });
    Object.entries(CHECKS[state.tab]).forEach(([id, [key, def]]) => { if ($(id).checked !== def) params.set(key, $(id).checked ? '1' : '0'); });
    if (state.period && state.tab !== 'catalogue') params.set('p', state.period);
    const q = $('search-input').value.trim();
    if (q && state.mode === 'site') params.set('q', q);
    const hash = '#' + state.tab + (params.toString() ? '?' + params : '');
    lastHash = hash;
    if (location.hash !== hash) history.replaceState(null, '', hash);
  }
  function readUrlState() {
    const h = location.hash.slice(1);
    if (!h || h.startsWith('q=')) return;
    const [tab, qs] = h.split('?');
    if (!URL_KEYS[tab] || !qs) return;
    const params = new URLSearchParams(qs);
    Object.entries(URL_KEYS[tab]).forEach(([id, key]) => {
      if (!params.has(key)) return;
      const el = $(id), v = params.get(key);
      if ([...el.options].some((o) => o.value === v)) el.value = v; else el.dataset.pending = v;
    });
    Object.entries(CHECKS[tab]).forEach(([id, [key]]) => { if (params.has(key)) $(id).checked = params.get(key) === '1'; });
    if (params.has('p')) state.period = +params.get('p') || 0;
    if (params.has('q')) $('search-input').value = params.get('q');
    document.querySelectorAll('#period-filter [data-period]').forEach((b) => b.classList.toggle('seg-active', +b.dataset.period === state.period));
  }

  /* ═══════════════ Échéances ═══════════════ */
  /** « J-12 », « aujourd'hui », « passée » : urgence lisible d'un coup d'œil. */
  function countdown(iso) {
    if (!iso || !state.today) return { label: '', cls: '' };
    const n = -daysAgo(iso);
    if (n < 0) return { label: t('dl_passed'), cls: 'dl-passed' };
    if (n === 0) return { label: t('dl_today'), cls: 'dl-urgent' };
    return { label: tf('dl_days', { n }), cls: n <= 14 ? 'dl-urgent' : n <= 45 ? 'dl-soon' : 'dl-later' };
  }
  function deadlineRow(icon, labelKey, iso, src) {
    if (!iso) return '';
    const c = countdown(iso);
    return `<li class="dl-row ${c.cls}" ${src ? `title="${esc(t('from_cfp_text'))}"` : ''}>
      <span class="dl-label">${ico(icon)} ${esc(t(labelKey))}${src ? ' *' : ''}</span>
      <span class="dl-date">${esc(fmtDate(iso))}${c.label ? ` <b>${esc(c.label)}</b>` : ''}</span></li>`;
  }
  /** Bloc « lieu · dates · résumés · articles · notification » d'un événement. */
  function deadlineRows(ev, compact = false) {
    const srcs = ev.deadline_sources || {};
    const when = ev.start ? `${fmtDate(ev.start)}${ev.end && ev.end !== ev.start ? ' → ' + fmtDate(ev.end) : ''}` : '';
    return `<ul class="dl-box${compact ? ' dl-compact' : ''}">
      ${ev.location ? `<li class="dl-row"><span class="dl-label">${ico('pin')} ${esc(t('dl_location'))}</span><span class="dl-date">${esc(ev.location)}</span></li>` : ''}
      ${when ? `<li class="dl-row"><span class="dl-label">${ico('calendar')} ${esc(t('dl_dates'))}</span><span class="dl-date">${esc(when)}</span></li>` : ''}
      ${deadlineRow('pen', 'dl_abstract', ev.abstract_deadline, srcs.abstract_deadline)}
      ${deadlineRow('file', 'dl_paper', ev.paper_deadline, srcs.paper_deadline)}
      ${compact ? '' : deadlineRow('bell', 'dl_notification', ev.notification, srcs.notification)}
      ${!ev.abstract_deadline && !ev.paper_deadline ? `<li class="dl-row dl-passed"><span class="dl-label">${esc(t('dl_unknown'))}</span></li>` : ''}
    </ul>`;
  }
  /** Bloc revue : soumission continue + numéros spéciaux ouverts avec leur date limite. */
  function journalRows(j) {
    const issues = (j.special_issues || []).slice(0, 3).map((i) => {
      const dl = i.abstract_deadline && (!i.deadline || i.abstract_deadline < i.deadline) ? i.abstract_deadline : i.deadline;
      const c = countdown(dl);
      return `<li class="dl-row ${c.cls}"><a class="dl-label link line-clamp-2" href="${esc(safeUrl(i.url))}" target="_blank" rel="noopener">${ico('megaphone')} ${esc(i.title)}</a>
        <span class="dl-date">${dl ? `${esc(fmtDate(dl))} <b>${esc(c.label)}</b>` : esc(t('dl_unknown'))}</span></li>`;
    }).join('');
    return `<ul class="dl-box">
      <li class="dl-row"><span class="dl-label">${ico('file')} ${esc(t('submission'))}</span><span class="dl-date">${esc(t('submission_continuous'))}</span></li>
      ${j.apc ? `<li class="dl-row"><span class="dl-label">APC</span><span class="dl-date">${esc(j.apc === 'oui' ? t('yes') : t('no'))}</span></li>` : ''}
      ${issues ? `<li class="dl-sub">${esc(t('special_issues'))}</li>${issues}` : `<li class="dl-row dl-passed"><span class="dl-label">${esc(t('no_special_issue'))}</span></li>`}
    </ul>`;
  }
  function sortRessources(items) {
    const mode = $('cat-sort').value;
    const arr = [...items];
    if (mode === 'deadline') arr.sort((a, b) => (a.deadline_next || '9999').localeCompare(b.deadline_next || '9999'));
    else if (mode === 'recent') arr.sort((a, b) => (b.added || '').localeCompare(a.added || ''));
    else if (mode === 'alpha') arr.sort((a, b) => a.nom.localeCompare(b.nom, locale()));
    return arr; // « pertinence » : catalogue éditorial d'abord, puis ajouts récents de la veille
  }

  /* ═══════════════ Rendu ═══════════════ */
  function refreshAll() {
    if (!state.loaded) return;
    renderBanners();
    renderList();
    renderActiveFilters();
    writeUrlState();
    const n = (v) => (v ? fmtNum(v) : '');
    $('tab-count-veille').textContent = n(state.notices.length);
    $('tab-count-catalogue').textContent = n(state.catalogueLoaded ? state.ressources.length : state.catTotal + localCatalogue().length);
    $('tab-count-opps').textContent = n(state.opps.length);
  }
  function renderList() {
    $('results-label').textContent = t(state.web ? 'results_web' : 'results_' + state.tab);
    if (state.tab === 'veille') {
      const items = filterNotices();
      const points = items.map((i) => [i, 'notice']);
      if ($('catalogue-layer').checked) {
        // les ajouts de la veille sont déjà sur la carte en tant qu'éléments de veille
        filterRessources(true).forEach((r) => { if (r.origin !== 'veille') points.push([r, 'catalogue']); });
      }
      if (state.web?.results?.length) state.web.results.forEach((r) => points.push([r, 'web']));
      if (state.web) renderWebResults(); else pagedList(items, noticeCard, 'no_notice');
      renderMap(points);
    } else if (state.tab === 'opps') {
      const items = filterOpps();
      pagedList(items, oppCard, 'no_opp');
      renderMap(items.map((o) => [o, 'opp']));
    } else {
      const items = sortRessources(filterRessources());
      renderCatalogue(items);
      renderMap(items.map((r) => [r, 'catalogue']));
    }
  }

  function geoTag(it) {
    if (!it.geo_precision) return '';
    return `<span class="tag" title="${esc(it.geo_source || '')}">${esc(t('geo_' + it.geo_precision))}</span>`;
  }
  function noticeCard(it, i = 0) {
    const isNew = it.first_seen === state.today;
    const place = it.type === 'Event' ? (it.location || it.city) : (it.city || (it.region !== 'International' ? it.region : ''));
    const tags = [
      isNew ? `<span class="tag tag-new">${esc(t('new'))}</span>` : '',
      it.web ? `<span class="tag tag-web">${esc(t('web_result'))}</span>` : '',
      langTags(it),
      it.topic ? `<span class="tag">${esc(it.topic)}</span>` : '',
      it.trending ? `<span class="tag">${ico('flame')}${esc(t('trending'))}</span>` : '',
      ...(it.queries || []).slice(0, 2).map((q) => `<span class="tag">${ico('search')}${esc(q)}</span>`),
    ].join('');
    const dateLabel = it.type === 'Event'
      ? `${fmtDate(it.date)}${it.date_end && it.date_end !== it.date ? ' → ' + fmtDate(it.date_end) : ''}`
      : fmtDate(it.date);
    return `
      <article class="card${it.known ? ' card-known' : ''}" tabindex="0" data-id="${esc(it.id)}" style="--i:${i}">
        <div class="card-top">
          <span class="chip ${TYPE_CHIP[it.type] || ''}">${esc(t('type_' + it.type))}</span>
          <span class="card-date">${esc(dateLabel)}</span>
        </div>
        <h3 class="card-title">${esc(it.title)}</h3>
        ${it.summary ? `<p class="card-text">${esc(it.summary)}</p>` : ''}
        ${tags ? `<div class="flex flex-wrap gap-1">${tags}</div>` : ''}
        ${it.event && (it.event.abstract_deadline || it.event.paper_deadline) ? `<ul class="dl-box dl-compact">
          ${deadlineRow('pen', 'dl_abstract', it.event.abstract_deadline, it.event.deadline_sources?.abstract_deadline)}
          ${deadlineRow('file', 'dl_paper', it.event.paper_deadline, it.event.deadline_sources?.paper_deadline)}</ul>` : ''}
        <div class="card-meta">
          <span>${esc(srcName(it.source))}${it.author && !['WikiCFP', 'ccfddl'].includes(it.author) ? ' · ' + esc(it.author) : ''}</span>
          ${place ? `<span class="flex-shrink-0 max-w-[45%]">${ico('pin')}${esc(place)}</span>` : ''}
        </div>
        <div class="card-actions">
          ${it.lat != null ? `<button type="button" class="btn-map" data-map-id="${esc(it.id)}">${ico('pin')}${esc(t('view_on_map'))}</button>` : ''}
          <a class="btn-open-ext" href="${esc(safeUrl(it.url))}" target="_blank" rel="noopener">${ico('external')}${esc(t('open'))}</a>
          ${geoTag(it)}
        </div>
      </article>`;
  }
  function emptyState(emptyKey) {
    const q = $('search-input').value.trim();
    const hasFilters = activeFilters().length > 0;
    return `<div class="empty-state"><p>${esc(t(emptyKey))}</p>
      ${hasFilters ? `<p class="text-sm">${esc(t('empty_hint'))}</p><button type="button" class="btn-ghost" data-clear="ALL">${esc(t('reset_filters'))}</button>` : ''}
      ${q && state.tab !== 'opps' ? ` <button type="button" class="btn-primary" data-web-q="${esc(q)}">${ico('globe')}${esc(tf('try_web', { q }))}</button>` : ''}</div>`;
  }
  /** Liste paginée : la page suivante est AJOUTÉE (seules les nouvelles fiches s'animent). */
  function renderPaged(items, cardFn, size, emptyKey, head = '') {
    const c = $('cards-container');
    $('results-count').textContent = fmtNum(items.length);
    if (!items.length) { c.innerHTML = head + emptyState(emptyKey); return; }
    let shown = 0;
    const more = () => {
      const next = items.slice(shown, shown + size);
      $('more-btn')?.remove();
      c.insertAdjacentHTML('beforeend', next.map((it, i) => cardFn(it, i)).join(''));
      shown += next.length;
      if (items.length > shown) {
        c.insertAdjacentHTML('beforeend', `<button type="button" class="btn-more" id="more-btn">${esc(tf('show_more', { n: Math.min(size, items.length - shown), total: fmtNum(items.length - shown) }))}</button>`);
        $('more-btn').addEventListener('click', more);
      }
    };
    c.innerHTML = head;
    more();
  }
  const pagedList = (items, cardFn, emptyKey) => renderPaged(items, cardFn, PAGE_SIZE, emptyKey);

  function oppCard(o, i = 0) {
    const isNew = o.first_seen === state.today;
    const linkWarn = o.source === 'formations' && o.link_status != null && (o.link_status === 0 || o.link_status >= 400);
    const iso = countryOf(o);
    return `
      <article class="card" tabindex="0" data-opp-id="${esc(o.id)}" style="--i:${i}">
        <div class="card-top">
          <span class="chip chip-opp" style="--opp:${OPP_COLOR[o.opp_kind] || '#0F8A80'}">${esc(t('opp_' + o.opp_kind))}</span>
          <span class="card-date">${esc(fmtDate(o.date))}</span>
        </div>
        <h3 class="card-title">${esc(o.title)}</h3>
        ${o.author ? `<p class="text-sm font-bold text-txt-2 truncate m-0">${esc(o.author)}</p>` : ''}
        ${o.summary && o.source !== 'formations' ? `<p class="card-text">${esc(o.summary)}</p>` : ''}
        ${o.event ? `<ul class="dl-box dl-compact">${deadlineRow('file', 'dl_application', o.event.paper_deadline || o.event.abstract_deadline)}</ul>` : ''}
        <div class="flex flex-wrap gap-1">
          ${isNew ? `<span class="tag tag-new">${esc(t('new'))}</span>` : ''}
          ${iso ? `<span class="tag tag-country">${ico('globe')}${esc(countryName(iso))}</span>` : ''}
          ${isRemote(o) ? `<span class="tag">${esc(t('remote_tag'))}</span>` : ''}
          ${o.thesis_status ? `<span class="tag">${esc(t('thesis_' + (o.thesis_status === 'en cours' ? 'ongoing' : 'defended')))}</span>` : ''}
          ${o.teaching_languages ? `<span class="tag">${ico('lang')}${esc(o.teaching_languages)}</span>` : ''}
          ${o.employment && !/remote/i.test(o.employment) ? `<span class="tag">${esc(o.employment)}</span>` : ''}
          ${linkWarn ? `<span class="tag tag-warn" title="HTTP ${esc(o.link_status)}">${ico('alert')}${esc(t('link_check'))}</span>` : ''}
          ${langTags(o)}
        </div>
        <div class="card-meta">
          <span>${esc(srcName(o.source))}</span>
          ${o.location ? `<span class="flex-shrink-0 max-w-[55%]">${ico('pin')}${esc(o.location)}</span>` : ''}
        </div>
        <div class="card-actions">
          ${o.lat != null ? `<button type="button" class="btn-map" data-map-id="${esc(o.id)}">${ico('pin')}${esc(t('view_on_map'))}</button>` : ''}
          <a class="btn-open-ext" href="${esc(safeUrl(o.url))}" target="_blank" rel="noopener">${ico('external')}${esc(t('open'))}</a>
          ${geoTag(o)}
        </div>
      </article>`;
  }

  function catalogueCard(r, i = 0) {
    const metaParts = [
      r.taille ? `${ico('package')} ${esc(r.taille)}` : '',
      r.langue ? `${ico('lang')} ${esc(r.langue)}` : '',
      r.city || (r.pays && r.pays !== 'International') ? `${ico('pin')} ${esc(r.city || r.pays)}` : '',
    ].filter(Boolean).join(' · ');
    return `
      <article class="card-cat" data-cat-id="${esc(r.id)}" style="--i:${i}">
        <div class="card-top flex-wrap">
          <span class="src-pill ${SRC_CLASS[r.source] || 'src-general'}">${esc(t('source_' + r.source))}</span>
          ${r.event ? '' : `<span class="text-xs px-2.5 py-1 rounded-md border font-medium font-mono whitespace-nowrap badge-oa-${esc(r.licence_class || 'unknown')}">${esc(r.licence || t('license_unknown'))}</span>`}
        </div>
        <div class="text-xs uppercase tracking-wider text-txt-3 font-bold">${esc(t(r.categorie_key))}${r.type ? ' · ' + esc(r.type) : ''}</div>
        <h3 class="card-title" style="-webkit-line-clamp:3">${esc(r.nom)}</h3>
        <p class="card-text" style="-webkit-line-clamp:${r.event || r.journal ? 5 : 4}">${esc(descOf(r))}</p>
        ${r.event ? deadlineRows(r.event) : ''}
        ${r.journal ? journalRows(r.journal) : ''}
        <div class="flex flex-wrap gap-1">
          ${r.origin === 'veille' ? `<span class="tag">${esc(tf('auto_added', { date: fmtDate(r.added) }))}</span>` : ''}
          ${r.origin === 'local' ? `<span class="tag tag-web">${ico('search')}${esc(r.queries?.[0] || '')}</span>` : ''}
          ${r.notice_by === 'ia' ? `<span class="tag" title="${esc(t('ai_notice_hint'))}">${ico('sparkles')}${esc(t('ai_notice'))}</span>` : ''}
          ${langTags(r)}
          ${r.trending ? `<span class="tag">${ico('flame')}${esc(t('trending'))}</span>` : ''}
          ${geoTag(r)}
        </div>
        <div class="card-meta" style="border-top:1px solid var(--border-color);padding-top:8px;margin-top:auto"><span>${metaParts || '—'}</span></div>
        <div class="card-actions">
          ${r.lat != null ? `<button type="button" class="btn-map" data-map-id="${esc(r.id)}">${ico('pin')}${esc(t('view_on_map'))}</button>` : ''}
          <a class="btn-open-ext" href="${esc(safeUrl(r.lien))}" target="_blank" rel="noopener">${ico('external')}${esc(r.event ? t('official_site') : t('open'))}</a>
          ${r.cfp_url && r.cfp_url !== r.lien ? `<a class="btn-open-ext" href="${esc(safeUrl(r.cfp_url))}" target="_blank" rel="noopener">CFP</a>` : ''}
          ${r.journal?.author_instructions ? `<a class="btn-open-ext" href="${esc(safeUrl(r.journal.author_instructions))}" target="_blank" rel="noopener">${esc(t('author_guide'))}</a>` : ''}
        </div>
      </article>`;
  }
  const renderCatalogue = (items) => renderPaged(items, catalogueCard, CAT_PAGE, 'no_resource');
  function renderSkeleton() {
    $('cards-container').innerHTML = Array.from({ length: 6 }, () => '<div class="skeleton" aria-hidden="true"></div>').join('');
  }
  function applyView() {
    const c = $('cards-container');
    // le catalogue est toujours en grille (fiches riches) ; veille et opportunités au choix
    const grid = state.tab === 'catalogue' || state.view === 'grid';
    c.classList.toggle('cards-grid', grid);
    c.classList.toggle('cards-list', !grid);
    document.querySelectorAll('.view-toggle [data-view]').forEach((b) => {
      const on = b.dataset.view === (grid ? 'grid' : 'list');
      b.classList.toggle('view-active', on);
      b.setAttribute('aria-pressed', String(on));
    });
    document.querySelector('.view-toggle').classList.toggle('hidden', state.tab === 'catalogue');
  }

  /* ═══════════════ Bandeaux : échéances imminentes · cette semaine · nouveautés ═══════════════ */
  /** Échéances à venir (événements, numéros spéciaux) précalculées par l'agent. */
  const allDeadlines = () => state.deadlines.filter((d) => d.date >= state.today);
  function renderBanners() {
    const box = $('banners-container');
    if (!state.today || query() || state.web) { box.innerHTML = ''; return; }
    const weekEnd = addDays(state.today, 7);
    const thisWeek = state.notices
      .filter((n) => n.type === 'Event' && n.date && n.date <= weekEnd && (n.date_end || n.date) >= state.today)
      .sort((a, b) => a.date.localeCompare(b.date));
    const imminent = allDeadlines().filter((d) => d.date <= addDays(state.today, 14));
    const pool = state.tab === 'opps' ? state.opps : state.notices;
    const freshAll = pool.filter((n) => n.first_seen === state.today)
      .sort((a, b) => Number(b.focus) - Number(a.focus) || Number(a.type === 'Event') - Number(b.type === 'Event'));
    const item = (n, meta) => `
      <button type="button" class="banner-item" data-banner-id="${esc(n.id)}" data-url="${esc(safeUrl(n.url))}">
        <span class="banner-dot" style="background:${n.type === 'Opportunity' ? OPP_COLOR[n.opp_kind] : TYPE_COLOR[n.type] || '#6D4BC4'}"></span>
        <span class="min-w-0 flex-1">
          <span class="banner-title">${esc(n.title)}</span>
          <span class="banner-meta">${meta}</span>
        </span>
      </button>`;
    const block = (icon, title, list, emptyKey, render, warm = false) => `
      <details class="banner-block${warm ? ' is-warm' : ''}" ${isDesktop() || list.length ? 'open' : ''}>
        <summary>${ico(icon, 'ico')}<span>${esc(t(title))}</span><span class="banner-count">${fmtNum(list.length)}</span></summary>
        <div class="banner-list">${list.length ? list.slice(0, 10).map(render).join('') : `<p class="text-xs text-txt-3 py-2 px-2 m-0">${esc(t(emptyKey))}</p>`}</div>
      </details>`;
    const dlHtml = block('clock', 'banner_deadlines', imminent, 'no_deadline', (d) => {
      const c = countdown(d.date);
      return item({ ...d, type: 'Event' }, `<b class="dl-inline ${c.cls}">${esc(c.label)}</b> ${esc(t(d.which))} · ${esc(fmtDate(d.date))}${d.place ? ' · ' + esc(d.place) : ''}`);
    }, true);
    const weekHtml = block('calendar', 'banner_week', thisWeek, 'no_week',
      (n) => item(n, `${esc(fmtDate(n.date))}${n.date_end && n.date_end !== n.date ? ' → ' + esc(fmtDate(n.date_end)) : ''} · ${esc(n.location || n.city || '')}`));
    const newHtml = block('sparkles', state.tab === 'opps' ? 'banner_new_opps' : 'banner_latest', freshAll, state.tab === 'opps' ? 'no_latest_opps' : 'no_latest',
      (n) => item(n, `${esc(srcName(n.source))}${n.location || n.city ? ' · ' + esc(n.location || n.city) : ''}`));
    box.innerHTML = state.tab === 'catalogue' ? dlHtml : state.tab === 'opps' ? newHtml : dlHtml + weekHtml + newHtml;
  }

  function renderLegend() {
    const rows = TYPES.map((ty) => `<li><span class="legend-dot" style="background:${TYPE_COLOR[ty]}"></span>${esc(t('type_' + ty))}</li>`).join('');
    $('legend-list').innerHTML = rows + `
      <li><span class="legend-dot" style="background:${TYPE_COLOR.Opportunity};border-radius:2px;transform:rotate(45deg)"></span>${esc(t('legend_opps'))}</li>
      <li><span class="legend-dot" style="background:var(--text-muted);box-shadow:0 0 0 2px var(--warm)"></span>${esc(t('legend_focus'))}</li>
      <li><span class="legend-dot" style="background:var(--text-muted);border-radius:2px"></span>${esc(t('legend_catalogue'))}</li>`;
  }
  function renderAgentStatus() {
    const s = state.agent.sources || {};
    const entries = Object.entries(s);
    $('agent-status').innerHTML = entries.map(([k, v]) => `
      <li class="agent-row"><span class="truncate">${esc(srcName(k))}</span>
        <span class="${v.ok ? 'agent-ok' : 'agent-ko'}" title="${esc(v.error || '')}">${v.ok ? `✓ +${v.new ?? 0}` : '✗ ' + esc(t('agent_error'))}</span></li>`).join('')
      || `<li class="text-txt-3">—</li>`;
    const ok = entries.filter(([, v]) => v.ok).length;
    $('agent-summary').textContent = entries.length ? `${ok}/${entries.length} ✓` : '';
    $('agent-dot').classList.toggle('is-warn', ok < entries.length);
  }
  /** Indicateurs animés (comptage progressif). */
  function renderKpis() {
    const s = state.agent.sources || {};
    const values = {
      new_today: state.stats.new_today ?? 0,
      new_7d: state.stats.new_7d ?? 0,
      deadlines: allDeadlines().filter((d) => d.date <= addDays(state.today, 14)).length,
      opps: state.opps.filter((o) => kindRank(o) === 0).length,
      langs: state.langs.length,
      sources: Object.values(s).filter((v) => v.ok).length,
    };
    document.querySelectorAll('[data-kpi]').forEach((el) => countUp(el, values[el.dataset.kpi] || 0));
  }
  function countUp(el, target) {
    const from = +(el.dataset.v || 0);
    el.dataset.v = target;
    if (reduceMotion() || from === target) { el.textContent = fmtNum(target); return; }
    const t0 = performance.now(), dur = 900;
    const step = (now) => {
      const p = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - p, 3);
      el.textContent = fmtNum(Math.round(from + (target - from) * e));
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
  /** « il y a 3 h » — rafraîchi chaque minute. */
  function relTime(iso) {
    const d = Date.parse(iso);
    if (isNaN(d)) return '—';
    const min = Math.max(0, Math.round((Date.now() - d) / 6e4));
    try {
      const rtf = new Intl.RelativeTimeFormat(state.lang === 'en' ? 'en' : 'fr', { numeric: 'auto' });
      if (min < 60) return rtf.format(-min, 'minute');
      if (min < 60 * 36) return rtf.format(-Math.round(min / 60), 'hour');
      return rtf.format(-Math.round(min / 1440), 'day');
    } catch { return new Date(d).toLocaleString(locale()); }
  }
  function updateHeader() {
    if (!state.lastUpdated) return;
    const abs = new Date(state.lastUpdated).toLocaleString(locale(), { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
    $('last-updated-time').textContent = relTime(state.lastUpdated);
    $('last-updated-badge').title = abs;
    $('footer-updated').textContent = `${t('updated')} : ${abs}.`;
  }
  function renderFooter() {
    $('footer-year').textContent = (state.today || new Date().toISOString()).slice(0, 4);
    $('footer-groups').innerHTML = GROUPS.map((g) => {
      const ls = state.langs.filter((l) => l.group === g);
      return ls.length ? `<li><a href="#veille?lang=g:${g}" data-lang-group="${g}">${esc(groupName(g))}</a> <span class="muted">· ${ls.length}</span></li>` : '';
    }).join('');
  }
  const showLoading = (on) => $('loading-overlay').classList.toggle('hidden', !on);
  function showError(msg) {
    const b = $('last-updated-badge');
    b.classList.remove('hidden'); b.classList.add('is-error', 'inline-flex');
    $('last-updated-time').textContent = msg;
    $('cards-container').innerHTML = `<div class="empty-state"><p>${esc(msg)}</p><button type="button" class="btn-primary" id="retry-btn">${esc(t('retry'))}</button></div>`;
    $('retry-btn')?.addEventListener('click', () => loadData());
  }

  /* ═══════════════ Recherche web (dans le navigateur) ═══════════════
   * Interroge en direct des API publiques autorisant les appels depuis un site (CORS).
   * Les résultats s'affichent tout de suite (liste + carte), sont gardés dans ce navigateur
   * (collection « Mes recherches » du catalogue) et peuvent être confiés à l'agent :
   * « Suivre cette recherche » ouvre une issue GitHub que l'agent relit chaque jour. */
  function detectLangs(text, codes = []) {
    const found = [];
    codes.forEach((c) => {
      const l = state.langs.find((x) => (x.codes || []).includes(String(c).toLowerCase().split(/[-_]/)[0]));
      if (l && !found.includes(l)) found.push(l);
    });
    state.langs.forEach((l) => { if (!found.includes(l) && l._rx?.some((rx) => rx.test(text))) found.push(l); });
    return found.sort((a, b) => Number(b.focus !== false) - Number(a.focus !== false));
  }
  function countryGeo(iso) {
    const c = state.pays[String(iso || '').toUpperCase()];
    return c ? { lat: c.lat, lng: c.lng, region: countryName(String(iso).toUpperCase()), city: countryName(String(iso).toUpperCase()), geo_precision: 'pays' } : null;
  }
  function normalizeWeb(raw, q) {
    const text = `${raw.title} ${raw.summary || ''} ${(raw.tags || []).join(' ')}`;
    const langs = detectLangs(text, (raw.codes || []).length > 12 ? [] : raw.codes || []);
    let geo = null;
    if (langs.length) geo = { lat: langs[0].lat, lng: langs[0].lng, region: langs[0].region, city: langs[0].region, geo_precision: 'langue' };
    else if (raw.country) geo = countryGeo(raw.country);
    return {
      ...raw, ...(geo || { lat: null, lng: null }), web: true, queries: [q], first_seen: state.today,
      date: (raw.date || '').slice(0, 10), summary: (raw.summary || '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 320),
      lang_codes: langs.map((l) => l.code), lang_groups: [...new Set(langs.map((l) => l.group))], focus: langs.some((l) => l.focus !== false),
    };
  }
  const WEB_SOURCES = {
    huggingface: async (q) => {
      const kinds = [['datasets', 'Corpus', 'https://huggingface.co/datasets/'], ['models', 'Model', 'https://huggingface.co/']];
      const res = await Promise.all(kinds.map(([k]) => getJSON(`https://huggingface.co/api/${k}?search=${encodeURIComponent(q)}&limit=20&sort=downloads&direction=-1`)));
      return res.flatMap((arr, i) => arr.map((e) => ({
        id: `hf:${kinds[i][0]}:${e.id}`, title: e.id, type: kinds[i][1], source: 'huggingface', url: kinds[i][2] + e.id,
        date: e.createdAt, author: e.author || e.id.split('/')[0], tags: e.tags || [],
        codes: (e.tags || []).filter((x) => x.startsWith('language:')).map((x) => x.split(':')[1]),
      })));
    },
    github: async (q) => {
      const d = await getJSON(`https://api.github.com/search/repositories?q=${encodeURIComponent(q)}&sort=stars&order=desc&per_page=20`);
      return (d.items || []).map((r) => ({ id: `gh:${r.full_name.toLowerCase()}`, title: r.full_name, type: 'Tool', source: 'github',
        url: r.html_url, date: r.created_at, summary: r.description, author: r.owner?.login, tags: r.topics || [] }));
    },
    zenodo: async (q) => {
      const d = await getJSON(`https://zenodo.org/api/records?q=${encodeURIComponent(q)}&size=20&sort=bestmatch`);
      return (d.hits?.hits || []).filter((r) => ['dataset', 'software', 'publication'].includes(r.metadata?.resource_type?.type)).map((r) => ({
        id: `zenodo:${r.conceptrecid || r.id}`, title: r.metadata.title, source: 'zenodo', url: r.links?.self_html,
        type: { dataset: 'Corpus', software: 'Tool' }[r.metadata.resource_type.type] || 'Paper', date: r.metadata.publication_date,
        summary: r.metadata.description, author: (r.metadata.creators || []).slice(0, 3).map((c) => c.name).join(', '),
        tags: r.metadata.keywords || [], codes: [r.metadata.language].filter(Boolean) }));
    },
    hal: async (q) => {
      const d = await getJSON(`https://api.archives-ouvertes.fr/search/?q=${encodeURIComponent(q)}&rows=20&wt=json&sort=submittedDate_tdate%20desc&fl=halId_s,title_s,abstract_s,uri_s,submittedDate_s,authFullName_s,structCountry_s`);
      return (d.response?.docs || []).map((x) => ({ id: `hal:${x.halId_s}`, title: (x.title_s || [''])[0], type: 'Paper', source: 'hal',
        url: x.uri_s, date: x.submittedDate_s, summary: (x.abstract_s || [''])[0], author: (x.authFullName_s || []).slice(0, 3).join(', '),
        country: (x.structCountry_s || [])[0] }));
    },
    theses: async (q) => {
      const d = await getJSON(`https://theses.fr/api/v1/theses/recherche/?q=${encodeURIComponent(q)}&debut=0&nombre=20&tri=pertinence`);
      return (d.theses || []).map((x) => ({ id: `theses:${x.id}`, title: x.titrePrincipal || x.titreEN, type: 'Paper', source: 'theses',
        url: `https://theses.fr/${x.id}`, date: (x.dateSoutenance || x.datePremiereInscriptionDoctorat || '').split('/').reverse().join('-'),
        summary: `${x.status === 'enCours' ? t('thesis_ongoing') : t('thesis_defended')} — ${x.etabSoutenanceN || ''}`,
        author: (x.auteurs || []).map((a) => `${a.prenom} ${a.nom}`).join(', '), country: 'FR', location: x.etabSoutenanceN }));
    },
  };
  async function webSearch(q) {
    q = (q || '').trim();
    if (q.length < 2) return;
    setMode('web', { keepValue: true });
    $('search-input').value = q;
    state.web = { q, results: [], loading: true, errors: [] };
    history.replaceState(null, '', '#q=' + encodeURIComponent(q));
    if (state.tab !== 'veille') switchTab('veille', { keepWeb: true });
    renderList(); renderBanners(); renderActiveFilters();
    const settled = await Promise.allSettled(Object.entries(WEB_SOURCES).map(async ([name, fn]) => {
      try { return await fn(q); } catch (e) { state.web.errors.push(srcName(name)); return []; }
    }));
    if (state.web?.q !== q) return; // recherche remplacée entre-temps
    const known = new Set([...state.notices.map((n) => n.id), ...state.ressources.map((r) => r.id)]);
    const raw = settled.flatMap((s) => s.value || []);
    const seen = new Set();
    const results = [];
    for (const r of raw) {
      if (!r.title || seen.has(r.id)) continue;
      seen.add(r.id);
      const n = normalizeWeb(r, q);
      n.known = known.has(n.id);
      results.push(n);
    }
    // ressources en langues suivies d'abord, puis les plus récentes
    results.sort((a, b) => Number(b.focus) - Number(a.focus) || (b.date || '').localeCompare(a.date || ''));
    state.web = { q, results: spread(results), loading: false, errors: state.web.errors };
    saveLocalSearch(q, results);
    state.ressources = spread([...state.ressources.filter((r) => r.origin !== 'local'), ...localCatalogue()]);
    populateFilters(); renderWebHistory();
    renderList();
    if (map && results.some((r) => r.lat != null)) {
      const b = L.latLngBounds(results.filter((r) => r.lat != null).map((r) => [r._lat ?? r.lat, r._lng ?? r.lng]));
      map.flyToBounds(b.pad(0.3), { maxZoom: 6, duration: reduceMotion() ? 0 : 1 });
    }
  }
  function followUrl(q) {
    const params = new URLSearchParams({ template: 'requete.yml', title: `Requête de veille : ${q}`, requete: q });
    return `https://github.com/${state.repo}/issues/new?${params}`;
  }
  function renderWebResults() {
    const w = state.web;
    const c = $('cards-container');
    const head = `
      <div class="web-head">
        <div class="flex items-start justify-between gap-2">
          <p class="text-sm text-txt m-0"><b>${w.loading ? esc(t('web_loading')) : esc(tf('web_count', { n: w.results.length }))}</b> — « ${esc(w.q)} »</p>
          <button type="button" class="btn-ghost-sm" id="web-clear" aria-label="${esc(t('web_clear'))}">${ico('x')}</button>
        </div>
        ${w.errors.length ? `<p class="text-xs text-txt-3 mt-1 mb-0">${esc(tf('web_errors', { list: w.errors.join(', ') }))}</p>` : ''}
        ${!w.loading ? `<p class="text-xs text-txt-3 mt-1">${esc(t('web_saved_local'))}</p>
          <a class="btn-primary mt-1" href="${esc(followUrl(w.q))}" target="_blank" rel="noopener">${ico('bell')} ${esc(t('web_follow'))}</a>
          <p class="text-xs text-txt-3 mt-2 mb-0">${esc(t('web_follow_hint'))}</p>` : '<div class="spinner spinner-sm mt-2"></div>'}
      </div>`;
    if (w.loading) c.innerHTML = head + Array.from({ length: 4 }, () => '<div class="skeleton" aria-hidden="true"></div>').join('');
    else renderPaged(w.results, noticeCard, PAGE_SIZE, 'no_notice', head);
    $('results-count').textContent = fmtNum(w.results.length);
    $('web-clear')?.addEventListener('click', clearWeb);
  }
  function clearWeb() {
    state.web = null;
    $('search-input').value = '';
    setMode('site');
    refreshAll();
  }
  /* Recherches gardées dans ce navigateur (10 dernières) → collection « Mes recherches » du catalogue */
  function loadLocalSearches() {
    try { return JSON.parse(store.get('omnital.web') || store.get('connectal.web') || '[]'); } catch { return []; }
  }
  function saveLocalSearch(q, results) {
    const keep = results.slice(0, 60).map(({ _lat, _lng, known, ...r }) => r);
    const all = [{ q, date: state.today, results: keep }, ...loadLocalSearches().filter((s) => s.q !== q)].slice(0, 10);
    store.set('omnital.web', JSON.stringify(all));
  }
  function localCatalogue() {
    const out = new Map();
    loadLocalSearches().forEach((s) => s.results.forEach((r) => {
      if (out.has(r.id)) return;
      out.set(r.id, { id: `local:${r.id}`, nom: r.title, source: 'local', origin: 'local', categorie_key:
        { Corpus: 'cat_Dataset', Model: 'cat_Model', Tool: 'cat_Tool', Paper: 'cat_Journal' }[r.type] || 'cat_Tool',
        type: srcName(r.source), lien: r.url, description: { fr: r.summary || '' }, added: s.date, queries: [s.q],
        lat: r.lat, lng: r.lng, city: r.city, region: r.region, geo_precision: r.geo_precision,
        lang_codes: r.lang_codes, lang_groups: r.lang_groups, focus: r.focus, licence_class: 'unknown' });
    }));
    return [...out.values()];
  }
  function renderWebHistory() {
    const list = state.mode === 'web' ? loadLocalSearches() : [];
    $('web-history').innerHTML = list.map((s) => `<button type="button" class="chip-btn" data-web-q="${esc(s.q)}">${ico('search')} ${esc(s.q)}</button>`).join('')
      + (state.mode === 'web' ? state.requetes.map((r) => `<button type="button" class="chip-btn chip-btn-tracked" data-web-q="${esc(r.q)}" title="${esc(t('tracked_query'))}">${ico('bell')} ${esc(r.q)}</button>`).join('') : '');
  }

  /* ═══════════════ Recherche : portée (site / web) ═══════════════ */
  function setMode(mode, { keepValue = false } = {}) {
    if (state.mode === mode) return;
    state.mode = mode;
    if (!keepValue) $('search-input').value = '';
    updateSearchMode();
    renderWebHistory();
    if (mode === 'site' && state.web) { state.web = null; }
    refreshAll();
  }
  function updateSearchMode() {
    const web = state.mode === 'web';
    document.querySelectorAll('.search-mode [data-mode]').forEach((b) => {
      const on = b.dataset.mode === state.mode;
      b.classList.toggle('mode-active', on);
      b.setAttribute('aria-checked', String(on));
    });
    $('search-input').placeholder = t(web ? 'web_placeholder' : 'search_site');
    $('web-go').classList.toggle('hidden', !web);
    $('web-hint').classList.toggle('hidden', !web);
    $('period-filter').classList.toggle('is-disabled', web || state.tab === 'catalogue');
  }

  /* ═══════════════ Navigation ═══════════════ */
  function switchTab(tab, { keepWeb = false } = {}) {
    state.tab = tab;
    if (!keepWeb && state.web) { state.web = null; $('search-input').value = ''; state.mode = 'site'; updateSearchMode(); renderWebHistory(); }
    document.querySelectorAll('.tab-btn').forEach((b) => {
      const on = b.dataset.tab === tab;
      b.classList.toggle('tab-active', on);
      b.setAttribute('aria-selected', String(on));
    });
    $('filters-veille').classList.toggle('hidden', tab !== 'veille');
    $('filters-catalogue').classList.toggle('hidden', tab !== 'catalogue');
    $('filters-opps').classList.toggle('hidden', tab !== 'opps');
    document.querySelector('.search-mode [data-mode="web"]').classList.toggle('hidden', tab === 'opps');
    if (tab === 'opps' && state.mode === 'web') setMode('site');
    updateSearchMode();
    applyView();
    if (tab === 'catalogue') ensureCatalogue();
    refreshAll();
    if (map) setTimeout(() => map.invalidateSize(), 100);
  }
  function toggleFilters(open) {
    const panel = $('filters-panel');
    const show = open ?? panel.hidden;
    panel.hidden = !show;
    $('toolbar').classList.toggle('has-panel', show);
    $('filters-toggle').setAttribute('aria-expanded', String(show));
    $('fab-filters').classList.toggle('is-hidden', show);
    document.body.style.overflow = show && !isDesktop() ? 'hidden' : '';
    if (show) panel.querySelector(`#filters-${state.tab} select`)?.focus({ preventScroll: true });
    measureToolbar();
  }
  /** Hauteurs réelles de l'en-tête et de la barre d'outils (carte collante, ancres). */
  function measureToolbar() {
    const r = document.documentElement.style;
    r.setProperty('--header-h', `${$('site-header').offsetHeight}px`);
    const sticky = isDesktop() && !$('toolbar').classList.contains('has-panel');
    r.setProperty('--toolbar-h', sticky ? `${$('toolbar').offsetHeight}px` : '0px');
  }

  /* ═══════════════ Démarrage ═══════════════ */
  document.addEventListener('DOMContentLoaded', async () => {
    await loadStatic();
    const stored = store.get('lang');
    const nav = (navigator.language || 'fr').slice(0, 2);
    state.lang = state.i18n[stored] ? stored : (state.i18n[nav] ? nav : 'fr');
    state.view = store.get('omnital.view') === 'grid' ? 'grid' : 'list';
    document.querySelectorAll('.lang-btn').forEach((b) => b.addEventListener('click', () => setLanguage(b.dataset.lang)));
    $('theme-toggle').setAttribute('aria-pressed', String(isDark()));
    $('theme-toggle').addEventListener('click', () => setTheme(isDark() ? 'light' : 'dark'));
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener?.('change', (e) => {
      if (!store.get('theme')) setTheme(e.matches ? 'dark' : 'light');
    });

    initMap();
    setLanguage(state.lang);
    measureToolbar();

    // Délégation d'événements (une seule écoute pour toutes les cartes)
    document.body.addEventListener('click', (e) => {
      const clear = e.target.closest('[data-clear]');
      if (clear) { clearFilter(clear.dataset.clear); return; }
      const mapBtn = e.target.closest('[data-map-id]');
      if (mapBtn) { e.preventDefault(); viewOnMap(mapBtn.dataset.mapId); return; }
      const hist = e.target.closest('[data-web-q]');
      if (hist) { webSearch(hist.dataset.webQ); return; }
      const tabLink = e.target.closest('[data-tab-link]');
      if (tabLink) { e.preventDefault(); switchTab(tabLink.dataset.tabLink); window.scrollTo({ top: 0, behavior: reduceMotion() ? 'auto' : 'smooth' }); return; }
      const grp = e.target.closest('[data-lang-group]');
      if (grp) {
        e.preventDefault(); switchTab('veille'); $('lang-filter').value = 'g:' + grp.dataset.langGroup; refreshAll();
        window.scrollTo({ top: 0, behavior: reduceMotion() ? 'auto' : 'smooth' }); return;
      }
      const banner = e.target.closest('[data-banner-id]');
      if (banner) {
        const id = banner.dataset.bannerId;
        const n = [...state.notices, ...state.opps, ...state.ressources].find((x) => x.id === id);
        if (n?.lat != null) viewOnMap(n.id); else window.open(banner.dataset.url, '_blank', 'noopener');
        return;
      }
      const card = e.target.closest('article.card[data-id], article.card[data-opp-id]');
      if (card && !e.target.closest('a, button')) {
        const id = card.dataset.id || card.dataset.oppId;
        const n = [...state.notices, ...state.opps, ...(state.web?.results || [])].find((x) => x.id === id);
        highlightCard(id);
        if (n?.lat != null) viewOnMap(n.id); else if (n) window.open(safeUrl(n.url), '_blank', 'noopener');
      }
    });
    document.body.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && e.target.matches('article.card[data-id], article.card[data-opp-id]')) e.target.click();
    });
    $('cards-container').addEventListener('mouseover', debounce((e) => {
      const card = e.target.closest?.('article.card');
      if (card) pulseMarker(card.dataset.id || card.dataset.oppId);
    }, 120));

    // Recherche : filtrage instantané (site) ou recherche web (Entrée / bouton)
    $('search-form').addEventListener('submit', (e) => {
      e.preventDefault();
      if (state.mode === 'web') webSearch($('search-input').value);
      else { refreshAll(); if (!isDesktop()) $('results').scrollIntoView({ behavior: 'smooth' }); }
    });
    $('search-input').addEventListener('input', debounce(() => { if (state.mode === 'site') refreshAll(); }, 200));
    document.querySelectorAll('.search-mode [data-mode]').forEach((b) => b.addEventListener('click', () => {
      setMode(b.dataset.mode, { keepValue: true });
      $('search-input').focus();
    }));
    document.addEventListener('keydown', (e) => {
      if (e.key === '/' && !e.target.matches('input, textarea, select')) { e.preventDefault(); $('search-input').focus(); }
      if (e.key === 'Escape' && !$('filters-panel').hidden) { toggleFilters(false); $('filters-toggle').focus(); }
    });

    document.querySelectorAll('.tab-btn').forEach((b) => b.addEventListener('click', () => switchTab(b.dataset.tab)));
    document.querySelectorAll('#period-filter [data-period]').forEach((b) => b.addEventListener('click', () => setPeriod(+b.dataset.period)));
    document.querySelectorAll('.filters-grid select, .filters-grid input[type="checkbox"]')
      .forEach((el) => el.addEventListener('change', refreshAll));
    $('reset-filters').addEventListener('click', resetFilters);
    $('filters-toggle').addEventListener('click', () => toggleFilters());
    $('fab-filters').addEventListener('click', () => toggleFilters(true));
    $('filters-close').addEventListener('click', () => toggleFilters(false));
    $('filters-apply').addEventListener('click', () => { toggleFilters(false); $('results').scrollIntoView({ behavior: reduceMotion() ? 'auto' : 'smooth' }); });
    $('filters-panel').addEventListener('click', (e) => { if (e.target.id === 'filters-panel' && !isDesktop()) toggleFilters(false); });
    $('map-toggle').addEventListener('click', () => setMapCollapsed($('map-toggle').getAttribute('aria-expanded') === 'true'));
    document.querySelectorAll('.view-toggle [data-view]').forEach((b) => b.addEventListener('click', () => {
      state.view = b.dataset.view; store.set('omnital.view', state.view); applyView();
    }));

    // En-tête : ombre au défilement ; bouton flottant masqué au-dessus du pied de page
    const onScroll = () => $('site-header').classList.toggle('is-scrolled', window.scrollY > 8);
    window.addEventListener('scroll', onScroll, { passive: true });
    if ('IntersectionObserver' in window) {
      new IntersectionObserver(([en]) => { if ($('filters-panel').hidden) $('fab-filters').classList.toggle('is-hidden', en.isIntersecting); })
        .observe(document.querySelector('.site-footer'));
    }
    window.addEventListener('resize', debounce(() => { measureToolbar(); map?.invalidateSize(); }, 150));
    // Liens internes / historique (#opps?country=FR…) : on suit le changement d'ancre
    window.addEventListener('hashchange', () => {
      const m = location.hash.match(/^#(veille|catalogue|opps)\b/);
      if (location.hash.startsWith('#q=')) { webSearch(decodeURIComponent(location.hash.slice(3))); return; }
      if (!m || location.hash === lastHash) return;
      // filtres de l'onglet remis à zéro puis relus depuis l'ancre (avant tout rendu, qui réécrit l'ancre)
      Object.keys(URL_KEYS[m[1]]).forEach((id) => { $(id).value = DEFAULTS[id] ?? 'ALL'; });
      Object.entries(CHECKS[m[1]]).forEach(([id, [, def]]) => { $(id).checked = def; });
      state.period = 0;
      readUrlState();
      if (m[1] !== state.tab) switchTab(m[1]); else refreshAll();
    });
    if ('ResizeObserver' in window) new ResizeObserver(debounce(measureToolbar, 50)).observe($('toolbar'));

    // Onglet initial (avant le chargement : les filtres de l'URL s'appliquent dès l'arrivée des données)
    const h = location.hash;
    const initialTab = (h.match(/^#(veille|catalogue|opps)\b/) || [])[1] || 'veille';
    switchTab(initialTab, { keepWeb: true });
    await loadData();
    if (h.startsWith('#q=')) webSearch(decodeURIComponent(h.slice(3)));
    else if (initialTab === 'catalogue') ensureCatalogue();

    // Rafraîchissement silencieux toutes les 30 min si l'onglet est visible ; horloge relative chaque minute
    setInterval(() => { if (document.visibilityState === 'visible' && !state.web) loadData({ silent: true }); }, 30 * 60 * 1000);
    setInterval(updateHeader, 60 * 1000);
  });
})();
