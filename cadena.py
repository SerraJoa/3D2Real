#!/usr/bin/env python3
"""
Cadenes d'operadors: base + bytes d'operació encadenats.

Es parteix d'un primer p (triat per posició, amb --primers bits) i s'hi
apliquen fins a --passos operacions. Cada operació és un byte:

    2 bits alts  -> operador: 0 = +, 1 = -, 2 = ×, 3 = ^
    6 bits baixos -> operand: 1 .. 64

Exemple: p=7, bytes [× 3][+ 5][^ 2] -> ((7·3)+5)^2 = 676

Per a cada nombre de passos el programa diu quins nombres de la línia
1 .. 2^limit s'han pogut generar, el primer que no, i quants bits caldria
guardar (posició del primer + 8 bits per pas + marcador de longitud).

Exemples:
  python cadena.py
  python cadena.py --primers 8 --passos 3 --limit 20
  python cadena.py --interactiu
"""
import argparse
import math
import sys

from cobertura import primers

OPERADORS = "+-×^"
OPERANDS = range(1, 65)


def posicions(bits, fins):
    """Posicions dels bits a 1 de `bits` menors que `fins`."""
    s = bin(bits & ((1 << fins) - 1))[:1:-1]
    i = s.find("1")
    while i != -1:
        yield i
        i = s.find("1", i + 1)


def pas(actual, limit):
    """Tots els valors que s'obtenen aplicant un byte d'operació a `actual`."""
    mascara = (1 << limit) - 1
    nou = 0
    for c in OPERANDS:
        nou |= (actual << c) & mascara      # + c
        nou |= actual >> c                  # - c
    # × c i ^ e: només cal mirar els valors prou petits perquè el resultat hi càpiga
    petits = list(posicions(actual, (limit - 1) // 2 + 1))
    for v in petits:
        for c in range(2, min(64, (limit - 1) // v) + 1):  # × c
            nou |= 1 << (v * c)
        if v < 2:
            continue
        r, e = v * v, 2
        while r < limit and e <= 64:  # ^ e
            nou |= 1 << r
            r *= v
            e += 1
    return nou


def calcula(a):
    limit_valor = 2 ** a.limit
    inicis = [p for p in primers(2 ** a.primers) if p < limit_valor]
    actual = 0
    for p in inicis:
        actual |= 1 << p
    total = limit_valor - 1
    print(f"\nLínia: 1 .. 2^{a.limit}-1 ({total:,} nombres)  |  base: {len(inicis):,} primers "
          f"({a.primers} bits)  |  byte d'operació: 4 operadors × 64 operands")
    cap = f"{'passos':>6}{'bits':>7}{'1r no representat':>20}{'cobertura':>12}{'màx. teòric':>13}"
    print(cap)
    print("-" * len(cap))
    teoric = 0
    for d in range(a.passos + 1):
        if d > 0:
            actual |= pas(actual, limit_valor)
        actual &= ~1  # el 0 no compta
        coberts = actual.bit_count()
        forats = ~(actual | 1)
        primer_no = (forats & -forats).bit_length() - 1
        bits = a.primers + 8 * d + math.ceil(math.log2(a.passos + 1))
        teoric += 2 ** (a.primers + 8 * d)
        pn = f"{primer_no:,}" if primer_no < limit_valor else "cap (tot cobert)"
        print(f"{d:>6}{bits:>7}{pn:>20}{coberts / total:>12.4%}{min(1, teoric / total):>13.4%}")
        if coberts == total:
            break
    print("\nbits = posició del primer + 8 per pas + marcador de longitud. "
          "Màx. teòric = programes possibles / nombres de la línia.")


def parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--primers", type=int, default=8, help="bits per a la posició del primer base (defecte 8)")
    p.add_argument("--passos", type=int, default=3, help="nombre màxim de bytes d'operació encadenats (defecte 3)")
    p.add_argument("--limit", type=int, default=20, help="mida de la línia en bits: 1 .. 2^limit (defecte 20, màx. 26)")
    p.add_argument("--interactiu", action="store_true", help="demana els valors i torna a calcular en bucle")
    return p


def valida(a):
    if not 4 <= a.limit <= 26:
        raise ValueError("--limit ha d'estar entre 4 i 26")
    if not 0 <= a.primers <= 20 or a.passos < 0:
        raise ValueError("--primers ha d'estar entre 0 i 20 i --passos ha de ser positiu")


def interactiu(a):
    print("Mode interactiu. Prem Enter per mantenir el valor actual, 'q' per sortir.")
    while True:
        try:
            for camp in ("primers", "passos", "limit"):
                r = input(f"{camp} [{getattr(a, camp)}]: ").strip()
                if r.lower() == "q":
                    return
                if r:
                    setattr(a, camp, int(r))
            valida(a)
            calcula(a)
            print()
        except ValueError as e:
            print(f"Valor no vàlid: {e}")
        except (EOFError, KeyboardInterrupt):
            print()
            return


if __name__ == "__main__":
    args = parser().parse_args()
    if args.interactiu:
        interactiu(args)
    else:
        try:
            valida(args)
        except ValueError as e:
            sys.exit(str(e))
        calcula(args)
