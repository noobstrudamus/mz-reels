"""Blender (bpy) 3D reel scene: container on hold at a generic dock -> certificate close-up ->
'Issued by' line changes -> stamp -> crane-up for the end card.
No real logos, seals, agencies or place names (CLAUDE.md truth rules).

python3 scene3d.py <timing.json> <out_dir> [--still t1 t2 ...] [--from F] [--to F]
timing.json: {"times": [0, s2, s3, s4, s5, total], "fps": 24, "w": 720, "h": 1280, "samples": 6,
              "sku": "BAG-24-KID"}
Skills used: blender-director, environment-artist, prop-artist, materials, lighting,
camera-cinematography, rendering (see .claude/skills/<name>/SKILL.md)."""
import bpy, sys, json, math, os
from mathutils import Vector

args = sys.argv[1:]
T = json.load(open(args[0])); OUT = args[1]; os.makedirs(OUT, exist_ok=True)
FPS = T.get("fps", 24); t = T["times"]
F = lambda sec: max(1, int(round(sec * FPS)) + 1)

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.engine = "CYCLES"; sc.cycles.device = "CPU"
sc.cycles.samples = T.get("samples", 6); sc.cycles.use_denoising = True
sc.cycles.max_bounces = 4; sc.cycles.diffuse_bounces = 2; sc.cycles.glossy_bounces = 2
sc.cycles.transmission_bounces = 2; sc.cycles.volume_bounces = 0
sc.render.use_persistent_data = True
sc.render.resolution_x, sc.render.resolution_y = T.get("w", 720), T.get("h", 1280)
sc.render.fps = FPS; sc.frame_start = 1; sc.frame_end = F(t[-1])
sc.view_settings.view_transform = "AgX"; sc.view_settings.look = "AgX - Medium High Contrast"

# ---------- materials (materials skill: simple PBR, roughness carries the read) ----------
def mat(name, rgb, rough=0.5, metal=0.0, emit=None, estr=0.0):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1); b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if emit:
        b.inputs["Emission Color"].default_value = (*emit, 1); b.inputs["Emission Strength"].default_value = estr
    return m

M = dict(
    concrete=mat("concrete", (0.32, 0.33, 0.35), 0.85),
    paint=mat("paint_line", (0.85, 0.65, 0.10), 0.7),
    box=mat("container_red", (0.62, 0.16, 0.07), 0.45, 0.35),
    box2=mat("container_blue", (0.08, 0.20, 0.45), 0.5, 0.3),
    box3=mat("container_teal", (0.05, 0.35, 0.33), 0.5, 0.3),
    box4=mat("container_grey", (0.45, 0.46, 0.48), 0.5, 0.3),
    steel=mat("steel", (0.55, 0.56, 0.58), 0.3, 1.0),
    wood=mat("crate_wood", (0.45, 0.30, 0.16), 0.75),
    paper=mat("paper", (0.93, 0.92, 0.88), 0.9),
    ink=mat("ink", (0.08, 0.09, 0.12), 0.6),
    red=mat("red_text", (0.75, 0.05, 0.05), 0.5, emit=(0.9, 0.05, 0.05), estr=0.4),
    green=mat("green_text", (0.05, 0.45, 0.15), 0.5, emit=(0.05, 0.6, 0.2), estr=0.4),
    white=mat("white_text", (0.95, 0.95, 0.95), 0.6),
)
beacon = mat("beacon", (0.2, 0.02, 0.02), 0.3, emit=(1.0, 0.08, 0.05), estr=0.0)

def box(name, loc, size, m, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc, rotation=rot)
    o = bpy.context.object; o.name = name; o.scale = size; o.data.materials.append(m)
    return o

def text(body, loc, size, m, rot=(math.radians(90), 0, 0), align="CENTER", parent=None):
    cu = bpy.data.curves.new(body[:16], "FONT"); cu.body = body; cu.size = size; cu.align_x = align
    cu.extrude = 0.002
    o = bpy.data.objects.new(body[:16], cu); bpy.context.collection.objects.link(o)
    o.location = loc; o.rotation_euler = rot; o.data.materials.append(m)
    if parent: o.parent = parent
    return o

def vis(o, on_frames):
    """on_frames: list of (frame, visible) keyframes for render + viewport visibility."""
    for f, v in on_frames:
        o.hide_render = not v; o.hide_viewport = not v
        o.keyframe_insert("hide_render", frame=f); o.keyframe_insert("hide_viewport", frame=f)

# ---------- environment (environment-artist + set-dressing) ----------
box("dock", (0, 10, -0.05), (60, 60, 0.1), M["concrete"])
for x in (-4.2, 4.2):
    box(f"line{x}", (x, 2, 0.002), (0.15, 30, 0.004), M["paint"])
stack_mats = [M["box2"], M["box3"], M["box4"], M["box2"], M["box"]]
for i, (x, y, lv) in enumerate([(-9, 16, 0), (-9, 16, 1), (-2.5, 20, 0), (4, 18, 0), (4, 18, 1), (10, 15, 0),
                                (10, 15, 1), (-14, 22, 0), (16, 24, 0), (0, 28, 0), (0, 28, 1)]):
    box(f"stack{i}", (x, y, 1.3 + lv * 2.6), (6.06, 2.44, 2.59), stack_mats[i % len(stack_mats)])

# hero container with corrugation ribs (hard-surface: array of thin boxes)
hero = box("hero", (0, 6, 1.295), (6.06, 2.44, 2.59), M["box"])
rib = box("ribs", (-2.9, 6, 1.295), (0.08, 2.52, 2.45), M["box"])
arr = rib.modifiers.new("arr", "ARRAY"); arr.count = 24; arr.relative_offset_displace = (3.1, 0, 0)
rib.parent = hero; rib.matrix_parent_inverse = hero.matrix_world.inverted()
lab = text(T.get("sku", "BAG-24-KID"), (0, 6 - 1.27, 1.9), 0.42, M["white"])
lab.parent = hero; lab.matrix_parent_inverse = hero.matrix_world.inverted()
# container drops in during scene 1
for f, z in ((F(0), 9.5), (F(t[0] + 1.0), 1.295), (F(t[0] + 1.15), 1.42), (F(t[0] + 1.3), 1.295)):
    hero.location.z = z; hero.keyframe_insert("location", index=2, frame=f)

# beacon on a pole: red blinking until the certificate is fixed, then steady green
pole = box("pole", (3.9, 4.3, 1.4), (0.08, 0.08, 2.8), M["steel"])
bpy.ops.mesh.primitive_uv_sphere_add(radius=0.2, location=(3.9, 4.3, 2.95)); lamp = bpy.context.object
bpy.ops.object.shade_smooth(); lamp.data.materials.append(beacon)
bsdf = beacon.node_tree.nodes["Principled BSDF"]
fix = t[3]  # scene 4: "So I issue my own"
f = F(0.2); on = True
while f < F(fix):
    bsdf.inputs["Emission Strength"].default_value = 30.0 if on else 1.0
    bsdf.inputs["Emission Strength"].keyframe_insert("default_value", frame=f)
    f += int(FPS * 0.35); on = not on
for fr, col, st in ((F(fix) - 1, (1.0, 0.08, 0.05), 1.0), (F(fix), (0.1, 1.0, 0.3), 25.0), (F(t[-1]), (0.1, 1.0, 0.3), 25.0)):
    bsdf.inputs["Emission Color"].default_value = (*col, 1); bsdf.inputs["Emission Color"].keyframe_insert("default_value", frame=fr)
    bsdf.inputs["Emission Strength"].default_value = st; bsdf.inputs["Emission Strength"].keyframe_insert("default_value", frame=fr)
bpy.ops.object.light_add(type="POINT", location=(3.9, 4.0, 2.95)); bl = bpy.context.object; bl.data.shadow_soft_size = 0.2
for fr, col, en in ((F(0.2), (1, 0.1, 0.05), 120), (F(fix) - 1, (1, 0.1, 0.05), 120), (F(fix), (0.1, 1, 0.3), 120)):
    bl.data.color = col; bl.data.energy = en
    bl.data.keyframe_insert("color", frame=fr); bl.data.keyframe_insert("energy", frame=fr)

# ---------- hero prop: crate + certificate (prop-artist) ----------
crate = box("crate", (0, 1.2, 0.5), (1.3, 0.9, 1.0), M["wood"])
tilt = math.radians(22)
doc = box("doc", (0, 1.15, 1.19), (0.62, 0.88, 0.006), M["paper"], rot=(tilt, 0, 0))
def on_doc(body, y_local, size, m, align="CENTER", x_local=0.0):
    o = text(body, (x_local, y_local, 0.006), size, m, rot=(0, 0, 0), align=align)
    o.parent = doc; o.matrix_parent_inverse.identity()
    o.scale = (1 / 0.62, 1 / 0.88, 1 / 0.006)  # undo the doc's scale
    o.location = (x_local / 0.62, y_local / 0.88, 0.6)
    return o
on_doc("CERTIFICATE", 0.33, 0.07, M["ink"])
on_doc("Product: " + T.get("sku", "BAG-24-KID"), 0.20, 0.035, M["ink"], "LEFT", -0.26)
on_doc("Each rule listed", 0.13, 0.035, M["ink"], "LEFT", -0.26)
on_doc("Issued by:", 0.02, 0.045, M["ink"], "LEFT", -0.26)
fac = on_doc("FACTORY", -0.07, 0.06, M["red"], "LEFT", -0.26)
imp = on_doc("IMPORTER", -0.07, 0.06, M["green"], "LEFT", -0.26)
tst = on_doc("Tested: date, place, lab", -0.19, 0.035, M["ink"], "LEFT", -0.26)
swap = F(t[2] + 1.6)
vis(fac, [(1, True), (swap, False)]); vis(imp, [(1, False), (swap, True)])
vis(tst, [(1, False), (F(t[3] + 0.4), True)])

# stamp presses the doc in scene 4, leaving an "ON FILE" mark
bpy.ops.mesh.primitive_cylinder_add(radius=0.11, depth=0.08, location=(0.16, 1.0, 12.0)); st = bpy.context.object
st.data.materials.append(M["steel"])
bpy.ops.mesh.primitive_cylinder_add(radius=0.035, depth=0.22, location=(0, 0, 0.15)); h = bpy.context.object
h.data.materials.append(M["wood"]); h.parent = st
mark = on_doc("ON FILE", -0.32, 0.05, M["green"], "CENTER", 0.16)
press = t[3] + 1.2
for fr, z in ((1, 12.0), (F(t[3]) - 1, 12.0), (F(t[3]), 2.4), (F(press), 1.13), (F(press + 0.25), 1.13), (F(press + 0.8), 12.0)):
    st.location.z = z; st.keyframe_insert("location", index=2, frame=fr)
vis(mark, [(1, False), (F(press + 0.1), True)])

# ---------- lighting (lighting skill: low warm key + cool sky fill + practicals) ----------
bpy.ops.object.light_add(type="SUN", rotation=(math.radians(74), 0, math.radians(-35)))
sun = bpy.context.object; sun.data.energy = 2.2; sun.data.color = (1.0, 0.62, 0.36); sun.data.angle = math.radians(2)
bpy.ops.object.light_add(type="AREA", location=(-4, -3, 5)); fl = bpy.context.object
fl.data.energy = 300; fl.data.size = 6; fl.data.color = (0.55, 0.7, 1.0)
fl.rotation_euler = (math.radians(45), 0, math.radians(-50))
bpy.ops.object.light_add(type="AREA", location=(0.4, -0.5, 2.6)); kl = bpy.context.object  # soft key on the paper
kl.data.energy = 45; kl.data.size = 1.0; kl.rotation_euler = (math.radians(25), 0, math.radians(15))
for i, x in enumerate((-7, 7)):  # yard floodlights
    bpy.ops.object.light_add(type="SPOT", location=(x, 2, 7)); sp = bpy.context.object
    sp.data.energy = 1500; sp.data.spot_size = math.radians(70); sp.data.color = (1.0, 0.85, 0.65)
    d = Vector((0, 5, 0)) - sp.location; sp.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
w = bpy.data.worlds.new("dusk"); sc.world = w; w.use_nodes = True
w.node_tree.nodes["Background"].inputs["Color"].default_value = (0.035, 0.05, 0.11, 1)
w.node_tree.nodes["Background"].inputs["Strength"].default_value = 1.0

# ---------- camera (camera-cinematography: wide -> push-in -> insert -> crane-up) ----------
bpy.ops.object.empty_add(location=(0, 5, 1.6)); tgt = bpy.context.object
bpy.ops.object.camera_add(location=(0, -9, 3)); cam = bpy.context.object; sc.camera = cam
cam.data.lens = 30; cam.data.dof.use_dof = True; cam.data.dof.focus_object = tgt; cam.data.dof.aperture_fstop = 4.0
c = cam.constraints.new("TRACK_TO"); c.target = tgt; c.track_axis = "TRACK_NEGATIVE_Z"; c.up_axis = "UP_Y"
doc_c = (0, 1.15, 1.2)
keys = [  # time, camera location, target location, lens
    (t[0], (-1.5, -10, 2.4), (0, 6, 1.6), 30),
    (t[1] - 0.2, (1.5, -7.5, 2.8), (0, 5, 1.6), 30),
    (t[1] + 0.8, (1.2, -1.6, 2.1), doc_c, 35),
    (t[2] - 0.1, (0.9, -0.8, 1.9), doc_c, 38),
    (t[2] + 1.0, (0.25, 0.05, 1.75), (0, 1.12, 1.17), 40),
    (t[3] - 0.1, (0.25, 0.0, 1.78), (0, 1.12, 1.17), 40),
    (t[3] + 0.6, (0.9, -0.7, 2.05), (0.1, 1.1, 1.2), 35),
    (t[4] - 0.1, (1.0, -0.9, 2.1), (0.1, 1.1, 1.2), 35),
    (t[4] + 1.5, (0, -7, 6.5), (0, 5, 1.5), 28),
    (t[5], (0, -7.5, 7.0), (0, 5, 1.5), 28),
]
for sec, cl, tl, lens in keys:
    fr = F(sec); cam.location = cl; tgt.location = tl; cam.data.lens = lens
    cam.keyframe_insert("location", frame=fr); tgt.keyframe_insert("location", frame=fr)
    cam.data.keyframe_insert("lens", frame=fr)

# ---------- render ----------
sc.render.image_settings.file_format = "PNG"
if "--still" in args:
    for s in [float(x) for x in args[args.index("--still") + 1:]]:
        sc.frame_set(F(s)); sc.render.filepath = os.path.join(OUT, f"still_{s:05.2f}.png")
        bpy.ops.render.render(write_still=True)
else:
    a = int(args[args.index("--from") + 1]) if "--from" in args else sc.frame_start
    b = int(args[args.index("--to") + 1]) if "--to" in args else sc.frame_end
    sc.frame_start, sc.frame_end = a, b
    sc.render.filepath = os.path.join(OUT, "f_"); sc.render.use_overwrite = False; sc.render.use_placeholder = True
    bpy.ops.render.render(animation=True)
print("DONE", OUT)
