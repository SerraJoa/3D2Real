"""«Voxel to Mesh (nítida)»: substitut directe de VoxelToMesh per al camp de Hunyuan 3D.

Marching cubes sobre el camp en brut (precisió per sota del vòxel), només la peça principal i sense buits
interiors: una sola malla estanca i varietat, sense els fragments ni les esquerdes del surface net.
Mateixes coordenades que VoxelToMesh (costat llarg de -1 a 1, eixos girats com fliplr), així que la
sortida MESH va directa a SaveGLB. També repara les llesques plenes que a vegades deixa el descodificador.
"""
import numpy as np
import torch
from scipy import ndimage as ndi
from skimage.measure import marching_cubes

from comfy_api.latest import Types


def _repara_plans(c, vora=0.3):
    """Llesques plenes del descodificador (banda exterior gairebé tota ocupada) -> interpolades dels veïns."""
    c = c.copy()       # còpia de imatge3d.repara_plans (3d2Real): ComfyUI no pot importar-lo
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


def malla_nitida(c, llindar):
    c = _repara_plans(np.asarray(c, dtype=np.float32))
    lab, _ = ndi.label(c > llindar)
    mida = np.bincount(lab.ravel())
    mida[0] = 0
    ple = ndi.binary_fill_holes(lab == mida.argmax())
    c = np.where(ple, np.maximum(c, llindar + 1e-3), np.minimum(c, llindar - 1e-3))
    v, f, _, _ = marching_cubes(np.pad(c, 1), llindar)
    v = (v - max(c.shape) / 2) / (max(c.shape) / 2)     # com VoxelToMesh: centrat, costat llarg a [-1, 1]
    v = np.ascontiguousarray(v[:, ::-1])                 # fliplr de VoxelToMesh
    f = np.ascontiguousarray(f)
    t = v[f]
    if np.einsum("ij,ij->i", t[:, 0], np.cross(t[:, 1], t[:, 2])).sum() < 0:   # normals cap a fora
        f = f[:, ::-1].copy()
    return torch.from_numpy(v.astype(np.float32)), torch.from_numpy(f.astype(np.int64))


class VoxelToMeshNitida:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"voxel": ("VOXEL",),
                             "threshold": ("FLOAT", {"default": 0.6, "min": -1.0, "max": 1.0, "step": 0.01})}}

    RETURN_TYPES = ("MESH",)
    FUNCTION = "execute"
    CATEGORY = "3d"

    def execute(self, voxel, threshold):
        vs, fs = zip(*(malla_nitida(x.float().cpu().numpy(), threshold) for x in voxel.data))
        if all(v.shape == vs[0].shape for v in vs) and all(f.shape == fs[0].shape for f in fs):
            return (Types.MESH(torch.stack(vs), torch.stack(fs)),)
        from comfy_extras.nodes_save_3d import pack_variable_mesh_batch
        return (pack_variable_mesh_batch(list(vs), list(fs)),)


NODE_CLASS_MAPPINGS = {"VoxelToMeshNitida": VoxelToMeshNitida}
NODE_DISPLAY_NAME_MAPPINGS = {"VoxelToMeshNitida": "Voxel to Mesh (nítida)"}
