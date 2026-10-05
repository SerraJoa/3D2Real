# Desplegables

Generador de volums de paper per a retallar: carrega una malla 3D (STL o OBJ) i obté
pàgines SVG per imprimir, retallar, plegar i enganxar.

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Què fa

1. **Simplifica** la malla al nombre de cares triat i l'**escala** a la mida final (mm).
2. **Desplega** en peces planes sense solapaments (`papercraft.unfold`):
   - les cares coplanars (una cara de caixa feta de molts triangles) van sempre juntes;
   - cada peça creix plegant primer per les arestes més planes i properes al centre;
   - cap peça no supera l'àrea imprimible del paper;
   - a cada aresta lliure es reserva l'espai d'una pestanya, de manera que no queden
     escletxes on no es pot enganxar res;
   - si en tancar el ventall d'un vèrtex les dues vores coincideixen, l'aresta es plega.
3. **Reenganxa** les peces molt petites a una veïna quan encara hi ha lloc per a pestanyes.
   **Línies naturals** (opcional, per defecte 40° a la interfície): primer es parteix la
   superfície per les arestes que pleguen més que l'angle triat, cada zona es desplega per
   separat (les zones de menys del 2 % de l'àrea s'uneixen a una veïna) i després les peces
   es tornen a unir per aquestes línies mentre hi càpiguen, no s'escampin i quedi lloc per
   a les pestanyes. Així, quan cal tallar, es talla per les línies del model.
4. **Pestanyes**: un trapezi a un dels dos costats de cada costura. Els trossos d'una
   mateixa aresta comparteixen número. Si una pestanya topa:
   - només amb altres pestanyes i poc (≤35 % de l'àrea) → s'encongeix una mica;
   - només amb altres pestanyes i molt → **es denten totes dues** com un engranatge: dents
     alternades perpendiculars a l'aresta, amb 0,4 mm de joc, i cadascuna conserva la vora;
   - si no es poden dentar sense deixar trossos solts → es passa a l'altre costat de la costura;
   - amb una cara, o no hi ha cap altra opció → es retalla.
5. **Pàgines**: gira cada peça a la capsa mínima i les col·loca en prestatges (A4, A3, Carta).

## Llegenda

| Línia | Significat |
|---|---|
| contínua | tallar |
| ratlles | plec de vall (cap a tu) |
| punt i ratlla | plec de muntanya (enrere) |
| gris | pestanya: s'enganxa sota la cara amb el mateix número |
| número vermell | les dues vores amb el mateix número s'uneixen |

## Limitacions

- En superfícies corbes sense línies marcades (esferes), tancar del tot el ventall d'un
  vèrtex deixa una escletxa massa estreta per a una pestanya. El desplegable prefereix
  deixar un triangle solt amb pestanyes: més peces, però totes es poden muntar.
- La col·locació a la pàgina fa servir capses rectangulars: peces corbes i llargues
  (anelles d'un tor) aprofiten poc el paper.
- Una peça unida pot quedar amb forats interiors, que s'han de retallar per dins.

## Tests

```bash
pip install pytest
pytest
```
