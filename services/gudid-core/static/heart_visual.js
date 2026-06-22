/*
 * Interactive 3D heart visual for cardiac rhythm devices (Three.js r128).
 *
 * Renders a STYLIZED, procedurally built heart (no patient imaging) with the
 * documented device drawn at its implant location, a beating animation, an
 * ECG-style strip, and an interactive magnet simulation whose behavior is
 * driven by the protocol knowledge base:
 *
 *   pacemaker / crt_p      -> asynchronous pacing at the brand magnet rate
 *   icd / crt_d            -> tachy therapy suspended, pacing unchanged
 *   leadless_pacemaker     -> no magnet response
 *
 * Honest-labeling rules implemented here:
 *  - "Location confirmed by clinician" vs "Typical placement — not confirmed"
 *  - magnet rate carries its knowledge-base verification status; when absent
 *    a generic 90 bpm is used and explicitly labeled illustrative
 *  - standing "Stylized anatomy — illustrative only" line + protocol disclaimer
 *
 * Loaded lazily by timeline.html AFTER three.min.js + OrbitControls (classic
 * builds). Exposes window.initHeartVisual(container, opts) -> { dispose }.
 * opts: { protocol, implant, deviceName, manufacturer, fhirId, onLocationSaved }
 */

(function () {
  'use strict';

  var esc = function (s) {
    return s == null ? '' : String(s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  };

  var BEHAVIOR = {
    pacemaker: 'async',
    crt_p: 'async',
    icd: 'suspend',
    crt_d: 'suspend',
    leadless_pacemaker: 'none',
  };

  var BEHAVIOR_BADGE = {
    async: { text: 'ASYNCHRONOUS PACING', bg: 'var(--honey-soft)', fg: 'var(--honey-deep)' },
    suspend: { text: 'TACHY THERAPY SUSPENDED — PACING UNCHANGED', bg: 'var(--coral-soft)', fg: 'var(--coral-deep)' },
    none: { text: 'NO MAGNET RESPONSE — REPROGRAMMING REQUIRED', bg: 'var(--slate-soft)', fg: 'var(--slate-deep)' },
  };

  var BASE_RATE = 60; // illustrative sensed rhythm
  var GENERIC_MAGNET_RATE = 90;

  // ---------------------------------------------------------------------
  // Anatomy anchors (viewer coordinates: +x = viewer right = patient LEFT)
  // ---------------------------------------------------------------------
  function anchors(pocketSide) {
    var V = THREE.Vector3;
    var px = pocketSide === 'right' ? -1 : 1; // left pectoral pocket = viewer right
    return {
      ra: new V(-1.05, 0.45, 0.35),
      ra_tip: new V(-1.0, 0.35, 0.55),
      rv: new V(-0.35, -0.55, 0.45),
      rv_apex: new V(-0.15, -1.05, 0.6),
      la: new V(0.85, 0.75, -0.45),
      lv: new V(0.8, -0.45, -0.15),
      lv_lateral: new V(1.25, -0.35, -0.25),
      svc_entry: new V(-0.95, 1.45, 0.15),
      can: new V(2.5 * px, 2.1, 0.35),
      sicd_can: new V(3.0 * px, -0.4, 0.3),
      sicd_mid: new V(0.9 * px, -1.1, 0.95),
      sicd_tip: new V(0.05, 0.9, 1.0),
      magnet_rest: new V(3.4, 2.7, 1.0),
    };
  }

  // lead_config -> list of leads, each a list of anchor names (can -> tip)
  var LEAD_ROUTES = {
    ra_rv: [
      ['can', 'svc_entry', 'ra_tip'],
      ['can', 'svc_entry', 'ra', 'rv_apex'],
    ],
    rv_only: [['can', 'svc_entry', 'ra', 'rv_apex']],
    ra_only: [['can', 'svc_entry', 'ra_tip']],
    ra_rv_lv: [
      ['can', 'svc_entry', 'ra_tip'],
      ['can', 'svc_entry', 'ra', 'rv_apex'],
      ['can', 'svc_entry', 'ra', 'lv_lateral'],
    ],
    subcutaneous: [['sicd_can', 'sicd_mid', 'sicd_tip']],
    leadless_rv: [], // capsule only, no leads
  };

  // Which chamber meshes pulse-flash when paced, per lead tip anchor.
  var TIP_CHAMBER = { ra_tip: 'ra', rv_apex: 'rv', lv_lateral: 'lv', sicd_tip: null };

  function parseMagnetRate(protocol) {
    var fact = protocol && protocol.facts && protocol.facts.magnet_rate;
    if (!fact || !fact.value) return null;
    var m = String(fact.value).match(/([\d.]+)\s*bpm/i);
    if (!m) return null;
    return { bpm: parseFloat(m[1]), verified: !fact.requires_verification, source: fact.source };
  }

  function webglAvailable() {
    try {
      var c = document.createElement('canvas');
      return !!(window.WebGLRenderingContext &&
        (c.getContext('webgl') || c.getContext('experimental-webgl')));
    } catch (e) {
      return false;
    }
  }

  // ---------------------------------------------------------------------
  // Scene construction
  // ---------------------------------------------------------------------
  function makeLabel(text) {
    var canvas = document.createElement('canvas');
    canvas.width = 128;
    canvas.height = 64;
    var ctx = canvas.getContext('2d');
    ctx.font = '600 34px "DM Sans", sans-serif';
    ctx.fillStyle = 'rgba(27,34,48,0.85)';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(text, 64, 32);
    var tex = new THREE.CanvasTexture(canvas);
    var sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false }));
    sprite.scale.set(0.9, 0.45, 1);
    return sprite;
  }

  function chamberMesh(pos, radius, squash, color) {
    var geo = new THREE.SphereGeometry(radius, 36, 28);
    // Slightly translucent so leads and electrodes ghost through the wall —
    // the implant location is the whole point of the visual.
    var mat = new THREE.MeshPhongMaterial({
      color: color, shininess: 18, transparent: true, opacity: 0.82, depthWrite: false,
    });
    var mesh = new THREE.Mesh(geo, mat);
    mesh.renderOrder = 1;
    mesh.position.copy(pos);
    mesh.scale.set(squash.x, squash.y, squash.z);
    mesh.userData.baseScale = squash;
    return mesh;
  }

  function tubeBetween(points, radius, color) {
    var curve = new THREE.CatmullRomCurve3(points);
    var geo = new THREE.TubeGeometry(curve, 48, radius, 10, false);
    return new THREE.Mesh(geo, new THREE.MeshPhongMaterial({ color: color, shininess: 30 }));
  }

  function buildHeart(group) {
    var A = anchors('left');
    var chambers = {
      ra: chamberMesh(A.ra, 0.78, { x: 0.92, y: 1.0, z: 0.9 }, 0xc97b8b),
      rv: chamberMesh(A.rv, 1.0, { x: 0.95, y: 1.15, z: 0.95 }, 0xb95f74),
      la: chamberMesh(A.la, 0.7, { x: 0.95, y: 0.9, z: 0.9 }, 0xb487a6),
      lv: chamberMesh(A.lv, 1.12, { x: 0.95, y: 1.25, z: 1.0 }, 0xa14a5e),
    };
    Object.keys(chambers).forEach(function (k) { group.add(chambers[k]); });

    // Great-vessel stubs for recognizability (stylized).
    var aorta = tubeBetween([
      new THREE.Vector3(0.15, 0.9, -0.1),
      new THREE.Vector3(0.05, 1.8, -0.15),
      new THREE.Vector3(0.7, 2.2, -0.3),
      new THREE.Vector3(1.25, 1.85, -0.4),
    ], 0.3, 0xc9a0a8);
    var svc = tubeBetween([
      new THREE.Vector3(-0.95, 2.0, 0.1),
      new THREE.Vector3(-0.97, 1.45, 0.15),
      new THREE.Vector3(-1.0, 0.9, 0.25),
    ], 0.24, 0x9c91b5);
    group.add(aorta, svc);

    // Labels
    var labels = { ra: 'RA', rv: 'RV', la: 'LA', lv: 'LV' };
    Object.keys(labels).forEach(function (k) {
      var s = makeLabel(labels[k]);
      s.position.copy(chambers[k].position);
      s.position.z += 1.25;
      group.add(s);
    });

    return chambers;
  }

  function buildHardware(group, leadConfig, pocketSide) {
    var A = anchors(pocketSide);
    var hw = { meshes: [], tips: [], can: null };

    function add(mesh) { group.add(mesh); hw.meshes.push(mesh); return mesh; }

    if (leadConfig === 'leadless_rv') {
      var capsule = new THREE.Mesh(
        new THREE.CylinderGeometry(0.17, 0.17, 0.62, 16),
        new THREE.MeshPhongMaterial({ color: 0x59616f, shininess: 90 })
      );
      // Sit proud of the RV anterior wall so the capsule reads as "in the RV"
      // on the stylized surface (chambers are opaque).
      var capsulePos = A.rv_apex.clone().add(new THREE.Vector3(0.05, 0.35, 0.72));
      capsule.position.copy(capsulePos);
      capsule.rotation.z = 0.35;
      add(capsule);
      hw.can = capsule;
      hw.tips.push({ anchor: 'rv_apex', pos: capsulePos.clone() });
      return hw;
    }

    var canPos = leadConfig === 'subcutaneous' ? A.sicd_can : A.can;
    var can = new THREE.Mesh(
      new THREE.BoxGeometry(0.85, 1.0, 0.28),
      new THREE.MeshPhongMaterial({ color: 0x97a1b2, shininess: 90 })
    );
    // Rounded look: scale a sphere behind it is overkill; bevel illusion via slight rotation.
    can.position.copy(canPos);
    can.rotation.z = canPos.x > 0 ? -0.18 : 0.18;
    add(can);
    hw.can = can;

    (LEAD_ROUTES[leadConfig] || []).forEach(function (route) {
      var pts = route.map(function (name) { return A[name].clone(); });
      pts[0] = can.position.clone(); // start at the can
      var lead = tubeBetween(pts, 0.075, 0x4a5160);
      add(lead);
      var tipName = route[route.length - 1];
      var tipPos = A[tipName].clone();
      var electrode = new THREE.Mesh(
        new THREE.SphereGeometry(0.1, 16, 12),
        new THREE.MeshPhongMaterial({ color: 0xe3e7ee, shininess: 100 })
      );
      electrode.position.copy(tipPos);
      add(electrode);
      hw.tips.push({ anchor: tipName, pos: tipPos });
    });

    return hw;
  }

  function buildMagnet(group) {
    var magnet = new THREE.Group();
    var ring = new THREE.Mesh(
      new THREE.TorusGeometry(0.5, 0.17, 14, 36),
      new THREE.MeshPhongMaterial({ color: 0x3a4150, shininess: 50 })
    );
    var stripe = new THREE.Mesh(
      new THREE.TorusGeometry(0.5, 0.175, 14, 36, Math.PI * 0.6),
      new THREE.MeshPhongMaterial({ color: 0xd86a4a, shininess: 50 })
    );
    magnet.add(ring, stripe);
    magnet.position.copy(anchors('left').magnet_rest);
    magnet.visible = false;
    group.add(magnet);
    return magnet;
  }

  // ---------------------------------------------------------------------
  // ECG strip (2D canvas)
  // ---------------------------------------------------------------------
  function EcgStrip(canvas) {
    var ctx = canvas.getContext('2d');
    var pxPerSec = 110;

    function wave(mode, rate, t) {
      // value in [-1, 1] at time t for a rhythm at `rate` bpm
      var period = 60 / rate;
      var ph = ((t % period) + period) % period;
      var v = 0;
      function bump(center, width, amp) {
        var d = (ph - center) / width;
        return amp * Math.exp(-d * d);
      }
      if (mode === 'async') {
        // pacing spike + wide QRS, no P wave
        if (ph > 0.0 && ph < 0.02) v += 1.6;              // spike
        v += bump(0.10, 0.045, 0.9) - bump(0.17, 0.05, 0.32); // wide QRS
        v += bump(0.38, 0.09, 0.25);                       // T
      } else {
        v += bump(0.10, 0.025, 0.18);                      // P
        v += bump(0.22, 0.012, 1.0) - bump(0.245, 0.014, 0.42); // QRS
        v += bump(0.45, 0.07, 0.28);                       // T
      }
      return v;
    }

    return {
      draw: function (mode, rate, now) {
        var w = canvas.width, h = canvas.height, mid = h * 0.62;
        ctx.clearRect(0, 0, w, h);
        // grid
        ctx.strokeStyle = 'rgba(107,61,92,0.10)';
        ctx.lineWidth = 1;
        for (var gx = 0; gx < w; gx += 22) {
          ctx.beginPath(); ctx.moveTo(gx, 0); ctx.lineTo(gx, h); ctx.stroke();
        }
        for (var gy = 0; gy < h; gy += 22) {
          ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(w, gy); ctx.stroke();
        }
        // trace
        ctx.strokeStyle = '#6B3D5C';
        ctx.lineWidth = 1.8;
        ctx.beginPath();
        for (var x = 0; x < w; x++) {
          var t = now - (w - x) / pxPerSec;
          var v = wave(mode === 'suspend' || mode === 'none' ? 'sensed' : mode, rate, t);
          var y = mid - v * h * 0.28;
          if (x === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.stroke();
      },
    };
  }

  // ---------------------------------------------------------------------
  // Main entry
  // ---------------------------------------------------------------------
  function initHeartVisual(container, opts) {
    opts = opts || {};
    var protocol = opts.protocol || null;
    var deviceClass = protocol ? protocol.device_class : null;

    if (!protocol || !deviceClass || !BEHAVIOR[deviceClass]) {
      container.innerHTML = '<p class="text-[14px]" style="color:var(--ink-4);">' +
        '3D view is available for cardiac rhythm devices once protocol data loads.</p>';
      return { dispose: function () { container.innerHTML = ''; } };
    }
    if (!webglAvailable()) {
      container.innerHTML = '<p class="text-[14px]" style="color:var(--ink-4);">' +
        '3D view requires WebGL, which this browser/device does not support.</p>';
      return { dispose: function () { container.innerHTML = ''; } };
    }

    var implantOptions = protocol.implant_options || null;
    var implant = opts.implant || null;

    function currentLeadConfig() {
      if (implant && implant.lead_config) return implant.lead_config;
      return implantOptions ? implantOptions.default_lead_config : 'ra_rv';
    }
    function currentPocketSide() {
      return (implant && implant.pocket_side) || 'left';
    }

    var magnetRate = parseMagnetRate(protocol);
    var behavior = BEHAVIOR[deviceClass];

    // ---- DOM scaffold -------------------------------------------------
    container.innerHTML = [
      '<div class="grid grid-cols-1 lg:grid-cols-[1fr_300px] gap-8">',
      '  <div class="min-w-0">',
      '    <div data-hv="canvas-wrap" class="rounded-2xl overflow-hidden relative" style="background:linear-gradient(180deg,#F4F2F5 0%,#ECEEF2 100%);border:1px solid var(--rule);height:480px;">',
      '      <div data-hv="badge" class="absolute top-3 left-3 z-10 hidden px-2.5 py-1 rounded-md text-[11px] font-semibold tracking-[0.06em]"></div>',
      '      <div class="absolute bottom-3 left-3 z-10 text-[11px]" style="color:var(--ink-4);">drag to rotate · scroll to zoom</div>',
      '    </div>',
      '    <canvas data-hv="ecg" height="96" class="w-full mt-3 rounded-xl" style="background:var(--surface);border:1px solid var(--rule);"></canvas>',
      '  </div>',
      '  <aside class="min-w-0">',
      '    <p class="text-[11px] font-mono uppercase tracking-[0.16em]" style="color:#9B2F47;">Cardiac rhythm</p>',
      '    <h3 class="text-[18px] font-semibold tracking-tight mt-1 leading-snug" style="color:var(--ink);">' + esc(opts.deviceName || protocol.class_display) + '</h3>',
      '    <p class="text-[12px] mt-0.5" style="color:var(--ink-4);">' + esc(protocol.class_display) + (opts.manufacturer ? ' · ' + esc(opts.manufacturer) : '') + '</p>',
      '    <div data-hv="loc-badge" class="mt-3"></div>',
      '    <div data-hv="loc-form" class="mt-2"></div>',
      '    <div class="mt-5 pt-4" style="border-top:1px solid var(--rule);">',
      '      <button data-hv="magnet-btn" class="w-full px-4 py-2.5 rounded-xl text-[13px] font-semibold text-white transition" style="background:var(--primary);">Apply magnet</button>',
      '      <div data-hv="status" class="mt-3"></div>',
      '    </div>',
      '    <p class="text-[12px] leading-relaxed mt-4 pt-4" style="color:var(--ink-3);border-top:1px solid var(--rule);">' +
             esc((protocol.facts && protocol.facts.magnet_behavior && protocol.facts.magnet_behavior.value) || '') + '</p>',
      '    <p class="text-[11px] leading-relaxed mt-3" style="color:var(--ink-4);">Stylized anatomy — illustrative, not a clinical image. ' + esc(protocol.disclaimer || '') + '</p>',
      '  </aside>',
      '</div>',
    ].join('');

    var q = function (k) { return container.querySelector('[data-hv="' + k + '"]'); };
    var canvasWrap = q('canvas-wrap');
    var ecgCanvas = q('ecg');
    var magnetBtn = q('magnet-btn');

    // ---- Three.js scene ----------------------------------------------
    var scene = new THREE.Scene();
    var camera = new THREE.PerspectiveCamera(40, 1, 0.1, 100);
    camera.position.set(0.6, 0.8, 9.2);

    var renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    canvasWrap.appendChild(renderer.domElement);

    var controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = 4;
    controls.maxDistance = 16;

    scene.add(new THREE.HemisphereLight(0xffffff, 0xd8dce4, 0.95));
    var dir = new THREE.DirectionalLight(0xffffff, 0.55);
    dir.position.set(4, 6, 8);
    scene.add(dir);

    var heartGroup = new THREE.Group();
    heartGroup.rotation.z = -0.12;
    scene.add(heartGroup);
    var chambers = buildHeart(heartGroup);

    var hardwareGroup = new THREE.Group();
    heartGroup.add(hardwareGroup);
    var hardware = buildHardware(hardwareGroup, currentLeadConfig(), currentPocketSide());

    var magnet = buildMagnet(scene);

    function rebuildHardware() {
      while (hardwareGroup.children.length) {
        var m = hardwareGroup.children.pop();
        if (m.geometry) m.geometry.dispose();
        if (m.material) m.material.dispose();
        hardwareGroup.remove(m);
      }
      hardware = buildHardware(hardwareGroup, currentLeadConfig(), currentPocketSide());
    }

    // Pulse rings shown at paced lead tips.
    var pulses = [];
    function spawnPulse(pos) {
      var ring = new THREE.Mesh(
        new THREE.RingGeometry(0.12, 0.16, 28),
        new THREE.MeshBasicMaterial({ color: 0xd86a4a, transparent: true, opacity: 0.9, side: THREE.DoubleSide })
      );
      ring.position.copy(pos);
      ring.userData.age = 0;
      heartGroup.add(ring);
      pulses.push(ring);
    }

    // ---- Beat engine ---------------------------------------------------
    var state = {
      magnet: 'idle', // idle | applying | applied | removing
      magnetT: 0,
      mode: 'sensed', // sensed | async | suspend | none
      rate: BASE_RATE,
      lastBeat: -1,
    };

    function effectiveMagnetRate() {
      return magnetRate ? magnetRate.bpm : GENERIC_MAGNET_RATE;
    }

    function applyMagnetState() {
      if (behavior === 'async') {
        state.mode = 'async';
        state.rate = effectiveMagnetRate();
      } else if (behavior === 'suspend') {
        state.mode = 'suspend';
        state.rate = BASE_RATE;
      } else {
        state.mode = 'none';
        state.rate = BASE_RATE;
      }
      renderStatus();
    }

    function clearMagnetState() {
      state.mode = 'sensed';
      state.rate = BASE_RATE;
      renderStatus();
    }

    function renderStatus() {
      var statusEl = q('status');
      var badgeEl = q('badge');
      var bits = [];
      var rateLabel;
      if (state.mode === 'async') {
        rateLabel = state.rate + ' bpm';
        var rateNote = magnetRate
          ? (magnetRate.verified ? '' : ' <span style="color:var(--coral-deep);">(unverified — pending clinician review)</span>')
          : ' <span style="color:var(--coral-deep);">(manufacturer-specific — illustrative 90 bpm shown)</span>';
        bits.push('<div class="text-[13px]" style="color:var(--ink-2);"><span class="font-mono font-semibold" style="color:var(--ink);">' +
          rateLabel + '</span> magnet rate' + rateNote + '</div>');
      } else {
        bits.push('<div class="text-[13px]" style="color:var(--ink-2);"><span class="font-mono font-semibold" style="color:var(--ink);">' +
          state.rate + ' bpm</span> ' + (state.mode === 'sensed' ? 'sensed rhythm (illustrative)' : 'rhythm unchanged') + '</div>');
      }
      statusEl.innerHTML = bits.join('');

      if (state.mode === 'sensed') {
        badgeEl.classList.add('hidden');
      } else {
        var b = BEHAVIOR_BADGE[behavior];
        badgeEl.textContent = b.text;
        badgeEl.style.background = b.bg;
        badgeEl.style.color = b.fg;
        badgeEl.classList.remove('hidden');
      }
    }

    function renderLocationChrome() {
      var badge = q('loc-badge');
      var form = q('loc-form');
      var confirmed = !!(implant && implant.confirmed);
      var configLabel = '';
      if (implantOptions) {
        var cfg = implantOptions.lead_configs.filter(function (c) { return c.code === currentLeadConfig(); })[0];
        configLabel = cfg ? cfg.label : currentLeadConfig();
      }
      badge.innerHTML =
        '<span class="text-[11px] font-semibold uppercase tracking-[0.08em] px-2 py-0.5 rounded-md" style="background:' +
        (confirmed ? 'var(--emerald-soft)' : 'var(--honey-soft)') + ';color:' +
        (confirmed ? 'var(--emerald-deep)' : 'var(--honey-deep)') + ';">' +
        (confirmed ? 'Location confirmed by clinician' : 'Typical placement — not confirmed') + '</span>' +
        '<p class="text-[12.5px] mt-1.5" style="color:var(--ink-2);">' + esc(configLabel) +
        (currentLeadConfig() !== 'leadless_rv' && currentLeadConfig() !== 'subcutaneous'
          ? ' · ' + esc(currentPocketSide()) + ' pectoral pocket' : '') + '</p>';

      if (confirmed || !implantOptions || !opts.fhirId) {
        form.innerHTML = '';
        return;
      }
      form.innerHTML =
        '<div class="rounded-xl p-3" style="background:var(--surface-warm);border:1px solid var(--rule);">' +
        '  <p class="text-[11px] font-semibold mb-1.5" style="color:var(--ink-3);">Set the actual location</p>' +
        '  <select data-hv="loc-select" class="w-full text-[12px] rounded-lg px-2 py-1.5" style="border:1px solid var(--rule);background:var(--surface);">' +
        implantOptions.lead_configs.map(function (c) {
          return '<option value="' + esc(c.code) + '"' + (c.code === currentLeadConfig() ? ' selected' : '') + '>' + esc(c.label) + '</option>';
        }).join('') +
        '  </select>' +
        (implantOptions.has_pocket
          ? '<select data-hv="loc-pocket" class="w-full text-[12px] rounded-lg px-2 py-1.5 mt-1.5" style="border:1px solid var(--rule);background:var(--surface);">' +
            implantOptions.pocket_sides.map(function (p) {
              return '<option value="' + esc(p.code) + '"' + (p.code === currentPocketSide() ? ' selected' : '') + '>' + esc(p.label) + '</option>';
            }).join('') + '</select>'
          : '') +
        '  <button data-hv="loc-save" class="w-full mt-2 px-3 py-1.5 rounded-lg text-[12px] font-semibold text-white" style="background:var(--ink);">Save to chart</button>' +
        '  <p data-hv="loc-msg" class="text-[11px] mt-1.5 hidden" style="color:var(--coral-deep);"></p>' +
        '</div>';

      q('loc-save').addEventListener('click', function () {
        var lead = q('loc-select').value;
        var pocketEl = q('loc-pocket');
        var body = { lead_config: lead };
        if (pocketEl) body.pocket_side = pocketEl.value;
        q('loc-save').textContent = 'Saving…';
        fetch('/api/device/' + encodeURIComponent(opts.fhirId) + '/implant-site', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        }).then(function (r) { return r.json(); }).then(function (data) {
          if (data.success) {
            implant = data.implant;
            if (opts.onLocationSaved) opts.onLocationSaved(implant);
            rebuildHardware();
            renderLocationChrome();
          } else {
            var msg = q('loc-msg');
            msg.textContent = data.error || 'Could not save';
            msg.classList.remove('hidden');
            q('loc-save').textContent = 'Save to chart';
          }
        }).catch(function (e) {
          var msg = q('loc-msg');
          msg.textContent = 'Could not save: ' + e.message;
          msg.classList.remove('hidden');
          q('loc-save').textContent = 'Save to chart';
        });
      });
    }

    // ---- Magnet interaction -------------------------------------------
    magnetBtn.addEventListener('click', function () {
      if (state.magnet === 'idle') {
        state.magnet = 'applying';
        state.magnetT = 0;
        magnet.visible = true;
        magnetBtn.textContent = 'Remove magnet';
        magnetBtn.style.background = 'var(--coral)';
      } else if (state.magnet === 'applied') {
        state.magnet = 'removing';
        state.magnetT = 0;
        magnetBtn.textContent = 'Apply magnet';
        magnetBtn.style.background = 'var(--primary)';
      }
    });

    // ---- Animation loop -------------------------------------------------
    var ecg = EcgStrip(ecgCanvas);
    var clock = new THREE.Clock();
    var elapsed = 0;
    var rafId = null;
    var disposed = false;
    var hidden = false;

    function magnetTarget() {
      var canPos = hardware.can ? hardware.can.position.clone() : new THREE.Vector3();
      heartGroup.localToWorld(canPos);
      return canPos.add(new THREE.Vector3(0, 0.25, 0.55));
    }

    function animate() {
      if (disposed) return;
      rafId = requestAnimationFrame(animate);
      if (hidden) return;
      var dt = Math.min(clock.getDelta(), 0.1);
      elapsed += dt;

      // Magnet movement
      if (state.magnet === 'applying' || state.magnet === 'removing') {
        state.magnetT = Math.min(state.magnetT + dt / 0.6, 1);
        var from = state.magnet === 'applying' ? anchors('left').magnet_rest : magnetTarget();
        var to = state.magnet === 'applying' ? magnetTarget() : anchors('left').magnet_rest;
        var ease = state.magnetT * state.magnetT * (3 - 2 * state.magnetT);
        magnet.position.lerpVectors(from, to, ease);
        if (state.magnetT >= 1) {
          if (state.magnet === 'applying') {
            state.magnet = 'applied';
            applyMagnetState();
          } else {
            state.magnet = 'idle';
            magnet.visible = false;
            clearMagnetState();
          }
        }
      }
      magnet.rotation.y += dt * 0.6;

      // Heartbeat: atria lead ventricles slightly.
      var period = 60 / state.rate;
      var beatIndex = Math.floor(elapsed / period);
      var phase = (elapsed % period) / period;
      var pacing = state.mode === 'async';

      function pulseScale(offset, amp) {
        var d = (phase - offset);
        if (d < 0) d += 1;
        return 1 + amp * Math.exp(-(d * d) / 0.004);
      }
      var atrialS = pulseScale(0.0, 0.06);
      var ventS = pulseScale(0.12, 0.09);
      ['ra', 'la'].forEach(function (k) {
        var b = chambers[k].userData.baseScale;
        chambers[k].scale.set(b.x * atrialS, b.y * atrialS, b.z * atrialS);
      });
      ['rv', 'lv'].forEach(function (k) {
        var b = chambers[k].userData.baseScale;
        chambers[k].scale.set(b.x * ventS, b.y * ventS, b.z * ventS);
      });

      // Pulse rings at paced tips on each new beat (async = visibly paced).
      if (beatIndex !== state.lastBeat) {
        state.lastBeat = beatIndex;
        if (pacing) {
          hardware.tips.forEach(function (tip) { spawnPulse(tip.pos); });
        }
      }
      for (var i = pulses.length - 1; i >= 0; i--) {
        var ring = pulses[i];
        ring.userData.age += dt;
        var a = ring.userData.age;
        ring.scale.setScalar(1 + a * 4);
        ring.material.opacity = Math.max(0, 0.9 - a * 1.6);
        ring.lookAt(camera.position);
        if (a > 0.6) {
          heartGroup.remove(ring);
          ring.geometry.dispose();
          ring.material.dispose();
          pulses.splice(i, 1);
        }
      }

      controls.update();
      renderer.render(scene, camera);
      ecg.draw(state.mode, state.rate, elapsed);
    }

    function resize() {
      var w = canvasWrap.clientWidth;
      var h = canvasWrap.clientHeight;
      if (!w || !h) return;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
      ecgCanvas.width = ecgCanvas.clientWidth;
    }

    function onVisibility() { hidden = document.hidden; }

    window.addEventListener('resize', resize);
    document.addEventListener('visibilitychange', onVisibility);

    resize();
    renderStatus();
    renderLocationChrome();
    animate();

    return {
      dispose: function () {
        disposed = true;
        if (rafId) cancelAnimationFrame(rafId);
        window.removeEventListener('resize', resize);
        document.removeEventListener('visibilitychange', onVisibility);
        controls.dispose();
        renderer.dispose();
        scene.traverse(function (obj) {
          if (obj.geometry) obj.geometry.dispose();
          if (obj.material) {
            if (obj.material.map) obj.material.map.dispose();
            obj.material.dispose();
          }
        });
        container.innerHTML = '';
      },
    };
  }

  window.initHeartVisual = initHeartVisual;
})();
