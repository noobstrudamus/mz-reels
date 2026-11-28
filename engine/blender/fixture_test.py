"""3D B-roll: an oversized bead fails to pass a test fixture (generic, no logos). Usage:
python3 fixture_test.py OUT_DIR [--anim]   -> still.png (or frames for a 2 s clip)"""
import bpy, sys, math, os
out = sys.argv[1]; anim = '--anim' in sys.argv
os.makedirs(out, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.engine = 'CYCLES'; sc.cycles.samples = 24; sc.cycles.use_denoising = True; sc.cycles.device = 'CPU'
sc.render.resolution_x, sc.render.resolution_y = 1080, 1920
sc.frame_start, sc.frame_end = 1, 60; sc.render.fps = 30
def mat(name, rgb, rough=0.4, metal=0.0, trans=0.0):
    m = bpy.data.materials.new(name); m.use_nodes = True; b = m.node_tree.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = (*rgb, 1); b.inputs['Roughness'].default_value = rough
    b.inputs['Metallic'].default_value = metal
    if trans: b.inputs['Transmission Weight'].default_value = trans
    return m
# table
bpy.ops.mesh.primitive_plane_add(size=20); bpy.context.object.data.materials.append(mat('table', (0.10, 0.12, 0.18), 0.6))
# fixture: block with a hole (boolean)
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0.6)); fx = bpy.context.object; fx.scale = (2.4, 2.4, 1.2)
bpy.ops.mesh.primitive_cylinder_add(radius=0.45, depth=3, location=(0, 0, 0.6)); hole = bpy.context.object
mod = fx.modifiers.new('hole', 'BOOLEAN'); mod.object = hole; mod.operation = 'DIFFERENCE'
bpy.context.view_layer.objects.active = fx; bpy.ops.object.modifier_apply(modifier='hole'); bpy.data.objects.remove(hole)
bev = fx.modifiers.new('bev', 'BEVEL'); bev.width = 0.05; bev.segments = 3
fx.data.materials.append(mat('steel', (0.75, 0.77, 0.80), 0.25, 1.0))
# bead (too big for the hole): drops and stops on the rim
bpy.ops.mesh.primitive_uv_sphere_add(radius=0.62, location=(0, 0, 3.4), segments=64, ring_count=32); bead = bpy.context.object
bpy.ops.object.shade_smooth(); bead.data.materials.append(mat('bead', (0.95, 0.55, 0.10), 0.05, 0, 0.6))
rest = 1.2 + 0.62 * 0.62  # sits on the rim of the hole
for f, z in ((1, 3.4), (22, rest), (26, rest + 0.18), (30, rest), (60, rest)):
    bead.location.z = z; bead.keyframe_insert('location', frame=f)
# light + camera
bpy.ops.object.light_add(type='AREA', location=(2.5, -2.5, 5)); L = bpy.context.object; L.data.energy = 900; L.data.size = 4
bpy.ops.object.light_add(type='AREA', location=(-3, 2, 3)); bpy.context.object.data.energy = 250
bpy.ops.object.camera_add(location=(0, -6.2, 3.6), rotation=(math.radians(66), 0, 0)); sc.camera = bpy.context.object
bpy.context.object.data.lens = 40
w = bpy.data.worlds.new('w'); sc.world = w; w.use_nodes = True
w.node_tree.nodes['Background'].inputs['Color'].default_value = (0.02, 0.03, 0.06, 1)
if anim:
    sc.render.filepath = os.path.join(out, 'f_'); sc.render.image_settings.file_format = 'PNG'
    bpy.ops.render.render(animation=True)
else:
    sc.frame_set(40); sc.render.filepath = os.path.join(out, 'still.png'); bpy.ops.render.render(write_still=True)
print('DONE', out)
