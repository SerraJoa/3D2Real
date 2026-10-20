"""Imatge → malla 3D (GLB) amb Hunyuan3D 2.1 a través d'un ComfyUI en marxa.

L'app no porta cap model: només parla amb l'API de ComfyUI (per defecte 127.0.0.1:8188) amb el
workflow de `workflows/`. Necessita el punt de control `hunyuan_3d_v2.1.safetensors`.
La malla que torna ja va amb la Y amunt (Hunyuan la desa amb la Z amunt).
"""
import io
import json
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import numpy as np
import scipy.ndimage as ndi
import trimesh
from PIL import Image

WORKFLOW = Path(__file__).with_name("workflows") / "hunyuan21_imatge_a_3d.json"
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


def _espera(base: str, pid: str, espera_max: float) -> dict:
    t0 = time.time()
    while time.time() - t0 < espera_max:
        h = _json(f"{base}/history/{pid}").get(pid)
        if h:
            if h["status"]["status_str"] != "success":
                raise RuntimeError(f"ComfyUI ha fallat: {h['status']}")
            return h["outputs"]
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
