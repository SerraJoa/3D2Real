#!/usr/bin/env python3
"""
Cobertura de la línia dels naturals per diferents funcions generadores.

Per a cada funció calcula, fins a un límit:
  - el primer nombre natural NO representable,
  - quants nombres representa (cobertura),
  - el forat més gran entre valors representats,
  - quants bits de paràmetres fa servir i el màxim teòric (2^bits).

Exemples:
  python cobertura.py
  python cobertura.py --funcions potencia,mirall --primers 10 --exp 5 --desp 6
  python cobertura.py --funcions ona --limit 20
  python cobertura.py --interactiu
"""
import argparse
import math
import sys

FUNCIONS = {}


def funcio(nom, descripcio):
    def registra(f):
        FUNCIONS[nom] = (f, descripcio)
        return f
    return registra


def primers(quants):
    """Els primers `quants` nombres primers (garbell d'Eratòstenes)."""
    if quants <= 0:
        return []
    n = max(15, int(quants * (math.log(quants) + math.log(math.log(quants + 2)) + 2)))
    while True:
        garbell = bytearray([1]) * (n + 1)
        garbell[0] = garbell[1] = 0
        for i in range(2, int(n ** 0.5) + 1):
            if garbell[i]:
                garbell[i * i::i] = bytearray(len(range(i * i, n + 1, i)))
        ps = [i for i in range(n + 1) if garbell[i]]
        if len(ps) >= quants:
            return ps[:quants]
        n *= 2


def potencies(p, limit, exp_max):
    """p^1 .. p^exp_max mentre no passin del límit."""
    v, n = p, 1
    while v < limit and n <= exp_max:
        yield n, v
        v *= p
        n += 1


def marca(mapa, v, desp):
    """Marca v i, si hi ha desplaçament, tot l'interval [v-desp, v+desp]."""
    a, b = max(1, v - desp), min(len(mapa) - 1, v + desp)
    if a <= b:
        mapa[a:b + 1] = b"\x01" * (b - a + 1)


@funcio("lineal", "v·n: base v (bits de primers) per multiplicador n (bits d'exponent)")
def f_lineal(mapa, a):
    limit = len(mapa)
    for v in range(1, 2 ** a.primers + 1):
        for n in range(1, 2 ** a.exp + 1):
            if v * n >= limit:
                break
            marca(mapa, v * n, a.d)
    return a.primers + a.exp + a.desp_bits


@funcio("potencia", "p^n: p = primer a la posició k (bits de primers), n (bits d'exponent)")
def f_potencia(mapa, a):
    for p in primers(2 ** a.primers):
        for _, v in potencies(p, len(mapa), 2 ** a.exp):
            marca(mapa, v, a.d)
    return a.primers + a.exp + a.desp_bits


@funcio("mirall", "p^n ± p^m (m<n): potència més el seu mirall cap avall i cap amunt")
def f_mirall(mapa, a):
    limit = len(mapa)
    for p in primers(2 ** a.primers):
        pw = [v for _, v in potencies(p, limit * p, 2 ** a.exp)]
        for i, A in enumerate(pw):
            if A < limit:
                marca(mapa, A, a.d)
            for B in pw[:i]:
                for v in (A - B, A + B):
                    if 0 < v < limit:
                        marca(mapa, v, a.d)
    # primer + exponent n + exponent m + 2 bits (sense mirall / - / +)
    return a.primers + 2 * a.exp + 2 + a.desp_bits


@funcio("ona", "dues sinusoidals desfasades 50%: freqüència (bits de primers), "
               "fase (bits d'exponent), mostra t (bits de desplaçament)")
def f_ona(mapa, a):
    limit = len(mapa)
    amp = (limit - 1) / 2
    nf, nph, nt = 2 ** a.primers, 2 ** a.exp, 2 ** a.desp
    for i in range(nf):
        w = math.pi * (i + 1) / nf
        for j in range(nph):
            ph = 2 * math.pi * j / nph
            for t in range(nt):
                for v in (math.sin(w * t + ph), math.cos(w * t + ph)):
                    x = int(amp * (1 + v))
                    if 0 < x < limit:
                        mapa[x] = 1
    # aquí el desplaçament fa de nombre de mostres; +1 bit per triar sin/cos
    return a.primers + a.exp + a.desp + 1


def analitza(nom, a):
    f, _ = FUNCIONS[nom]
    mapa = bytearray(2 ** a.limit)
    bits = f(mapa, a)
    mapa[0] = 1  # el 0 no compta
    primer_forat = mapa.find(0)
    primer_cobert = mapa.find(1, 1)
    forat_despres = mapa.find(0, primer_cobert) if primer_cobert != -1 else -1
    total = len(mapa) - 1
    coberts = mapa.count(1) - 1
    # forat més gran
    forat, pos, actual, inici = 0, None, 0, 0
    for i, x in enumerate(mapa):
        if x == 0:
            if actual == 0:
                inici = i
            actual += 1
            if actual > forat:
                forat, pos = actual, inici
        else:
            actual = 0
    return {
        "nom": nom,
        "bits": bits,
        "primer_no": primer_forat if primer_forat != -1 else None,
        "primer_cobert": primer_cobert if primer_cobert != -1 else None,
        "forat_despres": forat_despres if forat_despres != -1 else None,
        "coberts": coberts,
        "total": total,
        "forat": forat,
        "forat_pos": pos,
        "teoric": min(1.0, 2.0 ** (bits - a.limit)),
    }


def mostra(res, a):
    print(f"\nLínia: 1 .. 2^{a.limit}-1 ({2 ** a.limit - 1:,} nombres)  |  "
          f"primers={a.primers} bits ({2 ** a.primers:,})  exp={a.exp} bits ({2 ** a.exp})  "
          f"desp={a.desp} bits (±{a.d:,})")
    cap = f"{'funció':<10}{'bits':>6}{'1r no representat':>20}{'1r forat des del 1r cobert':>30}{'cobertura':>12}{'màx. teòric':>13}{'forat més gran':>26}"
    print(cap)
    print("-" * len(cap))
    for r in res:
        pn = f"{r['primer_no']:,}" if r["primer_no"] is not None else "cap (tot cobert)"
        forat = f"{r['forat']:,} a {r['forat_pos']:,}" if r["forat"] else "-"
        if r["primer_cobert"] is None:
            fd = "res cobert"
        elif r["forat_despres"] is None:
            fd = f"cap (des de {r['primer_cobert']:,})"
        else:
            fd = f"{r['forat_despres']:,} (cobert des de {r['primer_cobert']:,})"
        print(f"{r['nom']:<10}{r['bits']:>6}{pn:>20}{fd:>30}{r['coberts'] / r['total']:>12.4%}"
              f"{r['teoric']:>13.4%}{forat:>26}")
    print("\nbits = bits de paràmetres que caldria guardar. Màx. teòric = 2^bits / 2^límit: "
          "cap funció pot cobrir més nombres que combinacions de paràmetres té.")


def parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--funcions", default=",".join(FUNCIONS),
                   help=f"llista separada per comes: {', '.join(FUNCIONS)} (per defecte, totes)")
    p.add_argument("--primers", type=int, default=8, help="bits per a la posició del primer / base (defecte 8)")
    p.add_argument("--exp", type=int, default=4, help="bits per a l'exponent / multiplicador / fase (defecte 4)")
    p.add_argument("--desp", type=int, default=0,
                   help="bits del desplaçament: cobreix ±(2^desp - 1) al voltant de cada punt (defecte 0)")
    p.add_argument("--limit", type=int, default=24, help="mida de la línia en bits: 1 .. 2^limit (defecte 24, màx. 30)")
    p.add_argument("--interactiu", action="store_true", help="demana els valors i torna a calcular en bucle")
    return p


def prepara(a):
    if not 4 <= a.limit <= 30:
        sys.exit("--limit ha d'estar entre 4 i 30")
    a.d = 2 ** a.desp - 1 if a.desp > 0 else 0
    a.desp_bits = a.desp + 1 if a.desp > 0 else 0  # +1 pel signe
    noms = [n.strip() for n in a.funcions.split(",") if n.strip()]
    dolents = [n for n in noms if n not in FUNCIONS]
    if dolents:
        sys.exit(f"Funcions desconegudes: {', '.join(dolents)}. Disponibles: {', '.join(FUNCIONS)}")
    return noms


def executa(a):
    noms = prepara(a)
    mostra([analitza(n, a) for n in noms], a)


def interactiu(a):
    print("Mode interactiu. Prem Enter per mantenir el valor actual, 'q' per sortir.")
    for nom, (_, desc) in FUNCIONS.items():
        print(f"  {nom:<9} {desc}")
    while True:
        try:
            for camp in ("funcions", "primers", "exp", "desp", "limit"):
                actual = getattr(a, camp)
                r = input(f"{camp} [{actual}]: ").strip()
                if r.lower() == "q":
                    return
                if r:
                    setattr(a, camp, r if camp == "funcions" else int(r))
            executa(a)
            print()
        except ValueError:
            print("Valor no vàlid, torna-ho a provar.")
        except SystemExit as e:
            print(e)
        except (EOFError, KeyboardInterrupt):
            print()
            return


if __name__ == "__main__":
    args = parser().parse_args()
    if args.interactiu:
        interactiu(args)
    else:
        executa(args)
