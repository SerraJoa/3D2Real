# 3D2Real — Instruccions d'ús

Converteix un model 3D en peces per construir-lo de veritat:

- **Desplegable de paper**: pàgines per imprimir, retallar, plegar i enganxar.
- **Cares (làser)**: plaques planes amb suports per dins, per tallar amb làser i muntar.
- **Laminació (làser)**: capes horitzontals per tallar i apilar.

---

## 1. Posar-la en marxa

### Windows (el més fàcil)

1. Instal·la **Python 3.10 o més nou** des de <https://www.python.org/downloads/>.
   A la primera pantalla de l'instal·lador marca **"Add python.exe to PATH"**.
2. Descarrega el projecte: a GitHub, **Code → Download ZIP**, i descomprimeix-lo
   (o `git clone https://github.com/SerraJoa/3D2Real`).
3. Fes **doble clic a `iniciar.bat`**.
   - El primer cop crea un entorn propi (carpeta `.venv`) i hi instal·la el que cal: uns
     minuts i cal internet.
   - Les vegades següents s'obre directament.
4. L'app s'obre al navegador (`http://localhost:8501`). Per aturar-la, tanca la finestra
   negra.

Per actualitzar: torna a descarregar el ZIP (o `git pull`) i obre `iniciar.bat`; si han
canviat les dependències, les reinstal·la sol.

### Mac / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

### A internet (sense instal·lar res)

A <https://share.streamlit.io>: **Create app**, repositori `SerraJoa/3D2Real`, branca `main`,
fitxer `app.py`, i a *Advanced settings* Python 3.11 o 3.12.

---

## 2. Carregar el model

Arrossega els fitxers al requadre de dalt:

| Tipus | Què cal carregar |
|---|---|
| STL | el fitxer `.stl` |
| OBJ amb textura | el `.obj`, el `.mtl` i les imatges (`.png`, `.jpg`), **tots alhora** |
| GLB / glTF | el fitxer `.glb` (ja porta la textura) |

Surt el nombre de cares i vèrtexs, i si porta textura.

### Orientació (🧭)

Si el model surt tombat, obre **Orientació del model**:

- **Eix del fitxer que va amunt**: *auto* posa drets els GLB (que es desen amb la Y amunt);
  si no queda bé, prova +Z, +Y, −Y…
- **Gir al voltant de la vertical**: 0°, 90°, 180° o 270°.
- **Descarrega el model reorientat (GLB)**: per guardar-lo ja ben girat.

---

## 3. Reduir el model

Per construir-lo cal un model amb poques cares (fins a 1000).

- **Simplificació — nombre de cares**: quantes en vols. Menys cares = menys peces i més fàcil
  de muntar; més cares = més fidel. Per començar, 150–400.
- **Mida final**: el costat més llarg de la peça acabada, en mm.
- **Reducció**:
  - **Respecta la forma** (recomanat): dona més triangles als detalls (relleu, vores i el
    dibuix de la textura, com ulls o boca) i tracta igual les zones equivalents.
  - **Ràpida**: només l'error global; més ràpida en models molt grans.
- **Pes dels detalls** (0–60, per defecte 30): quant es protegeixen els detalls respecte de la
  resta.
- **Simetria** (per defecte *no*): *auto* només s'aplica si el model ja és simètric; x, y o z
  la força amb aquell pla.
- **Harmonitzar** (activat): fa els triangles més regulars, sense perdre forma.

A sota hi ha dues vistes 3D: **el model carregat** i **el simplificat** (amb les arestes).
Arrossega per girar, roda o pessic per ampliar, doble clic per tornar a la vista inicial.
Ajusta les cares fins que el simplificat t'agradi.

---

## 4. Triar la branca

### 📄 Desplegable de paper

| Opció | Què fa |
|---|---|
| Paper | A4, A3 o Carta; *Apaïsat* per girar-lo |
| Numerar les cares | escriu C1, C2… a cada cara (útil amb decoració) |
| Amplada de pestanyes | 5 mm va bé; més ample enganxa millor però xoca més |
| Zones naturals | (recomanat) agrupa els trossos problemàtics en peces petites |
| Tallar per arestes marcades | parteix primer per les arestes que pleguen més que l'angle (0 = no) |

Prem **🚀 Generar desplegable**. Surten les pàgines, un resum (peces, pàgines, pestanyes) i
la vista del muntatge. **Descarrega les pàgines (SVG en un ZIP)** i imprimeix-les a escala
100 %.

**Llegenda**: línia contínua = tallar · ratlles = plec de vall (cap a tu) · punt i ratlla =
plec de muntanya (enrere) · gris = pestanya (s'enganxa sota la cara amb el mateix número) ·
números vermells iguals = vores que s'uneixen.

### 🔷 Cares (làser)

Cada zona plana del model és una placa del gruix del material; per dins porten suports.

| Opció | Què fa |
|---|---|
| Gruix del material | el del contraplacat / MDF / metacrilat (p. ex. 3 mm) |
| Planxa | mida de la planxa de la talladora |
| Espai entre cares | 0 = tancat; > 0 per a làmpades (la llum passa per les escletxes; la punta dels suports omple l'escletxa a cada suport) |
| Suports | *encaix*: arc amb tenons que entren en ranures (més ferm); *cola*: estel enganxat, invisible |
| Llargada dels braços | mida dels suports |
| Distància entre suports | amb els braços: pocs suports grans o molts de petits |
| Xamfrà de les plaques | cantonades tallades, per a l'acabat (i radi de la punta del suport a l'escletxa) |
| Xamfrà dels tenons | 0,5–1 mm perquè els tenons entrin més fàcilment |
| Cerca de costelles ràpida | per a formes arrodonides amb moltes cares (més ràpid, pot unir menys) |

Prem **🚀 Generar cares**. Un avís groc diu si queden plaques en grups solts (plaques massa
petites per a suports): a la vista 3D cada grup té un color. Les formes amb poques zones
planes (caixes, poliedres) donen millor resultat.

### 🥞 Laminació (làser)

| Opció | Què fa |
|---|---|
| Gruix del material | gruix de cada capa |
| Diàmetre de les tiges | per a les columnes que alineen les capes |
| Buidar: gruix de paret | 0 = capes massisses; amb paret, s'estalvia material |
| Alineació | *costella*: una peça vertical dins la cavitat (cal buidar); *columnes*: tiges passants |

Prem **🚀 Generar capes**.

### Planxes i muntatge (làser)

**Descarrega les planxes (SVG + muntatge en un ZIP)**. Colors: **vermell = tallar**,
**blau = gravar**, **verd = només referència**. El ZIP porta també les instruccions de
muntatge (també a l'apartat *Instruccions de muntatge* de l'app).

---

## 5. Decoració (paper i cares)

Obre **🎨 Decoració de les cares**. Les cares es veuen numerades en dues vistes 3D; tria'n
una, diverses o totes i què hi vols:

- **Textura del model** (si el model en porta).
- **Imatge**: una imatge per cara, que l'omple o s'hi encabeix.
- **Patró**: ratlles, quadrícula, punts, hexàgons, color o text.
- **Dibuix a mà**: dibuixa amb el ratolí o el dit sobre la forma de la cara.
- **Marc**: vora sense decorar (0 = sense marc).
- Al làser: **gravar**, **tallar** (forats; sempre deixa 3 mm de marc i respecta ranures i
  suports) o totes dues.

Prem **Aplica a les cares triades**.

---

## 6. La vista 3D del muntatge

Sota el resultat de cada branca:

- **Separa**: allunya les peces (les capes s'obren cap amunt).
- **Tall x / y / z** i el lliscador: treu la part que mira a la càmera per veure l'interior.
- Botons per tipus de peça: ● sòlid → ◌ transparent → ○ amagat (p. ex. plaques
  transparents per veure els suports).

---

## 7. Si alguna cosa no va

| Problema | Solució |
|---|---|
| `iniciar.bat` diu que no troba Python | instal·la'l marcant "Add python.exe to PATH" i torna-hi |
| Error instal·lant dependències | revisa la connexió i torna a obrir `iniciar.bat`; si persisteix, esborra la carpeta `.venv` |
| Tarda molt | baixa el nombre de cares; a *Cares*, activa la cerca de costelles ràpida |
| El model surt tombat | 🧭 Orientació del model |
| Peces que no caben a la planxa / pàgina | baixa la mida final o tria una planxa / paper més gran |
| La vista 3D surt en blanc | el navegador ha de tenir WebGL (Chrome, Firefox, Edge i Safari el porten) |
| Al desplegable hi ha trossos sense pestanya | enganxa'ls amb cinta per darrere (ho avisa l'app) |
