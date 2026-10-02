# compressió

Eines per explorar quins nombres naturals es poden representar amb funcions generadores (potències de primers, miralls, sinusoidals…) i quins queden fora.

## cobertura.py

Calcula, per a cada funció i fins a un límit:

- **1r no representat**: el primer natural que la funció no genera.
- **1r forat des del 1r cobert**: el mateix, però comptant des del primer valor que sí que genera.
- **cobertura**: percentatge de la línia 1 … 2^límit que queda representat.
- **màx. teòric**: 2^bits / 2^límit. Cap funció pot cobrir més nombres que combinacions de paràmetres té.
- **forat més gran**: l'interval més llarg sense cap valor representat.

### Funcions

| Nom | Què genera |
|---|---|
| `lineal` | v · n |
| `potencia` | pⁿ, amb p = primer a la posició k |
| `mirall` | pⁿ ± pᵐ (m < n) |
| `ona` | dues sinusoidals desfasades un 50 % (sin i cos) |

### Paràmetres

| Opció | Significat | Defecte |
|---|---|---|
| `--primers` | bits per a la posició del primer (o base / freqüència) | 8 |
| `--exp` | bits per a l'exponent (o multiplicador / fase) | 4 |
| `--desp` | bits de desplaçament: cobreix ±(2^desp − 1) al voltant de cada punt (a `ona`, nombre de mostres) | 0 |
| `--limit` | mida de la línia en bits (4–30) | 24 |
| `--funcions` | llista separada per comes | totes |
| `--interactiu` | demana els valors i recalcula en bucle | |

### Exemples

```bash
python3 cobertura.py
python3 cobertura.py --funcions potencia,mirall --primers 12 --exp 4 --desp 6
python3 cobertura.py --interactiu
```

Només fa servir la biblioteca estàndard de Python 3. Amb `--limit 30` necessita uns 1 GB de RAM.
