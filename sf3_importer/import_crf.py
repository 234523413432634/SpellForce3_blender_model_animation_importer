# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

# Script copyright (C) Stanislav Bobovych

import sys
import os
import math
import fnmatch
import time
import bpy
import mathutils
import struct
from bpy_extras.io_utils import unpack_list, unpack_face_list, axis_conversion
from bpy_extras.image_utils import load_image

from .crf_objects import CRF_object

def find_files(base, pattern):
    '''Return list of files matching pattern in base folder.'''
    try:
        return [n for n in fnmatch.filter(os.listdir(base), pattern) if
            os.path.isfile(os.path.join(base, n))]
    except:
        print("File not found")

def truncate_bone_name(name):
    """Truncate a bone name to fit Blender's 63-character limit."""
    if len(name) <= 63:
        return name
    return name[:28] + "..." + name[-28:]

def find_texture(crf_filepath, tex_name):
    """
    Attempts to find a texture file using the extracted texture name.
    """
    if not crf_filepath or not tex_name: return None
    
    crf_filepath_str = os.fsdecode(crf_filepath).replace('\\', '/')
    
    # Internal texture names usually lack extensions. Default to .dds
    if not tex_name.lower().endswith(('.dds', '.tga', '.jpg', '.png')):
        tex_name += ".dds"
    
    # 1. Path replacement logic
    tex_path = crf_filepath_str.replace('/environment/', '/textures/environment/')
    tex_path = tex_path.replace('/characters/', '/textures/characters/')
    tex_path = os.path.join(os.path.dirname(tex_path), tex_name)
    
    if os.path.exists(tex_path):
        return tex_path
        
    # 2. Deep search in 'textures' folder relative to the CRF location
    current_dir = os.path.dirname(crf_filepath_str)
    textures_root = None
    for _ in range(4): # Search up to 4 folder levels up
        potential = os.path.join(current_dir, 'textures')
        if os.path.isdir(potential):
            textures_root = potential
            break
        
        parent = os.path.dirname(current_dir)
        if parent == current_dir:
            break
        current_dir = parent
        
    if textures_root:
        for root, dirs, files in os.walk(textures_root):
            files_lower = {f.lower(): f for f in files}
            if tex_name.lower() in files_lower:
                return os.path.join(root, files_lower[tex_name.lower()])
                
    # 3. Fallback to same directory as the CRF file
    fallback = os.path.join(os.path.dirname(crf_filepath_str), tex_name)
    if os.path.exists(fallback):
        return fallback
        
    return fallback

def createMaterial(name):        
    material = bpy.data.materials.new(name)
    material.use_backface_culling = True
    material.use_nodes = True
    return material

def addDiffuseTexture(color_filepath, mat):
    if not color_filepath or not os.path.exists(color_filepath):
        print(f"Diffuse texture not found: {color_filepath}")
        return None
    try:
        realpath = os.path.expanduser(color_filepath)
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if not bsdf: return None
        texImage = mat.node_tree.nodes.new('ShaderNodeTexImage')
        texImage.location = (-900, 350)
        texImage.image = bpy.data.images.load(realpath)
        
        # Connect Alpha; Base Color is wired later by the node chain builder
        if 'Alpha' in bsdf.inputs:
            mat.node_tree.links.new(texImage.outputs['Alpha'], bsdf.inputs['Alpha'])
        return texImage
    except Exception as e:
        print(f"Failed to load Diffuse Texture {color_filepath}: {e}")
        return None

def addSpecularTexture(specular_filepath, mat):
    if not specular_filepath or not os.path.exists(specular_filepath):
        print(f"Specular texture not found: {specular_filepath}")
        return None
    try:
        realpath = os.path.expanduser(specular_filepath)
        texImage = mat.node_tree.nodes.new('ShaderNodeTexImage')
        texImage.location = (-900, 100)
        texImage.image = bpy.data.images.load(realpath)
        return texImage
    except Exception as e:
        print(f"Failed to load Specular Texture {specular_filepath}: {e}")
        return None


def addNormalTexture(normals_filepath, mat):
    """
    Loads the normal texture and returns (texImage_node, normalMap_node).
    Reconstructs the Blue channel from the game's grayscale normal map format
    """
    if not normals_filepath or not os.path.exists(normals_filepath):
        print(f"Normal texture not found: {normals_filepath}")
        return None, None
    try:
        realpath = os.path.expanduser(normals_filepath)
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if not bsdf:
            return None, None

        # --- Image Texture ---
        texImage = mat.node_tree.nodes.new('ShaderNodeTexImage')
        texImage.location = (-1100, -600)
        img = bpy.data.images.load(realpath)
        img.colorspace_settings.name = 'Non-Color'
        texImage.image = img

        # --- Separate Color (extract Green from RGB) ---
        sep = mat.node_tree.nodes.new('ShaderNodeSeparateColor')
        sep.location = (-800, -600)
        mat.node_tree.links.new(texImage.outputs['Color'], sep.inputs['Color'])

        # --- Math Group: Reconstruct Blue (Z) from X and Y ---
        group_name = "CRF_ReconstructNormalZ"
        if group_name not in bpy.data.node_groups:
            group = bpy.data.node_groups.new(group_name, 'ShaderNodeTree')
            group.interface.new_socket(name="X", in_out='INPUT', socket_type='NodeSocketFloat')
            group.interface.new_socket(name="Y", in_out='INPUT', socket_type='NodeSocketFloat')
            group.interface.new_socket(name="Z", in_out='OUTPUT', socket_type='NodeSocketFloat')

            nodes = group.nodes
            links = group.links
            nodes.clear()

            inp = nodes.new('NodeGroupInput')
            inp.location = (-700, 0)
            out = nodes.new('NodeGroupOutput')
            out.location = (900, 0)

            # Unpack X: Alpha * 2 - 1
            unpack_x = nodes.new('ShaderNodeMath')
            unpack_x.operation = 'MULTIPLY_ADD'
            unpack_x.inputs[1].default_value = 2.0
            unpack_x.inputs[2].default_value = -1.0
            unpack_x.location = (-500, 200)
            links.new(inp.outputs['X'], unpack_x.inputs[0])

            # Unpack Y: Green * 2 - 1
            unpack_y = nodes.new('ShaderNodeMath')
            unpack_y.operation = 'MULTIPLY_ADD'
            unpack_y.inputs[1].default_value = 2.0
            unpack_y.inputs[2].default_value = -1.0
            unpack_y.location = (-500, 0)
            links.new(inp.outputs['Y'], unpack_y.inputs[0])

            # X^2
            pow_x = nodes.new('ShaderNodeMath')
            pow_x.operation = 'POWER'
            pow_x.inputs[1].default_value = 2.0
            pow_x.location = (-300, 200)
            links.new(unpack_x.outputs[0], pow_x.inputs[0])

            # Y^2
            pow_y = nodes.new('ShaderNodeMath')
            pow_y.operation = 'POWER'
            pow_y.inputs[1].default_value = 2.0
            pow_y.location = (-300, 0)
            links.new(unpack_y.outputs[0], pow_y.inputs[0])

            # X^2 + Y^2
            add_sq = nodes.new('ShaderNodeMath')
            add_sq.operation = 'ADD'
            add_sq.location = (-100, 100)
            links.new(pow_x.outputs[0], add_sq.inputs[0])
            links.new(pow_y.outputs[0], add_sq.inputs[1])

            # 1 - (X^2 + Y^2)
            sub = nodes.new('ShaderNodeMath')
            sub.operation = 'SUBTRACT'
            sub.inputs[0].default_value = 1.0
            sub.location = (100, 100)
            links.new(add_sq.outputs[0], sub.inputs[1])

            # max(0, result)
            clamp = nodes.new('ShaderNodeMath')
            clamp.operation = 'MAXIMUM'
            clamp.inputs[1].default_value = 0.0
            clamp.location = (300, 100)
            links.new(sub.outputs[0], clamp.inputs[0])

            # sqrt(result)
            sqrt = nodes.new('ShaderNodeMath')
            sqrt.operation = 'POWER'
            sqrt.inputs[1].default_value = 0.5
            sqrt.location = (500, 100)
            links.new(clamp.outputs[0], sqrt.inputs[0])

            # Pack Z: Z * 0.5 + 0.5
            pack_z = nodes.new('ShaderNodeMath')
            pack_z.operation = 'MULTIPLY_ADD'
            pack_z.inputs[1].default_value = 0.5
            pack_z.inputs[2].default_value = 0.5
            pack_z.location = (700, 100)
            links.new(sqrt.outputs[0], pack_z.inputs[0])

            links.new(pack_z.outputs[0], out.inputs['Z'])
        else:
            group = bpy.data.node_groups[group_name]

        group_node = mat.node_tree.nodes.new('ShaderNodeGroup')
        group_node.node_tree = group
        group_node.name = group_name
        group_node.label = "Reconstruct Z"
        group_node.location = (-650, -555)

        # Feed unpacked channels into the math group
        mat.node_tree.links.new(texImage.outputs['Alpha'], group_node.inputs['X'])
        mat.node_tree.links.new(sep.outputs['Green'], group_node.inputs['Y'])

        # --- Combine Color ---
        combine = mat.node_tree.nodes.new('ShaderNodeCombineColor')
        combine.location = (-500, -450)

        # Alpha -> Red, Green -> Green, Math group -> Blue
        mat.node_tree.links.new(texImage.outputs['Alpha'], combine.inputs['Red'])
        mat.node_tree.links.new(sep.outputs['Green'], combine.inputs['Green'])
        mat.node_tree.links.new(group_node.outputs['Z'], combine.inputs['Blue'])

        # --- Normal Map ---
        norm_node = mat.node_tree.nodes.new('ShaderNodeNormalMap')
        norm_node.location = (-300, -450)
        mat.node_tree.links.new(combine.outputs['Color'], norm_node.inputs['Color'])
        mat.node_tree.links.new(norm_node.outputs['Normal'], bsdf.inputs['Normal'])

        return texImage, norm_node
    except Exception as e:
        print(f"Failed to load Normal Texture {normals_filepath}: {e}")
        return None, None

def addXTexture(x_filepath, mat, has_s_texture=False):
    """
    Loads the _x mask texture (Non-Color) and builds:
      - Separate Color (R/G/B)
      - If has_s_texture is True:
          Team Color RGB node (default blue)
          Mix node for team-color overlay driven by the Red channel
      - If has_s_texture is False:
          Red channel wired to BSDF Specular IOR Level
      - Blue channel wired to BSDF Roughness (inverted)
    Returns (team_color_mix_node or None, separate_color_node).
    """
    if not x_filepath or not os.path.exists(x_filepath):
        print(f"X texture not found: {x_filepath}")
        return None, None
    try:
        realpath = os.path.expanduser(x_filepath)
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if not bsdf: return None, None
        
        texImage = mat.node_tree.nodes.new('ShaderNodeTexImage')
        texImage.location = (-900, -250)
        img = bpy.data.images.load(realpath)
        img.colorspace_settings.name = 'Non-Color'
        texImage.image = img
        
        sep = mat.node_tree.nodes.new('ShaderNodeSeparateColor')
        sep.location = (-600, -250)
        mat.node_tree.links.new(texImage.outputs['Color'], sep.inputs['Color'])
        
        # Blue channel -> Inverted Roughness (always)
        invert = mat.node_tree.nodes.new('ShaderNodeInvert')
        invert.location = (-380, -180)
        mat.node_tree.links.new(sep.outputs['Blue'], invert.inputs['Color'])
        
        # Green channel -> Emission
        mat.node_tree.links.new(sep.outputs['Green'], bsdf.inputs['Emission Strength'])
        if 'Roughness' in bsdf.inputs:
            mat.node_tree.links.new(invert.outputs['Color'], bsdf.inputs['Roughness'])
        
        mix_team = None
        
        if has_s_texture:
            # Red channel -> Team color tinting
            team_color = mat.node_tree.nodes.new('ShaderNodeRGB')
            team_color.location = (-600, -50)
            team_color.outputs['Color'].default_value = (0.025, 0.025, 0.09, 1.0)
            
            mix_team = mat.node_tree.nodes.new('ShaderNodeMix')
            mix_team.data_type = 'RGBA'
            mix_team.blend_type = 'MIX'
            mix_team.location = (-400, 250)
            mix_team.inputs['Factor'].default_value = 1.0
            mat.node_tree.links.new(team_color.outputs['Color'], mix_team.inputs['A'])
            mat.node_tree.links.new(sep.outputs['Red'], mix_team.inputs['Factor'])
        else:
            # Red channel -> Specular IOR Level (no _s texture present)
            spec_input = bsdf.inputs.get('Specular IOR Level')
            if not spec_input:
                spec_input = bsdf.inputs.get('Specular')
            if spec_input:
                mat.node_tree.links.new(sep.outputs['Red'], spec_input)
            
        return mix_team, sep
    except Exception as e:
        print(f"Failed to load X Texture {x_filepath}: {e}")
        return None, None


def createSimpleMaterial(use_shadeless, viz_normals):        
    mat = bpy.data.materials.new('SimpleMat')
    mat.use_shadeless = use_shadeless
    mat.use_vertex_color_paint = viz_normals
    return mat

def createTextureLayer(name, me, texFaces):
    uvtex = me.tessface_uv_textures.new()
    uvtex.name = name
    for n,tf in enumerate(texFaces):        
        datum = uvtex.data[n]
        datum.uv1 = tf[0]
        datum.uv2 = tf[1]
        datum.uv3 = tf[2]
    return uvtex

def setVertexNormalsColors(me, faces, vertex_normals):
    vtex_normals = me.tessface_vertex_colors.new()
    vtex_normals.name = "vertex_normal_xyz"
    for face in faces:
        verts_in_face = face.vertices[:]
        vtex_normals.data[face.index].color1 = vertex_normals[verts_in_face[0]][0:3]
        vtex_normals.data[face.index].color2 = vertex_normals[verts_in_face[1]][0:3]
        vtex_normals.data[face.index].color3 = vertex_normals[verts_in_face[2]][0:3]
    
    vtex_normals = me.tessface_vertex_colors.new()
    vtex_normals.name = "vertex_normal_w"
    for face in faces:
        verts_in_face = face.vertices[:]
        alpha0 = (vertex_normals[verts_in_face[0]][3], vertex_normals[verts_in_face[0]][3], vertex_normals[verts_in_face[0]][3])
        alpha1 = (vertex_normals[verts_in_face[1]][3], vertex_normals[verts_in_face[1]][3], vertex_normals[verts_in_face[1]][3])
        alpha2 = (vertex_normals[verts_in_face[2]][3], vertex_normals[verts_in_face[2]][3], vertex_normals[verts_in_face[2]][3])
        vtex_normals.data[face.index].color1 = alpha0
        vtex_normals.data[face.index].color2 = alpha1
        vtex_normals.data[face.index].color3 = alpha2

def setVertexSpecularColors(me, faces, vertex_specular):
    vtex_specular = me.tessface_vertex_colors.new()
    vtex_specular.name = "vertex_specular_colors"
    for face in faces:
        verts_in_face = face.vertices[:]
        vtex_specular.data[face.index].color1 = vertex_specular[verts_in_face[0]][0:3]
        vtex_specular.data[face.index].color2 = vertex_specular[verts_in_face[1]][0:3]
        vtex_specular.data[face.index].color3 = vertex_specular[verts_in_face[2]][0:3]
        
    vtex_specular = me.tessface_vertex_colors.new()
    vtex_specular.name = "vertex_specular_alpha"
    for face in faces:
        verts_in_face = face.vertices[:]
        alpha0 = (vertex_specular[verts_in_face[0]][3], vertex_specular[verts_in_face[0]][3], vertex_specular[verts_in_face[0]][3])
        alpha1 = (vertex_specular[verts_in_face[1]][3], vertex_specular[verts_in_face[1]][3], vertex_specular[verts_in_face[1]][3])
        alpha2 = (vertex_specular[verts_in_face[2]][3], vertex_specular[verts_in_face[2]][3], vertex_specular[verts_in_face[2]][3])
        vtex_specular.data[face.index].color1 = alpha0
        vtex_specular.data[face.index].color2 = alpha1
        vtex_specular.data[face.index].color3 = alpha2

def setVertexBlendweightColors(me, faces, vertex_blendweight):
    vtex_blendweight = me.tessface_vertex_colors.new()
    vtex_blendweight.name = "vertex_blendweight_xyz"
    for face in faces:
        verts_in_face = face.vertices[:]
        vtex_blendweight.data[face.index].color1 = vertex_blendweight[verts_in_face[0]][0:3]
        vtex_blendweight.data[face.index].color2 = vertex_blendweight[verts_in_face[1]][0:3]
        vtex_blendweight.data[face.index].color3 = vertex_blendweight[verts_in_face[2]][0:3]
        
    vtex_blendweight = me.tessface_vertex_colors.new()
    vtex_blendweight.name = "vertex_blendweight_w"
    for face in faces:
        verts_in_face = face.vertices[:]
        alpha0 = (vertex_blendweight[verts_in_face[0]][3], vertex_blendweight[verts_in_face[0]][3], vertex_blendweight[verts_in_face[0]][3])
        alpha1 = (vertex_blendweight[verts_in_face[1]][3], vertex_blendweight[verts_in_face[1]][3], vertex_blendweight[verts_in_face[1]][3])
        alpha2 = (vertex_blendweight[verts_in_face[2]][3], vertex_blendweight[verts_in_face[2]][3], vertex_blendweight[verts_in_face[2]][3])
        vtex_blendweight.data[face.index].color1 = alpha0
        vtex_blendweight.data[face.index].color2 = alpha1
        vtex_blendweight.data[face.index].color3 = alpha2        

def parseMaterialInfo(file, specular_list):
    texture_name = b''
    normals_name = b''
    specular_name = b''
    state = 0
    flag = 0
    print("Reading materials", hex(file.tell()))
    materials, = struct.unpack("2s", file.read(2))
    if materials == b'nm':
        unknown, = struct.unpack("<I", file.read(4))
        unknown, = struct.unpack("<I", file.read(4))
    else:
        state = -1

    running = True
    while running:
        if state == 0:
            variable, = struct.unpack("4s", file.read(4))
            if variable == b'sffd':
                state = 1
                flag = "dffs"
            elif variable == b'smrn':
                state = 1
                flag = "nrms"
            elif variable == b'lcps':
                state = 1
                flag = "spcl"
            elif variable == b'1tsc':
                state = 3
            else:
                state = -1
            
        if state == 1:
            length, = struct.unpack("<I", file.read(4))
            if length > 0 and flag == "dffs":
                state = 2
            elif length > 0 and flag == "nrms":
                state = 2
            elif length > 0 and flag == "spcl":
                state = 2
            elif length == 0 and flag == "spcl":
                state = 4
            else:
                state = -1

        if state == 2:
            if flag == "dffs":
                texture_name, = struct.unpack("%ss" % length, file.read(length))
                file.read(4)
                flag = 0
                state = 0                
            elif flag == "nrms":
                normals_name, = struct.unpack("%ss" % length, file.read(length))
                file.read(4)
                flag = 0
                state = 0                
            elif flag == "spcl":
                specular_name, = struct.unpack("%ss" % length, file.read(length))
                state = 4

        if state == 3:
            int1, int2 = struct.unpack("<II", file.read(8))
            if int1 == 0 and int2 == 0:
                variable, = struct.unpack("4s", file.read(4))
                if variable == b'lcps':
                    length, = struct.unpack("<I", file.read(4))
                    if length != 0:
                        flag = "spcl"
                        state = 2
                    else:
                        state = 4

        if state == 4:
            int1, int2 = struct.unpack("<II", file.read(8))            
            variable, = struct.unpack("4s", file.read(4))
            if variable == b'lcps':
                red,green,blue = struct.unpack("<fff", file.read(12))
                specular_list.append( (red, green, blue) )
                if int2 == 2:
                    variable, = struct.unpack("4s", file.read(4))
                    file.read(16)
                    variable, = struct.unpack("4s", file.read(4))
                    file.read(24)
                    state = 99
                if int2 == 1:
                    file.read(24)
                    state = 99                            

        if state == 99:
            return texture_name, normals_name, specular_name
        
        if state == -1:
            print("This object's materials format is unsupported. Unknown at", hex(file.tell()))
            return 

def bone_transform(joint_matrix):
    m = mathutils.Matrix(joint_matrix)
    m = m.inverted().transposed()
    return m

def build_armature(amt_ob, crf_jointmap, bone_name_map):
    bpy.context.view_layer.objects.active = amt_ob
    bpy.ops.object.mode_set(mode='EDIT', toggle=False)
    edit_bones = amt_ob.data.edit_bones

    id_to_bone = {}

    # Pass 1: create all bones
    for bone_id, crf_bone in crf_jointmap.bone_dict.items():
        if bone_id >= len(crf_jointmap.joint_list):
            continue

        joint = crf_jointmap.joint_list[bone_id]
        # Use the pre‑computed mapped name
        unique_name = bone_name_map.get(bone_id, f"Bone_{bone_id:08X}")

        new_bone = edit_bones.new(unique_name)

        m_game = bone_transform(joint.matrix)
        g_loc = m_game.translation
        b_loc = mathutils.Vector((g_loc.x * 0.1, g_loc.z * 0.1, g_loc.y * 0.1))

        g_x = m_game.to_3x3().col[0].normalized()
        g_y = m_game.to_3x3().col[1].normalized()
        g_z = m_game.to_3x3().col[2].normalized()

        b_x = mathutils.Vector((g_x.x, g_x.z, g_x.y))
        b_y = mathutils.Vector((g_z.x, g_z.z, g_z.y))
        b_z = mathutils.Vector((g_y.x, g_y.z, g_y.y))

        bone_mat = mathutils.Matrix()
        bone_mat.col[0] = b_x.to_4d()
        bone_mat.col[1] = b_y.to_4d()
        bone_mat.col[2] = b_z.to_4d()
        bone_mat.col[3] = b_loc.to_4d()
        bone_mat.col[3][3] = 1.0

        new_bone.head = (0, 0, 0)
        new_bone.tail = (0, 1, 0)
        new_bone.matrix = bone_mat
        new_bone.length = 0.1

        safe_bone_id = crf_bone.real_bone_id
        if safe_bone_id >= 0x80000000:
            safe_bone_id -= 0x100000000
        new_bone['bone_id'] = safe_bone_id
        new_bone['original_name'] = crf_bone.bone_name.decode('utf-8', errors='ignore').rstrip('\x00')

        id_to_bone[bone_id] = new_bone

    # Pass 2: set parenting
    for bone_id, crf_bone in crf_jointmap.bone_dict.items():
        if bone_id >= len(crf_jointmap.joint_list):
            continue

        joint = crf_jointmap.joint_list[bone_id]
        parent_id = joint.parent_id

        if parent_id != 0xFFFFFFFF and parent_id in id_to_bone:
            child_bone = id_to_bone[bone_id]
            parent_bone = id_to_bone[parent_id]
            child_bone.parent = parent_bone
            child_bone.use_connect = False

    bpy.ops.object.mode_set(mode='OBJECT', toggle=False)

def load(operator, context, filepath,
         global_clamp_size=0.0,
         use_verbose=False,
         dump_first_only=False,
         use_uv_map=True,
         use_diffuse_texture=True,
         use_normal_texture=True,
         use_specular_texture=True,         
         use_computed_normals=False,
         use_shadeless=True,
         viz_normals=True,
         viz_blendweights=False,
         use_specular=True,
         use_diffuse_only=False,
         global_matrix=None,
         use_custom_normals=False,
         ):

    print('\nimporting crf %r' % filepath)
    filepath = os.fsencode(filepath)

    global_matrix = mathutils.Matrix.Identity(4)

    new_objects = []
    time_main = time.time()

    file = open(filepath, "rb")
    CRF = CRF_object()    
    
    try:
        CRF.parse_bin(file)

    except Exception as e:
        print(f"Error parsing CRF bin file: {e}")
        return {'CANCELLED'}
        
    meshfile = CRF.meshfile
    bad_vertex_list = []
    
    if not hasattr(meshfile, 'num_meshes') or meshfile.num_meshes is None:
        print("No valid meshes found.")
        return {'CANCELLED'}

    bone_name_map = {}
    if hasattr(CRF, 'jointmap') and CRF.jointmap and hasattr(CRF.jointmap, 'bone_dict'):
        for bone_id, crf_bone in CRF.jointmap.bone_dict.items():
            if bone_id >= len(CRF.jointmap.joint_list):
                continue
            orig_name = crf_bone.bone_name.decode('utf-8', errors='ignore').rstrip('\x00')
            if not orig_name:
                orig_name = f"Bone_{bone_id:08X}"
            final_name = truncate_bone_name(orig_name)
            bone_name_map[bone_id] = final_name

    for i in range(0, len(meshfile.meshes)):
        verts_loc = []
        verts_tex0 = []
        vertex_normals = []
        
        mesh = meshfile.meshes[i]
        
        valid_faces = []
        max_idx = len(mesh.vertices0) - 1
        
        for j in range(0, len(mesh.face_list)):
            v1, v2, v3 = mesh.face_list[j]
            
            # 1. Skip degenerate faces (0 area)
            if v1 == v2 or v1 == v3 or v2 == v3:
                continue
                
            # 2. Skip faces with out-of-bounds indices
            if v1 > max_idx or v2 > max_idx or v3 > max_idx:
                print(f"Warning: Mesh {i} Face {j} has out-of-bounds index. Max allowed: {max_idx}")
                continue
                
            valid_faces.append((v3, v2, v1))
        
        for vertex in mesh.vertices0:
            verts_loc.append((vertex.x_blend, vertex.y_blend, vertex.z_blend))            
            verts_tex0.append((vertex.u0_blend, vertex.v0_blend))        
            vertex_normals.append((vertex.normal_x_blend, vertex.normal_y_blend, vertex.normal_z_blend))
            
        if bpy.ops.object.select_all.poll():
            bpy.ops.object.select_all(action='DESELECT')

        me = bpy.data.meshes.new("Dumped_Mesh")
        object_name = os.path.splitext(os.path.basename(filepath))[0]
        ob = bpy.data.objects.new(os.fsdecode(object_name) + "_%i" % mesh.mesh_number, me)
        
        try:
            me.from_pydata(verts_loc, [], valid_faces)
            
            for poly in me.polygons:
                poly.use_smooth = True

            # Auto Smooth / Custom Normal Logic
            if use_custom_normals:
                custom_normals = [mathutils.Vector(vertex_normals[loop.vertex_index]).normalized() for loop in me.loops]
                me.normals_split_custom_set(custom_normals)
                
            if hasattr(me, "use_auto_smooth"):
                me.use_auto_smooth = True

            verts_tex0 = [
                idx
                for poly in me.polygons
                for vidx in poly.vertices
                for idx in verts_tex0[vidx]
            ]
            me.uv_layers.new().data.foreach_set("uv", verts_tex0)
        except Exception as e:
            print(f"Failed setting mesh data for mesh {i}: {e}")

        # Material & Textures Setup
        mat = createMaterial('TexMat')
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            if bsdf.inputs.get("Roughness"):
                bsdf.inputs.get("Roughness").default_value = 0.5
            spec_input = bsdf.inputs.get('Specular IOR Level')
            if not spec_input:
                spec_input = bsdf.inputs.get('Specular')
            if spec_input:
                spec_input.default_value = 0.0

        # Diffuse Only Override
        local_use_normal = use_normal_texture if not use_diffuse_only else False
        local_use_specular = use_specular_texture if not use_diffuse_only else False

        diffuse_name = getattr(mesh.materials, 'diffuse_texture', "")
        normal_name  = getattr(mesh.materials, 'normal_texture', "")
        specular_name = getattr(mesh.materials, 'specular_texture', "")
        special_name = getattr(mesh.materials, 'special_texture', "")

        s_name = specular_name
        x_name = special_name
            
        # Load textures
        diff_node = None
        if use_diffuse_texture and diffuse_name:
            diff_fp = find_texture(filepath, diffuse_name)
            diff_node = addDiffuseTexture(diff_fp, mat)

        s_node = None
        if local_use_specular and s_name:
            s_fp = find_texture(filepath, s_name)
            s_node = addSpecularTexture(s_fp, mat)

        norm_tex_node = None
        norm_map_node = None
        if local_use_normal and normal_name:
            norm_fp = find_texture(filepath, normal_name)
            norm_tex_node, norm_map_node = addNormalTexture(norm_fp, mat)

        x_mix_node = None
        x_sep_node = None
        if not use_diffuse_only and x_name:
            x_fp = find_texture(filepath, x_name)
            x_mix_node, x_sep_node = addXTexture(x_fp, mat, has_s_texture=(s_node is not None))

        base_color_socket = None
        if diff_node:
            base_color_socket = diff_node.outputs['Color']

        if x_mix_node and base_color_socket:
            mat.node_tree.links.new(base_color_socket, x_mix_node.inputs['B'])
            base_color_socket = x_mix_node.outputs['Result']

        if base_color_socket and bsdf and 'Base Color' in bsdf.inputs:
            mat.node_tree.links.new(base_color_socket, bsdf.inputs['Base Color'])

        if diff_node and 'Alpha' in bsdf.inputs:
            already_connected = False
            for link in mat.node_tree.links:
                if (link.from_node == diff_node and 
                    link.from_socket.name == 'Alpha' and 
                    link.to_node == bsdf and 
                    link.to_socket.name == 'Alpha'):
                    already_connected = True
                    break
            if not already_connected:
                mat.node_tree.links.new(diff_node.outputs['Alpha'], bsdf.inputs['Alpha'])

        # If _s texture exists, build Glossy/Transparent mix
        if s_node:
            output_node = None
            for node in mat.node_tree.nodes:
                if node.type == 'OUTPUT_MATERIAL':
                    output_node = node
                    break
            if not output_node:
                output_node = mat.node_tree.nodes.new('ShaderNodeOutputMaterial')
                output_node.location = (300, 300)

            glossy = mat.node_tree.nodes.new('ShaderNodeBsdfGlossy')
            glossy.location = (-180, 325)
            glossy.inputs['Roughness'].default_value = 0.5
            mat.node_tree.links.new(s_node.outputs['Color'], glossy.inputs['Color'])

            if norm_map_node:
                mat.node_tree.links.new(norm_map_node.outputs['Normal'], glossy.inputs['Normal'])

            transparent = mat.node_tree.nodes.new('ShaderNodeBsdfTransparent')
            transparent.location = (-20, 230)

            # Mix Shader 1: Transparent + Glossy (Fac = diffuse alpha)
            mix1 = mat.node_tree.nodes.new('ShaderNodeMixShader')
            mix1.location = (160, 300)
            mat.node_tree.links.new(transparent.outputs['BSDF'], mix1.inputs[1])
            mat.node_tree.links.new(glossy.outputs['BSDF'], mix1.inputs[2])

            if diff_node:
                mat.node_tree.links.new(diff_node.outputs['Alpha'], mix1.inputs['Fac'])
            else:
                mix1.inputs['Fac'].default_value = 1.0

            # Mix Shader 2: Principled BSDF + Mix1 (Fac = 0.5)
            mix2 = mat.node_tree.nodes.new('ShaderNodeMixShader')
            mix2.location = (400, 300)
            mix2.inputs['Fac'].default_value = 0.5
            mat.node_tree.links.new(bsdf.outputs['BSDF'], mix2.inputs[1])
            mat.node_tree.links.new(mix1.outputs['Shader'], mix2.inputs[2])

            # Connect final mix to Material Output
            for link in mat.node_tree.links:
                if link.to_node == output_node and link.to_socket.name == 'Surface':
                    mat.node_tree.links.remove(link)
                    break
            mat.node_tree.links.new(mix2.outputs['Shader'], output_node.inputs['Surface'])

        ob.data.materials.append(mat)
        me.update(calc_edges=True)
        new_objects.append(ob)

        if hasattr(CRF, 'jointmap') and CRF.jointmap and hasattr(CRF.jointmap, 'bone_dict'):
            bone_palette = None
            if hasattr(CRF, 'skeleton') and CRF.skeleton and i < len(CRF.skeleton.skeleton_list):
                bone_palette = CRF.skeleton.skeleton_list[i]

            vgroups = {}
            blend_verts = []
            if hasattr(mesh, 'vertices2') and mesh.vertices2:
                blend_verts = mesh.vertices2
            elif hasattr(mesh, 'vertices1') and mesh.vertices1:
                blend_verts = mesh.vertices1

            if blend_verts:
                for v_idx, vertex in enumerate(blend_verts):
                    if not hasattr(vertex, 'blendindeces'):
                        continue

                    w_raw = getattr(vertex, 'blendweight', getattr(vertex, 'blendweights', []))
                    if not isinstance(w_raw, (list, tuple)):
                        w_raw = [w_raw]
                    w_array = [(b + 256) % 256 for b in w_raw] if w_raw else []

                    if not w_array:
                        if vertex.blendindeces:
                            local_idx = vertex.blendindeces[0]
                            global_bone_id = local_idx
                            if bone_palette and local_idx < len(bone_palette):
                                global_bone_id = bone_palette[local_idx]
                            # ---- USE MAPPED NAME ----
                            if global_bone_id in bone_name_map:
                                unique_bone_name = bone_name_map[global_bone_id]
                            else:
                                unique_bone_name = f"Bone_{global_bone_id:08X}"
                            # -------------------------
                            if unique_bone_name not in vgroups:
                                vgroups[unique_bone_name] = ob.vertex_groups.new(name=unique_bone_name)
                            vgroups[unique_bone_name].add([v_idx], 1.0, 'REPLACE')
                        continue

                    total = sum(w_array)
                    if total == 0:
                        total = 1

                    for j, local_idx in enumerate(vertex.blendindeces):
                        if j >= len(w_array):
                            break
                        weight = w_array[j] / 255.0
                        if weight > 0.0:
                            global_bone_id = local_idx
                            if bone_palette and local_idx < len(bone_palette):
                                global_bone_id = bone_palette[local_idx]
                            # ---- USE MAPPED NAME ----
                            if global_bone_id in bone_name_map:
                                unique_bone_name = bone_name_map[global_bone_id]
                            else:
                                unique_bone_name = f"Bone_{global_bone_id:08X}"
                            # -------------------------
                            if unique_bone_name not in vgroups:
                                vgroups[unique_bone_name] = ob.vertex_groups.new(name=unique_bone_name)
                            vgroups[unique_bone_name].add([v_idx], weight, 'REPLACE')

    # Armature / Skinning
    amt_ob = None
    if hasattr(CRF, 'footer') and CRF.footer and hasattr(CRF.footer, 'get_jointmap'):
        if CRF.footer.get_jointmap() is not None and hasattr(CRF, 'jointmap') and CRF.jointmap is not None:
            amt = bpy.data.armatures.new("Armature")
            amt_ob = bpy.data.objects.new("Armature", amt)
            bpy.context.scene.collection.objects.link(amt_ob)
            amt_ob.matrix_world = global_matrix
            try:
                build_armature(amt_ob, CRF.jointmap, bone_name_map)   # <-- added argument
            except Exception as e:
                print(f"Failed to build skeleton tree: {e}")
            bpy.ops.object.mode_set(mode='OBJECT')

    for ob in new_objects:
        if ob.name not in bpy.context.collection.objects:
            bpy.context.collection.objects.link(ob)
        ob.matrix_world = global_matrix

    # Armature Parenting
    if amt_ob and new_objects:
        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
            
        bpy.ops.object.select_all(action='DESELECT')
        
        for ob in new_objects:
            ob.select_set(True)
            
        amt_ob.select_set(True)
        bpy.context.view_layer.objects.active = amt_ob
        bpy.ops.object.parent_set(type='ARMATURE_NAME')

    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()

    if global_clamp_size:
        axis_min = [1000000000] * 3
        axis_max = [-1000000000] * 3
        for ob in new_objects:
            for v in ob.bound_box:
                for axis, value in enumerate(v):
                    if axis_min[axis] > value:
                        axis_min[axis] = value
                    if axis_max[axis] < value:
                        axis_max[axis] = value

        max_axis = max(axis_max[0] - axis_min[0], axis_max[1] - axis_min[1], axis_max[2] - axis_min[2])
        scale = 1.0
        while global_clamp_size < max_axis * scale:
            scale = scale / 10.0
        for obj in new_objects:
            obj.scale = scale, scale, scale

    print("finished importing: %r in %.4f sec." % (filepath, (time.time() - time_main)))
    return {'FINISHED'}