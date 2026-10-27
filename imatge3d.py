"""Imatge → malla 3D (GLB) amb Hunyuan3D 2.1 a través d'un ComfyUI en marxa.

L'app no porta cap model: només parla amb l'API de ComfyUI (per defecte 127.0.0.1:8188) amb el
workflow de `workflows/`. Necessita el punt de control `hunyuan_3d_v2.1.safetensors`.
La malla que torna ja va amb la Y amunt (Hunyuan la desa amb la Z amunt).
"""
import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import numpy as np
import scipy.ndimage as ndi
import trimesh
from PIL import Image, ImageDraw

WORKFLOW = Path(__file__).with_name("workflows") / "hunyuan21_imatge_a_3d.json"
WORKFLOWS_KLEIN = Path(__file__).with_name("workflows") / "klein_edit1.json"
Z_UP_TO_Y_UP = trimesh.transformations.rotation_matrix(np.radians(90), [1, 0, 0])


def prepara_imatge(data: bytes, mida: int = 512) -> bytes:
    """PNG quadrat RGB sobre blanc (el model espera l'objecte sol sobre fons blanc)."""
    im = Image.open(io.BytesIO(data))
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        fons = Image.new("RGB", im.size, "white")
        fons.paste(im, mask=im.split()[3])
        im = fons
    im = im.convert("RGB")
    costat = max(im.size)
    quadre = Image.new("RGB", (costat, costat), "white")
    quadre.paste(im, ((costat - im.width) // 2, (costat - im.height) // 2))
    out = io.BytesIO()
    quadre.resize((mida, mida), Image.LANCZOS).save(out, "PNG")
    return out.getvalue()


def _json(url: str, data: dict | None = None) -> dict:
    req = urllib.request.Request(url, json.dumps(data).encode() if data is not None else None,
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _puja(base: str, nom: str, png: bytes) -> None:
    b = uuid.uuid4().hex
    cos = (f"--{b}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{nom}\"\r\n"
           f"Content-Type: image/png\r\n\r\n").encode() + png + \
          (f"\r\n--{b}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n"
           f"--{b}--\r\n").encode()
    req = urllib.request.Request(f"{base}/upload/image", cos,
                                 {"Content-Type": f"multipart/form-data; boundary={b}"})
    urllib.request.urlopen(req, timeout=30).read()


ESTILS = {
    "normal": "single object, centered, three-quarter front view, clean studio product render, "
              "soft even lighting, no cast shadow, plain pure white background, full object in frame",
    "low poly": "low poly 3D model, simple faceted geometry with few large flat triangles, flat "
                "shading, solid flat colors per facet, centered, three-quarter front view, "
                "no cast shadow, plain pure white background, full object in frame",
}
NEGATIU = "blurry, text, watermark, multiple objects, cropped, background scenery, ground shadow"


def _workflow_imatge(prompt: str, estil: str, llavor: int, mida: int, passos: int) -> dict:
    """Z-Image Turbo (text → imatge) de ComfyUI: 8 passos, cfg 1, negatiu zero."""
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "z_image_turbo_bf16.safetensors",
                                                     "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_3_4b.safetensors",
                                                     "type": "lumina2", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "4": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": 3.0}},
        "5": {"class_type": "CLIPTextEncode",
              "inputs": {"clip": ["2", 0], "text": f"{prompt}, {ESTILS[estil]}"}},
        "6": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["5", 0]}},
        "7": {"class_type": "EmptySD3LatentImage",
              "inputs": {"width": mida, "height": mida, "batch_size": 1}},
        "8": {"class_type": "KSampler",
              "inputs": {"model": ["4", 0], "positive": ["5", 0], "negative": ["6", 0],
                         "latent_image": ["7", 0], "seed": llavor, "steps": passos, "cfg": 1.0,
                         "sampler_name": "res_multistep", "scheduler": "simple", "denoise": 1.0}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0],
                                                      "filename_prefix": "d2r_img"}},
    }


def _espera(base: str, pid: str, espera_max: float, progres=None) -> dict:
    t0 = time.time()
    while time.time() - t0 < espera_max:
        h = _json(f"{base}/history/{pid}").get(pid)
        if h:
            if h["status"]["status_str"] != "success":
                raise RuntimeError(f"ComfyUI ha fallat: {h['status']}")
            return h["outputs"]
        if progres:
            progres(time.time() - t0)
        time.sleep(1)
    raise RuntimeError("ComfyUI triga massa")


def genera_imatge(prompt: str, estil: str = "normal", base: str = "http://127.0.0.1:8188",
                  llavor: int | None = None, mida: int = 1024, passos: int = 8,
                  espera_max: float = 300) -> bytes:
    """Torna un PNG de l'objecte sol sobre fons blanc, apte per a `genera`.
    `estil`: clau d'`ESTILS` ("low poly" força cares planes i pocs polígons)."""
    base = base.rstrip("/")
    llavor = uuid.uuid4().int % 2**32 if llavor is None else llavor
    try:
        pid = _json(f"{base}/prompt",
                    {"prompt": _workflow_imatge(prompt, estil, llavor, mida, passos)})["prompt_id"]
        f = _espera(base, pid, espera_max)["10"]["images"][0]
        q = urllib.parse.urlencode({"filename": f["filename"], "subfolder": f["subfolder"],
                                    "type": f["type"]})
        with urllib.request.urlopen(f"{base}/view?{q}", timeout=60) as r:
            return r.read()
    except OSError as e:
        raise RuntimeError(f"No puc parlar amb ComfyUI a {base}: {e}") from e


def genera(imatge: bytes, base: str = "http://127.0.0.1:8188", passos: int = 30,
           espera_max: float = 900, progres=None) -> bytes:
    """Torna un GLB (Y amunt). Llança RuntimeError si ComfyUI falla o triga massa."""
    base = base.rstrip("/")
    nom = f"d2r_{uuid.uuid4().hex[:8]}.png"
    try:
        _puja(base, nom, prepara_imatge(imatge))
        wf = json.loads(WORKFLOW.read_text().replace("__IMAGE__", nom))
        wf["19:7"]["inputs"]["steps"] = passos
        wf["10"]["inputs"]["filename_prefix"] = "mesh/d2r"
        pid = _json(f"{base}/prompt", {"prompt": wf})["prompt_id"]
    except OSError as e:
        raise RuntimeError(f"No puc parlar amb ComfyUI a {base}: {e}") from e
    t0 = time.time()
    while time.time() - t0 < espera_max:
        h = _json(f"{base}/history/{pid}").get(pid)
        if h:
            if h["status"]["status_str"] != "success":
                raise RuntimeError(f"ComfyUI ha fallat: {h['status']}")
            f = h["outputs"]["10"]["3d"][0]
            q = urllib.parse.urlencode({"filename": f["filename"], "subfolder": f["subfolder"],
                                        "type": f["type"]})
            with urllib.request.urlopen(f"{base}/view?{q}", timeout=120) as r:
                return orienta(neteja(r.read()))
        if progres:
            progres(time.time() - t0)
        time.sleep(2)
    raise RuntimeError("ComfyUI triga massa")


def orienta(glb: bytes) -> bytes:
    m = trimesh.load(io.BytesIO(glb), file_type="glb", force="mesh")
    m.apply_transform(Z_UP_TO_Y_UP)
    return m.export(file_type="glb")


def neteja(glb: bytes, resolucio: int = 160) -> bytes:
    """Remalla la sortida de Hunyuan: té milers d'arestes no manifold (parts que es toquen) i
    cap reductor no hi arriba a poques cares (es queda a ~1.200 i arruga la forma). Es voxelitza,
    s'omple i es torna a extreure la superfície: queda estanca i manifold, sense perdre les parts
    fines més enllà d'un voxel (1/`resolucio` del costat més llarg)."""
    from skimage.measure import marching_cubes  # només cal per a aquesta funció

    m = trimesh.load(io.BytesIO(glb), file_type="glb", force="mesh")
    pas = float(m.extents.max()) / resolucio
    vox = m.voxelized(pas).fill()
    a = ndi.gaussian_filter(np.pad(vox.matrix, 3).astype(float), 1.0)
    v, f, _, _ = marching_cubes(a, 0.5)
    r = trimesh.Trimesh(v * pas + vox.translation - 3 * pas, f)
    if r.volume < 0:  # marching cubes les torna cap a dins
        r.invert()
    return r.export(file_type="glb")


# --- Malla nítida: el camp d'ocupació en brut, sense surface net ni `neteja` -----------------------
# Totes dues coses arrodoneixen les facetes que Hunyuan sí que dona (el surface net posa cada vèrtex
# a la mitjana dels talls i `neteja` difumina). Cal el node `SaveVoxelNpy` (comfy_nodes/) a ComfyUI.

def repara_plans(c: np.ndarray, vora: float = 0.3) -> np.ndarray:
    """El decodificador de Hunyuan a vegades deixa llesques senceres plenes (una placa que travessa
    tota la graella). Una llesca és dolenta si la franja del contorn, on l'objecte només hi toca de
    passada, és plena; se substitueix per la interpolació entre les veïnes bones. Les 2 primeres
    files de la vora no compten: el decodificador les deixa sempre buides."""
    c = c.copy()
    for ax in range(3):
        f = np.moveaxis(c, ax, 0)
        n, w = f.shape[1:], max(2, min(f.shape[1:]) // 16)
        franja = np.zeros(n, bool)
        franja[2:-2, 2:-2] = True
        franja[2 + w:-2 - w, 2 + w:-2 - w] = False
        anell = (f[:, franja] > 0.5).mean(1)
        dolentes = set(np.nonzero(anell > vora)[0].tolist())
        for x in sorted(dolentes):
            a, b = x - 1, x + 1
            while a in dolentes:
                a -= 1
            while b in dolentes:
                b += 1
            if a < 0 or b >= len(f):
                f[x] = 0.0
                continue
            t = (x - a) / (b - a)
            f[x] = f[a] * (1 - t) + f[b] * t
    return c


def malla_camp(c: np.ndarray, llindar: float = 0.5) -> trimesh.Trimesh:
    """Camp d'ocupació (D, H, W) → malla estanca i manifold, en coordenades de Hunyuan (Z amunt,
    costat llarg de -1 a 1). Marching cubes sense suavitzar; només la peça principal, sense buits."""
    from skimage.measure import marching_cubes

    c = repara_plans(np.asarray(c, dtype=np.float32))
    lab, _ = ndi.label(c > llindar)
    mida = np.bincount(lab.ravel())
    mida[0] = 0
    ple = ndi.binary_fill_holes(lab == mida.argmax())
    # fora de la peça principal i dins dels buits omplerts, el camp no pot creuar el llindar
    c = np.where(ple, np.maximum(c, llindar + 1e-3), np.minimum(c, llindar - 1e-3))
    v, f, _, _ = marching_cubes(np.pad(c, 1), llindar)
    v = (v - 1 - max(c.shape) / 2) / (max(c.shape) / 2)
    m = trimesh.Trimesh(v[:, ::-1], f)   # (z, y, x) → (x, y, z), com el VoxelToMesh de ComfyUI
    if m.volume < 0:
        m.invert()
    return m


# rotacions que porten cada eix (±X, ±Y, ±Z) a +Y: no se sap quin és l'amunt de la malla
_AMUNT = [trimesh.geometry.align_vectors(e, [0, 1, 0])[:3, :3]
          for e in ([1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1])]


def _rot(yaw: float, pitch: float, amunt: int = 2) -> np.ndarray:
    a, b = np.radians(yaw), np.radians(pitch)
    Ry = np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])
    Rx = np.array([[1, 0, 0], [0, np.cos(b), -np.sin(b)], [0, np.sin(b), np.cos(b)]])
    return Rx @ Ry @ _AMUNT[amunt]


def _silueta_imatge(img: Image.Image) -> np.ndarray:
    gris = np.asarray(img.convert("L"), float)
    m = ndi.binary_fill_holes(ndi.binary_closing(gris < 240, iterations=2))
    lab, n = ndi.label(m)
    return lab == np.argmax(np.bincount(lab.ravel())[1:]) + 1 if n else m


def _encaixa(Q: np.ndarray, mask: np.ndarray):
    """Escala i translació (s, tx, ty) perquè la capsa dels punts Q (x, y amunt) sigui la de la màscara."""
    ys, xs = np.nonzero(mask)
    s = 0.5 * ((ys.max() - ys.min()) / max(np.ptp(Q[:, 1]), 1e-9) + (xs.max() - xs.min()) / max(np.ptp(Q[:, 0]), 1e-9))
    tx = (xs.max() + xs.min()) / 2 - s * (Q[:, 0].max() + Q[:, 0].min()) / 2
    ty = (ys.max() + ys.min()) / 2 + s * (Q[:, 1].max() + Q[:, 1].min()) / 2
    return s, tx, ty


def camera_imatge(mesh: trimesh.Trimesh, mask: np.ndarray, mida: int = 160):
    """Càmera ortogràfica (eix amunt, gir, cabeceig, escala, translació) que fa coincidir la silueta
    de la malla amb la de la imatge. Torna (R, centre, s, tx, ty) en píxels de `mask`."""
    k = mida / mask.shape[0]
    petita = np.asarray(Image.fromarray(mask).resize((mida, mida), Image.NEAREST))
    c = mesh.bounds.mean(0)
    pts = np.vstack([mesh.vertices, mesh.triangles_center]) - c

    def iou(yaw, pitch, up):
        Q = pts @ _rot(yaw, pitch, up).T
        s, tx, ty = _encaixa(Q, petita)
        x = np.clip((tx + s * Q[:, 0]).astype(int), 0, mida - 1)
        y = np.clip((ty - s * Q[:, 1]).astype(int), 0, mida - 1)
        sil = np.zeros((mida, mida), bool)
        sil[y, x] = True
        sil = ndi.binary_fill_holes(ndi.binary_closing(sil, iterations=2))
        return (sil & petita).sum() / max((sil | petita).sum(), 1)

    _, yaw, pitch, up = max((iou(y, p, u), y, p, u) for u in range(6) for y in range(0, 360, 15)
                            for p in (-20, 0, 20))
    for pas in (6, 3, 1):
        _, yaw, pitch = max((iou(yaw + dy, pitch + dp, up), yaw + dy, pitch + dp)
                            for dy in (-pas, 0, pas) for dp in (-pas, 0, pas))
    R = _rot(yaw, pitch, up)
    s, tx, ty = _encaixa((mesh.vertices - c) @ R.T, mask)
    return R, c, s, tx, ty


def mascara_detalls(img: Image.Image, capses, dif: float = 35.0) -> np.ndarray:
    """Píxels de detall (ulls, nas, boca) dins de les capses (x0, y0, x1, y1), en fraccions de la
    imatge (com les dona un VL): els que es diferencien de tots els colors de la vora de la capsa,
    que són els de les cares del voltant (una capsa pot tocar-ne més d'una)."""
    from scipy.spatial import cKDTree
    a = np.asarray(img.convert("RGB"), float)
    H, W = a.shape[:2]
    out = np.zeros((H, W), bool)
    for x0, y0, x1, y1 in capses:
        # la capsa d'un VL és justa: s'eixampla perquè la vora sigui fons i no detall
        mx, my = 0.3 * (x1 - x0), 0.3 * (y1 - y0)
        X0, X1 = int(max(x0 - mx, 0) * W), int(np.ceil(min(x1 + mx, 1) * W))
        Y0, Y1 = int(max(y0 - my, 0) * H), int(np.ceil(min(y1 + my, 1) * H))
        z = a[Y0:Y1, X0:X1]
        vora = np.vstack([z[0], z[-1], z[:, 0], z[:, -1]])
        m = (cKDTree(vora).query(z.reshape(-1, 3))[0] > dif).reshape(z.shape[:2])
        lab, _ = ndi.label(ndi.binary_closing(m, iterations=2))
        dins = lab[int(y0 * H) - Y0:int(np.ceil(y1 * H)) - Y0, int(x0 * W) - X0:int(np.ceil(x1 * W)) - X0]
        m = np.isin(lab, np.unique(dins[dins > 0]))
        out[Y0:Y1, X0:X1] |= ndi.binary_fill_holes(m)
    return out


def pell_projectada(mesh: trimesh.Trimesh, imatge: bytes, detalls=None) -> trimesh.Trimesh:
    """La imatge d'origen com a textura de la malla: cada cara visible des de la càmera ajustada pren
    els píxels on cau (ulls, boca i colors acaben a Disseny com a «Pell»); les amagades, el color
    mitjà de l'objecte. Amb `detalls` (capses d'un VL, en fraccions) només hi queden els detalls
    sobre blanc: el que cal gravar al làser. La malla torna sense vèrtexs compartits (UV per cantonada)."""
    img = Image.open(io.BytesIO(prepara_imatge(imatge, 1024))).convert("RGB")
    W = img.width
    mask = _silueta_imatge(img)
    R, c, s, tx, ty = camera_imatge(mesh, mask)
    P = (mesh.vertices - c) @ R.T
    px = np.column_stack([tx + s * P[:, 0], ty - s * P[:, 1]])
    # visibilitat: índex de cara per píxel, pintant de lluny a prop (la Z de càmera mira cap a l'observador)
    ids = Image.new("I", (W, W), 0)
    d = ImageDraw.Draw(ids)
    for f in np.argsort(P[mesh.faces, 2].mean(1)):
        d.polygon([tuple(p) for p in px[mesh.faces[f]]], fill=int(f) + 1)
    vista = np.zeros(len(mesh.faces) + 1, bool)
    vista[np.unique(np.asarray(ids))] = True
    vista = vista[1:] & ((mesh.face_normals @ R.T)[:, 2] > 0)
    # franja de color neutre a sota de la imatge per a les cares amagades
    neutre = tuple(int(x) for x in np.median(np.asarray(img)[mask], 0))
    if detalls is not None:
        neutre = (255, 255, 255)
        img = Image.composite(img, Image.new("RGB", img.size, neutre),
                              Image.fromarray(mascara_detalls(img, detalls)))
    tex = Image.new("RGB", (W, W + 16), neutre)
    tex.paste(img, (0, 0))
    H = tex.height
    uv = np.column_stack([px[:, 0] / W, 1 - px[:, 1] / H])[mesh.faces]          # (F, 3, 2)
    uv[~vista] = (0.5, 8 / H)
    out = trimesh.Trimesh(mesh.vertices[mesh.faces].reshape(-1, 3), np.arange(len(mesh.faces) * 3).reshape(-1, 3),
                          process=False)
    out.visual = trimesh.visual.TextureVisuals(uv=uv.reshape(-1, 2), image=tex)
    return out


def pell_per_cares(mesh: trimesh.Trimesh, imatge: bytes, camera=None, cel: int | None = None,
                   detalls=None, mida: int = 1024) -> trimesh.Trimesh:
    """Textura per cara a partir del dibuix original. Cada cara objectiu té la seva cel·la a l'atles:
    el seu perímetre es projecta sobre el dibuix (càmera encaixada per silueta), es retalla i la imatge
    es deforma perquè cobreixi la cara (cada texel agafa el píxel on cau el seu punt 3D). Les cares
    obliqües queden estirades, no escapçades. Només s'hi pinta el que la càmera veu de debò: on una
    altra cara tapa el punt, o la cara mira d'esquena, queda el color mitjà de l'objecte.
    `camera`: (R, c, s, tx, ty) de `camera_imatge` (p. ex. la de la malla densa; si no, s'ajusta amb
    `mesh`). `detalls`: capses d'un VL; amb elles només es mantenen aquests detalls sobre blanc.
    Torna la malla sense vèrtexs compartits (UV per cantonada)."""
    from scipy import ndimage

    img = Image.open(io.BytesIO(prepara_imatge(imatge, mida))).convert("RGB")
    W = img.width
    mask = _silueta_imatge(img)
    R, c, s, tx, ty = camera if camera is not None else camera_imatge(mesh, mask)
    P = (mesh.vertices - c) @ R.T
    px = np.column_stack([tx + s * P[:, 0], ty - s * P[:, 1]])
    F = np.asarray(mesh.faces)
    n = len(F)
    ids = Image.new("I", (W, W), 0)
    d = ImageDraw.Draw(ids)
    for f in np.argsort(P[F, 2].mean(1)):                       # de lluny a prop: la cara més propera guanya
        d.polygon([tuple(p) for p in px[F[f]]], fill=int(f) + 1)
    ids = np.asarray(ids)
    davant = (mesh.face_normals @ R.T)[:, 2] > 0

    neutre = np.array(np.median(np.asarray(img)[mask], 0), float)
    arr = np.asarray(img, float)
    if detalls is not None:
        neutre = np.array([255.0, 255.0, 255.0])
        arr = np.where(mascara_detalls(img, detalls)[..., None], arr, neutre)

    dins = ndimage.binary_erosion(mask, iterations=2).astype(float)
    cols = int(np.ceil(np.sqrt(n)))
    k = cel or max(8, min(48, 4096 // cols))
    S = cols * k
    t = (np.arange(k) + 0.5) / k
    A, B = np.meshgrid(t, t, indexing="ij")                     # A al llarg de v0→v1, B de v0→v2
    fold = A + B > 1                                            # mig quadrat és fora del triangle: es plega a l'aresta
    A, B = np.where(fold, 1 - B, A), np.where(fold, 1 - A, B)
    atles = np.empty((S, S, 3))
    atles[:] = neutre
    for f0 in range(0, n, 256):                                 # per tongades: la memòria no depèn de n
        fs = np.arange(f0, min(f0 + 256, n))
        T = mesh.vertices[F[fs]]                                # (m, 3, 3)
        X = T[:, 0, None, None, :] + A[None, :, :, None] * (T[:, 1] - T[:, 0])[:, None, None, :] \
            + B[None, :, :, None] * (T[:, 2] - T[:, 0])[:, None, None, :]
        Q = (X - c) @ R.T
        u, v = tx + s * Q[..., 0], ty - s * Q[..., 1]           # píxels del dibuix
        vist = np.zeros(u.shape, bool)
        ui, vi = np.round(u).astype(int), np.round(v).astype(int)
        for dx in (-1, 0, 1):                                   # un píxel de marge: les vores no es perden
            for dy in (-1, 0, 1):
                xx, yy = np.clip(ui + dx, 0, W - 1), np.clip(vi + dy, 0, W - 1)
                vist |= ids[yy, xx] == (fs + 1)[:, None, None]
        vist &= davant[fs][:, None, None]
        vist &= ndimage.map_coordinates(dins, [v, u], order=0, mode="constant") > 0.5   # el fons no és pell
        col = np.stack([ndimage.map_coordinates(arr[..., q], [v, u], order=1, mode="nearest")
                        for q in range(3)], -1)
        col = np.where(vist[..., None], col, neutre)
        for i, f in enumerate(fs):
            ci, cj = f % cols, f // cols
            atles[cj * k:(cj + 1) * k, ci * k:(ci + 1) * k] = col[i].transpose(1, 0, 2)   # (B, A) → files, columnes
    ci, cj = np.arange(n) % cols, np.arange(n) // cols
    pad = 0.5
    cant = np.array([[0, 0], [1, 0], [0, 1]], float)           # (A, B) de cada cantonada
    uv = np.stack([(ci[:, None] * k + pad + cant[None, :, 0] * (k - 2 * pad)) / S,
                   1 - (cj[:, None] * k + pad + cant[None, :, 1] * (k - 2 * pad)) / S], -1)
    out = trimesh.Trimesh(mesh.vertices[F].reshape(-1, 3), np.arange(n * 3).reshape(-1, 3), process=False)
    out.visual = trimesh.visual.TextureVisuals(uv=uv.reshape(-1, 2),
                                               image=Image.fromarray(atles.clip(0, 255).astype(np.uint8)))
    return out


SENSE_DETALLS = ("Remove the eyes, the nose and the mouth. Keep the same low poly flat-shaded faces, the same colors, "
                 "shape, pose and white background. The face must stay a plain smooth muzzle with no facial features.")


def sense_detalls(imatge: bytes, base: str = "http://127.0.0.1:8188", espera_max: float = 600) -> bytes:
    """La imatge sense els detalls fins (ulls, nas, boca) per donar-la a Hunyuan: la malla en surt més neta.
    FLUX.2 Klein (una referència, 4 passos, ~1 min). La silueta es conserva (IoU 0,99 amb l'original a la guineu),
    així que la malla encara s'alinea amb el dibuix original, d'on surt la pell. Torna un PNG."""
    base = base.rstrip("/")
    nom = f"d2r_sd_{uuid.uuid4().hex[:8]}.png"
    _puja(base, nom, prepara_imatge(imatge, 1024))
    wf = json.loads(WORKFLOWS_KLEIN.read_text().replace("__IMAGE__", nom).replace("__PROMPT__", SENSE_DETALLS))
    r = _json(f"{base}/prompt", {"prompt": wf})
    sortida = _espera(base, r["prompt_id"], espera_max)
    f = [x for v in sortida.values() for l in v.values() for x in l
         if isinstance(x, dict) and str(x.get("filename", "")).endswith(".png")][-1]
    q = urllib.parse.urlencode({"filename": f["filename"], "subfolder": f["subfolder"], "type": f["type"]})
    with urllib.request.urlopen(f"{base}/view?{q}", timeout=120) as resp:
        return resp.read()


def genera_nitida(imatge: bytes, base: str = "http://127.0.0.1:8188", passos: int = 30,
                  resolucio: int = 256, espera_max: float = 900, progres=None, detalls_fora: bool = False) -> bytes:
    """Com `genera` però amb la superfície extreta del camp en brut: conserva les cares planes i
    les arestes vives. Torna un GLB (Y amunt)."""
    base = base.rstrip("/")
    nom = f"d2r_{uuid.uuid4().hex[:8]}.png"
    geometria = sense_detalls(imatge, base) if detalls_fora else imatge   # la pell sempre surt de l'original
    try:
        _puja(base, nom, prepara_imatge(geometria))
        wf = json.loads(WORKFLOW.read_text().replace("__IMAGE__", nom))
        del wf["19:9"], wf["10"]   # sense malla de ComfyUI: només el camp
        wf["19:7"]["inputs"]["steps"] = passos
        wf["19:8"]["inputs"]["octree_resolution"] = resolucio
        wf["20"] = {"class_type": "SaveVoxelNpy",
                    "inputs": {"voxel": ["19:8", 0], "filename_prefix": "voxels/d2r"}}
        r = _json(f"{base}/prompt", {"prompt": wf})
        f = _espera(base, r["prompt_id"], espera_max, progres)["20"]["voxels"][0]
        q = urllib.parse.urlencode({"filename": f["filename"], "subfolder": f["subfolder"],
                                    "type": f["type"]})
        with urllib.request.urlopen(f"{base}/view?{q}", timeout=120) as resp:
            c = np.load(io.BytesIO(resp.read()))
    except urllib.error.HTTPError as e:
        if "SaveVoxelNpy" in e.read().decode(errors="ignore"):
            raise RuntimeError("Falta el node SaveVoxelNpy a ComfyUI: copia comfy_nodes/save_voxel_npy.py "
                               "a custom_nodes/ i reinicia ComfyUI.") from e
        raise RuntimeError(f"ComfyUI ha refusat la feina: {e}") from e
    except OSError as e:
        raise RuntimeError(f"No puc parlar amb ComfyUI a {base}: {e}") from e
    m = malla_camp(c)
    m.apply_transform(Z_UP_TO_Y_UP)
    return pell_projectada(m, imatge).export(file_type="glb")
