<?php
// Rep sessions de captura del mòbil en trossos i les desa a dades/<sessió>/. No llista, no descarrega i no esborra:
// les sessions es baixen per SFTP. Protocol (totes les peticions són POST amb la capçalera X-Token):
//   ?a=inici                      cos JSON {sessio, fitxers:[{nom, mida, sha256}]} → {ok, rebut:{nom: bytes_ja_rebuts}}
//   ?a=tros&sessio=&nom=&offset=  cos binari (màx. 8 MB)                          → {ok, offset}  | 409 {esperat}
//   ?a=fi&sessio=                 comprova que tot és complet i crea .complet     → {ok}
// config.php (al costat d'aquest fitxer) torna ['token_sha256' => '<hash>'] i es crea amb genera_token.py.
declare(strict_types=1);
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

const MAX_TROS = 8 * 1024 * 1024;
const MAX_FITXER = 3 * 1024 * 1024 * 1024;       // 3 GB per fitxer
const MAX_FITXERS = 12;
const EXT_OK = ['mp4', 'csv', 'json'];

function surt(int $codi, array $cos): never {
    http_response_code($codi);
    echo json_encode($cos, JSON_UNESCAPED_UNICODE);
    exit;
}

$cfg = @include __DIR__ . '/config.php';
if (!is_array($cfg) || empty($cfg['token_sha256'])) surt(500, ['ok' => false, 'error' => 'servidor sense configurar']);
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') surt(405, ['ok' => false, 'error' => 'només POST']);

$token = $_SERVER['HTTP_X_TOKEN'] ?? '';
if (!is_string($token) || !hash_equals($cfg['token_sha256'], hash('sha256', $token))) {
    sleep(1);                                    // frena la força bruta
    surt(403, ['ok' => false, 'error' => 'token']);
}

$base = __DIR__ . '/dades';
if (!is_dir($base) && !@mkdir($base, 0750, true)) surt(500, ['ok' => false, 'error' => 'no puc crear dades/']);
if (!file_exists("$base/.htaccess")) {           // la carpeta de dades no s'ha de poder servir per HTTP
    @file_put_contents("$base/.htaccess", "Require all denied\n<IfModule !mod_authz_core.c>\nDeny from all\n</IfModule>\n");
}

function sessio_ok(string $s): bool { return (bool) preg_match('/^[0-9]{8}_[0-9]{6}$/', $s); }
function nom_ok(string $n): bool {
    return (bool) preg_match('/^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$/', $n)
        && in_array(strtolower(pathinfo($n, PATHINFO_EXTENSION)), EXT_OK, true) && !str_contains($n, '..');
}
function llegeix_manifest(string $dir): array {
    $m = @json_decode((string) @file_get_contents("$dir/manifest.json"), true);
    return is_array($m) ? $m : [];
}
function mida_part(string $dir, string $nom): int {
    clearstatcache();
    if (is_file("$dir/$nom")) return (int) filesize("$dir/$nom");
    return is_file("$dir/$nom.part") ? (int) filesize("$dir/$nom.part") : 0;
}

$accio = $_GET['a'] ?? '';

if ($accio === 'inici') {
    $d = json_decode((string) file_get_contents('php://input'), true);
    if (!is_array($d) || !isset($d['sessio'], $d['fitxers']) || !is_array($d['fitxers'])) surt(400, ['ok' => false, 'error' => 'cos']);
    if (!sessio_ok((string) $d['sessio'])) surt(400, ['ok' => false, 'error' => 'sessio']);
    if (count($d['fitxers']) < 1 || count($d['fitxers']) > MAX_FITXERS) surt(400, ['ok' => false, 'error' => 'nombre de fitxers']);
    $dir = "$base/{$d['sessio']}";
    if (!is_dir($dir) && !@mkdir($dir, 0750)) surt(500, ['ok' => false, 'error' => 'no puc crear la sessió']);
    $man = llegeix_manifest($dir);
    $rebut = [];
    foreach ($d['fitxers'] as $f) {
        $nom = (string) ($f['nom'] ?? '');
        $mida = $f['mida'] ?? -1;
        $sha = strtolower((string) ($f['sha256'] ?? ''));
        if (!nom_ok($nom) || !is_int($mida) || $mida < 0 || $mida > MAX_FITXER || !preg_match('/^[0-9a-f]{64}$/', $sha)) {
            surt(400, ['ok' => false, 'error' => 'fitxer', 'nom' => $nom]);
        }
        if (isset($man[$nom]) && ($man[$nom]['sha256'] !== $sha || $man[$nom]['mida'] !== $mida)) {
            @unlink("$dir/$nom.part"); @unlink("$dir/$nom");        // el mateix nom amb un altre contingut: es torna a començar
        }
        $man[$nom] = ['mida' => $mida, 'sha256' => $sha];
        $rebut[$nom] = mida_part($dir, $nom);
    }
    file_put_contents("$dir/manifest.json", json_encode($man), LOCK_EX);
    @unlink("$dir/.complet");
    surt(200, ['ok' => true, 'rebut' => (object) $rebut]);
}

if ($accio === 'tros') {
    $s = (string) ($_GET['sessio'] ?? ''); $nom = (string) ($_GET['nom'] ?? '');
    $off = filter_var($_GET['offset'] ?? null, FILTER_VALIDATE_INT);
    if (!sessio_ok($s) || !nom_ok($nom) || $off === false || $off < 0) surt(400, ['ok' => false, 'error' => 'paràmetres']);
    $dir = "$base/$s"; $man = llegeix_manifest($dir);
    if (!isset($man[$nom])) surt(404, ['ok' => false, 'error' => 'fitxer no declarat']);
    if (is_file("$dir/$nom")) surt(409, ['ok' => false, 'esperat' => (int) filesize("$dir/$nom"), 'complet' => true]);
    $part = "$dir/$nom.part";
    $tinc = is_file($part) ? (int) filesize($part) : 0;
    if ($off !== $tinc) surt(409, ['ok' => false, 'esperat' => $tinc]);
    $dades = (string) file_get_contents('php://input', false, null, 0, MAX_TROS + 1);
    $n = strlen($dades);
    if ($n < 1 || $n > MAX_TROS || $tinc + $n > $man[$nom]['mida']) surt(400, ['ok' => false, 'error' => 'mida del tros']);
    if (file_put_contents($part, $dades, FILE_APPEND | LOCK_EX) !== $n) surt(500, ['ok' => false, 'error' => 'escriptura']);
    $nou = $tinc + $n;
    if ($nou === $man[$nom]['mida']) {
        if (!hash_equals($man[$nom]['sha256'], (string) hash_file('sha256', $part))) {
            @unlink($part);
            surt(422, ['ok' => false, 'error' => 'sha256 no coincideix', 'esperat' => 0]);
        }
        rename($part, "$dir/$nom");
    }
    surt(200, ['ok' => true, 'offset' => $nou]);
}

if ($accio === 'fi') {
    $s = (string) ($_GET['sessio'] ?? '');
    if (!sessio_ok($s)) surt(400, ['ok' => false, 'error' => 'sessio']);
    $dir = "$base/$s"; $man = llegeix_manifest($dir);
    if (!$man) surt(404, ['ok' => false, 'error' => 'sessió desconeguda']);
    $falten = [];
    foreach ($man as $nom => $info) if (!is_file("$dir/$nom") || filesize("$dir/$nom") !== $info['mida']) $falten[] = $nom;
    if ($falten) surt(409, ['ok' => false, 'error' => 'incompleta', 'falten' => $falten]);
    file_put_contents("$dir/.complet", (string) time());
    surt(200, ['ok' => true]);
}

surt(400, ['ok' => false, 'error' => 'acció']);
