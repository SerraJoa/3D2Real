#!/usr/bin/env python3
"""
Gràfica: valor màxim representable amb b bits vs. el primer que hi ha a la
posició 2^b de la llista de primers.

  - Valor directe:      amb b bits es pot escriure fins a 2^b - 1.
  - Primer per posició: amb b bits es pot apuntar fins al primer número 2^b.

Genera grafica_primers.html (autònom, sense dependències). Els primers fins a
--exactes bits es calculen exactament amb un garbell; a partir d'aquí s'usa
l'aproximació asimptòtica de p_n (error relatiu < 0,1 % per a n > 10^6).

  python grafica_primers.py
  python grafica_primers.py --exactes 20 --max-bits 8192
"""
import argparse
import json
import math


def primers_fins(n):
    garbell = bytearray([1]) * (n + 1)
    garbell[0] = garbell[1] = 0
    for i in range(2, int(n ** 0.5) + 1):
        if garbell[i]:
            garbell[i * i::i] = bytearray(len(range(i * i, n + 1, i)))
    return garbell


def primer_n_exacte(posicions):
    """{k: p_k} per a les posicions demanades (k comença a 1: p_1 = 2)."""
    kmax = max(posicions)
    limit = max(15, int(kmax * (math.log(kmax) + math.log(math.log(kmax + 2)) + 2)))
    garbell = primers_fins(limit)
    volgudes, res, k = set(posicions), {}, 0
    for i, es in enumerate(garbell):
        if es:
            k += 1
            if k in volgudes:
                res[k] = i
                if len(res) == len(volgudes):
                    break
    return res


def log2_primer_n_aprox(b):
    """log2(p_n) per a n = 2^b, amb n(ln n + ln ln n - 1 + (ln ln n - 2)/ln n)."""
    ln_n = b * math.log(2)
    lln = math.log(ln_n)
    factor = ln_n + lln - 1 + (lln - 2) / ln_n
    return b + math.log2(factor)


def dades(exactes, max_bits):
    bits = list(range(1, 65)) + [b for b in (96, 128, 192, 256, 384, 512, 768, 1024, 1536,
                                              2048, 3072, 4096, 6144, 8192, 12288, 16384) if b <= max_bits]
    bits = [b for b in bits if b <= max_bits]
    exacte = primer_n_exacte([2 ** b for b in bits if b <= exactes])
    files = []
    for b in bits:
        directe = float(b)  # 2^b - 1 ocupa exactament b bits
        if b <= exactes:
            p = exacte[2 ** b]
            lp, tipus, pv = math.log2(p), "exacte", str(p)
        else:
            lp, tipus, pv = log2_primer_n_aprox(b), "aproximat", None
        files.append({"b": b, "directe": directe, "primer": lp, "guany": lp - b,
                      "tipus": tipus, "p": pv,
                      "max": str(2 ** b - 1) if b <= 64 else None})
    return files


PLANTILLA = r"""<!doctype html>
<html lang="ca">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Primers per posició</title>
<style>
:root{--surface:#fcfcfb;--text:#0b0b0b;--text2:#52514e;--muted:#8a8984;--grid:#e6e5e0;
--s1:#2a78d6;--s2:#eb6834;--tip:#ffffff;--tipb:#d8d7d1}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--surface:#1a1a19;--text:#fff;
--text2:#c3c2b7;--muted:#8e8d86;--grid:#2f2f2d;--s1:#3987e5;--s2:#d95926;--tip:#262625;--tipb:#3a3a37}}
:root[data-theme="dark"]{--surface:#1a1a19;--text:#fff;--text2:#c3c2b7;--muted:#8e8d86;--grid:#2f2f2d;
--s1:#3987e5;--s2:#d95926;--tip:#262625;--tipb:#3a3a37}
*{box-sizing:border-box}
body{margin:0;background:var(--surface);color:var(--text);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:960px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:22px;margin:0 0 4px}
h2{font-size:16px;margin:28px 0 2px}
p{margin:4px 0;color:var(--text2)}
.legend{display:flex;gap:18px;flex-wrap:wrap;margin:10px 0 4px;color:var(--text2)}
.legend > span{display:inline-flex;align-items:center;gap:6px}
.sw{width:14px;height:3px;border-radius:2px;display:inline-block}
.chart{position:relative;width:100%}
svg{display:block;width:100%;height:auto;overflow:visible}
.axis text{fill:var(--muted);font-size:11px}
.axis line{stroke:var(--grid)}
.lbl{fill:var(--text2);font-size:12px}
.tip{position:absolute;pointer-events:none;background:var(--tip);border:1px solid var(--tipb);border-radius:8px;
padding:8px 10px;font-size:12px;color:var(--text);box-shadow:0 2px 8px rgba(0,0,0,.12);display:none;min-width:200px;z-index:2}
.tip b{font-weight:600}
.tip .r{display:flex;justify-content:space-between;gap:12px;color:var(--text2)}
.tip .r span:last-child{color:var(--text);font-variant-numeric:tabular-nums}
details{margin-top:28px}
summary{cursor:pointer;color:var(--text2)}
table{border-collapse:collapse;width:100%;margin-top:8px;font-variant-numeric:tabular-nums;font-size:12px}
th,td{text-align:right;padding:4px 8px;border-bottom:1px solid var(--grid)}
th{color:var(--text2);font-weight:600}
.wrap{overflow-x:auto}
</style>
</head>
<body>
<main>
<h1>Primers per posició</h1>
<p>Amb <b>b</b> bits pots escriure un nombre fins a 2<sup>b</sup>−1, o bé apuntar a la posició 2<sup>b</sup> de la llista de primers. Quin nombre més gran assoleix cada opció?</p>

<h2>Mida del valor més gran (en bits) segons els bits disponibles</h2>
<p>Eix horitzontal logarítmic. Les dues línies gairebé es toquen: el primer només és una mica més gran.</p>
<div class="legend">
  <span><i class="sw" style="background:var(--s1)"></i><span>Valor directe: 2<sup>b</sup>−1</span></span>
  <span><i class="sw" style="background:var(--s2)"></i><span>Primer a la posició 2<sup>b</sup></span></span>
</div>
<div class="chart" id="c1"></div>

<h2>Bits extra que guanya el primer</h2>
<p>log<sub>2</sub>(primer) − b. Creix molt lentament (com log<sub>2</sub>(b)): amb 1 KB (8.192 bits) només en són uns 12,5.</p>
<div class="chart" id="c2"></div>
<p style="margin-top:10px">Punts plens: primer calculat exactament. Punts buits: aproximació asimptòtica de p<sub>n</sub>.</p>

<details>
<summary>Veure la taula de dades</summary>
<div class="wrap"><table id="taula"><thead><tr><th>bits</th><th>valor directe màx.</th><th>primer a la posició 2<sup>b</sup></th><th>bits del primer</th><th>bits extra</th><th>càlcul</th></tr></thead><tbody></tbody></table></div>
</details>
</main>
<script>
const D = __DADES__;
const fmt = (x, d=2) => x.toLocaleString('ca-ES', {minimumFractionDigits:d, maximumFractionDigits:d});
const fint = s => s ? BigInt(s).toLocaleString('ca-ES') : '—';
const NS = 'http://www.w3.org/2000/svg';
function el(t, a, p){const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);if(p)p.appendChild(e);return e;}

function chart(id, series, yLabel, logY){
  const box=document.getElementById(id);box.innerHTML='';const W=Math.max(320,box.clientWidth), H=Math.round(Math.min(340,Math.max(240,W*0.55))), m={l:W<500?62:56,r:W<500?70:96,t:12,b:40};
  const svg=el('svg',{viewBox:`0 0 ${W} ${H}`,role:'img'},box);
  const xs=D.map(d=>d.b), x0=Math.log2(1), x1=Math.log2(xs[xs.length-1]);
  const X=b=>m.l+(Math.log2(b)-x0)/(x1-x0)*(W-m.l-m.r);
  let ys=[];series.forEach(s=>D.forEach(d=>ys.push(d[s.k])));
  const fy=v=>logY?Math.log2(Math.max(v,1e-9)):v;
  let y0=logY?0:Math.min(0,...ys), y1=Math.max(...ys.map(fy));
  if(!logY) y1=Math.ceil(y1/2)*2;
  const Y=v=>H-m.b-(fy(v)-y0)/(y1-y0)*(H-m.t-m.b);
  const ax=el('g',{class:'axis'},svg);
  const yt=logY?[1,4,16,64,256,1024,4096,16384].filter(v=>Math.log2(v)<=y1+.01):[...Array(Math.floor(y1/2)+1).keys()].map(i=>i*2);
  yt.forEach(v=>{el('line',{x1:m.l,x2:W-m.r,y1:Y(v),y2:Y(v)},ax);const t=el('text',{x:m.l-8,y:Y(v)+4,'text-anchor':'end'},ax);t.textContent=v.toLocaleString('ca-ES');});
  [1,2,4,8,16,32,64,128,256,512,1024,2048,4096,8192,16384].filter((b,i)=>b<=xs[xs.length-1]&&(W>=600||i%2===0)).forEach(b=>{
    const t=el('text',{x:X(b),y:H-m.b+18,'text-anchor':'middle'},ax);t.textContent=b>=1024?(b/1024)+'K':b;});
  const xl=el('text',{x:(m.l+W-m.r)/2,y:H-4,'text-anchor':'middle',class:'lbl'},svg);xl.textContent='bits disponibles (b) · 1K = 1.024 bits';
  const yl=el('text',{x:12,y:(m.t+H-m.b)/2,'text-anchor':'middle',class:'lbl',transform:`rotate(-90 12 ${(m.t+H-m.b)/2})`},svg);yl.textContent=yLabel;
  // marca 1 KB
  if(xs.includes(8192)){const g=el('line',{x1:X(8192),x2:X(8192),y1:m.t,y2:H-m.b,stroke:'var(--muted)','stroke-dasharray':'3 4'},svg);
    const t=el('text',{x:X(8192)-4,y:m.t+12,'text-anchor':'end',class:'lbl'},svg);t.textContent='1 KB';}
  series.forEach(s=>{
    el('path',{d:D.map((d,i)=>(i?'L':'M')+X(d.b).toFixed(1)+' '+Y(d[s.k]).toFixed(1)).join(''),fill:'none',stroke:s.c,'stroke-width':2,'stroke-linejoin':'round'},svg);
    if(s.dots) D.forEach(d=>el('circle',{cx:X(d.b),cy:Y(d[s.k]),r:3.5,fill:d.tipus==='exacte'?s.c:'var(--surface)',stroke:s.c,'stroke-width':1.5},svg));
    const last=D[D.length-1], t=el('text',{x:W-m.r+8,y:Y(last[s.k])+(s.dy||0)+4,class:'lbl'},svg);t.textContent=s.n;
  });
  // hover
  const cross=el('line',{y1:m.t,y2:H-m.b,stroke:'var(--muted)','stroke-width':1,visibility:'hidden'},svg);
  const dots=series.map(s=>el('circle',{r:5,fill:s.c,stroke:'var(--surface)','stroke-width':2,visibility:'hidden'},svg));
  const tip=document.createElement('div');tip.className='tip';box.appendChild(tip);
  const hit=el('rect',{x:m.l,y:m.t,width:W-m.l-m.r,height:H-m.t-m.b,fill:'transparent'},svg);
  function show(ev){
    const r=svg.getBoundingClientRect(), px=(ev.clientX-r.left)*W/r.width;
    let best=D[0];D.forEach(d=>{if(Math.abs(X(d.b)-px)<Math.abs(X(best.b)-px))best=d;});
    cross.setAttribute('x1',X(best.b));cross.setAttribute('x2',X(best.b));cross.setAttribute('visibility','visible');
    series.forEach((s,i)=>{dots[i].setAttribute('cx',X(best.b));dots[i].setAttribute('cy',Y(best[s.k]));dots[i].setAttribute('visibility','visible');});
    tip.innerHTML=`<b>${best.b.toLocaleString('ca-ES')} bits</b>`+
      `<div class="r"><span>Valor directe</span><span>${fmt(best.directe)} bits</span></div>`+
      `<div class="r"><span>Primer a 2<sup>b</sup></span><span>${fmt(best.primer)} bits</span></div>`+
      `<div class="r"><span>Bits extra</span><span>+${fmt(best.guany)}</span></div>`+
      (best.p?`<div class="r"><span>Primer</span><span>${fint(best.p)}</span></div>`:`<div class="r"><span>Càlcul</span><span>aproximat</span></div>`);
    tip.style.display='block';
    const bx=box.getBoundingClientRect(), tx=ev.clientX-bx.left, tw=tip.offsetWidth;
    tip.style.left=Math.min(Math.max(0,tx+14), bx.width-tw)+'px';
    tip.style.top=(ev.clientY-bx.top+14)+'px';
  }
  function hide(){tip.style.display='none';cross.setAttribute('visibility','hidden');dots.forEach(d=>d.setAttribute('visibility','hidden'));}
  hit.addEventListener('pointermove',show);hit.addEventListener('pointerleave',hide);hit.addEventListener('pointerdown',show);
}
function dibuixa(){
chart('c1',[{k:'directe',c:'var(--s1)',n:'Directe',dy:10},{k:'primer',c:'var(--s2)',n:'Primer',dy:-8}],'mida en bits (escala log)',true);
chart('c2',[{k:'guany',c:'var(--s2)',n:'Bits extra',dots:true}],'bits extra',false);
}
dibuixa();let rt;addEventListener('resize',()=>{clearTimeout(rt);rt=setTimeout(dibuixa,150);});
const tb=document.querySelector('#taula tbody');
D.forEach(d=>{const tr=document.createElement('tr');tr.innerHTML=`<td>${d.b.toLocaleString('ca-ES')}</td><td>${d.max?fint(d.max):'2^'+d.b+' − 1'}</td><td>${d.p?fint(d.p):'≈ 2^'+fmt(d.primer)}</td><td>${fmt(d.primer)}</td><td>+${fmt(d.guany)}</td><td>${d.tipus}</td>`;tb.appendChild(tr);});
</script>
</body>
</html>
"""


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exactes", type=int, default=22, help="bits fins on es calcula el primer exactament (defecte 22)")
    ap.add_argument("--max-bits", type=int, default=16384, help="bits màxims de l'eix horitzontal (defecte 16384)")
    ap.add_argument("--sortida", default="grafica_primers.html")
    a = ap.parse_args()
    files = dades(a.exactes, a.max_bits)
    with open(a.sortida, "w", encoding="utf-8") as f:
        f.write(PLANTILLA.replace("__DADES__", json.dumps(files)))
    print(f"Escrit {a.sortida}")
    print(f"{'bits':>6} {'bits primer':>12} {'extra':>7}  càlcul")
    for r in files:
        if r["b"] in (1, 2, 4, 8, 16, 22, 32, 64, 1024, 8192, 16384):
            print(f"{r['b']:>6} {r['primer']:>12.2f} {r['guany']:>+7.2f}  {r['tipus']}")
