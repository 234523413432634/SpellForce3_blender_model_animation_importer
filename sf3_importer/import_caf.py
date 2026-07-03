import bpy
import struct
import os
from mathutils import Vector, Quaternion

FPS = 24.0

PERMUTATIONS = {
    "YZ_SWAP":      (lambda x,y,z: Vector((x*0.1,z*0.1,y*0.1)),   lambda w,x,y,z: Quaternion((w,x,z,y))),
}

BLENDER_VERSION = bpy.app.version
USE_SLOTTED_ACTIONS = BLENDER_VERSION >= (5, 0, 0)

class CAFHeader:
    def __init__(self, num_keys, track_type, bone_id):
        self.num_keys = num_keys
        self.track_type = track_type
        self.bone_id = bone_id

class CAFKeyframe:
    def __init__(self, data):
        self.x, self.y, self.z, self.w = data[0:4]
        self.tx, self.ty, self.tz, self.tw = data[4:8]

def get_bone_by_id(arm_obj, bone_id):
    """Finds a PoseBone by the custom 'bone_id' property set by the CRF importer."""
    for pb in arm_obj.pose.bones:
        stored_id = pb.bone.get('bone_id')
        if stored_id is not None and (int(stored_id) & 0xFFFFFFFF) == (bone_id & 0xFFFFFFFF):
            return pb
    print(f"Warning: Bone with ID 0x{bone_id:08X} not found in armature!")
    return None

def _get_channelbag(action, slot):
    """Get or create the channelbag for a given action slot (Blender 5.0+)."""
    if not action.layers:
        layer = action.layers.new("Layer")
    else:
        layer = action.layers[0]

    if not layer.strips:
        strip = layer.strips.new(type='KEYFRAME')
    else:
        strip = layer.strips[0]

    channelbag = strip.channelbag(slot, ensure=True)
    return channelbag


def _get_fcurves_container(action, obj):
    """
    Returns the object that owns .fcurves and .groups.
    - Blender < 5.0: returns the Action directly (legacy API).
    - Blender 5.0+: returns the channelbag for the object's assigned slot.
    """
    if not USE_SLOTTED_ACTIONS:
        return action

    # Blender 5.0+ path
    anim_data = obj.animation_data
    if anim_data.action_slot is None:
        # Auto-create or pick an OBJECT slot for this armature
        if len(action.slots) == 0:
            slot = action.slots.new(id_type='OBJECT', name=obj.name)
        else:
            slot = None
            for s in action.slots:
                if s.target_id_type == 'OBJECT':
                    slot = s
                    break
            if slot is None:
                slot = action.slots.new(id_type='OBJECT', name=obj.name)
        anim_data.action_slot = slot
    else:
        slot = anim_data.action_slot

    return _get_channelbag(action, slot)


def apply_hermite_to_fcurve(action, obj, bone_name, data_path, index, times_sec, values, tangents, fps):
    """
    Apply hermite interpolation to an fcurve.
    < 5.0  -> action.fcurves
    >= 5.0 -> channelbag.fcurves
    """
    fcurves_container = _get_fcurves_container(action, obj)
    full_data_path = f'pose.bones["{bone_name}"].{data_path}'

    fc = fcurves_container.fcurves.find(data_path=full_data_path, index=index)
    if not fc:
        fc = fcurves_container.fcurves.new(data_path=full_data_path, index=index)

    frames = [t * fps for t in times_sec]
    fc.keyframe_points.add(len(frames))

    for i in range(len(frames)):
        kp = fc.keyframe_points[i]
        x = frames[i]
        y = values[i]

        m = tangents[i] / fps

        kp.co = (x, y)
        kp.handle_left_type = 'FREE'
        kp.handle_right_type = 'FREE'

        if i < len(frames) - 1:
            dx_right = (frames[i+1] - x) / 3.0
        else:
            dx_right = (x - frames[i-1]) / 3.0 if i > 0 else 1.0

        if i > 0:
            dx_left = (x - frames[i-1]) / 3.0
        else:
            dx_left = (frames[i+1] - x) / 3.0 if i < len(frames) - 1 else 1.0

        kp.handle_left = (x - dx_left, y - dx_left * m)
        kp.handle_right = (x + dx_right, y + dx_right * m)

    fc.update()


def load(operator, context, filepath, loop_animation=True):
    print(f"\n{'='*50}\nIMPORTING CAF: {os.path.basename(filepath)}\n{'='*50}")
    print(f"Detected Blender version: {BLENDER_VERSION[0]}.{BLENDER_VERSION[1]}.{BLENDER_VERSION[2]}")
    print(f"Using slotted actions API: {USE_SLOTTED_ACTIONS}")

    headers, times_array, keyframes_array = [], [], []

    try:
        with open(filepath, 'rb') as f:
            num_tracks, _ = struct.unpack("<II", f.read(8))
            for i in range(num_tracks):
                n_keys, t_type, b_id, _ = struct.unpack("<IIII", f.read(16))
                headers.append(CAFHeader(n_keys, t_type, b_id))

            for hdr in headers:
                times = [struct.unpack("<f", f.read(4))[0] for _ in range(hdr.num_keys)]
                times_array.append(times)

            for hdr in headers:
                kfs = [CAFKeyframe(struct.unpack("<8f", f.read(32))) for _ in range(hdr.num_keys)]
                keyframes_array.append(kfs)
            try:
                duration_bytes = f.read(4)
                if len(duration_bytes) < 4:
                    raise ValueError("Missing duration footer")
                anim_duration = struct.unpack("<f", duration_bytes)[0]
                print(f"Animation duration read from file: {anim_duration:.6f} seconds")
            except Exception as e:
                max_time = max(max(track) for track in times_array) if times_array else 1.0
                anim_duration = max_time
                print(f"WARNING: Could not read duration footer ({e}). Using max key time: {anim_duration:.6f} s")

        # Debug print
        for i, hdr in enumerate(headers):
            t_type_str = "ROT" if hdr.track_type == 1 else "LOC"
            print(f"\n--- Track {i} | Bone ID: 0x{hdr.bone_id:08X} | Type: {t_type_str} | Keys: {hdr.num_keys} ---")
            for k in range(min(hdr.num_keys, 5)):  # print first 5 keys only
                t = times_array[i][k]
                kf = keyframes_array[i][k]
                print(f"  Key {k:02d} | Time: {t:.3f} -> Raw[X:{kf.x:.4f}, Y:{kf.y:.4f}, Z:{kf.z:.4f}, W:{kf.w:.4f}]")

        arm_obj = bpy.data.objects.get("Armature")
        if not arm_obj or arm_obj.type != 'ARMATURE':
            print("ERROR: No valid 'Armature' object found.")
            operator.report({'ERROR'}, "No valid 'Armature' object found. Import a CRF model first.")
            return {'CANCELLED'}

        if arm_obj.animation_data is None:
            arm_obj.animation_data_create()

        bpy.context.view_layer.objects.active = arm_obj
        bpy.ops.object.mode_set(mode='POSE')
        base_anim_name = bpy.path.display_name_from_filepath(filepath)

        # Organize tracks by bone ID
        bone_tracks = {}
        for i, hdr in enumerate(headers):
            if hdr.bone_id not in bone_tracks:
                bone_tracks[hdr.bone_id] = {'loc': None, 'rot': None}
            if hdr.track_type == 0:
                bone_tracks[hdr.bone_id]['loc'] = (times_array[i], keyframes_array[i])
            elif hdr.track_type == 1:
                bone_tracks[hdr.bone_id]['rot'] = (times_array[i], keyframes_array[i])

        # Apply time scaling and create actions
        for perm_name, (swizzle_loc, swizzle_quat) in PERMUTATIONS.items():
            action_name = f"{base_anim_name}"
            action = bpy.data.actions.new(name=action_name)
            arm_obj.animation_data.action = action

            # For Blender 5.0+, ensure a slot is assigned before any fcurve access
            if USE_SLOTTED_ACTIONS:
                _ = _get_fcurves_container(action, arm_obj)

            for bone_id, tracks in bone_tracks.items():
                pose_bone = get_bone_by_id(arm_obj, bone_id)
                if not pose_bone:
                    continue

                pose_bone.rotation_mode = "QUATERNION"

                # Rest pose matrices
                rest_matrix = pose_bone.bone.matrix_local
                if pose_bone.parent:
                    rest_matrix = pose_bone.parent.bone.matrix_local.inverted_safe() @ rest_matrix
                bind_loc = rest_matrix.to_translation()
                bind_rot_inv = rest_matrix.to_quaternion().conjugated()

                # LOCATION
                if tracks['loc']:
                    times_norm, kfs = tracks['loc']
                    scale_tan = 1.0 / anim_duration
                    scaled_times = [t * anim_duration for t in times_norm]
                    v_x, v_y, v_z = [], [], []
                    t_x, t_y, t_z = [], [], []
                    for kf in kfs:
                        blen_val = bind_rot_inv @ (swizzle_loc(kf.x, kf.y, kf.z) - bind_loc)
                        v_x.append(blen_val.x); v_y.append(blen_val.y); v_z.append(blen_val.z)
                        blen_tan = bind_rot_inv @ swizzle_loc(kf.tx, kf.ty, kf.tz)
                        t_x.append(blen_tan.x * scale_tan)
                        t_y.append(blen_tan.y * scale_tan)
                        t_z.append(blen_tan.z * scale_tan)

                    if loop_animation:
                        # Close the loop
                        scaled_times.append(anim_duration)
                        v_x.append(v_x[0]); v_y.append(v_y[0]); v_z.append(v_z[0])
                        t_x.append(t_x[0]); t_y.append(t_y[0]); t_z.append(t_z[0])

                    apply_hermite_to_fcurve(action, arm_obj, pose_bone.name, "location", 0, scaled_times, v_x, t_x, FPS)
                    apply_hermite_to_fcurve(action, arm_obj, pose_bone.name, "location", 1, scaled_times, v_y, t_y, FPS)
                    apply_hermite_to_fcurve(action, arm_obj, pose_bone.name, "location", 2, scaled_times, v_z, t_z, FPS)

                # ROTATION
                if tracks['rot']:
                    times_norm, kfs = tracks['rot']
                    scale_tan = 1.0 / anim_duration
                    scaled_times = [t * anim_duration for t in times_norm]
                    v_w, v_x, v_y, v_z = [], [], [], []
                    t_w, t_x, t_y, t_z = [], [], [], []
                    for kf in kfs:
                        blen_val = bind_rot_inv @ swizzle_quat(kf.w, kf.x, kf.y, kf.z)
                        v_w.append(blen_val.w); v_x.append(blen_val.x)
                        v_y.append(blen_val.y); v_z.append(blen_val.z)
                        blen_tan = bind_rot_inv @ swizzle_quat(kf.tw, kf.tx, kf.ty, kf.tz)
                        t_w.append(blen_tan.w * scale_tan)
                        t_x.append(blen_tan.x * scale_tan)
                        t_y.append(blen_tan.y * scale_tan)
                        t_z.append(blen_tan.z * scale_tan)

                    if loop_animation:
                        scaled_times.append(anim_duration)
                        v_w.append(v_w[0]); v_x.append(v_x[0])
                        v_y.append(v_y[0]); v_z.append(v_z[0])
                        t_w.append(t_w[0]); t_x.append(t_x[0])
                        t_y.append(t_y[0]); t_z.append(t_z[0])

                    apply_hermite_to_fcurve(action, arm_obj, pose_bone.name, "rotation_quaternion", 0, scaled_times, v_w, t_w, FPS)
                    apply_hermite_to_fcurve(action, arm_obj, pose_bone.name, "rotation_quaternion", 1, scaled_times, v_x, t_x, FPS)
                    apply_hermite_to_fcurve(action, arm_obj, pose_bone.name, "rotation_quaternion", 2, scaled_times, v_y, t_y, FPS)
                    apply_hermite_to_fcurve(action, arm_obj, pose_bone.name, "rotation_quaternion", 3, scaled_times, v_z, t_z, FPS)

            # Adjust timeline and action frame range
            max_frame = int(round(anim_duration * FPS))
            scene = bpy.context.scene
            scene.render.fps = 24
            scene.frame_start = 0
            scene.frame_end = max_frame-1
            action.frame_range = (0, max_frame-1)
            print()
            print(f"Timeline set to frames 0-{max_frame} ({anim_duration:.4f}s at {FPS} fps)")

        bpy.ops.object.mode_set(mode='OBJECT')
        return {'FINISHED'}
        
    except Exception as e:
        print(f"ERROR importing CAF: {e}")
        operator.report({'ERROR'}, f"Failed to import CAF: {e}")
        return {'CANCELLED'}