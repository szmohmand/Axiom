"""Adaptive Japanese large-formation detector (research-only).

Implementation ideas: Lo/Mamaysky/Wang 2000 (kernel smoothing and pivots),
Wan/Si 2017 (formal geometric pattern definitions), Chua/Teh/Si 2021
(curve fitting and segmentation), QuantConnect (normalized DTW).
This is an original synthesis, not an exact reproduction of those papers.
Data inputs must contain ONLY already-closed, timestamp-valid candles.
No Kalshi labels, prices, or AXIOM baseline probabilities enter this scanner.
"""
from __future__ import annotations

import math
import statistics


def _smooth(prices, h):
    n = len(prices)
    radius = max(2, int(3 * h))
    out = []
    for i in range(n):
        ws = [(math.exp(-.5 * ((j-i)/h)**2), prices[j])
              for j in range(max(0, i-radius), min(n, i+radius+1))]
        out.append(sum(w*y for w,y in ws)/sum(w for w,_ in ws))
    return out


def _auto_bandwidth(prices):
    """Choose smoothing scale from leave-one-out errors, not a magic h."""
    n = len(prices)
    choices = sorted({max(1.5, n/d) for d in (28,20,14,10)})
    scores = []
    for h in choices:
        errors = []
        radius = int(3*h)+1
        for i in range(max(2,n//5), n-2, 2):
            ws = [(math.exp(-.5*((j-i)/h)**2),prices[j])
                  for j in range(max(0,i-radius),min(n,i+radius+1)) if j!=i]
            if ws:
                estimate = sum(w*y for w,y in ws)/sum(w for w,_ in ws)
                errors.append((estimate-prices[i])**2)
        scores.append((statistics.median(errors) if errors else float("inf"),h))
    return min(scores)[1]


def _noise_and_atr(bars, smooth):
    residual = [abs(c["close"]-z) for c,z in zip(bars,smooth)]
    mad = statistics.median(residual)
    tr = [max(c["high"]-c["low"],abs(c["high"]-p["close"]),
              abs(c["low"]-p["close"]))
          for p,c in zip(bars[:-1],bars[1:])]
    atr = max(statistics.median(tr),1e-9)
    return max(1.4826*mad,.05*atr,1e-9),atr


def _turns(series,noise):
    """Confirmed local extrema; exclude tiny back-and-forth moves."""
    raw = []
    for i in range(1,len(series)-1):
        a,b,c = series[i-1:i+2]
        if a<=b>c: raw.append((i,"peak",b))
        elif a>=b<c: raw.append((i,"trough",b))
    if not raw:return []
    out = [raw[0]]
    for p in raw[1:]:
        prev=out[-1]
        if p[1]==prev[1]:
            if (p[1]=="peak" and p[2]>prev[2]) or (p[1]=="trough" and p[2]<prev[2]):
                out[-1]=p
        elif abs(p[2]-prev[2])>=noise:
            out.append(p)
    return out


def _resample(data,n=21):
    if len(data)==1:return data*n
    result=[]
    for i in range(n):
        position=i*(len(data)-1)/(n-1)
        l=int(position);r=min(len(data)-1,l+1)
        result.append(data[l]+(data[r]-data[l])*(position-l))
    return result


def _dtw_distance(prices,template):
    """Normalized DTW; a similarity diagnostic, not a hard visual veto."""
    a=_resample(prices);b=_resample(template)
    xlo=min(a);ylo=min(b)
    ascale=max(max(a)-xlo,1e-12)
    bscale=max(max(b)-ylo,1e-12)
    a=[(v-xlo)/ascale for v in a]
    b=[(v-ylo)/bscale for v in b]
    n=len(a);width=max(2,round(n/4))
    prev=[float("inf")]*(n+1);prev[0]=0.
    for i in range(1,n+1):
        cur=[float("inf")]*(n+1)
        for j in range(max(1,i-width),min(n,i+width)+1):
            cur[j]=abs(a[i-1]-b[j-1])+min(prev[j],cur[j-1],prev[j-1])
        prev=cur
    return prev[-1]/n


_TEMPLATES = {
    "mountain": [.46,1.,.25,.88,.2,.94,.05],
    "river": [.54,0.,.75,.12,.8,.06,.95],
    "buddha": [.5,.8,.32,1.,.33,.76,.12],
    "inverse_buddha": [.5,.2,.68,0.,.67,.24,.88],
}


def _event(name,direction,strength,**detail):
    # The experimental weight is not a textbook significance or a calibrated
    # probability. It is a bounded *shadow-only* evidence-strength hypothesis.
    strength=max(.01,min(1.,strength))
    return {"name":name,"chapter":6,
            "bias":"UP" if direction>0 else "DOWN",
            "experimental_weight":round(direction*strength*.8,5),
            "details":{"rule_type":"DATA_ADAPTIVE_FORMAL_GEOMETRY",
                       "strength_unfitted":round(strength,5),
                       "not_calibrated_win_probability":True,**detail}}


def _triples(bars,turns,noise,atr):
    found=[]
    n=len(bars)
    for kind,direction in (("peak",-1),("trough",1)):
        points=[p for p in turns if p[1]==kind]
        for a,b,c in zip(points[:-2],points[1:-1],points[2:]):
            opposite="trough" if kind=="peak" else "peak"
            mid1=[p for p in turns if a[0]<p[0]<b[0] and p[1]==opposite]
            mid2=[p for p in turns if b[0]<p[0]<c[0] and p[1]==opposite]
            if not mid1 or not mid2:continue
            v1=mid1[-1];v2=mid2[-1]
            highs=[a[2],b[2],c[2]]
            counter=[v1[2],v2[2]]
            if direction<0:
                amplitude=min(min(highs[0],highs[1])-counter[0],
                              min(highs[1],highs[2])-counter[1])
                confirmed=bars[-1]["close"]<min(counter)
                middle_extreme=highs[1]>max(highs[0],highs[2])+noise
                family="THREE_BUDDHA_TOP" if middle_extreme else "THREE_MOUNTAIN_TOP"
                template="buddha" if middle_extreme else "mountain"
            else:
                amplitude=min(counter[0]-max(highs[0],highs[1]),
                              counter[1]-max(highs[1],highs[2]))
                confirmed=bars[-1]["close"]>max(counter)
                middle_extreme=highs[1]<min(highs[0],highs[2])-noise
                family="INVERTED_THREE_BUDDHA" if middle_extreme else "THREE_RIVER_BOTTOM"
                template="inverse_buddha" if middle_extreme else "river"
            if amplitude<=noise or n-c[0]>max(5,n//4):
                continue
            dtw=_dtw_distance([v["close"] for v in bars[a[0]:]],_TEMPLATES[template])
            strength=(1/(1+dtw))*(1-math.exp(-amplitude/max(atr,noise)))
            status="CONFIRMED" if confirmed else "FORMING"
            found.append(_event(family if confirmed else family+"_FORMING",
                direction,strength*(1 if confirmed else .35),
                status=status,turning_point_indices=[a[0],v1[0],b[0],v2[0],c[0]],
                neckline_usd=round(sum(counter)/2,2),
                dtw_normalized_distance=round(dtw,6),
                prominence_in_volatility_units=round(amplitude/max(noise,atr),5),
                unequal_extrema_allowed=True,
                confirmed_close_beyond_both_counter_swings=confirmed))
    return found


def _linear_fit(values):
    n=len(values);mx=(n-1)/2;my=sum(values)/n
    den=sum((i-mx)**2 for i in range(n))
    slope=sum((i-mx)*(v-my) for i,v in enumerate(values))/den
    intercept=my-slope*mx
    sse=sum((v-(intercept+slope*i))**2 for i,v in enumerate(values))
    return intercept,slope,sse


def _quadratic_fit(values):
    n=len(values)
    x=[-1.+2*i/(n-1) for i in range(n)]
    x2=sum(v*v for v in x);x4=sum(v**4 for v in x)
    ym=sum(values)/n
    slope=sum(t*y for t,y in zip(x,values))/x2
    curve=(sum(t*t*y for t,y in zip(x,values))-ym*x2)/max(1e-12,x4-x2*x2/n)
    intercept=ym-curve*x2/n
    sse=sum((y-(intercept+slope*t+curve*t*t))**2 for t,y in zip(x,values))
    return intercept,slope,curve,sse


def _rounded(bars,atr):
    n=len(bars)
    spans=sorted({(n-1)//k for k in (1,2,3) if (n-1)//k>=15})
    options=[]
    for span in spans:
        y=[v["close"] for v in bars[-span-1:-1]]
        _,_,linear_sse=_linear_fit(y)
        _,slope,curve,quad_sse=_quadratic_fit(y)
        eps=max((atr*1e-6)**2,1e-20)
        linear_bic=span*math.log(max(linear_sse,eps)/span)+2*math.log(span)
        quad_bic=span*math.log(max(quad_sse,eps)/span)+3*math.log(span)
        improvement=linear_bic-quad_bic
        if improvement<=0 or abs(curve)<1e-12:continue
        vertex=-slope/(2*curve)
        if not -1<vertex<1:continue
        direction=1 if curve>0 else -1
        gap_up=bars[-1]["low"]>bars[-2]["high"]
        gap_down=bars[-1]["high"]<bars[-2]["low"]
        confirmed=gap_up if direction>0 else gap_down
        family=("FRYPAN_BOTTOM" if direction>0 else "DUMPLING_TOP") if confirmed else (
                "ROUNDING_BOTTOM_CANDIDATE" if direction>0 else "ROUNDING_TOP_CANDIDATE")
        strength=1-math.exp(-improvement/(2*span))
        entry=_event(family,direction,strength*(1 if confirmed else .4),
            status="CONFIRMED_WINDOW" if confirmed else "FORMING_NO_WINDOW",
            curve_fit="QUADRATIC_APPROXIMATION_NOT_ELLIPSE",
            bic_improvement=round(improvement,5),
            signed_quadratic_curvature=round(curve,7),
            vertex_fraction=round((vertex+1)/2,5),
            lookback_bars=span,strict_nison_window=confirmed)
        options.append((entry,improvement/span))
    return [max(options,key=lambda z:z[1])[0]] if options else []


def _towers(bars,atr):
    n=len(bars)
    spans=sorted({m for m in (n,min(n,48),min(n,31),min(n,21)) if m>=15})
    options=[]
    for span in spans:
        sample=bars[-span:]
        prices=[v["close"] for v in sample]
        _,_,line_sse=_linear_fit(prices)
        _,_,_,quad_sse=_quadratic_fit(prices)
        best=None
        # Breakpoints learned from data by minimizing three-segment SSE.
        # Each line has >=3 points to estimate slope/intercept.
        for j in range(3,span-5):
            for k in range(j+3,span-2):
                fits=(_linear_fit(prices[:j]),_linear_fit(prices[j:k]),
                      _linear_fit(prices[k:]))
                sse=sum(z[2] for z in fits)
                if best is None or sse<best[0]:
                    best=(sse,j,k,[z[1] for z in fits])
        if best is None:continue
        sse,j,k,(first,middle,last)=best
        eps=max((atr*1e-6)**2,1e-20)
        line_bic=span*math.log(max(line_sse,eps)/span)+2*math.log(span)
        quad_bic=span*math.log(max(quad_sse,eps)/span)+3*math.log(span)
        tower_bic=span*math.log(max(sse,eps)/span)+6*math.log(span)
        gain=min(line_bic,quad_bic)-tower_bic
        if gain<=0 or min(abs(first),abs(last))<=abs(middle):continue
        if first>0 and last<0:
            direction=-1;family="TOWER_TOP"
            confirmed=sample[-1]["close"]<min(z["low"] for z in sample[j:k])
        elif first<0 and last>0:
            direction=1;family="TOWER_BOTTOM"
            confirmed=sample[-1]["close"]>max(z["high"] for z in sample[j:k])
        else:continue
        strength=1-math.exp(-gain/(2*span))
        entry=_event(family if confirmed else family+"_FORMING",
            direction,strength*(1 if confirmed else .4),
            status="CONFIRMED_BREAK" if confirmed else "FORMING",
            bic_improvement=round(gain,5),lookback_bars=span,
            learned_segment_boundaries=[j,k],
            slopes_in_volatility_units=[round(x/atr,5) for x in (first,middle,last)],
            selected_by="THREE_SEGMENT_BIC_VS_LINE_AND_QUADRATIC")
        options.append((entry,gain/span))
    return [max(options,key=lambda z:z[1])[0]] if options else []


def scan_structural_formations(validated_closed_bars:list[dict],atr:float)->list[dict]:
    """Flexible book-informed shapes with auditable uncertainty diagnostics."""
    if len(validated_closed_bars)<31 or not math.isfinite(atr) or atr<=0:
        return []
    bars=validated_closed_bars[-96:]
    closes=[c["close"] for c in bars]
    h=_auto_bandwidth(closes)
    smoothed=_smooth(closes,h)
    noise,local_atr=_noise_and_atr(bars,smoothed)
    turns=_turns(smoothed,noise)
    found=(_triples(bars,turns,noise,local_atr)+
           _rounded(bars,local_atr)+_towers(bars,local_atr))
    strongest={}
    for item in found:
        item["details"]["adaptive_kernel_bandwidth_bars"]=round(h,3)
        item["details"]["estimated_market_noise_usd"]=round(noise,6)
        item["details"]["observed_closed_bars"]=len(bars)
        name=item["name"]
        if name not in strongest or abs(item["experimental_weight"])>abs(strongest[name]["experimental_weight"]):
            strongest[name]=item
    return list(strongest.values())
