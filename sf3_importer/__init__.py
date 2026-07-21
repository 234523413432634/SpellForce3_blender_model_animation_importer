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

bl_info = {
    "name": "Spellforce 3 CRF/CAF format",
    "author": "Stanislav Bobovych(original crf importer)",
    "version": (1, 6),
    "blender": (4, 0, 0),
    "location": "File > Import / Export",
    "description": "Import/Export CRF meshes and CAF animations.",
    "warning": "",
    "wiki_url": "",
    "tracker_url": "",
    "category": "Import-Export"}

if "bpy" in locals():
    import imp
    if "import_crf" in locals():
        imp.reload(import_crf)
    if "import_caf" in locals():
        imp.reload(import_caf)
    if "export_caf" in locals():
        imp.reload(export_caf)

import bpy
import os
from bpy.props import (BoolProperty,
                       FloatProperty,
                       StringProperty,
                       EnumProperty,
                       FloatVectorProperty,
                       CollectionProperty,
                       IntProperty,
                       )
from bpy_extras.io_utils import (ExportHelper,
                                 ImportHelper,
                                 path_reference_mode,
                                 axis_conversion,
                                 )


class ImportCRF(bpy.types.Operator, ImportHelper):
    '''Load SpellForce 3 CRF Files'''
    bl_idname = "import_scene.crf"
    bl_label = "Import CRF"
    bl_options = {'REGISTER', 'PRESET', 'UNDO'}
    filename_ext = ".crf"
    filter_glob: StringProperty(
        default="*.crf", options={"HIDDEN"}, maxlen=255
    )
    
    directory: StringProperty(
        subtype='DIR_PATH',
    )
    files: CollectionProperty(
        type=bpy.types.OperatorFileListElement,
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    use_custom_normals: BoolProperty(
            name="Use Custom Normals",
            description="Import explicit vertex normals from the CRF file. Uncheck to auto-smooth.",
            default=True,
            )
    use_diffuse_only: BoolProperty(
            name="Diffuse Texture Only",
            description="Skip importing normal, specular and _x mask textures.",
            default=False,
            )
    team_color: FloatVectorProperty(
            name="Team Color",
            description="Default team color (if applicable)",
            subtype='COLOR',
            size=4,
            default=(0.025, 0.025, 0.09, 1.0),
            min=0.0, max=1.0
            )
    glossiness_scale: FloatProperty(
            name="Glossiness Scale",
            description="Higher values make metallic parts more reflective. Recommended values: 1.2 - 1.4",
            default=1.0,
            )

    def execute(self, context):
        from . import import_crf

        if not self.files:
            return import_crf.load(self, context, self.filepath,
                        use_custom_normals=self.use_custom_normals,
                        use_diffuse_only=self.use_diffuse_only,
                        team_color=self.team_color,
                        glossiness_scale=self.glossiness_scale)

        for file_elem in self.files:
            current_filepath = os.path.join(self.directory, file_elem.name)
            print(f"Batch Importing: {current_filepath}")
            
            import_crf.load(self, context, current_filepath,
                        use_custom_normals=self.use_custom_normals,
                        use_diffuse_only=self.use_diffuse_only,
                        team_color=self.team_color,
                        glossiness_scale=self.glossiness_scale)

        return {'FINISHED'}

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "use_custom_normals")
        layout.prop(self, "use_diffuse_only")
        layout.prop(self, "team_color")
        layout.prop(self, "glossiness_scale")


class ImportCAF(bpy.types.Operator, ImportHelper):
    '''Load a SpellForce 3 CAF Animation File'''
    bl_idname = "import_scene.caf"
    bl_label = "Import CAF"
    bl_options = {'REGISTER', 'PRESET', 'UNDO'}
    filename_ext = ".caf"
    filter_glob: StringProperty(
        default="*.caf", options={"HIDDEN"}, maxlen=255
    )

    fps: IntProperty(
        name="FPS",
        description="Frames per second for the animation",
        default=30,
        min=1,
    )

    def execute(self, context):
        from . import import_caf
        return import_caf.load(self, context, self.filepath, fps=self.fps)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "fps")


class ExportCAF(bpy.types.Operator, ExportHelper):
    '''Export an Armature Action to SpellForce 3 CAF format'''
    bl_idname = "export_scene.caf"
    bl_label = "Export CAF"
    bl_options = {'REGISTER', 'PRESET', 'UNDO'}
    filename_ext = ".caf"
    filter_glob: StringProperty(
        default="*.caf", options={"HIDDEN"}, maxlen=255
    )

    fps: IntProperty(
        name="FPS",
        description="Frames per second for the animation",
        default=30,
        min=1,
    )

    def execute(self, context):
        from . import export_caf

        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Active object must be an Armature")
            return {'CANCELLED'}

        if not obj.animation_data or not obj.animation_data.action:
            self.report({'ERROR'}, "Armature must have an active Action assigned")
            return {'CANCELLED'}

        try:
            export_caf.export_caf(self.filepath, arm_obj=obj, fps=self.fps)
        except Exception as e:
            self.report({'ERROR'}, f"Export failed: {e}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}

        self.report({'INFO'}, f"CAF exported to {self.filepath}")
        return {'FINISHED'}

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "fps")


# ---------- Menu Registration ----------
_import_menus_attached = False
_export_menus_attached = False

def menu_func_import(self, context):
    self.layout.operator(ImportCRF.bl_idname, text="SpellForce 3 model (.crf)")
    self.layout.operator(ImportCAF.bl_idname, text="SpellForce 3 animation (.caf)")

def menu_func_export(self, context):
    self.layout.operator(ExportCAF.bl_idname, text="SpellForce 3 animation (.caf)")

def _attach_menus():
    global _import_menus_attached, _export_menus_attached

    # Import menu
    if not _import_menus_attached:
        try:
            bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
        except Exception:
            pass
        bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
        _import_menus_attached = True

    # Export menu
    if not _export_menus_attached:
        try:
            bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
        except Exception:
            pass
        bpy.types.TOPBAR_MT_file_export.append(menu_func_export)
        _export_menus_attached = True

def _detach_menus():
    global _import_menus_attached, _export_menus_attached
    try:
        bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    except Exception:
        pass
    _import_menus_attached = False

    try:
        bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    except Exception:
        pass
    _export_menus_attached = False


def register():
    bpy.utils.register_class(ImportCRF)
    bpy.utils.register_class(ImportCAF)
    bpy.utils.register_class(ExportCAF)
    _attach_menus()

def unregister():
    bpy.utils.unregister_class(ImportCRF)
    bpy.utils.unregister_class(ImportCAF)
    bpy.utils.unregister_class(ExportCAF)
    _detach_menus()

if __name__ == "__main__":
    register()