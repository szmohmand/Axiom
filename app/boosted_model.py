"""Fitted residual gradient-boosted model for BTC settlement-price direction.

Model artifact was fitted on real Binance BTCUSDT 1m closes across 90 days.
Training strikes are deliberately synthetic offsets; labels are the actual
future BTC prices, not retroactively published Kalshi floors. The model
learns residuals from a normal-volatility reference with gradient-boosted
regression trees. It is experimental; no claim of money-making alpha.

Inference uses only Python standard-library modules on Oracle.
"""
from __future__ import annotations
import base64
import functools
import json
import math
import statistics
import zlib

_MODEL_B85 = "c-nPXO^@R?68$TN&$7WPvWjHqmgEp10dh!oFO5L(*y<i3Zo47N31%1j-}jM{?RH!Z%m7W%q>5GVqp1Hb-;TR(zkFH_-KpQ5H~ZD=u-Wz9VO)JV9#3PpTkX1Sf9j8i)i`wBY1u6Q>V`7LB6h4Rq80P%`~I*wY`fK8$NgsP_x<>7b=eY2Ub@YA#(4SkyxjGtvHY~fPuu@s@~uCd$L`b)-P@)=^oLhG8#?^{&{F&5{Wg-j5#0~HyBq2}yv1`}@ZnLoJvzU2?SSV;48I(A-=>N4`+GOEfA`xzr}6&y_uUvFx4C6%UpMdN$shPhw;9SQ%5L5A$*o<KW{HE1{bt{uw#NZavC(Tkwj~q0&9G|^$KegL+ucihd}%*Kcp8WP&#vZa%Ky{z^RsK*+GAI068=IFIQsNQ^BkHL<u$ty5;fdNvnsPG_*`aF!|UX7ne$D+LdxDJ#mtJE6|Wsumw&Vt@6@^QFoPu?HD|$$$4D7JlSZ3Z-y}{r%fl*65lKQE#)ghVWG>-lyg0C`<_3RqeOVImQ|NJxSiScRxrWL@_8NmHE5@Wwy&5wblVl$;gDnI*3Ic8jn}&LTAmoXx12~t6L$anKXQwy;<{k<YVvZgYiZuv1GfB7=20^l~r}OKGjOTnQ3<-Ai#tD2v1#`ATbS%W>aEwahEQ$G6o6O0vxh@5c60JmPN>O#Ljq{9%Z?$p3U279uih*yn(S+l$u_ZGWk#(}@l2W{+BY`v$=h7fXavsSt!_O+tXDj>=NP{;E<Ab9-F~<9~WCxtx3KPJX5($Q03Z630mGKc6WD9lRpk%eq?7T{#FrUmjQoV7;i>m)*73Zw>k)x+d&s;$b8l-Dom?QZzSBkOD+2@kSxiA2{b7Z|Pkhqkr!hqE31K03noqR;bZ-qhlF+4^Y)=b^Xi3MTGDRMB&0)AB3*nB}8H6f3DK}M2TRq;v?Gc&)AO4&c7ix0xyOn!_kK~1`FqD;1wktlPX=_1et)f-)0h+>k06p=)Wn+l<FQ9qY54Me71flHinFr}<WNVZD@hF5L3J*KdbO^=Bha5}?eKrxttg%AWDVm-BCGLRZFGEz*&m6WT=B}~->8-#)G$Y*q6=pU)A!$g|RcLiWrYAyoG6f}L%F_>L)X6{iG0-G$&q!cCOe^f=QEau2G<-Jl^k~T%EYMFBgCIOS8{8b_F!va*7DWX_&DGR}^WiA%Yw`149q3Y=e<kvLTs&I9e55O<UFFq~caQZ~KU9z$(89r0Ndk1?ewVYtDA=&mwfTEgHs_29$TChiqA;;M$AZj6c)hp}?mMR5STy+f=c7eSI#IkvS06;i9LdYElv3-JLw)&4s2tZV9XD{Az^$CUd@&)#&aZa_)1qB|)Oex(Q+(S`6+m$`KxoC?m{82xHzLQBEP3UJcTX>8nL~3OwPY_VZ@wGfrxT<?D5+1<bTAN~nMM3<8lPdP;7w6iz(n7KIIu=C2pTH*~UEyLENDru7t5fj;Mp^nTg==EU1Sj+n`JTG@0%LHE+{H;eng_nQMT9d&XXT$0yg!nmwP=X5)VE#neRT@xn2)wogcKc_UAt<+9bsn7>Yg$h`P#=RLJILp7<jQ<8{)JUKpG3@vM5wqthYs<=L^nb7K@(Hr7CcAiC4~0LaQkz;-E+o{f<c|>_>9ZD-Zp@S_J@1u@V$-$k-oVbfZiOUVJny0U$LlS`c5jI86dmDjmT&mMdjE!&H+MWiek$X3<JlgKJYQ%?D^*3<GkO;yth?#zdq_YMVE8R4(wPGOU1=H<iE8EUD=-!GSU6?Xq;5X$Ap-s=%1P*ae6RtftA3k)T8{mUM9pKow1)1$_u}$~Hvc)skls#H(Q+9}I&^0n8?ZfmLto6>dT?JZ5;hsQ?5aPN%DP35ltCG87o%k}P_9@#@Srk8s<_wJKMd$xJhX3g|t}uH7pJQEhaG?94*}*}!&u0DdhBy5kt^>pRW%{$K|1eWaph3F%h!4;jR|s)U#6`iMH<RsmJV{c%Dfx=Hmu&K2_sm*h*Mk5l9BU?!?`oosg}1p*Rgm%v32hq)>@;Zk8LHzZTNZ3VzJ)tjD7w@27vxQRDsNK5^qf$5;oUf5o~IcrP~*Fp25g``I|@PYU}NIlUO4OYVaPj3<~xaKCiGgA-HMK-^M;BE}lMS+&%FnxGyk3;|3moIzS?G|7A(})M#&3-X|-CKPB`w##6?Z@92(<i&duRs0r!@rxw>Dyua+Kv5oF@3FCybk?tu{q%Xc06PG%ej30TTGwkPTwuIUx(x2SU!Q3%}?+9e*A86I4*wP>`!0&k1w7#+?-D5xA(C>9!|?S-1f`Rcf<1OaNh6dZ(}W<Zicac!E2XK#Q*z05Qe4h"

@functools.lru_cache(maxsize=1)
def _model():
    data=json.loads(zlib.decompress(base64.b85decode(_MODEL_B85)))
    if len(data["trees"])!=12 or len(data["features"])!=14:
        raise ValueError("Invalid bundled trained model")
    return data

def _ema(vals,span):
    a=2/(span+1)
    current=vals[0]
    for x in vals[1:]:
        current=current+a*(x-current)
    return current

def _vector(spot,target,hminutes,candles,now):
    if not isinstance(candles,list):return None
    closed=[]
    for bar in candles:
        if not isinstance(bar,dict):return None
        t=bar.get("t")
        if not isinstance(t,(int,float)) or not math.isfinite(t) or t%60:
            return None
        if t+60<=now: closed.append(bar)
    closed=closed[-62:]
    if len(closed)<62 or any(b["t"]-a["t"]!=60 for a,b in zip(closed,closed[1:])):
        return None
    if now-closed[-1]["t"]-60>150:return None
    closes=[float(v["close"]) for v in closed]
    if min(closes)<=0:return None
    returns=[math.log(b/a) for a,b in zip(closes,closes[1:])]
    s15=statistics.stdev(returns[-15:])
    s45=statistics.stdev(returns[-45:])
    if s45<1e-10:return None
    candle=closed[-1]
    c,o,h,l=[float(candle[k]) for k in ("close","open","high","low")]
    if not 0<l<=min(c,o)<=max(c,o)<=h:return None
    volumes=[float(b.get("volume") or 0.) for b in closed[-20:]]
    median=statistics.median(volumes)
    vratio=min(volumes[-1]/median,100) if median>0 else 0.
    z=math.log(spot/target)/(s45*math.sqrt(hminutes))
    features=[z,hminutes,
              10000*returns[-1],
              10000*math.log(c/closes[-6]),
              10000*math.log(c/closes[-16]),
              10000*math.log(c/closes[-31]),
              10000*math.log(c/closes[-61]),
              10000*s15,10000*s45,vratio,
              10000*(c-o)/c,
              10000*(h-max(c,o))/c,
              10000*(min(c,o)-l)/c,
              10000*(_ema(closes,9)-_ema(closes,21))/c]
    return features if all(map(math.isfinite,features)) else None

def boosted_forecast(spot,market,candles,now):
    wait={"name":"axiom_gradient_boosted_btc",
          "method":"learned_residual_gradient_boosting_12_tree",
          "available":False,"prob_above":None,"prob_below":None,"side":"WAIT",
          "reason":"Need published strike and 62 completed genuine 1m bars",
          "independent":True,"trained":True,"calibrated":False,
          "training_strikes_are_synthetic":True}
    if not isinstance(market,dict):return wait
    try:
        spot=float(spot);target=float(market["target"])
        minutes=float(market["seconds_left"])/60
        if not all(math.isfinite(x) and x>0 for x in (spot,target,minutes)):
            return wait
        xs=_vector(spot,target,minutes,candles,now)
        if xs is None:return wait
        data=_model()
        baseline=.5*math.erfc(-xs[0]/math.sqrt(2))
        clipped=min(.985,max(.015,baseline))
        score=math.log(clipped/(1-clipped))
        for tree in data["trees"]:
            node=0
            while tree[node][0]!=-2:
                feat,threshold,left,right,_=tree[node]
                node=left if xs[feat]<=threshold else right
            score=max(-8.,min(8.,score+data["learning_rate"]*
                      max(-5.,min(5.,tree[node][4]))))
        p=1/(1+math.exp(-score))
        return {**wait,"available":True,"prob_above":round(p,6),
                "prob_below":round(1-p,6),
                "side":"ABOVE" if p>.5 else "BELOW",
                "reason":"Historically fitted BTC residual gradient boosting, active ensemble vote",
                "base_normal_probability":round(baseline,6),
                "trees":len(data["trees"]),
                "out_of_training_strike_range":abs(xs[0])>1.5,
                "labels_are_real_future_binance_prices":True}
    except (TypeError,ValueError,OverflowError,ZeroDivisionError,KeyError,IndexError):
        return wait
