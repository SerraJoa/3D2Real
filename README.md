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

## cadena.py

Parteix d'un primer base (triat per posició) i hi encadena fins a `--passos` bytes d'operació. Cada byte és un operador (2 bits: `+`, `-`, `×`, `^`) i un operand (6 bits: 1 … 64). Per exemple, p = 7 amb els bytes `[×3][+5][^2]` dona ((7·3)+5)² = 676.

Per a cada nombre de passos mostra el primer nombre no representat, la cobertura i els bits que caldria guardar (posició del primer + 8 per pas + marcador de longitud).

```bash
python3 cadena.py                                  # primers=8 bits, 3 passos, línia de 2^20
python3 cadena.py --primers 4 --passos 3 --limit 24
python3 cadena.py --interactiu
```

Amb línies grans i molts passos pot tardar minuts: cada pas prova els 256 bytes sobre tots els valors ja coberts.
