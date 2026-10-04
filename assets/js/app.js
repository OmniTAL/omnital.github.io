/* ConnecTAL — application front (sans build JS, sans dépendance hors Leaflet/MapLibre).
 * Données : data/radar.json   (généré chaque jour par scripts/agent_veille_nlp.py)
 *           data/i18n.json    (traductions FR / EN / Taqbaylit)
 *           data/langues.json (langues peu dotées suivies : codes, mots-clés, région)
 *           data/pays.json    (centroïdes des pays, pour la recherche web)
 */
(() => {
  'use strict';

  /* ═══════════════ Constantes ═══════════════ */
  const PAGE_SIZE = 50;
  const CAT_PAGE = 60;
  const TYPES = ['Paper', 'Corpus', 'Model', 'Tool', 'Event', 'Journal'];
  const TYPE_COLOR = { Corpus: '#138A07', Paper: '#0EA5E9', Model: '#F59E0B', Tool: '#EC4899', Event: '#8B5CF6',
                       Journal: '#A16207', Opportunity: '#0D9488' };
  const TYPE_CHIP = { Corpus: 'chip-corpus', Paper: 'chip-paper', Model: 'chip-model', Tool: 'chip-tool',
                      Event: 'chip-event', Journal: 'chip-journal', Opportunity: 'chip-opp' };
  const CAT_TO_TYPE = { cat_Dataset: 'Corpus', cat_Model: 'Model', cat_Tool: 'Tool', cat_Event: 'Event', cat_Journal: 'Journal', cat_Job: 'Opportunity' };
  const SRC_CLASS = { general: 'src-general', berbere: 'src-berbere', ecosysteme: 'src-ecosysteme', veille: 'src-veille', local: 'src-local' };
  const SOURCES = { arxiv: 'arXiv', hal: 'HAL', huggingface: 'Hugging Face', github: 'GitHub', wikicfp: 'WikiCFP',
                    zenodo: 'Zenodo', elg: 'European Language Grid', doaj: 'DOAJ', nlppeople: 'NLP People',
                    greenhouse: 'Greenhouse', ashby: 'Ashby', lever: 'Lever', remotive: 'Remotive', arbeitnow: 'Arbeitnow',
                    theses: 'theses.fr', formations: 'Formations (liste ConnecTAL)', requetes: 'Requêtes suivies' };
  const OPP_KINDS = ['job', 'internship', 'phd', 'postdoc', 'thesis', 'master', 'bachelor', 'school'];
  const OPP_COLOR = { job: '#0D9488', internship: '#0891B2', phd: '#7C3AED', postdoc: '#9333EA', thesis: '#6366F1',
                      master: '#DB2777', bachelor: '#E11D48', school: '#EA580C' };

  const state = {
    tab: 'veille', mobileView: 'map', lang: 'fr', period: 0,
    i18n: {}, notices: [], opps: [], ressources: [], requetes: [], repo: null,
    langs: [], groups: {}, pays: null, today: null, agent: {}, stats: {},
    shown: PAGE_SIZE, catShown: CAT_PAGE,
    web: null, // { q, results, loading, errors }
    deadlines: [], catTotal: 0, catalogueLoaded: false,
  };
  let map = null, baseLayer = null, cluster = null, tempMarker = null;
  const markers = new Map();
  const $ = (id) => document.getElementById(id);
  const store = {
    get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* navigation privée / quota */ } },
  };

  /* ═══════════════ Utilitaires ═══════════════ */
  const esc = (s) => s == null ? '' : String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  /** N'autorise que http(s) : protège contre les liens javascript: injectés dans les données. */
  const safeUrl = (u) => (/^https?:\/\//i.test(String(u || '').trim()) ? String(u).trim() : '#');
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
  const debounce = (fn, ms) => { let id; return (...a) => { clearTimeout(id); id = setTimeout(() => fn(...a), ms); }; };
  const isDesktop = () => window.matchMedia('(min-width: 1024px)').matches;
  const srcName = (s) => SOURCES[s] || s;
  const langName = (code) => { const l = state.langs.find((x) => x.code === code); return l ? (state.lang === 'en' ? l.en : l.fr) : code; };
  const groupName = (g) => t('group_' + g);

  /* ═══════════════ i18n ═══════════════ */
  function applyI18n() {
    document.querySelectorAll('[data-i18n]').forEach((el) => { el.textContent = t(el.dataset.i18n); });
    document.querySelectorAll('[data-i18n-placeholder]').forEach((el) => { el.placeholder = t(el.dataset.i18nPlaceholder); });
    document.querySelectorAll('[data-i18n-title]').forEach((el) => { el.title = t(el.dataset.i18nTitle); });
    document.documentElement.lang = state.lang;
    document.title = `${t('site_title')} — ${t('site_subtitle')}`;
    $('theme-toggle').setAttribute('aria-label', t('theme_toggle'));
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
    if (state.today) { populateFilters(); renderLegend(); renderAgentStatus(); renderWebHistory(); }
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
    map = L.map('map', { zoomControl: true, worldCopyJump: true, minZoom: 2 }).setView([30, 5], 3);
    setBaseLayer();
    cluster = L.markerClusterGroup({
      showCoverageOnHover: false, maxClusterRadius: 45, spiderfyOnMaxZoom: true, chunkedLoading: true,
      iconCreateFunction: (c) => {
        const n = c.getChildCount();
        const size = n < 10 ? 34 : n < 100 ? 42 : 52;
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
    const color = kind === 'opp' ? OPP_COLOR[item.opp_kind] || TYPE_COLOR.Opportunity : TYPE_COLOR[type] || '#138A07';
    const cls = ['marker-pin', item.focus ? 'is-focus' : '', `is-${kind}`].join(' ');
    const icon = L.divIcon({
      className: '', iconSize: [16, 16], iconAnchor: [8, 8],
      html: `<div class="${cls}" style="background:${color};width:16px;height:16px;box-shadow:0 0 8px ${color}90"></div>`,
    });
    const m = L.marker([item._lat ?? item.lat, item._lng ?? item.lng], { icon, title: item.title || item.nom, keyboard: true });
    m.bindPopup(() => (kind === 'catalogue' ? popupCatalogue(item) : kind === 'opp' ? popupOpp(item) : popupNotice(item)), { maxWidth: 330 });
    return m;
  }
  function geoLine(it) {
    const place = it.location || it.city || it.region || '';
    if (!place && it.lat == null) return '';
    const prec = it.geo_precision ? ` <span class="geo-prec" title="${esc(it.geo_source || '')}">${esc(t('geo_' + it.geo_precision))}</span>` : '';
    return `<div class="popup-meta">📍 ${esc(place)}${prec}</div>`;
  }
  function langTags(it) {
    return (it.lang_codes || []).slice(0, 3).map((c) => `<span class="tag tag-focus">${esc(langName(c))}</span>`).join('');
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
      <p>${esc(descOf(r))}</p>
      ${r.event ? deadlineRows(r.event, true) : ''}
      <div class="popup-meta">${esc(t(r.categorie_key))}${r.langue ? ' · ' + esc(r.langue) : ''}</div>
      ${geoLine(r)}
      <a href="${esc(safeUrl(r.lien))}" target="_blank" rel="noopener">${esc(t('open'))} →</a>
    </div>`;
  }
  function popupOpp(o) {
    return `<div>
      <span class="chip chip-opp" style="--opp:${OPP_COLOR[o.opp_kind] || '#0D9488'}">${esc(t('opp_' + o.opp_kind))}</span>
      <h3>${esc(o.title)}</h3>
      ${o.author ? `<p><b>${esc(o.author)}</b></p>` : ''}
      ${o.summary ? `<p>${esc(o.summary.slice(0, 220))}${o.summary.length > 220 ? '…' : ''}</p>` : ''}
      ${geoLine(o)}
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
    $('map-counter-num').textContent = layers.length;
    $('map-unlocated').textContent = unlocated ? tf('unlocated', { n: unlocated }) : '';
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
    if (!target || target.lat == null) return;
    if (state.tab === 'catalogue') switchTab(kind === 'opp' ? 'opps' : 'veille');
    if (!isDesktop()) { state.mobileView = 'map'; applyMobileView(); }
    setTimeout(() => {
      map.invalidateSize();
      let m = markers.get(id);
      if (!m) { m = tempMarker = markerFor(target, kind).addTo(map); }
      if (cluster.hasLayer(m)) cluster.zoomToShowLayer(m, () => m.openPopup());
      else { map.flyTo(m.getLatLng(), 8, { duration: 1.2 }); setTimeout(() => m.openPopup(), 1300); }
    }, 150);
  }

  /* ═══════════════ Données ═══════════════ */
  async function getJSON(url) {
    const r = await fetch(url, { cache: 'no-cache' });
    if (!r.ok) throw new Error(`${url} : HTTP ${r.status}`);
    return r.json();
  }
  async function loadStatic() {
    const [i18n, langues] = await Promise.allSettled([getJSON('data/i18n.json'), getJSON('data/langues.json')]);
    state.i18n = i18n.value || {};
    state.i18n.fr ||= {};
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
    if (!silent) showLoading(true);
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
      updateHeader(data.last_updated);
      populateFilters();
      renderLegend();
      renderAgentStatus();
      renderWebHistory();
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
      refreshAll();
    } catch (e) { console.warn('[catalogue]', e); } finally { showLoading(false); }
  }

  /* ═══════════════ Filtres ═══════════════ */
  function populateSelect(id, values, allKey, labelFn = (v) => v, extra = '') {
    const sel = $(id);
    const cur = sel.value;
    sel.innerHTML = `<option value="ALL">${esc(t(allKey))}</option>${extra}` +
      values.map(([v, n]) => `<option value="${esc(v)}">${esc(labelFn(v))}${n != null ? ` (${n})` : ''}</option>`).join('');
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
  function populateFilters() {
    const N = state.notices;
    populateSelect('vsource-filter', byCount(countBy(N, 'source')), 'source_all', srcName);
    const types = countBy(N, 'type');
    populateSelect('type-filter', TYPES.filter((x) => types.has(x)).map((x) => [x, types.get(x)]), 'type_all', (v) => t('type_' + v));
    populateSelect('region-filter', byCount(countBy(N, 'region')).filter(([r]) => r !== 'International'), 'region_all');
    populateSelect('lang-filter', byCount(countBy(N, 'lang_codes')), 'language_all', langName);
    if (state.requetes.length) {
      $('query-filter-wrap').classList.remove('hidden');
      populateSelect('query-filter', state.requetes.map((r) => [r.q, r.results]), 'tracked_all');
    }

    const O = state.opps;
    const kinds = countBy(O, 'opp_kind');
    populateSelect('opp-kind', OPP_KINDS.filter((k) => kinds.has(k)).map((k) => [k, kinds.get(k)]), 'opp_all', (k) => t('opp_' + k));
    populateSelect('opp-region', byCount(countBy(O, 'region')).filter(([r]) => r !== 'International'), 'region_all');
    populateSelect('opp-source', byCount(countBy(O, 'source')), 'source_all', srcName);

    const R = state.ressources;
    populateSelect('source-filter', [...countBy(R, 'source')], 'source_all', (v) => t('source_' + v));
    populateSelect('cat-filter', [...countBy(R, 'categorie_key')].sort((a, b) => t(a[0]).localeCompare(t(b[0]))), 'category_all', t);
    populateSelect('langue-filter', byCount(countBy(R, (r) => r.lang_codes || [])), 'language_all', langName);
  }
  const query = () => $('search-input').value.toLowerCase().trim();
  function matchLang(it) {
    const g = $('langgroup-filter').value, code = $('lang-filter').value;
    if (g === 'ANY' && !(it.lang_groups || []).length && !it.focus) return false;
    if (!['ALL', 'ANY'].includes(g) && !(it.lang_groups || []).includes(g)) return false;
    if (code !== 'ALL' && !(it.lang_codes || []).includes(code)) return false;
    return true;
  }

  function filterNotices() {
    const q = query(), src = $('vsource-filter').value, typ = $('type-filter').value, reg = $('region-filter').value;
    const rq = $('query-filter').value, p = state.period;
    return state.notices.filter((i) => {
      if (src !== 'ALL' && i.source !== src) return false;
      if (typ !== 'ALL' && i.type !== typ) return false;
      if (reg !== 'ALL' && i.region !== reg) return false;
      if (rq !== 'ALL' && !(i.queries || []).includes(rq)) return false;
      if (!matchLang(i)) return false;
      if (p && daysAgo(i.first_seen) >= p) return false;
      if (q) {
        const hay = `${i.title} ${i.summary} ${i.author} ${i.city || ''} ${i.region || ''} ${i.location || ''} ${(i.lang_codes || []).map(langName).join(' ')}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }
  function filterOpps() {
    const q = query(), kind = $('opp-kind').value, reg = $('opp-region').value, src = $('opp-source').value;
    const remote = $('opp-remote').checked;
    return state.opps.filter((o) => {
      if (kind !== 'ALL' && o.opp_kind !== kind) return false;
      if (reg !== 'ALL' && o.region !== reg) return false;
      if (src !== 'ALL' && o.source !== src) return false;
      if (remote && !/remote|télétravail|hybrid/i.test(`${o.location || ''} ${o.title}`)) return false;
      if (q && !`${o.title} ${o.summary || ''} ${o.author || ''} ${o.location || ''} ${o.region || ''}`.toLowerCase().includes(q)) return false;
      return true;
    }).sort((a, b) => kindRank(a) - kindRank(b) || (b.date || '').localeCompare(a.date || ''));
  }
  // offres ouvertes d'abord (emplois, stages, thèses, postdocs), puis thèses en cours, puis formations
  const kindRank = (o) => (o.opp_kind === 'thesis' ? 1 : ['master', 'bachelor', 'school'].includes(o.opp_kind) ? 2 : 0);

  /** Notice rédigée par l'agent en priorité, sinon description du classeur. */
  const descOf = (r) => r.notice?.[state.lang] || r.notice?.fr
    || r.description?.[state.lang] || r.description?.fr || r.type || '';
  function filterRessources(forMap = false) {
    const q = query();
    const src = $('source-filter').value, cat = $('cat-filter').value, langue = $('langue-filter').value, oa = $('oa-filter').value;
    return state.ressources.filter((r) => {
      if (!forMap || state.tab === 'catalogue') {
        if (src !== 'ALL' && r.source !== src) return false;
        if (cat !== 'ALL' && r.categorie_key !== cat) return false;
        if (langue !== 'ALL' && !(r.lang_codes || []).includes(langue)) return false;
        if (oa !== 'ALL' && r.licence_class !== oa) return false;
        if ($('deadline-filter').checked && !r.deadline_next) return false;
      }
      if (forMap && !matchLang(r)) return false;
      if (q) {
        const hay = `${r.nom} ${r.type || ''} ${descOf(r)} ${r.langue || ''} ${r.region || ''} ${r.city || ''}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }
  function resetFilters() {
    ['vsource-filter', 'type-filter', 'region-filter', 'langgroup-filter', 'lang-filter', 'query-filter',
     'source-filter', 'cat-filter', 'langue-filter', 'oa-filter', 'opp-kind', 'opp-region', 'opp-source']
      .forEach((id) => { $(id).value = 'ALL'; });
    $('deadline-filter').checked = false;
    $('opp-remote').checked = false;
    $('cat-sort').value = 'relevance';
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
      <span class="dl-label">${icon} ${esc(t(labelKey))}${src ? ' *' : ''}</span>
      <span class="dl-date">${esc(fmtDate(iso))}${c.label ? ` <b>${esc(c.label)}</b>` : ''}</span></li>`;
  }
  /** Bloc « lieu · dates · résumés · articles · notification » d'un événement. */
  function deadlineRows(ev, compact = false) {
    const srcs = ev.deadline_sources || {};
    const when = ev.start ? `${fmtDate(ev.start)}${ev.end && ev.end !== ev.start ? ' → ' + fmtDate(ev.end) : ''}` : '';
    return `<ul class="dl-box${compact ? ' dl-compact' : ''}">
      ${ev.location ? `<li class="dl-row"><span class="dl-label">📍 ${esc(t('dl_location'))}</span><span class="dl-date">${esc(ev.location)}</span></li>` : ''}
      ${when ? `<li class="dl-row"><span class="dl-label">🗓 ${esc(t('dl_dates'))}</span><span class="dl-date">${esc(when)}</span></li>` : ''}
      ${deadlineRow('✍️', 'dl_abstract', ev.abstract_deadline, srcs.abstract_deadline)}
      ${deadlineRow('📄', 'dl_paper', ev.paper_deadline, srcs.paper_deadline)}
      ${compact ? '' : deadlineRow('🔔', 'dl_notification', ev.notification, srcs.notification)}
      ${!ev.abstract_deadline && !ev.paper_deadline ? `<li class="dl-row dl-passed"><span class="dl-label">${esc(t('dl_unknown'))}</span></li>` : ''}
    </ul>`;
  }
  /** Bloc revue : soumission continue + numéros spéciaux ouverts avec leur date limite. */
  function journalRows(j) {
    const issues = (j.special_issues || []).slice(0, 3).map((i) => {
      const dl = i.abstract_deadline && (!i.deadline || i.abstract_deadline < i.deadline) ? i.abstract_deadline : i.deadline;
      const c = countdown(dl);
      return `<li class="dl-row ${c.cls}"><a class="dl-label link line-clamp-2" href="${esc(safeUrl(i.url))}" target="_blank" rel="noopener">📢 ${esc(i.title)}</a>
        <span class="dl-date">${dl ? `${esc(fmtDate(dl))} <b>${esc(c.label)}</b>` : esc(t('dl_unknown'))}</span></li>`;
    }).join('');
    return `<ul class="dl-box">
      <li class="dl-row"><span class="dl-label">📝 ${esc(t('submission'))}</span><span class="dl-date">${esc(t('submission_continuous'))}</span></li>
      ${j.apc ? `<li class="dl-row"><span class="dl-label">💶 APC</span><span class="dl-date">${esc(j.apc === 'oui' ? t('yes') : t('no'))}</span></li>` : ''}
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
    state.shown = PAGE_SIZE;
    state.catShown = CAT_PAGE;
    renderBanners();
    renderList();
    $('tab-count-veille').textContent = state.notices.length || '';
    $('tab-count-catalogue').textContent = (state.catalogueLoaded ? state.ressources.length : state.catTotal + localCatalogue().length) || '';
    $('tab-count-opps').textContent = state.opps.length || '';
  }
  function renderList() {
    if (state.tab === 'veille') {
      const items = filterNotices();
      const points = items.map((i) => [i, 'notice']);
      if ($('catalogue-layer').checked) {
        // les ajouts de la veille sont déjà sur la carte en tant qu'éléments de veille
        filterRessources(true).forEach((r) => { if (r.origin !== 'veille') points.push([r, 'catalogue']); });
      }
      if (state.web?.results?.length) state.web.results.forEach((r) => points.push([r, 'web']));
      if (state.web) renderWebResults(); else renderNoticeCards(items);
      renderMap(points);
    } else if (state.tab === 'opps') {
      const items = filterOpps();
      renderOppCards(items);
      renderMap(items.map((o) => [o, 'opp']));
    } else {
      renderCatalogue(sortRessources(filterRessources()));
    }
  }

  function geoTag(it) {
    if (!it.geo_precision) return '';
    return `<span class="tag" title="${esc(it.geo_source || '')}">${esc(t('geo_' + it.geo_precision))}</span>`;
  }
  function noticeCard(it) {
    const isNew = it.first_seen === state.today;
    const place = it.type === 'Event' ? (it.location || it.city) : (it.city || (it.region !== 'International' ? it.region : ''));
    const tags = [
      isNew ? `<span class="tag tag-new">${esc(t('new'))}</span>` : '',
      it.web ? `<span class="tag tag-web">${esc(t('web_result'))}</span>` : '',
      langTags(it),
      it.topic ? `<span class="tag">${esc(it.topic)}</span>` : '',
      it.trending ? `<span class="tag">🔥 ${esc(t('trending'))}</span>` : '',
      ...(it.queries || []).slice(0, 2).map((q) => `<span class="tag">🔎 ${esc(q)}</span>`),
    ].join('');
    const dateLabel = it.type === 'Event'
      ? `${fmtDate(it.date)}${it.date_end && it.date_end !== it.date ? ' → ' + fmtDate(it.date_end) : ''}`
      : fmtDate(it.date);
    return `
      <article class="card" tabindex="0" data-id="${esc(it.id)}">
        <div class="flex items-center justify-between gap-2">
          <span class="chip ${TYPE_CHIP[it.type] || ''}">${esc(t('type_' + it.type).toUpperCase())}</span>
          <span class="text-xs text-txt-3 whitespace-nowrap font-mono">${esc(dateLabel)}</span>
        </div>
        <h3 class="text-[0.95rem] font-medium text-txt leading-snug line-clamp-2">${esc(it.title)}</h3>
        ${it.summary ? `<p class="text-sm text-txt-2 leading-relaxed line-clamp-2">${esc(it.summary)}</p>` : ''}
        ${tags ? `<div class="flex flex-wrap gap-1">${tags}</div>` : ''}
        ${it.event && (it.event.abstract_deadline || it.event.paper_deadline) ? `<ul class="dl-box dl-compact">
          ${deadlineRow('✍️', 'dl_abstract', it.event.abstract_deadline, it.event.deadline_sources?.abstract_deadline)}
          ${deadlineRow('📄', 'dl_paper', it.event.paper_deadline, it.event.deadline_sources?.paper_deadline)}</ul>` : ''}
        <div class="text-xs text-txt-3 pt-1 flex items-center justify-between gap-2">
          <span class="truncate font-mono">${esc(srcName(it.source))}${it.author && it.author !== 'WikiCFP' ? ' · ' + esc(it.author) : ''}</span>
          ${place ? `<span class="truncate font-mono flex-shrink-0 max-w-[45%]">📍 ${esc(place)}</span>` : ''}
        </div>
        <div class="flex items-center gap-2 pt-1 flex-wrap">
          ${it.lat != null ? `<button type="button" class="btn-map" data-map-id="${esc(it.id)}">📍 ${esc(t('view_on_map'))}</button>` : ''}
          <a class="btn-open-ext" href="${esc(safeUrl(it.url))}" target="_blank" rel="noopener">↗ ${esc(t('open'))}</a>
          ${geoTag(it)}
        </div>
      </article>`;
  }
  function pagedList(items, cardFn, emptyKey) {
    const c = $('cards-container');
    $('results-count').textContent = items.length;
    if (!items.length) { c.innerHTML = `<div class="empty-state">${esc(t(emptyKey))}</div>`; return; }
    const slice = items.slice(0, state.shown);
    c.innerHTML = slice.map(cardFn).join('') + (items.length > slice.length
      ? `<button type="button" class="btn-more" id="more-btn">${esc(tf('show_more', { n: Math.min(PAGE_SIZE, items.length - slice.length), total: items.length - slice.length }))}</button>`
      : '');
    $('more-btn')?.addEventListener('click', () => { state.shown += PAGE_SIZE; pagedList(items, cardFn, emptyKey); });
  }
  const renderNoticeCards = (items) => pagedList(items, noticeCard, 'no_notice');

  function oppCard(o) {
    const isNew = o.first_seen === state.today;
    const linkWarn = o.source === 'formations' && o.link_status != null && (o.link_status === 0 || o.link_status >= 400);
    return `
      <article class="card" tabindex="0" data-opp-id="${esc(o.id)}">
        <div class="flex items-center justify-between gap-2">
          <span class="chip chip-opp" style="--opp:${OPP_COLOR[o.opp_kind] || '#0D9488'}">${esc(t('opp_' + o.opp_kind).toUpperCase())}</span>
          <span class="text-xs text-txt-3 whitespace-nowrap font-mono">${esc(fmtDate(o.date))}</span>
        </div>
        <h3 class="text-[0.95rem] font-medium text-txt leading-snug line-clamp-2">${esc(o.title)}</h3>
        ${o.author ? `<p class="text-sm font-medium text-txt-2 truncate">${esc(o.author)}</p>` : ''}
        ${o.summary && o.source !== 'formations' ? `<p class="text-sm text-txt-2 leading-relaxed line-clamp-2">${esc(o.summary)}</p>` : ''}
        ${o.event ? `<ul class="dl-box dl-compact">${deadlineRow('📄', 'dl_application', o.event.paper_deadline || o.event.abstract_deadline)}</ul>` : ''}
        <div class="flex flex-wrap gap-1">
          ${isNew ? `<span class="tag tag-new">${esc(t('new'))}</span>` : ''}
          ${o.thesis_status ? `<span class="tag">${esc(t('thesis_' + (o.thesis_status === 'en cours' ? 'ongoing' : 'defended')))}</span>` : ''}
          ${o.teaching_languages ? `<span class="tag">🗣 ${esc(o.teaching_languages)}</span>` : ''}
          ${o.employment ? `<span class="tag">${esc(o.employment)}</span>` : ''}
          ${linkWarn ? `<span class="tag tag-warn" title="HTTP ${esc(o.link_status)}">⚠ ${esc(t('link_check'))}</span>` : ''}
          ${langTags(o)}
        </div>
        <div class="text-xs text-txt-3 pt-1 flex items-center justify-between gap-2">
          <span class="truncate font-mono">${esc(srcName(o.source))}</span>
          ${o.location ? `<span class="truncate font-mono flex-shrink-0 max-w-[55%]">📍 ${esc(o.location)}</span>` : ''}
        </div>
        <div class="flex items-center gap-2 pt-1 flex-wrap">
          ${o.lat != null ? `<button type="button" class="btn-map" data-map-id="${esc(o.id)}">📍 ${esc(t('view_on_map'))}</button>` : ''}
          <a class="btn-open-ext" href="${esc(safeUrl(o.url))}" target="_blank" rel="noopener">↗ ${esc(t('open'))}</a>
          ${geoTag(o)}
        </div>
      </article>`;
  }
  const renderOppCards = (items) => pagedList(items, oppCard, 'no_opp');

  function catalogueCard(r) {
    const metaParts = [
      r.taille ? `📦 ${esc(r.taille)}` : '',
      r.langue ? `🗣 ${esc(r.langue)}` : '',
      r.city || (r.pays && r.pays !== 'International') ? `📍 ${esc(r.city || r.pays)}` : '',
    ].filter(Boolean).join(' · ');
    return `
      <article class="card-cat">
        <div class="flex items-start justify-between gap-3 flex-wrap">
          <span class="src-pill ${SRC_CLASS[r.source] || 'src-general'}">${esc(t('source_' + r.source))}</span>
          ${r.event ? '' : `<span class="text-xs px-2.5 py-1 rounded-md border font-medium font-mono whitespace-nowrap badge-oa-${esc(r.licence_class || 'unknown')}">${esc(r.licence || t('license_unknown'))}</span>`}
        </div>
        <div class="text-xs uppercase tracking-wider text-txt-3 font-medium">${esc(t(r.categorie_key))}${r.type ? ' · ' + esc(r.type) : ''}</div>
        <h3 class="text-base font-semibold text-txt leading-snug line-clamp-3">${esc(r.nom)}</h3>
        <p class="text-sm text-txt-2 leading-relaxed ${r.event || r.journal ? 'line-clamp-5' : 'line-clamp-4'}">${esc(descOf(r))}</p>
        ${r.event ? deadlineRows(r.event) : ''}
        ${r.journal ? journalRows(r.journal) : ''}
        <div class="flex-1"></div>
        <div class="flex flex-wrap gap-1">
          ${r.origin === 'veille' ? `<span class="tag">${esc(tf('auto_added', { date: fmtDate(r.added) }))}</span>` : ''}
          ${r.origin === 'local' ? `<span class="tag tag-web">🔎 ${esc(r.queries?.[0] || '')}</span>` : ''}
          ${r.notice_by === 'ia' ? `<span class="tag" title="${esc(t('ai_notice_hint'))}">✨ ${esc(t('ai_notice'))}</span>` : ''}
          ${langTags(r)}
          ${r.trending ? `<span class="tag">🔥 ${esc(t('trending'))}</span>` : ''}
          ${geoTag(r)}
        </div>
        <div class="text-xs text-txt-3 pt-2 border-t border-line font-mono truncate">${metaParts || '—'}</div>
        <div class="flex items-center gap-2 pt-1 flex-wrap">
          ${r.lat != null ? `<button type="button" class="btn-map" data-map-id="${esc(r.id)}">📍 ${esc(t('view_on_map'))}</button>` : ''}
          <a class="btn-open-ext" href="${esc(safeUrl(r.lien))}" target="_blank" rel="noopener">↗ ${esc(r.event ? t('official_site') : t('open'))}</a>
          ${r.cfp_url && r.cfp_url !== r.lien ? `<a class="btn-open-ext" href="${esc(safeUrl(r.cfp_url))}" target="_blank" rel="noopener">CFP</a>` : ''}
          ${r.journal?.author_instructions ? `<a class="btn-open-ext" href="${esc(safeUrl(r.journal.author_instructions))}" target="_blank" rel="noopener">${esc(t('author_guide'))}</a>` : ''}
        </div>
      </article>`;
  }
  function renderCatalogue(items) {
    $('results-count').textContent = items.length;
    const slice = items.slice(0, state.catShown);
    $('catalogue-grid').innerHTML = items.length
      ? slice.map(catalogueCard).join('') + (items.length > slice.length
        ? `<button type="button" class="btn-more col-span-full" id="cat-more-btn">${esc(tf('show_more', { n: Math.min(CAT_PAGE, items.length - slice.length), total: items.length - slice.length }))}</button>` : '')
      : `<div class="empty-state col-span-full">${esc(t('no_resource'))}</div>`;
    $('cat-more-btn')?.addEventListener('click', () => { state.catShown += CAT_PAGE; renderCatalogue(items); });
    // Liste latérale compacte (utile sur mobile)
    $('cards-container').innerHTML = items.length
      ? items.slice(0, 200).map((r) => `
        <a class="card block" href="${esc(safeUrl(r.lien))}" target="_blank" rel="noopener">
          <span class="src-pill ${SRC_CLASS[r.source] || 'src-general'}">${esc(t(r.categorie_key))}</span>
          <h3 class="text-[0.95rem] font-medium text-txt leading-snug line-clamp-2">${esc(r.nom)}</h3>
          <p class="text-sm text-txt-2 line-clamp-2">${esc(descOf(r))}</p>
        </a>`).join('')
      : `<div class="empty-state">${esc(t('no_resource'))}</div>`;
  }

  /* ═══════════════ Bandeaux : cette semaine · échéances imminentes · nouveautés ═══════════════ */
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
        <span class="banner-dot" style="background:${n.type === 'Opportunity' ? OPP_COLOR[n.opp_kind] : TYPE_COLOR[n.type] || '#8B5CF6'}"></span>
        <span class="min-w-0 flex-1">
          <span class="banner-title">${esc(n.title)}</span>
          <span class="banner-meta">${meta}</span>
        </span>
      </button>`;
    const block = (icon, title, list, emptyKey, render, open) => `
      <details class="banner-block" ${list.length && open ? 'open' : ''}>
        <summary><span>${icon} ${esc(t(title))}</span><span class="banner-count">${list.length}</span></summary>
        <div class="banner-list">${list.length ? list.slice(0, 8).map(render).join('') : `<p class="text-xs text-txt-3 py-2 text-center">${esc(t(emptyKey))}</p>`}</div>
      </details>`;
    const weekHtml = block('📅', 'banner_week', thisWeek, 'no_week',
      (n) => item(n, `${esc(fmtDate(n.date))}${n.date_end && n.date_end !== n.date ? ' → ' + esc(fmtDate(n.date_end)) : ''} · ${esc(n.location || n.city || '')}`), true);
    const dlHtml = block('⏰', 'banner_deadlines', imminent, 'no_deadline', (d) => {
      const c = countdown(d.date);
      return item({ ...d, type: 'Event' }, `<b class="dl-inline ${c.cls}">${esc(c.label)}</b> ${esc(t(d.which))} · ${esc(fmtDate(d.date))}${d.place ? ' · ' + esc(d.place) : ''}`);
    }, true);
    const newHtml = block('🆕', state.tab === 'opps' ? 'banner_new_opps' : 'banner_latest', freshAll, 'no_latest',
      (n) => item(n, `${esc(srcName(n.source))}${n.location || n.city ? ' · ' + esc(n.location || n.city) : ''}`), state.tab !== 'catalogue');
    box.innerHTML = dlHtml + weekHtml + (state.tab === 'catalogue' ? '' : newHtml);
  }

  function renderLegend() {
    const typeRows = TYPES.map((ty) => `
      <li class="flex items-center gap-3"><span class="w-3.5 h-3.5 rounded-full flex-shrink-0" style="background:${TYPE_COLOR[ty]}"></span>
      <span class="text-txt-2">${esc(t('type_' + ty))}</span></li>`).join('');
    $('legend-list').innerHTML = typeRows + `
      <li class="flex items-center gap-3"><span class="w-3.5 h-3.5 flex-shrink-0 bg-[#0D9488]" style="transform:rotate(45deg);border-radius:2px"></span>
      <span class="text-txt-2">${esc(t('legend_opps'))}</span></li>
      <li class="flex items-center gap-3"><span class="w-3.5 h-3.5 rounded-full flex-shrink-0 bg-txt-3" style="box-shadow:0 0 0 2px #0EA5E9"></span>
      <span class="text-txt-2">${esc(t('legend_focus'))}</span></li>
      <li class="flex items-center gap-3"><span class="w-3.5 h-3.5 flex-shrink-0 bg-txt-3" style="border-radius:3px"></span>
      <span class="text-txt-2">${esc(t('legend_catalogue'))}</span></li>
      <li class="flex items-center gap-3"><span class="w-3.5 h-3.5 rounded-full flex-shrink-0" style="border:2px dashed #0EA5E9"></span>
      <span class="text-txt-2">${esc(t('web_result'))}</span></li>`;
  }
  function renderAgentStatus() {
    const s = state.agent.sources || {};
    const rows = Object.entries(s).map(([k, v]) => `
      <li class="agent-row"><span>${esc(srcName(k))}</span>
        <span class="${v.ok ? 'agent-ok' : 'agent-ko'}" title="${esc(v.error || '')}">${v.ok ? `✓ +${v.new ?? 0}` : '✗ ' + esc(t('agent_error'))}</span></li>`);
    $('agent-status').innerHTML = rows.join('') || `<li class="text-txt-3">—</li>`;
    const allOk = Object.values(s).every((v) => v.ok);
    $('agent-dot').className = `w-2 h-2 rounded-full ${allOk ? 'bg-emerald-500 animate-pulse' : 'bg-amber-500'}`;
  }
  function updateHeader(iso) {
    const d = new Date(iso);
    $('last-updated-time').textContent = isNaN(d) ? '—'
      : d.toLocaleString(locale(), { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
    $('new-today-num').textContent = state.stats.new_today ?? 0;
  }
  const showLoading = (on) => $('loading-overlay').classList.toggle('hidden', !on);
  function showError(msg) {
    const b = $('last-updated-badge');
    b.classList.remove('hidden'); b.classList.add('flex');
    b.style.cssText = 'background:rgba(239,68,68,.12);color:#DC2626;border-color:rgba(239,68,68,.4)';
    $('last-updated-time').textContent = msg;
    $('cards-container').innerHTML = `<div class="empty-state">${esc(msg)}</div>`;
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
    return found;
  }
  async function countryGeo(iso) {
    if (!iso) return null;
    if (!state.pays) { try { state.pays = await getJSON('data/pays.json'); } catch { state.pays = {}; } }
    const c = state.pays[String(iso).toUpperCase()];
    return c ? { lat: c.lat, lng: c.lng, region: state.lang === 'en' ? c.en : c.fr, city: state.lang === 'en' ? c.en : c.fr, geo_precision: 'pays' } : null;
  }
  async function normalizeWeb(raw, q) {
    const text = `${raw.title} ${raw.summary || ''} ${(raw.tags || []).join(' ')}`;
    const langs = detectLangs(text, raw.codes || []);
    let geo = null;
    if (langs.length) geo = { lat: langs[0].lat, lng: langs[0].lng, region: langs[0].region, city: langs[0].region, geo_precision: 'langue' };
    else if (raw.country) geo = await countryGeo(raw.country);
    return {
      ...raw, ...(geo || { lat: null, lng: null }), web: true, queries: [q], first_seen: state.today,
      date: (raw.date || '').slice(0, 10), summary: (raw.summary || '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 320),
      lang_codes: langs.map((l) => l.code), lang_groups: [...new Set(langs.map((l) => l.group))], focus: langs.length > 0,
    };
  }
  const WEB_SOURCES = {
    huggingface: async (q) => {
      const kinds = [['datasets', 'Corpus', 'https://huggingface.co/datasets/'], ['models', 'Model', 'https://huggingface.co/']];
      const res = await Promise.all(kinds.map(([k]) => getJSON(`https://huggingface.co/api/${k}?search=${encodeURIComponent(q)}&limit=20&sort=downloads&direction=-1`)));
      return res.flatMap((arr, i) => arr.map((e) => ({
        id: `hf:${kinds[i][0]}:${e.id}`, title: e.id, type: kinds[i][1], source: 'huggingface', url: kinds[i][2] + e.id,
        date: e.createdAt, author: e.author || e.id.split('/')[0], tags: e.tags || [],
        codes: (e.tags || []).filter((x) => x.startsWith('language:')).map((x) => x.split(':')[1]).concat(e.tags || []),
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
    q = q.trim();
    if (q.length < 2) return;
    state.web = { q, results: [], loading: true, errors: [] };
    if (location.hash !== '#q=' + encodeURIComponent(q)) history.replaceState(null, '', '#q=' + encodeURIComponent(q));
    if (state.tab !== 'veille') switchTab('veille', { keepWeb: true });
    if (!isDesktop()) { state.mobileView = 'notices'; applyMobileView(); }
    renderList(); renderBanners();
    const settled = await Promise.allSettled(Object.entries(WEB_SOURCES).map(async ([name, fn]) => {
      try { return await fn(q); } catch (e) { state.web.errors.push(srcName(name)); return []; }
    }));
    const known = new Set([...state.notices.map((n) => n.id), ...state.ressources.map((r) => r.id)]);
    const raw = settled.flatMap((s) => s.value || []);
    const seen = new Set();
    const results = [];
    for (const r of raw) {
      if (!r.title || seen.has(r.id)) continue;
      seen.add(r.id);
      const n = await normalizeWeb(r, q);
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
    if (results.some((r) => r.lat != null)) {
      const b = L.latLngBounds(results.filter((r) => r.lat != null).map((r) => [r._lat ?? r.lat, r._lng ?? r.lng]));
      map.flyToBounds(b.pad(0.3), { maxZoom: 6, duration: 1 });
    }
  }
  function followUrl(q) {
    const params = new URLSearchParams({ template: 'requete.yml', title: `Requête de veille : ${q}`, requete: q });
    return `https://github.com/${state.repo}/issues/new?${params}`;
  }
  function renderWebResults() {
    const w = state.web;
    const c = $('cards-container');
    $('results-count').textContent = w.results.length;
    const head = `
      <div class="web-head">
        <div class="flex items-start justify-between gap-2">
          <p class="text-sm text-txt"><b>${w.loading ? esc(t('web_loading')) : esc(tf('web_count', { n: w.results.length }))}</b> — « ${esc(w.q)} »</p>
          <button type="button" class="btn-ghost-sm" id="web-clear" aria-label="${esc(t('web_clear'))}">✕</button>
        </div>
        ${w.errors.length ? `<p class="text-xs text-txt-3 mt-1">${esc(tf('web_errors', { list: w.errors.join(', ') }))}</p>` : ''}
        ${!w.loading ? `<p class="text-xs text-txt-3 mt-1">${esc(t('web_saved_local'))}</p>
          <a class="btn-primary mt-2 inline-flex" href="${esc(followUrl(w.q))}" target="_blank" rel="noopener">🔔 ${esc(t('web_follow'))}</a>
          <p class="text-[0.7rem] text-txt-3 mt-1.5">${esc(t('web_follow_hint'))}</p>` : '<div class="spinner spinner-sm mt-2"></div>'}
      </div>`;
    const slice = w.results.slice(0, state.shown);
    c.innerHTML = head + slice.map((r) => noticeCard(r).replace('class="card"', `class="card${r.known ? ' card-known' : ''}"`)).join('') +
      (w.results.length > slice.length ? `<button type="button" class="btn-more" id="more-btn">${esc(tf('show_more', { n: Math.min(PAGE_SIZE, w.results.length - slice.length), total: w.results.length - slice.length }))}</button>` : '');
    $('more-btn')?.addEventListener('click', () => { state.shown += PAGE_SIZE; renderWebResults(); });
    $('web-clear')?.addEventListener('click', clearWeb);
  }
  function clearWeb() {
    state.web = null;
    $('web-q').value = '';
    if (location.hash.startsWith('#q=')) history.replaceState(null, '', '#veille');
    refreshAll();
  }
  /* Recherches gardées dans ce navigateur (10 dernières) → collection « Mes recherches » du catalogue */
  function loadLocalSearches() { try { return JSON.parse(store.get('connectal.web') || '[]'); } catch { return []; } }
  function saveLocalSearch(q, results) {
    const keep = results.slice(0, 60).map(({ _lat, _lng, known, ...r }) => r);
    const all = [{ q, date: state.today, results: keep }, ...loadLocalSearches().filter((s) => s.q !== q)].slice(0, 10);
    store.set('connectal.web', JSON.stringify(all));
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
    const list = loadLocalSearches();
    $('web-history').innerHTML = list.map((s) => `<button type="button" class="chip-btn" data-web-q="${esc(s.q)}">🔎 ${esc(s.q)}</button>`).join('')
      + state.requetes.map((r) => `<button type="button" class="chip-btn chip-btn-tracked" data-web-q="${esc(r.q)}" title="${esc(t('tracked_query'))}">🔔 ${esc(r.q)}</button>`).join('');
  }

  /* ═══════════════ Navigation ═══════════════ */
  function switchTab(tab, { keepWeb = false } = {}) {
    state.tab = tab;
    if (!keepWeb && tab !== 'veille') state.web = null;
    document.querySelectorAll('.tab-btn').forEach((b) => {
      const on = b.dataset.tab === tab;
      b.classList.toggle('tab-active', on);
      b.setAttribute('aria-selected', String(on));
    });
    const withMap = tab !== 'catalogue';
    $('map').classList.toggle('hidden', !withMap);
    $('map-legend-mini').classList.toggle('hidden', !withMap);
    $('catalogue-view').classList.toggle('hidden', withMap);
    $('filters-veille').classList.toggle('hidden', tab !== 'veille');
    $('filters-catalogue').classList.toggle('hidden', tab !== 'catalogue');
    $('filters-opps').classList.toggle('hidden', tab !== 'opps');
    $('web-search-form').classList.toggle('hidden', tab === 'opps');
    // Sur grand écran, la grille suffit : la liste latérale ne sert qu'en veille / opportunités (et sur mobile)
    $('cards-container').classList.toggle('lg:hidden', tab === 'catalogue');
    const lbl = document.querySelector('#mobile-nav [data-mobile-view="map"] .mobile-nav-label');
    lbl.dataset.i18n = withMap ? 'view_map' : 'view_grid';
    lbl.textContent = t(lbl.dataset.i18n);
    if (!keepWeb && location.hash !== '#' + tab) history.replaceState(null, '', '#' + tab);
    if (tab === 'catalogue') ensureCatalogue();
    state.mobileView = 'map';
    applyMobileView();
    refreshAll();
    if (withMap && map) setTimeout(() => map.invalidateSize(), 100);
  }
  function applyMobileView() {
    const panels = { notices: $('notices-panel'), filters: $('filters-panel'), map: $('main-content') };
    if (isDesktop()) {
      Object.values(panels).forEach((p) => { p.style.display = ''; });
    } else {
      Object.entries(panels).forEach(([k, p]) => {
        p.style.display = state.mobileView === k ? (k === 'map' ? 'block' : 'flex') : 'none';
      });
    }
    document.querySelectorAll('#mobile-nav .mobile-nav-btn').forEach((b) => {
      const on = b.dataset.mobileView === state.mobileView;
      b.classList.toggle('mobile-nav-active', on);
      b.setAttribute('aria-current', on ? 'page' : 'false');
    });
    if (state.mobileView === 'map' && map) setTimeout(() => map.invalidateSize(), 100);
  }

  /* ═══════════════ Démarrage ═══════════════ */
  document.addEventListener('DOMContentLoaded', async () => {
    await loadStatic();
    const stored = store.get('lang');
    const nav = (navigator.language || 'fr').slice(0, 2);
    state.lang = state.i18n[stored] ? stored : (state.i18n[nav] ? nav : 'fr');
    document.querySelectorAll('.lang-btn').forEach((b) => b.addEventListener('click', () => setLanguage(b.dataset.lang)));
    $('theme-toggle').setAttribute('aria-pressed', String(isDark()));
    $('theme-toggle').addEventListener('click', () => setTheme(isDark() ? 'light' : 'dark'));
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener?.('change', (e) => {
      if (!store.get('theme')) setTheme(e.matches ? 'dark' : 'light');
    });

    initMap();
    setLanguage(state.lang);

    // Délégation d'événements (une seule écoute pour toutes les cartes)
    document.body.addEventListener('click', (e) => {
      const mapBtn = e.target.closest('[data-map-id]');
      if (mapBtn) { e.preventDefault(); viewOnMap(mapBtn.dataset.mapId); return; }
      const hist = e.target.closest('[data-web-q]');
      if (hist) { $('web-q').value = hist.dataset.webQ; webSearch(hist.dataset.webQ); return; }
      const banner = e.target.closest('[data-banner-id]');
      if (banner) {
        const id = banner.dataset.bannerId;
        const n = [...state.notices, ...state.opps, ...state.ressources].find((x) => x.id === id);
        if (n?.lat != null) viewOnMap(n.id); else window.open(banner.dataset.url, '_blank', 'noopener');
        return;
      }
      const card = e.target.closest('article.card[data-id], article.card[data-opp-id]');
      if (card && !e.target.closest('a')) {
        const id = card.dataset.id || card.dataset.oppId;
        const n = [...state.notices, ...state.opps, ...(state.web?.results || [])].find((x) => x.id === id);
        if (n?.lat != null) viewOnMap(n.id); else if (n) window.open(safeUrl(n.url), '_blank', 'noopener');
      }
    });
    document.body.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && e.target.matches('article.card[data-id], article.card[data-opp-id]')) e.target.click();
    });
    $('web-search-form').addEventListener('submit', (e) => { e.preventDefault(); webSearch($('web-q').value); });

    document.querySelectorAll('.tab-btn').forEach((b) => b.addEventListener('click', () => switchTab(b.dataset.tab)));
    document.querySelectorAll('#mobile-nav .mobile-nav-btn').forEach((b) => b.addEventListener('click', () => {
      state.mobileView = b.dataset.mobileView; applyMobileView();
    }));
    document.querySelectorAll('#period-filter [data-period]').forEach((b) => b.addEventListener('click', () => setPeriod(+b.dataset.period)));
    $('search-input').addEventListener('input', debounce(refreshAll, 220));
    ['vsource-filter', 'type-filter', 'region-filter', 'langgroup-filter', 'lang-filter', 'query-filter', 'catalogue-layer',
     'source-filter', 'cat-filter', 'langue-filter', 'oa-filter', 'cat-sort', 'deadline-filter',
     'opp-kind', 'opp-region', 'opp-source', 'opp-remote']
      .forEach((id) => $(id).addEventListener('change', refreshAll));
    $('reset-filters').addEventListener('click', resetFilters);
    window.addEventListener('resize', debounce(applyMobileView, 150));

    await loadData();
    const h = location.hash;
    if (h.startsWith('#q=')) {
      switchTab('veille', { keepWeb: true });
      const q = decodeURIComponent(h.slice(3));
      $('web-q').value = q;
      webSearch(q);
    } else {
      switchTab(['#catalogue', '#opps'].includes(h) ? h.slice(1) : 'veille');
    }

    // Rafraîchissement silencieux toutes les 30 min si l'onglet est visible
    setInterval(() => { if (document.visibilityState === 'visible' && !state.web) loadData({ silent: true }); }, 30 * 60 * 1000);
  });
})();
