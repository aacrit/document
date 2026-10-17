"""Run inside every Cycles render process (blender -b <blend> --python gpu.py -o ... -a). The device is a user
preference, not saved in the .blend, so without this a background render silently falls back to the CPU (found
2026-10-17: the first 37 final frames and every earlier proof timing were CPU). GPU only, OptiX; exits if none."""

import sys

import bpy

prefs = bpy.context.preferences.addons["cycles"].preferences
prefs.compute_device_type = "OPTIX"
prefs.refresh_devices()
used = []
for d in prefs.devices:
    d.use = d.type == "OPTIX"
    if d.use:
        used.append(d.name)
if not used:
    print("gpu.py: no OptiX device: refusing to render on the CPU")
    sys.exit(3)
for sc in bpy.data.scenes:
    sc.cycles.device = "GPU"
print(f"gpu.py: rendering on {used} (OptiX)")
