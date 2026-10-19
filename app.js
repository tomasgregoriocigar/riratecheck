'use strict';
/* ============================================================
   RI RATE CHECK — app logic
   Rules enforced here (Tom's standard: "positive sales, not lies,
   always facts"):
   - Every rate, fee, and track-record figure comes from
     data/supplier_offers.json or data/aggregation_towns.json.
     Nothing is hard-coded except the RI Energy Last Resort
     benchmark lookup (found in the JSON) and the two state bill
     credits, which are CONFIRMED by tariff (see the constants
     below). The credits are still displayed as their own lines:
     they sit on the DELIVERY side of the bill and are identical
     for every household, so they must never be folded into a
     supplier's "savings."
   - Any field the JSON stores as null renders as "not confirmed".
   - verified:false rates always carry the badge
     "ADVERTISED — NOT YET ZIP-VERIFIED".
   - Suppliers with a caution flag or a >= $900 average customer
     premium in the RI DPUC data are rendered as warnings and are
     never eligible for the "top honest pick" badge or ranked in
     the clean group, regardless of headline rate.
   - Suppliers whose JSON entry carries availability: "not_served"
     (verified as not selling in Rhode Island) are excluded from
     the rankings entirely and rendered in their own section —
     an unobtainable rate must never look like a deal.
   - Offers whose notes carry a TEASER / TERM RISK flag (a short
     term whose renewal rate is unknown) get an explicit badge,
     so a cheap headline rate is never mistaken for a year of
     cheap electricity.
   ============================================================ */

/* State bill credits — CONFIRMED by tariff (researched Oct 17, 2026;
   full memo: data/winter_credits_eligibility.md). Both are
   fixed-dollar line items on the DELIVERY side of the Rhode Island
   Energy bill, with NO supply-source condition: third-party
   supplier customers and municipal aggregation customers keep both.
   - Hold Harmless credit: $14.50/mo on bills rendered Oct 2026 –
     Sep 2027 (12 months). Tariff R.I.P.U.C. No. 2304 (PUC Docket
     25-45-GE). Every active electric distribution account.
   - RGGI emergency credit: $20.45/mo in each of the Jan, Feb and
     Mar 2027 billing periods, for distribution accounts in rate
     classes A-16 / A-60 (standard + low-income residential —
     effectively all RI households). Tariff R.I.P.U.C. No. 2309
     (PUC Docket 26-28-EL).
   Flat monthly amounts, NOT per-kWh. */
const CREDIT_HOLD_HARMLESS = 14.50;    // $/mo, Oct 2026 – Sep 2027
const CREDIT_RGGI = 20.45;             // $/mo, Jan–Mar 2027 billing periods
const CREDIT_COMBINED_JAN_MAR = 34.95; // both credits together, Jan–Mar 2027

function fmtRate(n) {
  // 17.029 -> "17.029", 10 -> "10.0", 13.47 -> "13.47"
  let s = Number(n).toFixed(3);
  s = s.replace(/0+$/, '').replace(/\.$/, '.0');
  return s;
}

function fmtMoney(n) {
  const sign = n < 0 ? '-$' : '$';
  return sign + Math.abs(n).toFixed(2);
}

function orNotConfirmed(v, format) {
  if (v === null || v === undefined) return 'not confirmed';
  return format ? format(v) : String(v);
}

/* Track-record figures live inside the JSON `notes` text
   (Green Energy Consumers Alliance analysis of RI DPUC data,
   2017-2024). Parse them out — never retype them by hand. */
function parseTrackRecord(notes) {
  if (!notes) return { premium: null, saved: null };
  let saved = null;
  const savedMatch = notes.match(/SAVED money[\s\S]*?\(-\$([\d,]+)/i);
  if (savedMatch) saved = parseInt(savedMatch[1].replace(/,/g, ''), 10);
  let premium = null;
  const premMatch = notes.match(/\+\$([\d,]+)/);
  if (premMatch) premium = parseInt(premMatch[1].replace(/,/g, ''), 10);
  return { premium, saved };
}

function isCautionFlagged(offer) {
  const tr = parseTrackRecord(offer.notes);
  return /caution/i.test(offer.notes || '') || (tr.premium !== null && tr.premium >= 900);
}

function monthlySupplyCost(offer, kwh) {
  const fee = typeof offer.monthly_fee_usd === 'number' ? offer.monthly_fee_usd : 0;
  return (kwh * offer.rate_cents_per_kwh) / 100 + fee;
}

/* "Honest pick" eligibility: clean track record, confirmed $0 ETF,
   confirmed term, confirmed fixed rate, beats the benchmark. */
function isHonestPickEligible(offer, benchmarkRate) {
  return !isCautionFlagged(offer)
    && offer.early_termination_fee_usd === 0
    && typeof offer.term_months === 'number'
    && offer.rate_type === 'fixed'
    && offer.rate_cents_per_kwh < benchmarkRate;
}

function badgesFor(offer) {
  const notes = offer.notes || '';
  const tr = parseTrackRecord(notes);
  const badges = [];
  if (offer.verified) {
    badges.push({ cls: 'ok', text: 'VERIFIED' });
  } else if (/PARTLY CONFIRMED/i.test(notes)) {
    badges.push({ cls: 'warn', text: 'PARTLY CONFIRMED — TERMS VERIFIED, RATE ADVERTISED' });
    badges.push({ cls: 'warn', text: 'ADVERTISED — NOT YET ZIP-VERIFIED' });
  } else {
    badges.push({ cls: 'warn', text: 'ADVERTISED — NOT YET ZIP-VERIFIED' });
  }
  if (offer.availability === 'not_served') {
    badges.push({ cls: 'bad', text: 'NOT AVAILABLE IN RHODE ISLAND' });
  }
  if (/TEASER|TERM RISK/i.test(notes)) {
    badges.push({ cls: 'warn', text: 'SHORT TERM — RENEWAL RATE UNKNOWN (TEASER RISK)' });
  }
  if (/SOURCES DISAGREE/i.test(notes)) {
    badges.push({ cls: 'warn', text: 'SOURCES DISAGREE ON THIS RATE' });
  }
  if (/not published/i.test(notes) && offer.rate_type === 'variable') {
    badges.push({ cls: 'warn', text: 'TERMS NOT PUBLISHED — HEADLINE RATE ONLY' });
  }
  if (/could NOT be confirmed/i.test(notes)) {
    badges.push({ cls: 'warn', text: 'DIRECT SIGN-UP OFFER NOT CONFIRMED — FIGURE MAY REFLECT AGGREGATION SUPPLY' });
  }
  if (isCautionFlagged(offer)) {
    badges.push({ cls: 'bad', text: 'TRACK RECORD WARNING — SEE BELOW' });
  } else if (tr.saved !== null) {
    badges.push({ cls: 'ok', text: 'TRACK RECORD: CUSTOMERS SAVED MONEY ON AVERAGE' });
  } else if (tr.premium !== null && tr.premium < 300) {
    badges.push({ cls: 'ok', text: 'TRACK RECORD: ROUGHLY BROKE EVEN VS DEFAULT' });
  } else if (tr.premium !== null) {
    badges.push({ cls: 'warn', text: 'TRACK RECORD: CUSTOMERS PAID MORE THAN DEFAULT ON AVERAGE' });
  }
  /* PLACEHOLDER: referral-fee disclosure badge goes here. If a
     supplier ever pays a referral fee, that offer's card MUST get:
     { cls: 'warn', text: 'WE MAY EARN A REFERRAL FEE FROM THIS SUPPLIER' } */
  return badges;
}

function trackRecordLine(offer) {
  const tr = parseTrackRecord(offer.notes);
  if (tr.saved !== null) {
    return { cls: 'hot', text: 'customers SAVED $' + tr.saved.toLocaleString('en-US') + ' on average vs default (2017–2024)' };
  }
  if (tr.premium !== null) {
    const bad = isCautionFlagged(offer);
    return {
      cls: bad ? 'bad' : (tr.premium < 300 ? 'hot' : 'warnv'),
      text: 'customers paid +$' + tr.premium.toLocaleString('en-US') + ' MORE on average vs default (2017–2024)'
    };
  }
  return { cls: '', text: 'no RI track-record figure in our data' };
}

/* ============ browser-only rendering below ============ */

function el(html) {
  const t = document.createElement('template');
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

function rline(k, v, vcls) {
  return '<div class="rline"><span class="k">' + k + '</span><span class="dots"></span>' +
    '<span class="v' + (vcls ? ' ' + vcls : '') + '">' + v + '</span></div>';
}

function badgesHtml(badges) {
  return badges.map(b => '<span class="badge ' + b.cls + '">' + b.text + '</span>').join('');
}

function renderBenchmark(bench, kwh) {
  const cost = monthlySupplyCost(bench, kwh);
  return '<div class="card benchmark">' +
    '<div class="card-top"><span class="card-name">' + bench.supplier.toUpperCase() + ' — ' + bench.plan_name + '</span>' +
    '<span class="card-rate">' + fmtRate(bench.rate_cents_per_kwh) + '&cent;<small>/kWh</small></span></div>' +
    '<div>' + badgesHtml(badgesFor(bench)) + '</div>' +
    '<div class="readout">' +
    rline('SUPPLY COST @ ' + kwh + ' kWh', fmtMoney(cost) + '/mo', 'hot') +
    rline('CONTRACT', 'none — this is the default') +
    rline('EARLY TERMINATION FEE', '$0') +
    rline('RATE PERIOD', 'Oct 1, 2026 – Mar 31, 2027') +
    rline('SOURCE', bench.source_name) +
    rline('CHECKED', bench.checked_date) +
    '</div></div>';
}

function renderSummary(bench, kwh) {
  const gross = monthlySupplyCost(bench, kwh);
  const afterHH = gross - CREDIT_HOLD_HARMLESS;
  const afterBoth = gross - CREDIT_COMBINED_JAN_MAR;
  return rline('DEFAULT SUPPLY (LAST RESORT) @ ' + kwh + ' kWh', fmtMoney(gross) + '/mo', 'hot') +
    rline('LESS: HOLD HARMLESS CREDIT (OCT 2026–SEP 2027)', '−' + fmtMoney(CREDIT_HOLD_HARMLESS) + '/mo') +
    rline('DEFAULT AFTER HOLD HARMLESS CREDIT', fmtMoney(afterHH) + '/mo') +
    rline('LESS: BOTH CREDITS COMBINED, JAN–MAR 2027', '−' + fmtMoney(CREDIT_COMBINED_JAN_MAR) + '/mo') +
    rline('DEFAULT AFTER BOTH CREDITS, JAN–MAR 2027', fmtMoney(afterBoth) + '/mo') +
    '<p class="note">&gt; Both credits are CONFIRMED for every Rhode Island household — including ' +
    'third-party supplier customers — because they sit on the DELIVERY side of the bill ' +
    '(Tariffs R.I.P.U.C. No. 2304 &amp; No. 2309). They are the same no matter who supplies you, ' +
    'so supplier savings below stay supply-only and never count them. See WINTER CREDITS.</p>';
}

/* PLACEHOLDER LINK — href="#" is inert on purpose.
   No enrollment / referral / affiliate link may be wired to these
   buttons until BOTH: (1) the specific plan is verified live for
   the visitor's ZIP, and (2) Tom has approved the exact supplier
   deal terms. Until then the button explains itself and goes nowhere. */
function renderOffer(offer, bench, kwh, isPick) {
  const cost = monthlySupplyCost(offer, kwh);
  const benchCost = monthlySupplyCost(bench, kwh);
  const diff = benchCost - cost;
  const caution = isCautionFlagged(offer);
  const tr = trackRecordLine(offer);
  let verdict, verdictCls;
  if (diff > 0) { verdict = '&gt; SAVES ≈ ' + fmtMoney(diff) + '/mo vs default at ' + kwh + ' kWh/mo (supply only, estimated)'; verdictCls = 'good'; }
  else if (diff < 0) { verdict = '&gt; COSTS ≈ ' + fmtMoney(-diff) + '/mo MORE than default at ' + kwh + ' kWh/mo (supply only, estimated)'; verdictCls = 'bad'; }
  else { verdict = '&gt; SAME as default at ' + kwh + ' kWh/mo (supply only, estimated)'; verdictCls = 'mid'; }
  if (caution) { verdictCls = 'bad'; }

  const badges = badgesFor(offer);
  if (isPick) badges.unshift({ cls: 'pick', text: '★ TOP HONEST PICK' });

  const planLabel = offer.plan_name ? offer.plan_name : 'plan name not confirmed';
  return '<article class="card' + (caution ? ' caution' : '') + '">' +
    '<div class="card-top"><span class="card-name">' + offer.supplier.toUpperCase() + ' — ' + planLabel + '</span>' +
    '<span class="card-rate">' + fmtRate(offer.rate_cents_per_kwh) + '&cent;<small>/kWh</small></span></div>' +
    '<div>' + badgesHtml(badges) + '</div>' +
    (isPick ? '<p class="note">&gt; TOP HONEST PICK — meets all of: clean track record in the sourced data, confirmed $0 early-termination fee, confirmed term, fixed rate, and beats the Last Resort benchmark at the stated usage. See Methodology &amp; Corrections.</p>' : '') +
    '<p class="verdict ' + verdictCls + '">' + verdict + '</p>' +
    '<div class="readout">' +
    rline('EST. SUPPLY COST @ ' + kwh + ' kWh', fmtMoney(cost) + '/mo') +
    rline('RATE TYPE', offer.rate_type ? offer.rate_type.toUpperCase() : 'not confirmed') +
    rline('TERM', orNotConfirmed(offer.term_months, v => v + ' months')) +
    rline('EARLY TERMINATION FEE', orNotConfirmed(offer.early_termination_fee_usd, v => (v === 0 ? '$0 — confirmed' : fmtMoney(v)))) +
    rline('MONTHLY FEE', orNotConfirmed(offer.monthly_fee_usd, v => (v === 0 ? '$0' : fmtMoney(v) + '/mo'))) +
    rline('RENEWABLE', orNotConfirmed(offer.renewable_pct, v => v + '%')) +
    rline('TRACK RECORD (RI DPUC)', tr.text, tr.cls) +
    rline('SOURCE', offer.source_name) +
    rline('CHECKED', offer.checked_date) +
    '</div>' +
    '<details><summary>[+] FULL DATA NOTES</summary><p>' + offer.notes + '</p>' +
    '<p>Source: <a href="' + offer.source_url + '" rel="noopener">' + offer.source_url + '</a></p></details>' +
    '<a class="btn" href="#" onclick="return false" aria-disabled="true">[ CHECK THIS OFFER ]</a>' +
    '<p class="btn-note">Enrollment links are not live yet — we only link offers after they are ZIP-verified and any referral terms are approved and disclosed here.</p>' +
    '</article>';
}

/* Suppliers verified as NOT serving Rhode Island. Their advertised
   rates are unobtainable at any RI address, so they are never ranked
   and never get a savings verdict — the card exists so a visitor who
   saw the teaser headline somewhere else learns why it's absent. */
function renderNotServed(offer) {
  return '<article class="card caution">' +
    '<div class="card-top"><span class="card-name">' + offer.supplier.toUpperCase() + '</span>' +
    '<span class="card-rate">' + fmtRate(offer.rate_cents_per_kwh) + '&cent;<small>/kWh advertised elsewhere</small></span></div>' +
    '<div>' + badgesHtml(badgesFor(offer)) + '</div>' +
    '<p class="verdict bad">&gt; DOES NOT SERVE RHODE ISLAND — THIS RATE CANNOT BE OBTAINED HERE.</p>' +
    '<div class="readout">' +
    rline('SOURCE', offer.source_name) +
    rline('CHECKED', offer.checked_date) +
    '</div>' +
    '<details><summary>[+] FULL DATA NOTES</summary><p>' + offer.notes + '</p>' +
    '<p>Source: <a href="' + offer.source_url + '" rel="noopener">' + offer.source_url + '</a></p></details>' +
    '</article>';
}

function renderTown(town, bench, kwh) {
  const r = town.rates_cents_per_kwh;
  const stdCost = (kwh * r.standard) / 100;
  const benchCost = monthlySupplyCost(bench, kwh);
  const diff = benchCost - stdCost;
  let verdict;
  if (diff > 0) verdict = '&gt; Your town Standard rate SAVES ≈ ' + fmtMoney(diff) + '/mo vs default at ' + kwh + ' kWh.';
  else verdict = '&gt; Your town Standard rate is ≈ ' + fmtMoney(-diff) + '/mo above default at ' + kwh + ' kWh.';
  return '<p class="verdict good">&gt; YOU ARE LIKELY ALREADY COVERED.</p>' +
    '<p>' + town.town + ' runs <strong>' + town.program_name + '</strong> (consultant: ' + town.consultant +
    '; supplier: ' + town.supplier + '). Eligible households are auto-enrolled in the Standard tier. ' +
    'You can leave or change tiers at any time, with no fee.</p>' +
    '<div class="readout">' +
    rline('BASIC', fmtRate(r.basic) + '¢/kWh → ' + fmtMoney((kwh * r.basic) / 100) + '/mo @ ' + kwh + ' kWh') +
    rline('STANDARD (COMMUNITY DEFAULT)', fmtRate(r.standard) + '¢/kWh → ' + fmtMoney(stdCost) + '/mo @ ' + kwh + ' kWh', 'hot') +
    rline('TIER 50 (50% RENEWABLE)', fmtRate(r.tier_50) + '¢/kWh → ' + fmtMoney((kwh * r.tier_50) / 100) + '/mo') +
    rline('TIER 100 (100% RENEWABLE)', fmtRate(r.tier_100) + '¢/kWh → ' + fmtMoney((kwh * r.tier_100) / 100) + '/mo') +
    rline('RATE PERIOD', town.rate_period) +
    rline('CHECKED', town.checked_date) +
    '</div>' +
    '<p>' + verdict + '</p>' +
    '<p class="note">Compare any supplier offer against your TOWN rate — not the Last Resort rate. ' +
    'Most offers above would not beat it honestly. Program notes: ' + town.notes + '</p>' +
    '<p class="note">Source: <a href="' + town.source_url + '" rel="noopener">' + town.source_url + '</a></p>';
}

function init() {
  const state = { offers: [], towns: [], bench: null, kwh: 600 };

  function currentKwh() {
    const v = parseInt(document.getElementById('kwh').value, 10);
    return Number.isFinite(v) && v > 0 ? v : 600;
  }

  function renderAll() {
    const kwh = state.kwh;
    document.getElementById('benchmark-card').innerHTML = renderBenchmark(state.bench, kwh);
    document.getElementById('summary').innerHTML = renderSummary(state.bench, kwh);

    const served = state.offers.filter(o => o.availability !== 'not_served');
    const notServed = state.offers.filter(o => o.availability === 'not_served');
    const clean = [], flagged = [];
    served.forEach(o => (isCautionFlagged(o) ? flagged : clean).push(o));
    const byCost = (a, b) => monthlySupplyCost(a, kwh) - monthlySupplyCost(b, kwh);
    clean.sort(byCost); flagged.sort(byCost);

    const pick = clean.find(o => isHonestPickEligible(o, state.bench.rate_cents_per_kwh));
    let html = '';
    clean.forEach(o => { html += renderOffer(o, state.bench, kwh, o === pick); });
    if (notServed.length) {
      html += '<h3 class="subhead" style="color:var(--red)">&gt; NOT AVAILABLE IN RHODE ISLAND</h3>' +
        '<p class="note">These suppliers advertise low rates that show up in national search results, ' +
        'but they do not sell electricity in Rhode Island — verified on their own sites and against the ' +
        'state&rsquo;s Empower RI list. They are excluded from the rankings above on purpose.</p>';
      notServed.forEach(o => { html += renderNotServed(o); });
    }
    if (flagged.length) {
      html += '<h3 class="subhead" style="color:var(--red)">&gt; FLAGGED ON TRACK RECORD — LISTED AFTER CLEANER OFFERS ON PURPOSE</h3>' +
        '<p class="note">These suppliers&rsquo; Rhode Island customers paid far more than the default rate on ' +
        'average between 2017 and 2024 (RI DPUC data). They are listed after cleaner offers on purpose, and they ' +
        'never receive a top-pick badge here.</p>';
      flagged.forEach(o => { html += renderOffer(o, state.bench, kwh, false); });
    }
    document.getElementById('offers').innerHTML = html;

    const sel = document.getElementById('town-select');
    if (sel.value && sel.value !== '__none') {
      const town = state.towns.find(t => t.town === sel.value);
      if (town) document.getElementById('town-result').innerHTML = renderTown(town, state.bench, kwh);
    }
  }

  Promise.all([
    fetch('data/supplier_offers.json').then(r => r.json()),
    fetch('data/aggregation_towns.json').then(r => r.json())
  ]).then(([offers, towns]) => {
    state.bench = offers.find(o => o.supplier === 'Rhode Island Energy');
    state.offers = offers.filter(o => o.supplier !== 'Rhode Island Energy');
    state.towns = towns;

    const dates = offers.map(o => o.checked_date).sort();
    document.getElementById('checked-date').textContent = dates[dates.length - 1];

    const sel = document.getElementById('town-select');
    towns.slice().sort((a, b) => a.town.localeCompare(b.town)).forEach(t => {
      const opt = document.createElement('option');
      opt.value = t.town; opt.textContent = t.town.toUpperCase();
      sel.insertBefore(opt, sel.querySelector('option[value="__none"]'));
    });

    sel.addEventListener('change', () => {
      const out = document.getElementById('town-result');
      if (!sel.value) {
        out.innerHTML = '<p class="note">&gt; SELECT A TOWN TO SEE ITS PROGRAM, RATES, AND WHAT THEY COST AT YOUR USAGE.</p>';
      } else if (sel.value === '__none') {
        out.innerHTML = '<p class="verdict mid">&gt; NO AGGREGATION PROGRAM IN OUR DATA FOR YOUR TOWN.</p>' +
          '<p>Your baseline is the Last Resort rate above, and the supplier offers on this page are your ' +
          'comparison set. (Example: North Providence — ZIP 02911 — has no municipal aggregation program.) ' +
          'If your town launches a program, it will appear here with its checked rates.</p>';
      } else {
        renderAll();
      }
    });

    const kwhInput = document.getElementById('kwh');
    const kwhRange = document.getElementById('kwh-range');
    kwhInput.addEventListener('input', () => {
      state.kwh = currentKwh();
      if (state.kwh >= 100 && state.kwh <= 2000) kwhRange.value = state.kwh;
      renderAll();
    });
    kwhRange.addEventListener('input', () => {
      state.kwh = parseInt(kwhRange.value, 10);
      kwhInput.value = state.kwh;
      renderAll();
    });

    renderAll();
  }).catch(err => {
    document.getElementById('offers').innerHTML =
      '<p class="error-box">!! DATA FAILED TO LOAD. This page reads data/supplier_offers.json and ' +
      'data/aggregation_towns.json — open it through a local web server, not as a file:// page. ' +
      'See BUILD_NOTES.md for preview instructions.</p>';
    console.error(err);
  });
}

if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    fmtRate, fmtMoney, parseTrackRecord, isCautionFlagged,
    monthlySupplyCost, isHonestPickEligible, badgesFor, trackRecordLine,
    CREDIT_HOLD_HARMLESS, CREDIT_RGGI, CREDIT_COMBINED_JAN_MAR
  };
}
