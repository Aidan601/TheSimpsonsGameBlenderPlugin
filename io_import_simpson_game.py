bl_info = {
    "name": "Simpsons Game Importer",
    "author": "Turk (updated by Figglebottom)",
    "version": (1, 1, 0),
    "blender": (5, 0, 0),
    "location": "File > Import",
    "description": "Imports Simpsons Game mesh chunks from .preinstanced files",
    "warning": "",
    "category": "Import-Export",
}

import bpy
import bmesh
import struct
import math
import re
from bpy.props import (
    StringProperty,
    CollectionProperty,
)
from bpy_extras.io_utils import ImportHelper


def strip2face(strip):
    """Convert a triangle strip index list to triangle faces."""
    flipped = False
    faces = []
    for x in range(len(strip) - 2):
        if flipped:
            faces.append((strip[x + 2], strip[x + 1], strip[x]))
        else:
            faces.append((strip[x + 1], strip[x + 2], strip[x]))
        flipped = not flipped
    return faces


def set_smoothing(obj, angle_rad=math.radians(60.0)):
    """set_smoothing"""
    mesh = obj.data
    if mesh and getattr(mesh, "polygons", None):
        try:
            mesh.polygons.foreach_set("use_smooth", [True] * len(mesh.polygons))
        except Exception:
            for p in mesh.polygons:
                p.use_smooth = True

    # Old API (<= 3.x)
    if hasattr(mesh, "use_auto_smooth"):
        try:
            mesh.use_auto_smooth = True
            if hasattr(mesh, "auto_smooth_angle"):
                mesh.auto_smooth_angle = angle_rad
            return
        except Exception:
            pass

    # Newer operator (4.x/5.x) if present
    try:
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        if hasattr(bpy.ops.object, "shade_smooth_by_angle"):
            bpy.ops.object.shade_smooth_by_angle(angle=angle_rad)
            return
        elif hasattr(bpy.ops.object, "shade_smooth"):
            bpy.ops.object.shade_smooth()
    except Exception:
        pass

    # Last resort fallback (kept as a modifier so it can be removed)
    try:
        mod = obj.modifiers.new(name="SmoothByAngle_Fallback", type='EDGE_SPLIT')
        mod.use_edge_angle = True
        mod.split_angle = angle_rad
    except Exception:
        pass


class SimpGameImport(bpy.types.Operator, ImportHelper):
    bl_idname = "custom_import_scene.simpgame"
    bl_label = "Import Simpsons Game Mesh"
    bl_options = {'PRESET', 'UNDO'}

    filter_glob: StringProperty(
        default="*.preinstanced",
        options={'HIDDEN'},
        maxlen=255,
    )
    filepath: StringProperty(subtype='FILE_PATH')
    files: CollectionProperty(type=bpy.types.OperatorFileListElement)

    def draw(self, context):
        # Nothing custom yet
        pass

    def execute(self, context):
        with open(self.filepath, "rb") as cur_file:
            cur_collection = bpy.data.collections.new("Simpsons Import")
            context.scene.collection.children.link(cur_collection)

            tmp_read = cur_file.read()

            msh_bytes = re.compile(b"\x33\xEA\x00\x00....\x2D\x00\x02\x1C", re.DOTALL)
            mesh_iter = 0

            for x in msh_bytes.finditer(tmp_read):
                cur_file.seek(x.end() + 4)
                face_data_off = int.from_bytes(cur_file.read(4), byteorder='little')
                _mesh_data_size = int.from_bytes(cur_file.read(4), byteorder='little')
                mesh_chunk_start = cur_file.tell()

                cur_file.seek(0x14, 1)
                mdata_table_count = int.from_bytes(cur_file.read(4), byteorder='big')
                mdata_sub_count = int.from_bytes(cur_file.read(4), byteorder='big')

                # Table offsets (currently unused, but kept to match original structure)
                mdata_offsets = []
                for _ in range(mdata_table_count):
                    cur_file.seek(4, 1)
                    mdata_offsets.append(int.from_bytes(cur_file.read(4), byteorder='big'))

                mdata_sub_start = cur_file.tell()

                for i in range(mdata_sub_count):
                    cur_file.seek(mdata_sub_start + i * 0xC + 8)
                    offset = int.from_bytes(cur_file.read(4), byteorder='big')

                    cur_file.seek(offset + mesh_chunk_start + 0xC)
                    vert_count_data_off = int.from_bytes(cur_file.read(4), byteorder='big') + mesh_chunk_start

                    # Vertex count & layout
                    cur_file.seek(vert_count_data_off)
                    vert_chunk_total_size = int.from_bytes(cur_file.read(4), byteorder='big')
                    vert_chunk_size = int.from_bytes(cur_file.read(4), byteorder='big')
                    vert_count = int(vert_chunk_total_size / vert_chunk_size)

                    cur_file.seek(8, 1)
                    vertex_start = int.from_bytes(cur_file.read(4), byteorder='big') + face_data_off + mesh_chunk_start

                    # Face/strip data
                    cur_file.seek(0x14, 1)
                    face_count = int(int.from_bytes(cur_file.read(4), byteorder='big') / 2)
                    cur_file.seek(4, 1)
                    face_start = int.from_bytes(cur_file.read(4), byteorder='big') + face_data_off + mesh_chunk_start

                    # Read strips
                    cur_file.seek(face_start)
                    strip_list = []
                    tmp_list = []
                    for _f in range(face_count):
                        idx = int.from_bytes(cur_file.read(2), byteorder='big')
                        if idx == 65535:
                            if tmp_list:
                                strip_list.append(tmp_list.copy())
                                tmp_list.clear()
                        else:
                            tmp_list.append(idx)
                    if tmp_list:
                        strip_list.append(tmp_list.copy())

                    face_table = []
                    for strip in strip_list:
                        face_table.extend(strip2face(strip))

                    # Read verts + uvs
                    vert_table = []
                    uv_table = []
                    for v in range(vert_count):
                        cur_file.seek(vertex_start + v * vert_chunk_size)
                        temp_vert = struct.unpack('>fff', cur_file.read(4 * 3))
                        vert_table.append(temp_vert)

                        cur_file.seek(vertex_start + v * vert_chunk_size + vert_chunk_size - 8)
                        temp_uv = struct.unpack('>ff', cur_file.read(4 * 2))
                        uv_table.append((temp_uv[0], 1.0 - temp_uv[1]))

                    # Build mesh
                    mesh_data = bpy.data.meshes.new("Mesh")
                    obj = bpy.data.objects.new(f"Mesh_{mesh_iter}_{i}", mesh_data)
                    cur_collection.objects.link(obj)

                    bm = bmesh.new()

                    for v in vert_table:
                        bm.verts.new((v[0], v[1], v[2]))
                    bm.verts.ensure_lookup_table()

                    vert_list = [v for v in bm.verts]

                    for f in face_table:
                        try:
                            bm.faces.new((vert_list[f[0]], vert_list[f[1]], vert_list[f[2]]))
                        except Exception:
                            # Duplicate face or bad indices; skip
                            continue

                    bm.faces.ensure_lookup_table()

                    # UVs + smooth shading at the bmesh level
                    uv_layer = bm.loops.layers.uv.verify()
                    for face in bm.faces:
                        face.smooth = True
                        for loop in face.loops:
                            try:
                                loop[uv_layer].uv = uv_table[loop.vert.index]
                            except Exception:
                                continue

                    bm.to_mesh(mesh_data)
                    bm.free()

                    mesh_data.update()

                    # Orientation (match original)
                    obj.rotation_euler = (math.radians(90.0), 0.0, 0.0)

                    # Auto smooth compatibility (fixes Blender 4/5 "use_auto_smooth" removal)
                    set_smoothing(obj)

                mesh_iter += 1

        return {'FINISHED'}


def menu_func_import(self, context):
    self.layout.operator(SimpGameImport.bl_idname, text="Simpsons Game (.preinstanced)")


def register():
    bpy.utils.register_class(SimpGameImport)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.utils.unregister_class(SimpGameImport)


if __name__ == "__main__":
    register()
