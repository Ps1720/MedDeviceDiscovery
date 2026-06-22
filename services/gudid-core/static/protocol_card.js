/*
 * Shared perioperative protocol panel renderer.
 *
 * Used by scan_to_chart.html (scan result) and timeline.html (full-page
 * protocol view). Expects the timeline CSS variables (--ink, --coral,
 * --honey, …) to be defined on the page. No build step: plain script,
 * exposes window.renderProtocolPanel(container, protocol, deviceIdentifier).
 *
 * Two switchable layouts (preference persisted in localStorage):
 *   split    — sticky left rail with key info (class, context, headline,
 *              support line) + detail column right; collapses to a single
 *              column below the lg breakpoint
 *   document — single-column editorial document
 *
 * Context switching re-fetches /api/protocol/by-di/<di>?context=… and
 * re-renders the panel (checklist ticks are client-side only and reset).
 */

(function () {
  'use strict';

  const esc = s => (s == null ? '' : String(s).replace(/[&<>"]/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])));

  const LAYOUT_KEY = 'periop-protocol-layout';
  function getLayout() {
    try { return localStorage.getItem(LAYOUT_KEY) || 'split'; } catch (e) { return 'split'; }
  }
  function setLayout(v) {
    try { localStorage.setItem(LAYOUT_KEY, v); } catch (e) { /* private mode */ }
  }

  const CONTEXT_LABELS = { surgery: 'Surgery', mri: 'MRI', ep_study: 'EP study' };

  const MODULE_LABELS = {
    cardiac_rhythm: 'Cardiac rhythm',
    neuromodulation: 'Neuromodulation',
    diabetes: 'Diabetes technology',
  };

  const MODULE_COLOR = {
    cardiac_rhythm: '#9B2F47',
    neuromodulation: '#553B91',
    diabetes: '#4A6B24',
  };

  const SOURCE_LABEL = {
    institution_override: { label: 'Institution', color: 'var(--honey-deep)' },
    brand_fact:           { label: 'Brand',       color: 'var(--slate-deep)' },
    class_protocol:       { label: 'Guideline',   color: 'var(--primary)' },
    gudid:                { label: 'GUDID',       color: 'var(--ink-4)' },
  };

  const SEVERITY_COLOR = {
    critical: 'var(--coral)',
    caution: 'var(--honey)',
  };

  const FACT_LABELS = {
    magnet_behavior: 'Magnet behavior',
    magnet_rate: 'Magnet rate',
    electrocautery: 'Electrocautery',
    mri: 'MRI compatibility',
    support_phone: '24-hr support line',
    nbg_semantics: 'NBG pacing code',
    pacer_dependence: 'Pacing dependence',
    mode_guidance: 'Pre-procedure mode',
    closed_loop_note: 'Closed-loop caution',
    closed_loop_algorithm: 'AID algorithm',
    cgm_interference: 'CGM interference',
  };

  // Render order: action-critical facts first, reference facts last.
  const FACT_ORDER = [
    'pacer_dependence', 'magnet_behavior', 'magnet_rate', 'electrocautery',
    'mode_guidance', 'closed_loop_note', 'cgm_interference', 'mri',
    'closed_loop_algorithm', 'nbg_semantics',
  ];

  const rule = '<div style="border-top:1px solid var(--rule);" class="mt-7"></div>';

  const sectionTitle = (t, first) =>
    `<h4 class="text-[11px] font-mono uppercase tracking-[0.16em] ${first ? 'pb-1' : 'pt-6 pb-1'}" style="color:var(--ink-4);">${esc(t)}</h4>`;

  function provenance(source) {
    const s = SOURCE_LABEL[source] || SOURCE_LABEL.gudid;
    return `<span class="text-[10px] font-semibold uppercase tracking-[0.08em]" style="color:${s.color};">${s.label}</span>`;
  }

  function severityDot(severity) {
    const c = SEVERITY_COLOR[severity];
    return c ? `<span class="inline-block w-[7px] h-[7px] rounded-full mr-2 align-middle" style="background:${c};"></span>` : '';
  }

  function citeLine(f) {
    if (!f.guideline_source && !f.citation) return '';
    const txt = [f.guideline_source, f.citation].filter(Boolean).join(' — ');
    return `<p class="text-[11px] mt-1.5" style="color:var(--ink-4);">${esc(txt)}</p>`;
  }

  function factRow(key, f) {
    const label = FACT_LABELS[key] || key.replace(/_/g, ' ');
    return `
      <div class="py-4 flex flex-col sm:flex-row gap-1.5 sm:gap-8" style="border-top:1px solid var(--rule-soft);">
        <div class="sm:w-44 shrink-0 sm:pt-0.5 flex sm:flex-col items-baseline sm:items-start gap-2 sm:gap-0.5">
          <span class="text-[11px] font-mono uppercase tracking-[0.1em]" style="color:var(--ink-3);">${esc(label)}</span>
          ${provenance(f.source)}
        </div>
        <div class="flex-1 min-w-0 max-w-[78ch]">
          <p class="text-[14px] leading-relaxed font-medium" style="color:var(--ink);">${severityDot(f.severity)}${esc(f.value)}</p>
          ${f.detail ? `<p class="text-[13px] leading-relaxed mt-1.5" style="color:var(--ink-3);">${esc(f.detail)}</p>` : ''}
          ${citeLine(f)}
        </div>
      </div>`;
  }

  function headlineHTML(actions, compact) {
    if (!actions || !actions.length) return '';
    const size = compact ? 'text-[16px]' : 'text-[18px] sm:text-[20px]';
    return actions.map(a => `
      <div class="mt-6" style="border-left:3px solid ${SEVERITY_COLOR[a.severity] || 'var(--honey)'};">
        <p class="pl-4 ${size} leading-snug font-semibold tracking-tight" style="color:var(--ink);">
          ${esc(a.value)}
        </p>
        ${a.guideline_source ? `<p class="pl-4 text-[11px] mt-1.5" style="color:var(--ink-4);">${esc(a.guideline_source)}</p>` : ''}
      </div>`).join('');
  }

  function supportHTML(f, stacked) {
    if (!f) return '';
    const phoneable = /\d/.test(f.value || '');
    const value = phoneable
      ? `<a href="tel:${esc(String(f.value).replace(/[^+\d]/g, ''))}" class="text-[16px] font-semibold tracking-tight hover:underline" style="color:var(--primary);">${esc(f.value)}</a>`
      : `<span class="text-[14px] font-medium" style="color:var(--ink);">${esc(f.value)}</span>`;
    if (stacked) {
      return `
        <div class="mt-6">
          <span class="block text-[11px] font-mono uppercase tracking-[0.1em]" style="color:var(--ink-3);">24-hr support</span>
          <span class="block mt-1">${value}</span>
          ${f.detail ? `<span class="block text-[12px] mt-0.5" style="color:var(--ink-4);">${esc(f.detail)}</span>` : ''}
        </div>`;
    }
    return `
      <div class="mt-5 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span class="text-[11px] font-mono uppercase tracking-[0.1em]" style="color:var(--ink-3);">24-hr support</span>
        ${value}
        ${f.detail ? `<span class="text-[12px]" style="color:var(--ink-4);">${esc(f.detail)}</span>` : ''}
        ${provenance(f.source)}
      </div>`;
  }

  function checklistHTML(items, first) {
    if (!items || !items.length) return '';
    const rows = items.map((it, i) => `
      <li class="flex gap-4 items-start py-3.5" style="border-top:1px solid var(--rule-soft);">
        <span class="font-mono text-[13px] w-5 text-right shrink-0 pt-0.5" style="color:var(--ink-4);">${i + 1}</span>
        <input type="checkbox" id="pc-chk-${i}" class="mt-1 shrink-0" style="width:16px;height:16px;accent-color:var(--primary);"
               onchange="this.closest('li').style.opacity = this.checked ? 0.45 : 1">
        <label for="pc-chk-${i}" class="cursor-pointer min-w-0 max-w-[78ch]">
          <span class="block text-[14px] leading-relaxed" style="color:var(--ink);">${esc(it.text)}</span>
          ${it.rationale ? `<span class="block text-[12.5px] leading-relaxed mt-1" style="color:var(--ink-3);">${esc(it.rationale)}</span>` : ''}
          ${it.guideline_source || it.citation ? `<span class="block text-[11px] mt-1" style="color:var(--ink-4);">${esc([it.guideline_source, it.citation].filter(Boolean).join(' — '))}</span>` : ''}
        </label>
      </li>`).join('');
    return `${sectionTitle('What to do right now', first)}<ul>${rows}</ul>`;
  }

  function overridesHTML(applied) {
    if (!applied || !applied.length) return '';
    return sectionTitle('Institutional policy') + applied.map(o => `
      <div class="mt-2" style="border-left:3px solid var(--honey);">
        <div class="pl-4">
          ${o.supersedes_manufacturer_labeling
            ? `<p class="text-[11px] font-semibold uppercase tracking-[0.08em]" style="color:var(--honey-deep);">Supersedes manufacturer labeling</p>`
            : ''}
          <p class="text-[14px] leading-relaxed mt-1" style="color:var(--ink);">${esc(o.annotation || '')}</p>
          <p class="text-[11px] mt-1.5" style="color:var(--ink-4);">${esc(o.author || '')}${o.effective_date ? ' · effective ' + esc(o.effective_date) : ''}</p>
        </div>
      </div>`).join('');
  }

  function contextTabs(p) {
    return (p.available_contexts || []).map(c => {
      const active = c === p.context;
      return `
        <button data-ctx="${esc(c)}" class="pc-ctx pb-1.5 text-[13px] font-semibold transition"
          style="color:${active ? 'var(--ink)' : 'var(--ink-4)'};border-bottom:2px solid ${active ? 'var(--primary)' : 'transparent'};">
          ${esc(CONTEXT_LABELS[c] || c)}
        </button>`;
    }).join('<span class="w-5"></span>');
  }

  function layoutToggle(layout) {
    const btn = (val, label) => `
      <button data-layout="${val}" class="pc-layout px-2.5 py-1 text-[11px] font-semibold rounded-md transition"
        style="${layout === val ? 'background:var(--surface);color:var(--ink);box-shadow:0 1px 2px rgba(20,28,45,0.08);' : 'color:var(--ink-4);'}">
        ${label}
      </button>`;
    // Split has no effect below lg, so hide the toggle there.
    return `
      <div class="hidden lg:inline-flex items-center gap-0.5 p-0.5 rounded-lg" style="background:var(--surface-cool);" title="Panel layout">
        ${btn('split', '◫ Split')}${btn('document', '▤ Document')}
      </div>`;
  }

  function unverifiedHTML(p) {
    const unverified = Object.values(p.facts || {}).some(f => f.requires_verification) ||
      (p.checklist || []).some(it => it.requires_verification);
    if (!unverified) return '';
    return `
      <p class="text-[12px] mt-4 flex items-start gap-2" style="color:var(--coral-deep);">
        <span class="inline-block w-[7px] h-[7px] rounded-full mt-[5px] shrink-0" style="background:var(--coral);"></span>
        <span>Unverified content — seeded guidance pending clinician review. Confirm against the cited guideline and manufacturer labeling before acting.</span>
      </p>`;
  }

  function identityHTML(p) {
    const modColor = MODULE_COLOR[p.module] || 'var(--ink-3)';
    const overrideFlag = (p.overrides_applied || []).length
      ? `<span class="text-[11px] font-semibold uppercase tracking-[0.08em] px-2 py-0.5 rounded-md" style="background:var(--honey-soft);color:var(--honey-deep);">Institutional override active</span>`
      : '';
    return { modColor, overrideFlag };
  }

  function factsHTML(p) {
    const facts = FACT_ORDER
      .filter(k => p.facts && p.facts[k])
      .map(k => factRow(k, p.facts[k]));
    Object.keys(p.facts || {}).forEach(k => {
      if (!FACT_ORDER.includes(k) && k !== 'support_phone') facts.push(factRow(k, p.facts[k]));
    });
    return facts.join('');
  }

  const disclaimerHTML = p => `
    <p class="text-[11px] mt-8 pt-4" style="color:var(--ink-4);border-top:1px solid var(--rule);">
      ${esc(p.disclaimer || '')}
    </p>`;

  // ---- Layout: single-column editorial document ----
  // Deliberately centered at a reading width — prose wider than ~80ch is hard
  // to scan; use the Split layout to fill the whole screen.
  function documentHTML(p) {
    const { modColor, overrideFlag } = identityHTML(p);
    return `
      <div class="max-w-4xl mx-auto">
        <div class="flex items-end justify-between gap-4 flex-wrap pb-4" style="border-bottom:1px solid var(--rule);">
          <div>
            <p class="text-[11px] font-mono uppercase tracking-[0.16em]" style="color:${modColor};">
              ${esc(MODULE_LABELS[p.module] || p.module)}
            </p>
            <div class="flex items-baseline gap-3 flex-wrap mt-1">
              <h3 class="text-[17px] font-semibold tracking-tight" style="color:var(--ink);">${esc(p.class_display)}</h3>
              <span class="text-[11px]" style="color:var(--ink-4);">${esc(p.resolution.confidence)}-confidence match</span>
              ${overrideFlag}
            </div>
          </div>
          <div class="flex items-center gap-5">
            <div class="flex">${contextTabs(p)}</div>
            ${layoutToggle('document')}
          </div>
        </div>

        ${unverifiedHTML(p)}
        ${headlineHTML(p.headline_actions)}
        ${supportHTML((p.facts || {}).support_phone)}

        ${rule}
        ${checklistHTML(p.checklist)}

        ${rule}
        ${sectionTitle('Device facts')}
        <div>${factsHTML(p)}</div>

        ${(p.overrides_applied || []).length ? rule + overridesHTML(p.overrides_applied) : ''}
        ${disclaimerHTML(p)}
      </div>`;
  }

  // ---- Layout: sticky key-info rail left, detail column right ----
  function splitHTML(p) {
    const { modColor, overrideFlag } = identityHTML(p);
    return `
      <div class="grid grid-cols-1 lg:grid-cols-[300px_1fr] xl:grid-cols-[340px_1fr] lg:gap-x-12 xl:gap-x-16 gap-y-8">

        <aside class="lg:sticky lg:top-24 self-start min-w-0">
          <div class="flex items-start justify-between gap-3">
            <p class="text-[11px] font-mono uppercase tracking-[0.16em]" style="color:${modColor};">
              ${esc(MODULE_LABELS[p.module] || p.module)}
            </p>
            ${layoutToggle('split')}
          </div>
          <h3 class="text-[20px] font-semibold tracking-tight mt-1.5 leading-snug" style="color:var(--ink);">${esc(p.class_display)}</h3>
          <p class="text-[11px] mt-1" style="color:var(--ink-4);">${esc(p.resolution.confidence)}-confidence match</p>
          ${overrideFlag ? `<div class="mt-2.5">${overrideFlag}</div>` : ''}

          <div class="flex mt-5 pb-1" style="border-bottom:1px solid var(--rule);">${contextTabs(p)}</div>

          ${headlineHTML(p.headline_actions, true)}
          ${supportHTML((p.facts || {}).support_phone, true)}
          ${unverifiedHTML(p)}
        </aside>

        <div class="min-w-0">
          ${checklistHTML(p.checklist, true)}

          ${rule}
          ${sectionTitle('Device facts')}
          <div>${factsHTML(p)}</div>

          ${(p.overrides_applied || []).length ? rule + overridesHTML(p.overrides_applied) : ''}
          ${disclaimerHTML(p)}
        </div>
      </div>`;
  }

  async function switchContext(container, di, context) {
    try {
      const res = await fetch(`/api/protocol/by-di/${encodeURIComponent(di)}?context=${encodeURIComponent(context)}`);
      const data = await res.json();
      if (data.found && data.protocol) {
        renderProtocolPanel(container, data.protocol, di);
      }
    } catch (e) {
      console.error('protocol context switch failed', e);
    }
  }

  function renderProtocolPanel(container, protocol, deviceIdentifier) {
    if (!container || !protocol) return;
    const layout = getLayout();
    container.innerHTML = layout === 'document' ? documentHTML(protocol) : splitHTML(protocol);
    container.querySelectorAll('.pc-ctx').forEach(btn => {
      btn.addEventListener('click', () => {
        if (btn.dataset.ctx !== protocol.context && deviceIdentifier) {
          switchContext(container, deviceIdentifier, btn.dataset.ctx);
        }
      });
    });
    container.querySelectorAll('.pc-layout').forEach(btn => {
      btn.addEventListener('click', () => {
        if (btn.dataset.layout !== layout) {
          setLayout(btn.dataset.layout);
          renderProtocolPanel(container, protocol, deviceIdentifier);
        }
      });
    });
  }

  window.renderProtocolPanel = renderProtocolPanel;
})();
