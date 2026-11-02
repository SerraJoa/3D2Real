# Captura 3d2Real

Clon de l'app de captura de `048-escena-video` (paquet `cat.escena.captura3d`, no trepitja l'original) amb:
GPS + brúixola (`posicio.csv`, declinació al `meta.json`) i pujada a un servidor (`Pujada.java`).
Es descarrega des del PC per SFTP (`baixa_sessions.py`). L'APK no du cap clau SFTP: només un token que
permet pujar, no llegir ni esborrar.

## Compilar i instal·lar
    bash captura/app/build.sh     # APK a captura/app/build/captura.apk
    ~/Android/Sdk/platform-tools/adb install -r captura/app/build/captura.apk

## Servidor (un cop)
1. `python3 captura/genera_token.py` → imprimeix `config.php` i `pujada.json`.
2. Puja `captura/servidor/pujada.php` i el `config.php` generat a una carpeta del teu hosting, p. ex. `/captura/`.
   La carpeta `dades/` es crea sola, amb un `.htaccess` que la fa inaccessible per HTTP.
3. `python3 captura/prova_servidor.py https://EL-TEU-DOMINI/captura/pujada.php` (ha de sortir tot OK).
4. Al mòbil: copia el `pujada.json` a `Android/data/cat.escena.captura3d/files/` (amb `adb push` o el gestor de fitxers).

## Ús
Grava, prem **Puja** (reprèn si es talla; torna a prémer per cancel·lar) i al PC: `python3 captura/baixa_sessions.py`.
Les sessions queden a `dades/captures/<sessió>/` amb el sha256 comprovat.

## Estat
- Provat: compila; el client Java contra un servidor de referència (4 tests: trossos, represa, token, contingut canviat).
- NO provat: `pujada.php` en un PHP real (no n'hi ha a aquesta màquina; per això `prova_servidor.py`), `baixa_sessions.py` contra un SFTP real, i l'app al mòbil (GPS, brúixola i botó Puja).
