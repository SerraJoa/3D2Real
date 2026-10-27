"""Desa el camp de vòxels (VOXEL, p. ex. de «Hunyuan 3D VAE Decode») en brut com a .npy (float16).

Per a 3d2Real: extreure la superfície amb altres mètodes (dual contouring) fora de ComfyUI.
"""
import os

import numpy as np

import folder_paths


class SaveVoxelNpy:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"voxel": ("VOXEL",),
                             "filename_prefix": ("STRING", {"default": "voxels/camp"})}}

    RETURN_TYPES = ()
    FUNCTION = "save"
    OUTPUT_NODE = True
    CATEGORY = "3d"

    def save(self, voxel, filename_prefix):
        out_dir, name, counter, subfolder, _ = folder_paths.get_save_image_path(
            filename_prefix, folder_paths.get_output_directory())
        files = []
        for i, x in enumerate(voxel.data):
            fn = f"{name}_{counter + i:05}_.npy"
            np.save(os.path.join(out_dir, fn), x.float().cpu().numpy().astype(np.float16))
            files.append({"filename": fn, "subfolder": subfolder, "type": "output"})
        return {"ui": {"voxels": files}}


NODE_CLASS_MAPPINGS = {"SaveVoxelNpy": SaveVoxelNpy}
NODE_DISPLAY_NAME_MAPPINGS = {"SaveVoxelNpy": "Save Voxel (.npy)"}
