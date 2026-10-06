# Desplegables

Generador de volums per a retallar: carrega una malla 3D (STL o OBJ) i obté els fitxers
per construir-la en paper o amb tall làser.

| Fase | Mòdul | Què fa |
|---|---|---|
| Importació | `papercraft.load_mesh` | STL/OBJ → malla neta (vèrtexs fusionats, sense cares degenerades) |
| Reducció | `papercraft.simplify`, `scale_to` | nombre de cares i mida final en mm |
| Branca 1: desplegable | `papercraft.py` | pàgines de paper per plegar i enganxar (vegeu més avall) |
| Branca 2: cares | `cares.py` | plaques per a làser, una per zona plana, amb suports per dins |
| Branca 3: laminació | `laminacio.py` | capes per a làser per apilar, amb columnes passants |
| Planxes | `laser.py` | peces planes comunes i col·locació a la planxa (vermell = tallar, blau = gravar) |
| Decoració | `decor.py`, `dibuix.py` | textures, imatges, patrons i dibuixos a les cares, amb o sense marc |
| Vista del muntatge | `visor.py` | el resultat de cada branca en 3D, muntat, per girar, separar i tallar |

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
   **Zones naturals** (activat per defecte): les cares que han quedat en peces petites són
   els problemes. Els propers (a menys de 6 cares) s'ajunten amb el camí de cares més curt
   en una zona pròpia: una tira o arbre estret, la peça més petita que en tanca el màxim
   alhora. Una tira estreta té tots els vèrtexs a la vora i es desplega sense escletxes, i
   en treure-la, els vèrtexs problemàtics de la resta també queden a la vora. Es repeteix
   amb els problemes nous (fins a 4 rondes) i es queda el millor resultat.
   **Arestes marcades** (opcional): es parteix primer per les arestes que pleguen més que
   l'angle triat, cada zona es desplega per separat i després les peces es tornen a unir
   mentre hi càpiguen, no s'escampin i quedi lloc per a les pestanyes.
4. **Pestanyes**: un trapezi a un dels dos costats de cada costura. Els trossos d'una
   mateixa aresta comparteixen número. Si una pestanya topa:
   - només amb altres pestanyes i poc (≤35 % de l'àrea) → s'encongeix una mica;
   - només amb altres pestanyes i molt → **es denten totes dues** com un engranatge: dents
     alternades perpendiculars a l'aresta, amb 0,4 mm de joc, i cadascuna conserva la vora;
   - si no es poden dentar sense deixar trossos solts → es passa a l'altre costat de la costura;
   - amb una cara, o no hi ha cap altra opció → es retalla.
5. **Pàgines** (A4, A3, Carta): les peces es col·loquen segons la seva forma real, no per
   capses. La pàgina és una graella d'1 mm; cada peça, de la més gran a la més petita,
   prova uns 30 girs i es queda el lloc lliure que deixa la seva vora de baix més amunt
   (la cerca es fa amb FFT). Entre peces hi ha 3 mm de separació. Cada pàgina recorda les
   formes que ja no hi caben (les peces repetides, com els suports, no les tornen a provar), i
   un gir que ja no pot deixar la vora de baix més amunt que el millor trobat no es prova: el
   temps creix en línia recta amb el nombre de peces.

## Branca 2: cares (làser)

- Cada zona plana és una placa del gruix del material; la cara de fora coincideix amb la
  superfície del model i el gruix creix cap endins.
- A cada aresta, les dues plaques es retiren el mínim perquè els gruixos no xoquin (es
  calcula a la secció de l'aresta; serveix per a arestes convexes i còncaves), més mitja
  **separació entre cares** si se'n vol (làmpades).
- **Suports encaixats** (per defecte): un arc perpendicular a l'aresta que ressegueix la cara
  interior de les dues plaques, amb dos tenons per braç que entren en ranures de les
  plaques (0,1 mm de joc); als racons còncaus, l'arc passa per darrere la cantonada. Els
  tenons travessen la placa: es veuen com a petits rectangles a fora.
- **Suports enganxats**: un estel per dins, del tot invisible.
- Primer es posen els suports que uneixen totes les plaques (arbre, arestes llargues
  primer); cada suport es mou al llarg de l'aresta o s'escurça fins que cap dins les dues
  plaques i no en toca cap altre. També es comprova en 3D que l'arc no toqui cap altre
  suport ni cap altra placa per dins (als vèrtexs on es troben moltes plaques, com la punta
  d'un con).
- **Costelles interiors**: si hi ha plaques massa estretes per a suports (la punta d'un con),
  el grup es tanca amb una costella: la secció del model en un pla, menys el gruix de les
  plaques i buidada per dins, amb un tenó a cada placa que travessa. Es retalla amb la
  secció real de totes les plaques que talla, i la ranura de cada tenó segueix el biaix de
  la placa al llarg de tot el gruix. Es tria el pla que
  uneix més grups (i, a igualtat, la costella més petita). Si les costelles no milloren el
  resultat, no se'n posen.
- **Distància entre suports** d'una mateixa aresta (80 mm per defecte): amb la llargada dels
  braços, tria entre pocs suports grans o molts de petits, que caben millor a les plaques
  estretes.
- **Més suports i més petits quan topen**: primer cada aresta rep el suport més gran que hi
  cap; si no n'hi cap cap, se'n proven més i més petits. Després, quan totes les arestes ja
  tenen el seu, les que s'han quedat amb suports petits proven de canviar-los per diversos de
  mitjans (més braç total), sense treure lloc a cap altra aresta.
- La cerca de costelles mira primer, només amb l'alçada dels vèrtexs, quants grups pot unir
  cada pla com a molt (plaques que talla, prou grans per a una ranura i no paral·leles al pla)
  i construeix primer les dels plans que en poden unir més; descarta els que ja no poden
  igualar la millor, i les costelles candidates es reaprofiten d'una ronda a l'altra. Les
  alçades a menys de mig gruix l'una de l'altra i les direccions a menys de 2° es proven un
  sol cop (donen pràcticament la mateixa costella).
- **Xamfrà de les plaques** (1 mm per defecte a l'app): talla les cantonades que punxen del
  contorn de les plaques, per a l'efecte (sobretot amb llum a dins). Els forats i les ranures
  no es toquen.
- **Punta del suport a l'escletxa**: amb espai entre cares, la punta de cada suport omple
  l'escletxa entre les dues plaques fins a la cara de fora (enrasada), i la cantonada de
  fora s'arrodoneix amb el radi del xamfrà de les plaques. En un racó còncau l'arrodoniment
  sortiria del model i la cantonada queda viva.
- **Xamfrà dels tenons** (0,5 mm per defecte; 0,5–1 mm): a les puntes dels tenons de suports
  i costelles, perquè entrin més fàcilment a les ranures.
- Els suports entren cap a dins la meitat que abans: l'arc té un gruix de max(1,25 × gruix,
  4 mm) i l'estel una fondària del 30 % del braç.
- **Cerca de costelles ràpida** (opcional): amb formes arrodonides hi ha moltes plaques
  petites i molts grups solts, i la cerca completa pot trigar molts minuts. La ràpida prova
  menys plans i s'atura als 10 s, però pot deixar més grups sense unir.
- On un suport creua una costella, s'encaixen **a mitja fusta**: el suport s'osca des d'una
  punta fins a la meitat del creuament i la costella des de l'altra, amb el gruix de l'altra
  peça vist de biaix i 0,1 mm de joc. Si no es pot (cap punta no queda a la vora), el suport
  esquiva la costella.
- Gravat a la cara interior (la que queda amunt en tallar): número de placa, número
  d'aresta i on va cada suport.

## Branca 3: laminació (làser)

- Capes horitzontals del gruix del material, tallades pel pla mig de cada capa.
- **Columnes passants**: forats alineats que travessen capes consecutives per posar-hi tiges;
  cada tros en rep dos si hi caben (fixen posició i gir), a 2 mm de la vora i a dos
  diàmetres entre elles. Es dona la llista de tiges amb la llargada.
- Gravat a la cara de dalt: número de capa (llegible = cara amunt), fletxa d'orientació
  comuna, contorn de la capa de sobre (continu) i de la de sota (ratlles).
- **Buidar** (opcional, 6 mm a la interfície): cada capa perd la seva secció retirada un
  gruix de paret, intersecada amb la de les capes veïnes fins a aquest gruix amunt i avall;
  així la cavitat no arriba mai a la superfície i les capes de dalt i de baix fan de tapa.
  Les columnes es trien abans de buidar: al voltant de cada una queda una anella de
  material unida a la paret per un pont, i si el buidat parteix una capa, es torna a unir
  amb un pont. Les peces petites poden anar dins la cavitat de les grans a la planxa.
- **Alineació amb costella** (per defecte quan es buida): en lloc de columnes, una costella
  vertical dins la cavitat, seguint-ne l'eix llarg, amb una dent a cada capa que entra a
  dues osques de la paret (mitja paret de fondària, 0,1 mm de joc): fixa la capa en totes
  direccions i en el gir. Es munta començant per la capa més ampla i enfilant les altres
  cap amunt (per dalt) i cap avall (per baix): cada capa passa per trams de costella que
  caben dins les seves osques. Només es parteix a les cintures (on la cavitat s'estreny i
  torna a eixamplar-se), i dos trams comparteixen la capa de la cintura (mitja dent
  cadascun). Les instruccions diuen l'ordre. Les peces que la costella no toca (tapes,
  trossos massissos) van amb columnes.

## Decoració de les cares (paper i làser)

Una **cara** és una zona plana del model, amb el mateix número que les plaques (C1, C2…).
Cada cara té coordenades pròpies en mm, vista des de fora i amb l'amunt del model cap amunt.
A la interfície es veuen numerades en dues vistes 3D i es poden triar una, diverses o totes.

- **Textura del model**: carrega un OBJ amb el seu MTL i imatges (o un GLB). Encara que la
  malla se simplifiqui, cada triangle nou pren les UV del triangle original més proper.
- **Imatge**: una imatge per cara, que omple (retallant) o s'encabeix a la cara.
- **Patró**: ratlles, quadrícula, punts, hexàgons, color pla o text, amb separació, gruix,
  angle i color.
- **Dibuix a mà**: un llenç amb la forma de la cara on es dibuixa amb el ratolí o el dit.
- **Marc**: deixa una vora sense decorar del gruix triat (0 = sense marc).

Al **paper**, la decoració s'imprimeix a cada triangle retallada al triangle i al marc.
Al **làser** (cares), es pot **gravar** (imatges en ràster, vectors en blau; la placa es talla
amb la cara de fora amunt i les seves marques de muntatge passen a referència, en verd),
**tallar** (forats: zones fosques d'una imatge, cel·les de quadrícula i hexàgons, punts,
ratlles i traços del dibuix; sempre amb un marc mínim de 3 mm des de la vora de la placa i
2 mm lluny de ranures i suports) o fer **totes dues coses**.

## Vista del model

En carregar un model, es veu tal com s'ha carregat i, al costat, com queda amb la
simplificació triada (amb totes les arestes, per veure'n els triangles) i a quina mida. Els
models molt grans es mostren amb una còpia de 60.000 cares com a molt.

## Vista del muntatge

Sota el resultat de cada branca hi ha el model muntat en 3D: les peces de paper plegades
(un color per peça), les plaques amb els suports i les costelles, o les capes amb la
costella i les tiges. És un visor WebGL propi, sense dependències externes.

- **Girar**: arrossega (ratolí o un dit). **Ampliar**: roda o pessic. **Doble clic**: vista
  inicial.
- **Separa**: les peces s'allunyen del centre (plaques i paper), les capes s'obren cap
  amunt i la costella surt de costat.
- **Tall x / y / z**: treu la banda del model que mira a la càmera fins al punt triat, per
  veure'n l'interior (cavitat, costelles, suports).
- Un botó per tipus de peça: sòlid ● → transparent ◌ → amagat ○ (per exemple, plaques
  transparents per veure els suports).

Cada peça làser guarda on va (`Part.pose`: matriu 4×4 i gruix) abans de girar-la per a la
planxa. Els tests (`tests/test_visor.py`) comproven amb aquestes posicions que cap peça
muntada no comparteix volum amb cap altra.

## Llegenda (paper)

| Línia | Significat |
|---|---|
| contínua | tallar |
| ratlles | plec de vall (cap a tu) |
| punt i ratlla | plec de muntanya (enrere) |
| gris | pestanya: s'enganxa sota la cara amb el mateix número |
| número vermell | les dues vores amb el mateix número s'uneixen |

## Limitacions

- En superfícies corbes (esferes), tancar del tot el ventall d'un vèrtex deixa una escletxa
  massa estreta per a una pestanya. Les zones naturals ho resolen en gran part (esfera de
  320 cares: de 42 peces a 11), però en poden quedar algunes de petites.
- Les peces grans es fan tan grans com permet la pàgina: dues peces de mitja pàgina
  ramificades poden no compartir full encara que l'àrea total ho permeti.
- Una peça unida pot quedar amb forats interiors, que s'han de retallar per dins.

## Tests

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest
```
