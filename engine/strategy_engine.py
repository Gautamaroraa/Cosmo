"""
COSMO - Indian Stocks F&O Strategy Engine
Generates daily trade setups for NIFTY and BANKNIFTY options/futures.
Combines: Astro + Technical + OI + PCR + Max Pain + Confidence
"""

import json
import os
from datetime import datetime, timezone

DATA_DIR     = os.path.join(os.path.dirname(__file__), '..', 'data')
LATEST_PATH  = os.path.join(DATA_DIR, 'latest.json')
FNO_PATH     = os.path.join(DATA_DIR, 'fno.json')
STRATEGY_OUT = os.path.join(DATA_DIR, 'strategy.json')

# ── Thresholds ────────────────────────────────────────────────────────────
PCR_BULLISH       = 1.1    # PCR above = bullish sentiment
PCR_BEARISH       = 0.85   # PCR below = bearish sentiment
PCR_EXTREME_BULL  = 1.3    # Extreme = mean reversion risk
PCR_EXTREME_BEAR  = 0.7    # Extreme = mean reversion risk
RSI_OVERBOUGHT    = 68
RSI_OVERSOLD      = 32
FUNDING_HIGH      = 0.08   # Longs overcrowded
FUNDING_NEG       = -0.05  # Shorts overcrowded
MIN_CONFIDENCE    = 40     # Minimum score to generate a trade

# ── Moon phase bias ───────────────────────────────────────────────────────
MOON_BIAS = {
    'New Moon':        'neutral',
    'Waxing Crescent': 'bullish',
    'First Quarter':   'bullish',
    'Waxing Gibbous':  'bullish',
    'Full Moon':       'volatile',
    'Waning Gibbous':  'neutral',
    'Last Quarter':    'bearish',
    'Waning Crescent': 'bearish',
}

def load_json(path):
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except:
        return {}

# ── Index Technical Analysis ──────────────────────────────────────────────

def get_index_technicals(latest_data):
    """Extract NIFTY and BANKNIFTY technicals from market data."""
    indices = latest_data.get('market', {}).get('indices', {})
    stocks  = latest_data.get('stocks', [])

    nifty    = indices.get('NIFTY50', {})
    banknifty = indices.get('NIFTYBANK', {})

    # Average RSI of top stocks as market RSI proxy
    top_stocks  = latest_data.get('summary', {}).get('top_stocks_today', [])
    avg_rsi     = sum(s.get('rsi', 50) for s in top_stocks) / len(top_stocks) if top_stocks else 50
    breadth     = latest_data.get('summary', {}).get('breadth', {})
    breadth_pct = breadth.get('breadth_ratio', 50)

    return {
        'nifty':       nifty,
        'banknifty':   banknifty,
        'avg_rsi':     round(avg_rsi, 1),
        'breadth_pct': breadth_pct,
        'direction':   latest_data.get('market', {}).get('direction', 'Neutral'),
        'volatility':  latest_data.get('market', {}).get('volatility_bias', 'Low'),
    }

# ── Momentum Strategy ─────────────────────────────────────────────────────

def check_momentum_setup(technicals, astro, fno_data, confidence_data):
    """
    Momentum setup: sky + technicals + OI all pointing same direction.
    """
    setups = []

    direction    = technicals['direction']
    breadth      = technicals['breadth_pct']
    rsi          = technicals['avg_rsi']
    moon_phase   = astro.get('moon_phase', '')
    moon_bias    = MOON_BIAS.get(moon_phase, 'neutral')
    day_ruler    = astro.get('day_ruler', '')
    retrograde   = astro.get('retrograde_planets', [])
    astro_score  = astro.get('astro_score', 50)
    conf_score   = confidence_data.get('today', {}).get('confidence_score', 50) if confidence_data else 50

    # NIFTY data
    nifty     = technicals['nifty']
    nifty_chg = nifty.get('change_pct', 0)

    # FNO data
    nifty_fno    = fno_data.get('NIFTY', {}) if fno_data else {}
    banknifty_fno = fno_data.get('BANKNIFTY', {}) if fno_data else {}
    nifty_pcr    = nifty_fno.get('pcr', {}).get('pcr', 1.0) if nifty_fno.get('status') == 'ok' else 1.0
    nifty_oi     = nifty_fno.get('oi_analysis', {})
    max_pain     = nifty_fno.get('max_pain', {})

    # ── BULLISH MOMENTUM ──────────────────────────────────────────────────
    bull_score = 0
    bull_reasons = []

    if direction == 'Bullish':
        bull_score += 25
        bull_reasons.append(f"Market direction Bullish (breadth {breadth}%)")

    if moon_bias == 'bullish':
        bull_score += 15
        bull_reasons.append(f"{moon_phase} — bullish moon phase")

    if astro_score >= 60:
        bull_score += 15
        bull_reasons.append(f"Astro score {astro_score}/100 — favorable sky")

    if PCR_BULLISH <= nifty_pcr <= PCR_EXTREME_BULL:
        bull_score += 15
        bull_reasons.append(f"NIFTY PCR {nifty_pcr} — bullish sentiment")

    if 45 <= rsi <= 65:
        bull_score += 10
        bull_reasons.append(f"RSI {rsi} — healthy momentum zone")

    if breadth >= 60:
        bull_score += 10
        bull_reasons.append(f"Broad market advance {breadth}%")

    if nifty_chg > 0.3:
        bull_score += 10
        bull_reasons.append(f"NIFTY up {nifty_chg}% today")

    # Penalty for retrograde
    major_retro = [p for p in retrograde if p in ['Mercury','Mars','Jupiter','Venus']]
    if major_retro:
        bull_score -= len(major_retro) * 8
        bull_reasons.append(f"⚠ {', '.join(major_retro)} retrograde — reduce size")

    if moon_bias == 'volatile':
        bull_score -= 15
        bull_reasons.append(f"⚠ Full Moon — volatility risk")

    if bull_score >= MIN_CONFIDENCE:
        # Entry zone based on max pain
        entry_note = ''
        sl_note = ''
        target_note = ''

        if max_pain:
            mp_strike = max_pain.get('max_pain_strike')
            spot      = max_pain.get('spot_price')
            if mp_strike and spot:
                if mp_strike > spot:
                    entry_note  = f"Buy NIFTY CE — strike near {int(spot * 1.005 / 50) * 50} (ATM+1)"
                    sl_note     = f"SL: NIFTY closes below {int(spot * 0.995 / 50) * 50}"
                    target_note = f"Target: {int(mp_strike / 50) * 50} (Max Pain)"
                else:
                    entry_note  = f"Buy NIFTY CE — ATM strike"
                    sl_note     = f"SL: 0.7% below entry"
                    target_note = f"Target: 1.5% above entry"
        else:
            entry_note  = "Buy NIFTY CE — ATM or ATM+1 strike"
            sl_note     = "SL: Close below nearest support"
            target_note = "Target: 1.5x risk"

        setups.append({
            'type':        'MOMENTUM',
            'direction':   'BULLISH',
            'instrument':  'NIFTY CE (Buy)',
            'index':       'NIFTY',
            'entry':       entry_note,
            'stop_loss':   sl_note,
            'target':      target_note,
            'confidence':  min(100, bull_score),
            'expiry_note': 'Use weekly expiry. Exit if momentum fades.',
            'reasons':     bull_reasons,
            'warning':     f"{', '.join(major_retro)} retrograde — use smaller size" if major_retro else '',
        })

    # ── BEARISH MOMENTUM ──────────────────────────────────────────────────
    bear_score = 0
    bear_reasons = []

    if direction == 'Bearish':
        bear_score += 25
        bear_reasons.append(f"Market direction Bearish (breadth {breadth}%)")

    if moon_bias == 'bearish':
        bear_score += 15
        bear_reasons.append(f"{moon_phase} — bearish moon phase")

    if astro_score <= 40:
        bear_score += 15
        bear_reasons.append(f"Astro score {astro_score}/100 — unfavorable sky")

    if nifty_pcr <= PCR_BEARISH:
        bear_score += 15
        bear_reasons.append(f"NIFTY PCR {nifty_pcr} — bearish sentiment")

    if rsi >= RSI_OVERBOUGHT:
        bear_score += 10
        bear_reasons.append(f"RSI {rsi} — overbought")

    if breadth <= 40:
        bear_score += 10
        bear_reasons.append(f"Broad market decline {breadth}%")

    if nifty_chg < -0.3:
        bear_score += 10
        bear_reasons.append(f"NIFTY down {abs(nifty_chg)}% today")

    if bear_score >= MIN_CONFIDENCE:
        setups.append({
            'type':        'MOMENTUM',
            'direction':   'BEARISH',
            'instrument':  'NIFTY PE (Buy)',
            'index':       'NIFTY',
            'entry':       "Buy NIFTY PE — ATM or ATM-1 strike",
            'stop_loss':   "SL: NIFTY closes above recent resistance",
            'target':      "Target: 1.5x risk",
            'confidence':  min(100, bear_score),
            'expiry_note': 'Use weekly expiry. Exit before Full Moon.',
            'reasons':     bear_reasons,
            'warning':     '',
        })

    return setups

# ── Mean Reversion Strategy ───────────────────────────────────────────────

def check_mean_reversion_setup(technicals, astro, fno_data):
    """
    Mean reversion: extreme conditions that are likely to snap back.
    """
    setups = []

    rsi        = technicals['avg_rsi']
    breadth    = technicals['breadth_pct']
    moon_phase = astro.get('moon_phase', '')
    moon_bias  = MOON_BIAS.get(moon_phase, 'neutral')

    nifty_fno = fno_data.get('NIFTY', {}) if fno_data else {}
    nifty_pcr = nifty_fno.get('pcr', {}).get('pcr', 1.0) if nifty_fno.get('status') == 'ok' else 1.0
    max_pain  = nifty_fno.get('max_pain', {})

    # ── FADE THE EXTREME BULLISHNESS ──────────────────────────────────────
    rev_bear_score = 0
    rev_bear_reasons = []

    if rsi >= RSI_OVERBOUGHT:
        rev_bear_score += 30
        rev_bear_reasons.append(f"RSI {rsi} — extreme overbought, reversal risk")

    if nifty_pcr >= PCR_EXTREME_BULL:
        rev_bear_score += 25
        rev_bear_reasons.append(f"PCR {nifty_pcr} — extreme put buying = complacency")

    if moon_bias == 'volatile':
        rev_bear_score += 20
        rev_bear_reasons.append(f"Full Moon — peak energy, reversals common")

    if breadth >= 75:
        rev_bear_score += 15
        rev_bear_reasons.append(f"Breadth {breadth}% — extreme advance, mean reversion likely")

    if max_pain:
        spot = max_pain.get('spot_price', 0)
        mp   = max_pain.get('max_pain_strike', 0)
        if spot and mp and spot > mp * 1.015:
            rev_bear_score += 20
            rev_bear_reasons.append(f"Spot {spot} far above Max Pain {mp} — gravity pull downward")

    if rev_bear_score >= MIN_CONFIDENCE:
        setups.append({
            'type':        'MEAN_REVERSION',
            'direction':   'FADE_BULLISH',
            'instrument':  'NIFTY PE (Buy) or Bear Call Spread',
            'index':       'NIFTY',
            'entry':       "Buy NIFTY PE — ATM strike on any bounce",
            'stop_loss':   "SL: New 5-day high on NIFTY",
            'target':      f"Target: Max Pain {max_pain.get('max_pain_strike', 'N/A')} or -1.5% from entry",
            'confidence':  min(100, rev_bear_score),
            'expiry_note': 'Use nearest weekly expiry. Quick trade — 1-2 days max.',
            'reasons':     rev_bear_reasons,
            'warning':     'Mean reversion trade — use small size, respect stop loss',
        })

    # ── FADE THE EXTREME BEARISHNESS ─────────────────────────────────────
    rev_bull_score = 0
    rev_bull_reasons = []

    if rsi <= RSI_OVERSOLD:
        rev_bull_score += 30
        rev_bull_reasons.append(f"RSI {rsi} — extreme oversold, bounce likely")

    if nifty_pcr <= PCR_EXTREME_BEAR:
        rev_bull_score += 25
        rev_bull_reasons.append(f"PCR {nifty_pcr} — extreme call buying = panic")

    if moon_bias in ['bullish']:
        rev_bull_score += 15
        rev_bull_reasons.append(f"{moon_phase} — waxing energy supports bounce")

    if breadth <= 25:
        rev_bull_score += 15
        rev_bull_reasons.append(f"Breadth {breadth}% — extreme decline, bounce imminent")

    if max_pain:
        spot = max_pain.get('spot_price', 0)
        mp   = max_pain.get('max_pain_strike', 0)
        if spot and mp and spot < mp * 0.985:
            rev_bull_score += 20
            rev_bull_reasons.append(f"Spot {spot} far below Max Pain {mp} — gravity pull upward")

    if rev_bull_score >= MIN_CONFIDENCE:
        setups.append({
            'type':        'MEAN_REVERSION',
            'direction':   'FADE_BEARISH',
            'instrument':  'NIFTY CE (Buy) or Bull Put Spread',
            'index':       'NIFTY',
            'entry':       "Buy NIFTY CE — ATM strike on any dip",
            'stop_loss':   "SL: New 5-day low on NIFTY",
            'target':      f"Target: Max Pain {max_pain.get('max_pain_strike', 'N/A')} or +1.5% from entry",
            'confidence':  min(100, rev_bull_score),
            'expiry_note': 'Use nearest weekly expiry. Quick trade — 1-2 days max.',
            'reasons':     rev_bull_reasons,
            'warning':     'Mean reversion trade — use small size, respect stop loss',
        })

    return setups

# ── No Trade Conditions ───────────────────────────────────────────────────

def check_no_trade_conditions(astro, technicals, confidence_data):
    """Returns reasons to avoid trading today."""
    reasons = []
    retrograde = astro.get('retrograde_planets', [])
    moon_phase = astro.get('moon_phase', '')
    conf       = confidence_data.get('today', {}).get('confidence_score', 50) if confidence_data else 50
    risk       = confidence_data.get('today', {}).get('confidence_level', '') if confidence_data else ''

    major_retro = [p for p in retrograde if p in ['Mercury','Mars','Jupiter','Venus']]
    if len(major_retro) >= 2:
        reasons.append(f"Multiple retrogrades ({', '.join(major_retro)}) — high reversal risk")

    if moon_phase == 'Full Moon':
        reasons.append("Full Moon — maximum volatility, unpredictable moves")

    if moon_phase == 'New Moon':
        reasons.append("New Moon — low energy, wait for direction clarity")

    if conf < 35:
        reasons.append(f"Confidence score {conf}/100 — conditions unfavorable")

    transitions = astro.get('upcoming_transitions', [])
    for t in transitions:
        if t.get('planet') in ['Jupiter', 'Saturn', 'Mars'] and t.get('within_days', 99) <= 1:
            reasons.append(f"{t['planet']} changing sign today — unpredictable energy shift")

    return reasons

# ── Trend Summary ─────────────────────────────────────────────────────────

def build_trend_summary(latest_data, astro, fno_data):
    """Plain English current market trend."""
    direction   = latest_data.get('market', {}).get('direction', 'Neutral')
    vol_bias    = latest_data.get('market', {}).get('volatility_bias', 'Low')
    moon_phase  = astro.get('moon_phase', '')
    day_ruler   = astro.get('day_ruler', '')
    strongest   = latest_data.get('summary', {}).get('strongest_sector', '')
    weakest     = latest_data.get('summary', {}).get('weakest_sector', '')
    retrograde  = astro.get('retrograde_planets', [])
    breadth     = latest_data.get('summary', {}).get('breadth', {})
    adv         = breadth.get('advancing', 0)
    dec         = breadth.get('declining', 0)

    nifty_fno = fno_data.get('NIFTY', {}) if fno_data else {}
    pcr = nifty_fno.get('pcr', {}).get('pcr', 'N/A') if nifty_fno.get('status') == 'ok' else 'N/A'
    pcr_sent = nifty_fno.get('pcr', {}).get('sentiment', '') if nifty_fno.get('status') == 'ok' else ''

    lines = [
        f"Market is {direction} with {vol_bias} volatility.",
        f"{adv} stocks advancing vs {dec} declining.",
        f"Strongest sector: {strongest}. Weakest: {weakest}.",
        f"Moon is {moon_phase} — {MOON_BIAS.get(moon_phase, 'neutral')} energy.",
        f"Today is ruled by {day_ruler}.",
    ]

    if pcr != 'N/A':
        lines.append(f"NIFTY PCR: {pcr} — {pcr_sent}.")

    if retrograde:
        lines.append(f"Retrograde planets: {', '.join(retrograde)} — exercise caution.")

    return ' '.join(lines)

# ── Main Strategy Engine ──────────────────────────────────────────────────

def run_strategy_engine():
    print("\n🎯 Indian F&O Strategy Engine starting...")

    latest_data     = load_json(LATEST_PATH)
    fno_data        = load_json(FNO_PATH)
    confidence_data = load_json(os.path.join(DATA_DIR, 'confidence.json'))

    if not latest_data:
        print("   ⚠ No latest.json data")
        return

    astro       = latest_data.get('astro', {})
    technicals  = get_index_technicals(latest_data)

    print(f"   Direction : {technicals['direction']}")
    print(f"   RSI avg   : {technicals['avg_rsi']}")
    print(f"   Moon      : {astro.get('moon_phase')}")

    # Check no-trade conditions
    no_trade = check_no_trade_conditions(astro, technicals, confidence_data)

    # Generate setups
    momentum_setups    = check_momentum_setup(technicals, astro, fno_data, confidence_data)
    reversion_setups   = check_mean_reversion_setup(technicals, astro, fno_data)
    all_setups         = momentum_setups + reversion_setups

    # Sort by confidence
    all_setups.sort(key=lambda x: x['confidence'], reverse=True)

    # Trend summary
    trend_summary = build_trend_summary(latest_data, astro, fno_data)

    # Overall recommendation
    if no_trade:
        recommendation = 'NO_TRADE'
        rec_reason     = ' | '.join(no_trade)
    elif all_setups:
        top = all_setups[0]
        recommendation = f"{top['type']} {top['direction']}"
        rec_reason     = f"Confidence {top['confidence']}/100 — {top['instrument']}"
    else:
        recommendation = 'WAIT'
        rec_reason     = 'No clear setup today. Wait for better conditions.'

    output = {
        'meta': {
            'date':         latest_data.get('meta', {}).get('date'),
            'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'market':       'Indian Stocks F&O',
        },
        'trend_summary':    trend_summary,
        'recommendation':   recommendation,
        'rec_reason':       rec_reason,
        'no_trade_reasons': no_trade,
        'setups':           all_setups,
        'technicals':       technicals,
        'astro_summary': {
            'moon_phase':        astro.get('moon_phase'),
            'moon_bias':         MOON_BIAS.get(astro.get('moon_phase',''), 'neutral'),
            'day_ruler':         astro.get('day_ruler'),
            'astro_score':       astro.get('astro_score'),
            'retrograde_planets': astro.get('retrograde_planets', []),
        }
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STRATEGY_OUT, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\n✅ Strategy Engine complete → {STRATEGY_OUT}")
    print(f"   Recommendation : {recommendation}")
    print(f"   Reason         : {rec_reason}")
    print(f"   Setups found   : {len(all_setups)}")
    for s in all_setups:
        print(f"   [{s['confidence']}] {s['type']} {s['direction']} — {s['instrument']}")
    if no_trade:
        print(f"   ⚠ No-trade conditions: {len(no_trade)}")

    return output

if __name__ == '__main__':
    run_strategy_engine()
