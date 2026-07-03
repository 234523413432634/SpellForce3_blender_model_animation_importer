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
    "version": (1, 0),
    "blender": (4, 0, 0),
    "location": "File > Import",
    "description": "Import CRF, Import CRF mesh, UV's, "
                   "materials and textures. Import CAF animations.",
    "warning": "",
    "wiki_url": "",
    "tracker_url": "",
    "category": "Import"}

if "bpy" in locals():
    import imp
    if "import_crf" in locals():
        imp.reload(import_crf)
    if "caf_importer_script" in locals():
        imp.reload(caf_importer_script)

import bpy
from bpy.props import (BoolProperty,
                       FloatProperty,
                       StringProperty,
                       EnumProperty,
                       FloatVectorProperty,
                       )
from bpy_extras.io_utils import (ExportHelper,
                                 ImportHelper,
                                 path_reference_mode,
                                 axis_conversion,
                                 )


class ImportCRF(bpy.types.Operator, ImportHelper):
    '''Load a SpellForce 3 CRF File'''
    bl_idname = "import_scene.crf"
    bl_label = "Import CRF"
    bl_options = {'REGISTER', 'PRESET', 'UNDO'}
    filename_ext = ".crf"
    filter_glob: StringProperty(
        default="*.crf", options={"HIDDEN"}, maxlen=255
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

        return import_crf.load(self, context, self.filepath,
                    use_custom_normals=self.use_custom_normals,
                    use_diffuse_only=self.use_diffuse_only,
                    team_color=self.team_color,
                    glossiness_scale=self.glossiness_scale)

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
    loop_animation: BoolProperty(
            name="Looping Animation",
            description="Insert keyframes at the end to close the animation loop.",
            default=True,
            )

    def execute(self, context):
        from . import import_caf

        return import_caf.load(self, context, self.filepath,
                    loop_animation=self.loop_animation)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "loop_animation")


_menus_attached = False

def _attach_menus_idempotent():
    global _menus_attached
    if _menus_attached:
        return
    # Remove old callbacks if they exist (safe if they don't)
    try:
        bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    except Exception:  # pylint: disable=broad-exception-caught
        pass
    # Append once
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    _menus_attached = True

def _detach_menus_safely():
    global _menus_attached
    try:
        bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    except Exception:  # pylint: disable=broad-exception-caught
        pass
    _menus_attached = False

def menu_func_import(self, context):
    self.layout.operator(ImportCRF.bl_idname, text="SpellForce 3 model (.crf)")
    self.layout.operator(ImportCAF.bl_idname, text="SpellForce 3 animation (.caf)")

def register():
    bpy.utils.register_class(ImportCRF)
    bpy.utils.register_class(ImportCAF)
    _attach_menus_idempotent()
    

def unregister():
    bpy.utils.unregister_class(ImportCRF)
    bpy.utils.unregister_class(ImportCAF)
    _detach_menus_safely()

if __name__ == "__main__":
    register()