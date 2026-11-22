"""Longer structural Nison Chapter 6 formations.

These are explicit, conservative geometric *proxies*, not claimed exact
translations of the book's discretionary chart interpretation. In particular
dumpling/frypan confirmation REQUIRES a real shadow-to-shadow window.
Only fully completed market bars from the parent validator may be passed.
"""
from __future__ import annotations


def _entry(name, weight, **details):
    return {"name":name,"chapter":6,
            "bias":"UP" if weight>0 else "DOWN" if weight<0 else "NEUTRAL",
            "experimental_weight":weight,
            "details":{"rule_type":"AXIOM_GEOMETRIC_PROXY_NOT_BOOK_CERTIFIED",**details}}


def _pivots(bars, kind):
    # A pivot is not considered confirmed until two later bars are CLOSED.
    key="high" if kind=="high" else "low"
    out=[]
    for i in range(2,len(bars)-2):
        x=bars[i][key]
        neighbors=[bars[i+j][key] for j in (-2,-1,1,2)]
        valid=(x>max(neighbors) if kind=="high" else x<min(neighbors))
        if valid:
            out.append((i,x))
    return out


def _three_swings(bars,atr,kind):
    piv=_pivots(bars,kind)
    if len(piv)<3:return None
    for k in range(len(piv)-3,-1,-1):
        triple=piv[k:k+3]
        if triple[-1][0]-triple[0][0]>40:
            continue
        if min(triple[j+1][0]-triple[j][0] for j in (0,1))<4:
            continue
        p=[value for _,value in triple]
        if max(p)-min(p)>2.5*atr:
            continue
        i0,i1,i2=[z[0] for z in triple]
        if kind=="high":
            valleys=[min(z["low"] for z in bars[i0+1:i1]),
                     min(z["low"] for z in bars[i1+1:i2])]
            if any(p[j]-v<.7*atr for j,v in enumerate([valleys[0],valleys[1],valleys[1]])):
                continue
            neckline=min(valleys)
            if bars[-1]["close"]>=neckline-.1*atr:
                continue
            subtype="THREE_BUDDHA_TOP" if p[1]>p[0]+.7*atr and p[1]>p[2]+.7*atr else "THREE_MOUNTAIN_TOP"
            return _entry(subtype,-.55,pivot_indices=[i0,i1,i2],
                          neckline=round(neckline,2),required_break_confirmed=True)
        else:
            crests=[max(z["high"] for z in bars[i0+1:i1]),
                    max(z["high"] for z in bars[i1+1:i2])]
            if any(v-p[j]<.7*atr for j,v in enumerate([crests[0],crests[1],crests[1]])):
                continue
            neckline=max(crests)
            if bars[-1]["close"]<=neckline+.1*atr:
                continue
            subtype="INVERTED_THREE_BUDDHA" if p[1]<p[0]-.7*atr and p[1]<p[2]-.7*atr else "THREE_RIVER_BOTTOM"
            return _entry(subtype,.55,pivot_indices=[i0,i1,i2],
                          neckline=round(neckline,2),required_break_confirmed=True)
    return None


def _dumpling_or_frypan(bars,atr):
    # Explicitly refuse "no gap" rounded formations: the book requires a
    # completing window. Price curvature alone is not the named formation.
    if len(bars)<13:return None
    prev,last=bars[-2:]
    rising_gap=last["low"]>prev["high"]
    falling_gap=last["high"]<prev["low"]
    if not (rising_gap or falling_gap):
        return None
    middle=bars[-13:-1]
    # Four equally sized price regions show a smooth dome/bowl, and small
    # bodies represent the consolidation (not any one huge breakout candle).
    parts=[[c["close"] for c in middle[i:i+3]] for i in (0,3,6,9)]
    means=[sum(x)/len(x) for x in parts]
    bodies=[abs(c["open"]-c["close"]) for c in middle[3:-1]]
    if max(bodies)>1.2*atr:
        return None
    if rising_gap and means[0]>means[1]>means[2] and means[3]>means[2]+.35*atr:
        return _entry("FRYPAN_BOTTOM",.5,strict_rising_window=True,
                      shape="rounded_concave_proxy")
    if falling_gap and means[0]<means[1]<means[2] and means[3]<means[2]-.35*atr:
        return _entry("DUMPLING_TOP",-.5,strict_falling_window=True,
                      shape="rounded_convex_proxy")
    return None


def _tower(bars,atr):
    if len(bars)<13:return None
    lead=bars[-13:-8];pause=bars[-8:-3];exit_bars=bars[-3:]
    first=lead[-1]["close"]-lead[0]["open"]
    last=exit_bars[-1]["close"]-exit_bars[0]["open"]
    pause_span=max(x["high"] for x in pause)-min(x["low"] for x in pause)
    if pause_span>2.3*atr or abs(first)<2*atr or abs(last)<2*atr:
        return None
    if first>0 and last<0 and bars[-1]["close"]<min(x["low"] for x in pause):
        return _entry("TOWER_TOP",-.5,initial_impulse=round(first,2),
                      confirmed_reversal_leg=True)
    if first<0 and last>0 and bars[-1]["close"]>max(x["high"] for x in pause):
        return _entry("TOWER_BOTTOM",.5,initial_impulse=round(first,2),
                      confirmed_reversal_leg=True)
    return None


def scan_structural_formations(validated_closed_bars:list[dict],atr:float)->list[dict]:
    if len(validated_closed_bars)<31 or atr<=0:
        return []
    bars=validated_closed_bars[-61:]
    results=[]
    for event in (_three_swings(bars,atr,"high"),
                  _three_swings(bars,atr,"low"),
                  _dumpling_or_frypan(bars,atr),_tower(bars,atr)):
        if event:
            results.append(event)
    return results
