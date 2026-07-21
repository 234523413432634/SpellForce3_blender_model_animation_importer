import bpy
import struct
import os
from mathutils import Vector, Quaternion

BLENDER_VERSION = bpy.app.version
USE_SLOTTED_ACTIONS = BLENDER_VERSION >= (5, 0, 0)


def get_action_fcurves(action, obj):
    """Retrieves all F-Curves for an Action"""
    if not USE_SLOTTED_ACTIONS:
        return action.fcurves

    anim_data = obj.animation_data
    if not anim_data or not anim_data.action_slot:
        slot = next((s for s in action.slots if s.target_id_type == 'OBJECT'), None)
        if not slot and len(action.slots) > 0:
            slot = action.slots[0]
        if not slot:
            return []
    else:
        slot = anim_data.action_slot

    if not action.layers or not action.layers[0].strips:
        return []

    cb = action.layers[0].strips[0].channelbag(slot, ensure=False)
    return cb.fcurves if cb else []


def get_fcurve_tangent_slope(fc, key_idx):
    """Calculates slope dy/dx (in frames) from keyframe handles."""
    kp = fc.keyframe_points[key_idx]
    num_keys = len(fc.keyframe_points)

    # Right handle (forward velocity)
    if key_idx < num_keys - 1:
        dx = kp.handle_right.x - kp.co.x
        if abs(dx) > 1e-6:
            return (kp.handle_right.y - kp.co.y) / dx

    # Left handle (fallback for end keyframes)
    if key_idx > 0:
        dx = kp.co.x - kp.handle_left.x
        if abs(dx) > 1e-6:
            return (kp.co.y - kp.handle_left.y) / dx

    return 0.0


def export_caf(filepath, arm_obj=None, fps=30):
    """Exports active Blender Action to SpellForce 3 binary CAF format."""
    if not arm_obj:
        arm_obj = bpy.context.active_object

    if not arm_obj or arm_obj.type != 'ARMATURE':
        raise ValueError("Selected object must be an ARMATURE.")

    if not arm_obj.animation_data or not arm_obj.animation_data.action:
        raise ValueError("Armature does not have an active Action assigned.")

    action = arm_obj.animation_data.action
    print(f"\n{'='*50}\nEXPORTING CAF: {os.path.basename(filepath)}\n{'='*50}")
    print(f"FPS: {fps}")

    # 1. Determine Duration & Looping
    duration = action.get("duration_sec")
    if duration is None:
        duration = (action.frame_range[1] - action.frame_range[0]) / fps
        if duration <= 0:
            duration = 1.0

    is_looping = int(action.get("is_looping", 1))
    fcurves = get_action_fcurves(action, arm_obj)

    # 2. Extract Events (from Pose Markers or Custom Property)
    events = []
    if action.pose_markers:
        for pm in action.pose_markers:
            ev_time = pm.frame / fps
            events.append((pm.name, ev_time))
    elif "events" in action:
        for ev in action["events"]:
            events.append((ev["name"], float(ev["time"])))

    # 3. Build Tracks
    tracks = []
    for pb in arm_obj.pose.bones:
        bone_id = pb.bone.get('bone_id')
        if bone_id is None:
            continue

        bone_id = int(bone_id) & 0xFFFFFFFF
        bone_path = f'pose.bones["{pb.name}"]'

        # Compute Bind Matrices
        rest_matrix = pb.bone.matrix_local
        if pb.parent:
            rest_matrix = pb.parent.bone.matrix_local.inverted_safe() @ rest_matrix

        bind_loc = rest_matrix.to_translation()
        bind_rot = rest_matrix.to_quaternion()

        # Find F-Curves for Location (0..2) and Rotation (0..3)
        loc_fcs = [next((fc for fc in fcurves if fc.data_path == f"{bone_path}.location" and fc.array_index == idx), None) for idx in range(3)]
        rot_fcs = [next((fc for fc in fcurves if fc.data_path == f"{bone_path}.rotation_quaternion" and fc.array_index == idx), None) for idx in range(4)]

        # --- LOCATION TRACK (Type 0) ---
        if any(loc_fcs):
            ref_fc = next(fc for fc in loc_fcs if fc is not None)
            num_keys = len(ref_fc.keyframe_points)

            times = []
            keyframes = []

            for k_idx in range(num_keys):
                frame_time = ref_fc.keyframe_points[k_idx].co.x / fps
                norm_time = max(0.0, min(1.0, frame_time / duration))
                times.append(norm_time)

                # Extract local Blender location & tangent velocity
                blen_loc = Vector((
                    loc_fcs[0].keyframe_points[k_idx].co.y if loc_fcs[0] else 0.0,
                    loc_fcs[1].keyframe_points[k_idx].co.y if loc_fcs[1] else 0.0,
                    loc_fcs[2].keyframe_points[k_idx].co.y if loc_fcs[2] else 0.0
                ))

                blen_tan_sec = Vector((
                    get_fcurve_tangent_slope(loc_fcs[0], k_idx) * fps if loc_fcs[0] else 0.0,
                    get_fcurve_tangent_slope(loc_fcs[1], k_idx) * fps if loc_fcs[1] else 0.0,
                    get_fcurve_tangent_slope(loc_fcs[2], k_idx) * fps if loc_fcs[2] else 0.0
                ))

                # Inverse rest-pose transformation
                raw_loc_blender = bind_loc + (bind_rot @ blen_loc)
                raw_tan_blender = bind_rot @ blen_tan_sec

                # Inverse Swizzle & Scale Factor (0.1 -> 10.0)
                caf_x = raw_loc_blender.x * 10.0
                caf_y = raw_loc_blender.z * 10.0
                caf_z = raw_loc_blender.y * 10.0
                caf_w = 1.0

                caf_tx = raw_tan_blender.x * 10.0 * duration
                caf_ty = raw_tan_blender.z * 10.0 * duration
                caf_tz = raw_tan_blender.y * 10.0 * duration
                caf_tw = 0.0

                keyframes.append((caf_x, caf_y, caf_z, caf_w, caf_tx, caf_ty, caf_tz, caf_tw))

            tracks.append({
                'num_keys': num_keys,
                'track_type': 0,
                'bone_id': bone_id,
                'times': times,
                'keyframes': keyframes
            })

        # --- ROTATION TRACK (Type 1) ---
        if any(rot_fcs):
            ref_fc = next(fc for fc in rot_fcs if fc is not None)
            num_keys = len(ref_fc.keyframe_points)

            times = []
            keyframes = []

            for k_idx in range(num_keys):
                frame_time = ref_fc.keyframe_points[k_idx].co.x / fps
                norm_time = max(0.0, min(1.0, frame_time / duration))
                times.append(norm_time)

                # Extract local Blender quat & tangent velocity
                blen_quat = Quaternion((
                    rot_fcs[0].keyframe_points[k_idx].co.y if rot_fcs[0] else 1.0,
                    rot_fcs[1].keyframe_points[k_idx].co.y if rot_fcs[1] else 0.0,
                    rot_fcs[2].keyframe_points[k_idx].co.y if rot_fcs[2] else 0.0,
                    rot_fcs[3].keyframe_points[k_idx].co.y if rot_fcs[3] else 0.0
                ))

                blen_tan_sec = Quaternion((
                    get_fcurve_tangent_slope(rot_fcs[0], k_idx) * fps if rot_fcs[0] else 0.0,
                    get_fcurve_tangent_slope(rot_fcs[1], k_idx) * fps if rot_fcs[1] else 0.0,
                    get_fcurve_tangent_slope(rot_fcs[2], k_idx) * fps if rot_fcs[2] else 0.0,
                    get_fcurve_tangent_slope(rot_fcs[3], k_idx) * fps if rot_fcs[3] else 0.0
                ))

                # Inverse rest-pose transformation
                raw_quat_blender = bind_rot @ blen_quat
                raw_tan_blender = bind_rot @ blen_tan_sec

                # Inverse Swizzle
                caf_w = raw_quat_blender.w
                caf_x = raw_quat_blender.x
                caf_y = raw_quat_blender.z
                caf_z = raw_quat_blender.y

                caf_tw = raw_tan_blender.w * duration
                caf_tx = raw_tan_blender.x * duration
                caf_ty = raw_tan_blender.z * duration
                caf_tz = raw_tan_blender.y * duration

                keyframes.append((caf_x, caf_y, caf_z, caf_w, caf_tx, caf_ty, caf_tz, caf_tw))

            tracks.append({
                'num_keys': num_keys,
                'track_type': 1,
                'bone_id': bone_id,
                'times': times,
                'keyframes': keyframes
            })

    # 4. Pack Binary Structures
    num_tracks = len(tracks)
    header_flags = 0

    with open(filepath, 'wb') as f:
        # Header (8 bytes)
        f.write(struct.pack("<II", num_tracks, header_flags))

        # Track Descriptors (16 bytes each)
        cumulative_keys = 0
        for trk in tracks:
            cumulative_keys += trk['num_keys']
            f.write(struct.pack("<IIII", trk['num_keys'], trk['track_type'], trk['bone_id'], cumulative_keys))

        # Keyframe Time Buffer (4 bytes per timestamp)
        for trk in tracks:
            for t in trk['times']:
                f.write(struct.pack("<f", t))

        # Keyframe Data Buffer (32 bytes per keyframe)
        for trk in tracks:
            for kf in trk['keyframes']:
                f.write(struct.pack("<8f", *kf))

        # Footer (Duration, Loop Flag, Event Count)
        f.write(struct.pack("<fII", duration, is_looping, len(events)))

        # Animation Events Array
        for ev_name, ev_time in events:
            name_bytes = ev_name.encode('ascii')
            f.write(struct.pack("<I", len(name_bytes)))
            f.write(name_bytes)
            f.write(struct.pack("<f", ev_time))

    print(f"Successfully exported {num_tracks} tracks to {filepath}")
    print(f"Duration: {duration:.4f}s | Looping: {bool(is_looping)} | Events: {len(events)}\n")
