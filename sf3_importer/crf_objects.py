from __future__ import print_function    
    
import math
import struct

# Footer constants
CRF_ROOT_NODE = 0x0
CRF_MESHFILE = 0x1b4f7cc7
CRF_JOINTMAP = 0xb8fa7643
CRF_SKELETON = 0xbd9d53a3

CRF_FOOTER_ENTRY_CONSTANTS = {CRF_ROOT_NODE:"CRF_ROOT_NODE", CRF_MESHFILE:"CRF_MESHFILE", CRF_JOINTMAP:"CRF_JOINTMAP", CRF_SKELETON:"CRF_SKELETON"}

# unsupported constants
CRF_SKININFO = None
CRF_GEOMESH = None
CRF_COLLISION_SHAPE = None
CRF_OCCLUSION_SHAPE = None

# Supported texture formats
CRF_TexFormats = ["bmp", "tga", "jpg", "dds"]

# Materials constants
CRF_Diffuse = b"sffd"
CRF_Normals = b"smrn"
CRF_Specular = b"lcps"
CRF_Custom1 = b"1tsc"
CRF_Custom2 = b"2tsc"
CRF_Custom3 = b"3tcs"
CRF_Custom4 = b"4tcs"
CRF_Custom5 = b"5tcs"
CRF_Custom6 = b"6tcs"
CRF_Custom7 = b"7tcs"
CRF_Custom8 = b"8tcs"
CRF_Custom9 = b"9tcs"
CRF_Custom10 = b"01tcs"
CRF_Custom11 = b"11cs"
CRF_Custom12 = b"21cs"

CRF_NormalLayered = "smrn1tsclcps" # MoG TangentNormalLayered
CRF_NormalLayeredMagick = 0x10004000

CRF_TransperentEnvM = "smrnlcps" # M+ Transparent Env
CRF_TransperentEnvMMagick = 0x0000000

# unsupported materials
CRF_Relection = "clfr"
CRF_Brightness = "snrb"
CRF_Environment = "tvne"
CRF_Emissive = "vsme"

CRF_MultiFunctional = "1tsc2tscsffd" # MoG MultiFunctional

CRF_SkinLayeredM = "lcpssmrn1tsc2tsc" #M+ SkinLayered
CRF_SkinLayeredMMagick = 0x10002000

CRF_SkinLayeredMP = "6tsc5tsc" #MP+ SkinLayered

def dump_hex(file_obj, title, size=4096):
    """Reads ahead in the file to print a formatted hex dump, then resets the cursor."""
    pos = file_obj.tell()
    data = file_obj.read(size)
    file_obj.seek(pos)
    
    print(f"\n=== {title} HEX DUMP ===")
    for i in range(0, len(data), 16):
        chunk = data[i:i+16]
        hex_str = ' '.join(f'{b:02X}' for b in chunk)
        ascii_str = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in chunk)
        print(f'{i:04X}  {hex_str:<48}  {ascii_str}')
    print("========================\n")
    
def float2uint32(number):
    return int(number * 4294967295)    

def uint2float(uint_number):
    """Convert an unsigned byte (0-255) to a float in [-1.0, 1.0]."""
    return (uint_number - 128) / 127.0
    
class CRF_object(object):
    def __init__(self):
        self.header = CRF_header()
        self.footer = CRF_footer()
        self.meshfile = CRF_meshfile()
        self.jointmap = None
        self.skeleton = None
        
    def parse_bin(self, file):        
        self.header.parse_bin(file)        
        self.footer.parse_bin(file, self.header.footer_offset1, self.header.footer_offset2, self.header.footer_entries)        
        self.meshfile.parse_bin(file, self.footer.get_meshfile().file_offset)
        
        if(self.footer.get_jointmap() != None):
            try:
                self.jointmap = CRF_jointmap(file, self.footer.get_jointmap().file_offset)
            except Exception as e:
                print("Ignored missing/corrupted jointmap:", e)
                self.jointmap = None

        if(self.footer.get_skeleton() != None):
            try:
                self.skeleton = CRF_skeleton(file, self.footer.get_skeleton().file_offset)
            except Exception as e:
                print("Ignored missing/corrupted skeleton:", e)
                self.skeleton = None
            
    def get_bin(self):
        data = b""
        #TODO update all data structures, then write them out
        mesh_data = self.meshfile.get_bin()
        
        meshfile_size = len(mesh_data)
        footer1_size = len(self.footer.entries * 32)
        self.footer.update_meshfile(meshfile_size)
        self.header.footer_offset1 = 0x14 + meshfile_size 
        self.header.footer_offset2 = 0x14 + meshfile_size + footer1_size
        data += self.header.get_bin()
        data += mesh_data
        data += self.footer.get_bin()
        return data
    
class CRF_header(object):
    def __init__(self):
        self.crf_magick = b"fknc"
        self.version = 1
        self.footer_offset1 = 0
        self.footer_offset2 = 0
        self.footer_entries = 2 #TODO This only supports static objects. For animated objects, more complex footer has to be supported.
		
    def parse_bin(self,file):
        print("===Parsing header===")
        self.crf_magick, self.version = struct.unpack("<4sI", file.read(8))    
        if self.crf_magick != b"fknc":
            print("Not a CRF file!")
            return 
        self.footer_offset1,self.footer_offset2 = struct.unpack("<II", file.read(8))
        self.footer_entries, = struct.unpack("<I", file.read(4))
        #print("Footer offset 1: %s, footer offset 2: %s" % (hex(self.footer_offset1).strip('L'), hex(self.footer_offset2).strip('L')))
        #print("Footer entries", self.footer_entries)
        print("===End of parsing header===")
        
    def get_bin(self):
        data = b""
        data += self.crf_magick
        data += struct.pack("<I", self.version)
        # footer offsets are blank and will get filled in later
        data += struct.pack("<I", self.footer_offset1)
        data += struct.pack("<I", self.footer_offset2)
        data += struct.pack("<I", self.footer_entries)     
        return data
        
class CRF_footer(object):
    def __init__(self):
        self.entries = []
        self.entry_descriptors = []

    def parse_bin(self, file, footer_offset1, footer_offset2, footer_entries): 
        print("===Parsing footer===")
        file.seek(footer_offset1)
        for i in range(0, footer_entries):
            entry = CRF_entry()            
            entry.parse_bin(file)
            self.entries.append(entry)
                
        for entry in self.entries:
            entry_description = CRF_entry_descriptor()
            entry_description.parse_bin(file, entry.type)
            self.entry_descriptors.append(entry_description)
        print("===End of parsing footer===")

    def get_meshfile(self):
        for entry in self.entries:
            if entry.type == CRF_MESHFILE:
                return entry
        return None

    def get_jointmap(self):
        for entry in self.entries:
            if entry.type == CRF_JOINTMAP:
                return entry
        return None

    def get_skeleton(self):
        for entry in self.entries:
            if entry.type == CRF_SKELETON:
                return entry
        return None
    
    def update_meshfile(self, new_size):
        for i in range(0, len(self.entries)):
            entry = self.entries[i]
            if entry.type == CRF_MESHFILE:
                self.entries[i].size = new_size 

    def get_bin(self):
        data = b""
        for entry in self.entries:
            data += entry.get_bin()
        for entry in self.entry_descriptors:
            data += entry.get_bin()
        return data
        
class CRF_entry(object):
    def __init__(self):
        self.type = None
        self.entry_id = None
        self.file_offset = None
        self.size = None
        self.const = None #(a, b, c, d) unknown
        
    def parse_bin(self, file):
        self.type, self.entry_id, self.file_offset, self.size = struct.unpack("<IIII", file.read(16))
        print("Type:%s \n Entry: %s \n File offset: %s \n Size: %s" % (hex(self.type), self.entry_id, hex(self.file_offset), self.size) )
        self.const = struct.unpack("<IIII", file.read(16))
        print(" Unknown constants:", self.const)
        
    def create_rootnode(self):        
        self.type = CRF_ROOT_NODE
        self.entry_id = 0
        self.file_offset = 0
        self.size = 0
        self.const = (0xFFFFFFFF, 1, 1, 0)

    def create_meshfile(self, size):        
        self.type = CRF_MESHFILE
        self.entry_id = 1
        self.file_offset = 0x14
        self.size = size
        self.const = (0, 0, 0, 0)
        
    def get_bin(self):
        data = b""
        data = struct.pack("<IIIIIIII", self.type, self.entry_id, self.file_offset, self.size, *self.const)
        return data
        
class CRF_entry_descriptor(object):        
    def __init__(self):
        self.type = None
        self.entry_id = None
        self.name_length = None
        self.name = None

    def create_rootnode(self):
        self.type = CRF_ROOT_NODE
        self.entry_id = 0
        self.name_length = 9
        self.name = b"root node"
        
    def create_meshfile(self):
        self.type = CRF_MESHFILE
        self.entry_id = 1
        self.name_length = 8
        self.name = b"meshfile"
        
    def parse_bin(self, file, CRF_TYPE):
        self.type = CRF_TYPE
        self.entry_id = 0
        if(self.type == CRF_ROOT_NODE):
            file.read(4)
            self.entry_id, = struct.unpack("<I", file.read(4))            
            self.name_length, = struct.unpack("<I", file.read(4))
            self.name, = struct.unpack("%ss" % self.name_length, file.read(self.name_length))
        if(self.type == CRF_MESHFILE or self.type == CRF_SKELETON):             
            self.entry_id, = struct.unpack("<I", file.read(4))            
            self.name_length, = struct.unpack("<I", file.read(4))
            self.name, = struct.unpack("%ss" % self.name_length, file.read(self.name_length))
            file.read(4)
        if(self.type == CRF_JOINTMAP):
            self.entry_id, = struct.unpack("<I", file.read(4))            
            self.name_length, = struct.unpack("<I", file.read(4))
            self.name, = struct.unpack("%ss" % self.name_length, file.read(self.name_length))
            file.read(4)
        if (CRF_TYPE not in CRF_FOOTER_ENTRY_CONSTANTS):
            self.entry_id, = struct.unpack("<I", file.read(4))
            self.name_length, = struct.unpack("<I", file.read(4))
            self.name, = struct.unpack("%ss" % self.name_length, file.read(self.name_length))
            file.read(4)
        print("Entry id: %i, entry name: %s, entry type: %s" %(self.entry_id, self.name, self.type))

    def get_bin(self):
        if(self.type == CRF_ROOT_NODE):
            data = struct.pack("<xxxxII%ss" % self.name_length, self.entry_id, self.name_length, self.name)
        if(self.type == CRF_MESHFILE or self.type == CRF_JOINTMAP or self.type == CRF_SKELETON):
            data = struct.pack("<II%ssxxxx" % self.name_length, self.entry_id, self.name_length, self.name)
        return data

class CRF_meshfile(object):
    def __init__(self):
        self.num_meshes = None
        self.model_bounding_box = None # ((LoX, LoY, LoZ), (HiX, HiY, HZ))
        self.meshes = []

    def parse_bin(self, file, file_offset, verbose=False):
            print("===Parsing meshfile===")
            file.seek(file_offset)
            magick, self.num_meshes = struct.unpack("<II", file.read(8))
            print(f"Meshfile magick: 0x{magick:08X}, num_meshes declared: {self.num_meshes}")
            LoX, LoY, LoZ = struct.unpack("<fff", file.read(12))
            HiX, HiY, HiZ = struct.unpack("<fff", file.read(12))
            self.model_bounding_box = ((LoX, LoY, LoZ), (HiX, HiY, HiZ))

            for i in range(0, self.num_meshes):
                try:
                    # If we just finished a mesh, scan forward to align the pointer for the next one
                    if i > 0:
                        self.align_to_next_mesh(file, i)

                    mesh = CRF_mesh()
                    mesh.parse_bin(file, file.tell(), i, verbose)
                    self.meshes.append(mesh)
                except Exception as e:
                    print(f"*** Failed to parse mesh {i}: {e}. Aborting further meshes. ***")
                    break

            print("===End of parsing meshfile===")

    def align_to_next_mesh(self, file, mesh_index):
            start_pos = file.tell()
            
            # Scan up to 200KB forward to bypass broken materials, LODs, and separators
            for _ in range(200000):
                pos = file.tell()
                buf = file.read(8)
                if len(buf) < 8:
                    break
                
                num_verts, num_faces = struct.unpack("<II", buf)

                # Heuristic 1: Vert and Face counts must be positive and reasonable
                if 0 < num_verts < 500000 and 0 < num_faces < 500000:
                    
                    # Heuristic 2: Known index size based on vertex count
                    is_32bit = num_verts > 65535
                    face_bytes = num_faces * (12 if is_32bit else 6)
                    
                    try:
                        # Jump past the faces
                        file.seek(pos + 8 + face_bytes)
                        stream_count_buf = file.read(1)
                        if stream_count_buf:
                            stream_count, = struct.unpack("<B", stream_count_buf)
                            if stream_count in (1, 2, 3, 4):
                                
                                # Heuristic 3: Check stream declarations and skip interleaved vertex blocks
                                decl_buf = file.read(8)
                                if len(decl_buf) == 8:
                                    layout, stride = struct.unpack("<II", decl_buf)
                                    if stride in (4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 48, 64):
                                        
                                        # Skip Stream 0 vertices
                                        file.seek(file.tell() + (num_verts * stride))
                                        
                                        valid_streams = True
                                        for s in range(1, stream_count):
                                            s_decl = file.read(8)
                                            if len(s_decl) == 8:
                                                s_layout, s_stride = struct.unpack("<II", s_decl)
                                                if s_stride in (4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 48, 64):
                                                    # Skip Stream 's' vertices
                                                    file.seek(file.tell() + (num_verts * s_stride))
                                                else:
                                                    valid_streams = False
                                                    break
                                            else:
                                                valid_streams = False
                                                break
                                        
                                        # Heuristic 4: Validate Bounding Box floats
                                        if valid_streams:
                                            bbox_buf = file.read(24)
                                            if len(bbox_buf) == 24:
                                                lox, loy, loz, hix, hiy, hiz = struct.unpack("<ffffff", bbox_buf)
                                                
                                                # Reject crazy float garbage often found in false positives
                                                if all(-50000.0 < val < 50000.0 for val in (lox, loy, loz, hix, hiy, hiz)):
                                                    file.seek(pos) # Revert to exact start of the new mesh
                                                    print(f"Recovered alignment for Mesh {mesh_index} at offset 0x{pos:X}")
                                                    return
                    except Exception:
                        pass

                # Move forward 1 byte and try the pattern again
                file.seek(pos + 1)
                
            print(f"Warning: Could not find next mesh signature for Mesh {mesh_index}. Relying on current offset.")
            file.seek(start_pos)

    def scale(self, scale_factor):
        #TODO need to scale the bounding box
        for mesh in self.meshes:
            for i in range(0, len(mesh.vertices0)):
                mesh.vertices0[i].x = mesh.vertices0[i].x*scale_factor
                mesh.vertices0[i].y = mesh.vertices0[i].y*scale_factor
                mesh.vertices0[i].z = mesh.vertices0[i].z*scale_factor                

    def translate(self, translation):
        x_offset, y_offset, z_offset = translation
        #TODO need to translate the bounding box
        for mesh in self.meshes:
            for i in range(0, len(mesh.vertices0)):
                mesh.vertices0[i].x = mesh.vertices0[i].x+x_offset
                mesh.vertices0[i].y = mesh.vertices0[i].y+y_offset
                mesh.vertices0[i].z = mesh.vertices0[i].z+z_offset

    def __str__(self):
        string = ""
        string += "Number of meshes: %s\n" % self.num_meshes
        string += "Model bounding box: (%s, %s)\n" % (self.model_bounding_box[0], self.model_bounding_box[1])
        for mesh in self.meshes:
            string += mesh.__str__()
        return string
        
    def get_bin(self):
        data = b""
        # some unknown magick number
        data += struct.pack("<I", 0xFFFF0006)        
        data += struct.pack("<I", self.num_meshes)
        LoXYZ = self.model_bounding_box[0]
        HiXYZ = self.model_bounding_box[1]
        data += struct.pack("<fff", *list(LoXYZ))
        data += struct.pack("<fff", *list(HiXYZ))
        # loop through all meshes
        for mesh in self.meshes:
            data += mesh.get_bin()
            print("Writing mesh", mesh.mesh_number)
            # write separator, unknown format
            if self.num_meshes > 1:
                data += struct.pack("<I%sx" % 0x10, 2)
        return data

class CRF_mesh(object):
    def __init__(self):
        self.mesh_number = 0
        self.number_of_vertices = None
        self.number_of_faces = None
        self.face_list = []
        self.stream_count = 0
        self.vertex_stream0_layout = [] # [layout, stride]
        self.vertices0 = [] # 3d data, colors, uv, normals, specular, blendweight
        self.vertex_stream1_layout = [] # [layout, stride]        
        self.vertices1 = [] # blendindeces and blendweight
        self.vertex_stream2_layout = [] # [layout, stride]             
        self.vertices2 = [] # unknown stream, used on animated meshes
        self.bounding_box = None # ((LoX, LoY, LoZ), (HiX, HiY, HZ))
        self.materials = None

    def parse_bin(self, file, file_offset, mesh_number, verbose=False):
        self.mesh_number = mesh_number
        print(f"Mesh {mesh_number}: reading header at offset 0x{file.tell():X}")
        self.number_of_vertices, = struct.unpack("<I", file.read(4))
        self.number_of_faces, = struct.unpack("<I", file.read(4))
        print(f"Mesh {mesh_number}: vertices={self.number_of_vertices}, faces={self.number_of_faces}")

        # --- Face list reading with dynamic 16-bit/32-bit detection ---
        use_32bit_indices = self.number_of_vertices > 65535
        face_format = "<III" if use_32bit_indices else "<HHH"
        bytes_per_face = 12 if use_32bit_indices else 6
        face_data_len = self.number_of_faces * bytes_per_face
        
        current_pos = file.tell()
        print(f"Mesh {mesh_number}: reading {self.number_of_faces} faces ({face_data_len} bytes, 32-bit: {use_32bit_indices}) from 0x{current_pos:X}")
        try:
            for i in range(0, self.number_of_faces):
                v1, v2, v3 = struct.unpack(face_format, file.read(bytes_per_face))
                self.face_list.append((v1, v2, v3))
        except struct.error as e:
            print(f"ERROR reading faces for mesh {mesh_number}: {e}")
            raise RuntimeError(f"Face data truncated for mesh {mesh_number}: {e}") from e

        # --- Stream count and vertex streams ---
        self.stream_count, = struct.unpack("<B", file.read(1))
        print(f"Mesh {mesh_number}: stream count = {self.stream_count}")

        layout, stride = struct.unpack("<II", file.read(8))
        self.vertex_stream0_layout = [layout, stride]
        print(f"Stream0 declaration: 0x{layout:08X}, stride: {stride} bytes")

        # read vertices 0
        print(f"Mesh {mesh_number}: reading {self.number_of_vertices} vertices from stream 0")
        for i in range(0, self.number_of_vertices):
            vertex = CRF_vertex()
            vertex.bin2raw(file, file.tell(), i)
            vertex.raw2blend()
            self.vertices0.append(vertex)

        if self.stream_count > 1:
            layout, stride = struct.unpack("<II", file.read(8))
            self.vertex_stream1_layout = [layout, stride]
            print(f"Stream1 declaration: 0x{layout:08X}, stride: {stride} bytes")
            for i in range(0, self.number_of_vertices):
                vertex_blend = CRF_vertex_blend()
                vertex_blend.bin2raw(file, file.tell(), i, verbose)
                self.vertices1.append(vertex_blend)

        if self.stream_count > 2:
            layout, stride = struct.unpack("<II", file.read(8))
            self.vertex_stream2_layout = [layout, stride]
            print(f"Stream2 declaration: 0x{layout:08X}, stride: {stride} bytes")
            for i in range(0, self.number_of_vertices):
                if stride == 4:
                    vertex_blend = CRF_vertex_blend_indeces_only()
                elif stride == 8:
                    vertex_blend = CRF_vertex_blend()
                else:
                    print(f"WARNING: unknown stream2 stride {stride}")
                    vertex_blend = CRF_vertex_blend_indeces_only()  # fallback
                vertex_blend.bin2raw(file, file.tell(), i, verbose)
                self.vertices2.append(vertex_blend)

        print("End of vertex data at", hex(file.tell()))

        # bounding box
        LoX, LoY, LoZ = struct.unpack("<fff", file.read(12))
        HiX, HiY, HiZ = struct.unpack("<fff", file.read(12))
        self.bounding_box = ((LoX, LoY, LoZ), (HiX, HiY, HiZ))
        print(f"Bounding box of model {self.mesh_number}: {self.bounding_box}")

        # materials
        print("==Parsing meshfile materials==")
        self.materials = CRF_materials()
        self.materials.parse_bin(file, file.tell(), verbose)
        print("==End of parsing meshfile materials==")

    def __str__(self):
        string = ""
        string += "Mesh number: %s, vertices= %s, faces = %s\n" % (self.mesh_number, self.number_of_vertices, self.number_of_faces)
        return string
        
    def get_bin(self):
        data = b""
        data += struct.pack("<I", self.number_of_vertices)
        data += struct.pack("<I", self.number_of_faces)
        for face in self.face_list:
            data += struct.pack("<HHH", *list(face))
        data += struct.pack("<B", self.stream_count)
        
        # write first stream
        if len(self.vertex_stream0_layout) != 0:
            data += struct.pack("<II", *self.vertex_stream0_layout)
            for vertex in self.vertices0:
                #TODO should convert blender to raw here
                data += vertex.get_bin()
            
        # write second stream
        if len(self.vertex_stream1_layout) != 0:
            data += struct.pack("<II", *self.vertex_stream1_layout)
            for vertex in self.vertices1:
                #TODO should convert blender to raw here
                data += vertex.get_bin()

        # write third stream
        if len(self.vertex_stream2_layout) != 0:        
            data += struct.pack("<II", *self.vertex_stream2_layout)
            for vertex in self.vertices2:
                #TODO should convert blender to raw here
                data += vertex.get_bin()

        # write mesh's bounding box
        LoXYZ = self.bounding_box[0]
        HiXYZ = self.bounding_box[1]
        data += struct.pack("<fff", *list(LoXYZ))
        data += struct.pack("<fff", *list(HiXYZ))

        # write materials
        if self.materials != None:
            data += self.materials.get_bin()
        
        return data
    
class CRF_materials(object):
    def __init__(self):
        self.material_type = b''
        self.material_subtype = b''
        self.diffuse_texture = ""
        self.normal_texture = ""
        self.specular_texture = ""
        self.special_texture = ""
        self.specular_constant = (0.0, 0.0, 0.0) # (R, G, B)
        self.specular_constant_alpha = 0.0 
        self.overlay_texture = ""
        self.unknown_texture = ""        
        self.custom_data_count = 0
        self.custom1_1 = (0, 0, 0)
        self.custom1_2 = 0
        self.custom_array = [(0,0,0), (0,0,0), (0,0,0), (0,0,0), (0,0,0), (0,0,0), (0,0,0)]

    def read_utf16_texture(self, file):
        length, = struct.unpack("<I", file.read(4))
        byte_len = length * 2
        if byte_len > 0:
            raw_data = file.read(byte_len)
            tex_name = raw_data.decode('utf-16le', errors='ignore').rstrip('\x00')
        else:
            tex_name = ""
        file.read(4) # Consume the trailing padding/zeros
        return tex_name

    def write_utf16_texture(self, tex_name):
        if not tex_name:
            return struct.pack("<I", 0) + struct.pack("xxxx")
        raw_data = tex_name.encode('utf-16le')
        length = len(tex_name)
        return struct.pack("<I", length) + raw_data + struct.pack("xxxx")

    def parse_bin(self, file, file_offset, verbose=False):
        self.material_type, = struct.unpack("2s", file.read(2))
        self.material_subtype, = struct.unpack(">Q", file.read(8))

        if self.material_type in (b"nm", b"tm", b"ts", b"ti"):
            
            # 1. Dynamically read all texture strings based on their tags
            valid_tex_tags = [b"sffd", b"smrn", b"1tsc", b"lcps", b"ccps", b"2tsc", b"3tsc", b"4tsc"]
            
            while True:
                pos = file.tell()
                tag = file.read(4)
                
                # If it's a texture tag, read the UTF-16 string and assign it
                if tag in valid_tex_tags:
                    tex_name = self.read_utf16_texture(file)
                    if verbose: print(f"Parsed {tag.decode('ascii', errors='ignore')}: {tex_name}")
                    
                    if tag == b"sffd": self.diffuse_texture = tex_name
                    elif tag == b"smrn": self.normal_texture = tex_name
                    elif tag == b"lcps": self.special_texture = tex_name
                    elif tag == b"ccps": self.specular_texture = tex_name
                    elif tag == b"1tsc": self.overlay_texture = tex_name
                    elif tag == b"2tsc": self.unknown_texture = tex_name
                else:
                    # We hit the constants block (or end of textures), rewind the 4 bytes and move on
                    file.seek(pos)
                    break
                    
            # 2. Parse the remainder of the material block (Constants and custom vectors)
            if self.material_type == b"tm":
                file.read(0x1C)
            elif self.material_type == b"ts":
                self.custom_data_count, = struct.unpack("<I", file.read(4))
                for _ in range(self.custom_data_count):
                    file.read(4) # tag
                    unknown = struct.unpack("<III", file.read(12))
                    self.custom_array.append(unknown)
                file.read(0x10) # trailer
            elif self.material_type == b"nm":
                # Check if we have trailing constant data by reading the custom_data_count
                data = file.read(4)
                if len(data) == 4:
                    self.custom_data_count, = struct.unpack("<I", data)
                    
                    if self.custom_data_count >= 1:
                        file.read(4) # Expected 'lcps' tag for constants
                        self.specular_constant = struct.unpack("<fff", file.read(12))
                        if self.custom_data_count == 1:
                            self.specular_constant_alpha, = struct.unpack("f", file.read(4))
                            
                    if self.custom_data_count == 2:
                        file.read(4) # Expected '1tsc'
                        self.custom1_1 = struct.unpack("<IIII", file.read(16))
                        file.read(4) # Expected '2tsc' or '1tsc'
                        self.custom1_2, = struct.unpack("<I", file.read(4))
                        
        else:
            print(f"Material type {self.material_type} is not supported")

    def get_bin(self):
        data = b""
        writing_materials = True
        current_state = "start"

        while writing_materials:
            if self.material_type == b"nm":
                if current_state == "start":
                    data += struct.pack("2s", self.material_type)
                    data += struct.pack(">Q", self.material_subtype)
                    current_state = "write_diffuse"
                elif current_state == "write_diffuse":
                    current_state = "write_normal"
                elif current_state == "write_normal":
                    current_state = "write_overlay"
                elif current_state == "write_overlay":
                    if self.material_subtype == 0x100000003000000:
                        current_state = "write_specular_constant"
                    else:                    
                        current_state = "write_specular"
                elif current_state == "write_specular":
                    current_state = "write_specular_constant"
                elif current_state == "write_specular_constant":
                    if self.material_subtype == 0x100000003000000:
                        current_state = "done"
                    else:
                        current_state = "write_custom"
                elif current_state == "write_custom":
                    current_state = "done"
                elif current_state == "done":
                    writing_materials = False
                    
                if current_state == "write_diffuse":                
                    data += struct.pack("4s", b"sffd")
                    data += self.write_utf16_texture(self.diffuse_texture)
                elif current_state == "write_normal":            
                    data += struct.pack("4s", b"smrn")
                    data += self.write_utf16_texture(self.normal_texture)
                elif current_state == "write_overlay":
                    data += struct.pack("4s", b"1tsc")
                    data += self.write_utf16_texture(self.overlay_texture)
                elif current_state == "write_specular":
                    data += struct.pack("4s", b"lcps")
                    data += self.write_utf16_texture(self.special_texture)
                elif current_state == "write_specular_constant":
                    if self.custom_data_count == 1:
                        data += struct.pack("<I", 0x1)
                        data += struct.pack("4s", b"lcps")
                        data += struct.pack("<fff", *list(self.specular_constant))
                        data += struct.pack("<f", self.specular_constant_alpha)
                    elif self.custom_data_count == 2:
                        data += struct.pack("<I", 0x2)
                        data += struct.pack("4s", b"lcps")
                        data += struct.pack("<fff", *list(self.specular_constant))
                elif current_state == "write_custom":
                    if self.custom_data_count == 2:
                        data += struct.pack("4s", b"1tsc")
                        data += struct.pack("<IIII", *list(self.custom1_1))
                        data += struct.pack("4s", b"1tsc")
                        data += struct.pack("<I", self.custom1_2)                                                                    
        return data
        
class CRF_vertex_blend(object):
    def __init__(self):
        self.index = 0
        self.blendweight = (0, 0, 0, 0)
        self.blendindeces = (0, 0, 0, 0)        
        self.blendweight_blend = (0, 0, 0)
        
    def raw2blend(self):
        self.blendweight_blend = (uint2float(self.blendweight[0]), uint2float(self.blendweight[1]), uint2float(self.blendweight[2]), uint2float(self.blendweight[3]))
        
    def bin2raw(self, file, file_offset, index, verbose=False):
        self.index = index
        self.blendweight = struct.unpack("<bbbb", file.read(4))
        self.blendindeces = struct.unpack("<bbbb", file.read(4))
        if verbose:
            print("vert index=%s, blendweights: %s, blendindeces: %s" % (self.index, self.blendweight, self.blendindeces))

    def get_bin(self):
        data = b""
        data += struct.pack("<bbbb", *self.blendweight)
        data += struct.pack("<bbbb", *self.blendindeces)
        return data
                                
class CRF_vertex_blend_indeces_only(object):
    def bin2raw(self, file, file_offset, index, verbose=False):
        self.index = index
        self.blendindeces = None
        self.blendindeces = struct.unpack("<bbbb", file.read(4))
        if verbose:
            print("vert index=%s, blendindeces: %s" % (self.index, self.blendindeces))
            
    def get_bin(self):
        data = b""
        data += struct.pack("<bbbb", *self.blendindeces)
        return data
    
class CRF_vertex(object):
    def __init__(self):
        self.index = 0
        
        # Raw CRF variables:
        self.x = 0
        self.y = 0
        self.z = 0
        self.normal_x = 0
        self.normal_y = 0
        self.normal_z = 0
        self.normal_w = 0
        self.specular_blue = 0
        self.specular_green = 0
        self.specular_red = 0
        self.specular_alpha = 0
        self.u0 = 0
        self.v0 = 0
        self.u1 = 0
        self.v1 = 0
        self.blendweights1_x = 0
        self.blendweights1_y = 0
        self.blendweights1_z = 0
        self.blendweights1_w = 0

        # Blender variables
        self.x_blend = 0
        self.y_blend = 0
        self.z_blend = 0
        self.normal_x_blend = 0
        self.normal_y_blend = 0
        self.normal_z_blend = 0
        self.normal_w_blend = 0
        self.specular_blue_blend = 0
        self.specular_green_blend = 0
        self.specular_red_blend = 0
        self.specular_alpha_blend = 0 #Not iplemented      
        self.u0_blend = 0
        self.v0_blend = 0
        self.u1_blend = 0
        self.v1_blend = 0
        self.blendweights1_blend = 0
        self.blendweights1_x_blend = 0
        self.blendweights1_y_blend = 0
        self.blendweights1_z_blend = 0
        self.blendweights1_w_blend = 0

            
    
    def __str__(self):
        string = "Vertex index = %s\n" % (self.index)
        string += "Blender values:\n"
        string += "xyz = %f %f %f\n" % (self.x_blend, self.y_blend, self.z_blend)
        string += "\tvertex normal XYZW  = %f %f %f %f\n" % (self.normal_x_blend, self.normal_y_blend, self.normal_z_blend, self.normal_w_blend)                                                                    
        string += "\tspecular BGRA  = %f %f %f %f\n" % (self.normal_x_blend, self.normal_y_blend, self.normal_z_blend, self.normal_w_blend)                                                 
        string += "\tuv0 = %f %f\n" % (self.u0_blend, self.v0_blend)
        string += "\tuv1 = %f %f\n" % (self.u1_blend, self.v1_blend)
        string += "\tblendeweight = %f %f %f %f\n" % (self.blendweights1_x_blend, self.blendweights1_y_blend, self.blendweights1_z_blend, self.blendweights1_w_blend)     

        string += "CRF values:\n"
        string += "xyz = %f %f %f\n" % (self.x, self.y, self.z)        
        string += "\tvertex normal XYZW  = %i %i %i %i, %s %s %s %s\n" % (self.normal_x, self.normal_y, self.normal_z, self.normal_w,
                                                                     hex(self.normal_x), hex(self.normal_y), hex(self.normal_z), hex(self.normal_w))
        string += "\tspecular BGRA  = %i %i %i %i, %s %s %s %s\n" % (self.normal_x, self.normal_y, self.normal_z, self.normal_w,
                                                                     hex(self.specular_blue), hex(self.specular_green), hex(self.specular_red), hex(self.specular_alpha))
        string += "\tuv0 = %i %i, 0x%x 0x%x\n" % (self.u0, self.v0, self.u0, self.v0)
        string += "\tuv1 = %i %i, 0x%x 0x%x\n" % (self.u1, self.v1, self.u1, self.v1)        
        string += "\tblendweight = 0x%x 0x%x 0x%x 0x%x\n" % (self.blendweights1_x & 0xff, self.blendweights1_y & 0xff, self.blendweights1_z & 0xff, self.blendweights1_w & 0xff)       
        return string

    def float2uint(self, f_number):
        if f_number > 0.0:
            return int(128 + f_number * 127)
        elif f_number < 0.0:
            return int(128 - math.fabs(f_number) * 128)
        else:
            return 128
        
    def uint2float(self, uint_number):
        """Convert an unsigned byte (0-255) to a float in [-1.0, 1.0].
        Standard signed-normalized byte mapping: 128 -> 0.0, 255 -> 1.0, 0 -> -1.0.
        """
        return (uint_number - 128) / 127.0

    def raw2blend(self):
        """ Convert raw CRF values to Blender values using the CAF‑compatible mapping """
        SCALE = 0.1

        self.x_blend =  self.x * SCALE
        self.y_blend =  self.z * SCALE
        self.z_blend =  self.y * SCALE

        n_x = self.uint2float(self.normal_x)
        n_y = self.uint2float(self.normal_y)
        n_z = self.uint2float(self.normal_z)

        self.normal_x_blend = n_x
        self.normal_y_blend = n_z
        self.normal_z_blend = n_y
        self.normal_w_blend = self.uint2float(self.normal_w)

        self.specular_blue_blend  = self.specular_blue  / 255
        self.specular_green_blend = self.specular_green / 255
        self.specular_red_blend   = self.specular_red   / 255
        self.specular_alpha_blend = self.specular_alpha / 255

        self.u0_blend = 0.5 + (self.u0 / 32768) / 2.0
        self.v0_blend = 0.5 - (self.v0 / 32768) / 2.0
        self.u1_blend = 0.5 + (self.u1 / 32768) / 2.0
        self.v1_blend = 0.5 - (self.v1 / 32768) / 2.0

        self.blendweights1_x_blend = self.blendweights1_x / 255
        self.blendweights1_y_blend = self.blendweights1_y / 255
        self.blendweights1_z_blend = self.blendweights1_z / 255
        self.blendweights1_w_blend = self.blendweights1_w / 255   
        
    def blend2raw(self):
        """ Convert blender values to raw values """
        SCALE_INV = 10.0
        
        # Inverse mapping
        self.x = self.x_blend * SCALE_INV
        self.y = self.z_blend * SCALE_INV
        self.z = self.y_blend * SCALE_INV
        
        self.normal_x = self.float2uint(-self.normal_x_blend)
        self.normal_y = self.float2uint(self.normal_z_blend)
        self.normal_z = self.float2uint(-self.normal_y_blend) 
        self.normal_w = self.float2uint(self.normal_w_blend)
        
        self.specular_blue = int(self.specular_blue_blend * 255)
        self.specular_green = int(self.specular_green_blend * 255)
        self.specular_red = int(self.specular_red_blend * 255)
        self.specular_alpha = int(self.specular_alpha_blend * 255)
        
        self.u0 = int(((self.u0_blend - 0.5) * 2) * 32768)
        self.v0 = int(((self.v0_blend - 0.5) * -2) * 32768)
        self.u1 = int(((self.u1_blend - 0.5) * 2) * 32768)
        self.v1 = int(((self.v1_blend - 0.5) * -2) * 32768)

        self.blendweights1_x = int(self.blendweights1_x_blend * 255)
        self.blendweights1_y = int(self.blendweights1_y_blend * 255)
        self.blendweights1_z = int(self.blendweights1_z_blend * 255)
        self.blendweights1_w = int(self.blendweights1_w_blend * 255)

        # clamp uv values to be <= 32768 and >=-32768
        if self.u0 >= 32768:
            self.u0 = 32767
        if self.v0 >= 32767:
            self.v0 = 32767
        if self.u1 >= 32768:
            self.u1 = 32767
        if self.v1 >= 32768:
            self.v1 = 32767
        if self.u0 <= -32768:
            self.u0 = -32767
        if self.v0 <= -32768:
            self.v0 = -32767
        if self.u1 <= -32768:
            self.u1 = -32767
        if self.v1 <= -32768:
            self.v1 = -32767               

    def bin2raw(self, file, file_offset, index):
            self.index = index
            self.x, self.y, self.z, \
                self.normal_x, self.normal_y, self.normal_z, self.normal_w, \
                self.specular_blue, self.specular_green, self.specular_red, self.specular_alpha, \
                self.u0, self.v0, self.u1, self.v1, \
                self.blendweights1_x, self.blendweights1_y, \
                self.blendweights1_z, self.blendweights1_w = struct.unpack("<fffBBBBBBBBhhhhBBBB", file.read(32))
            
        
    def get_bin(self):        
        data = struct.pack("<fffBBBBBBBBhhhhBBBB", self.x, self.y, self.z,
                                                         self.normal_x, self.normal_y, self.normal_z, self.normal_w,
                                                         self.specular_blue, self.specular_green, self.specular_red, self.specular_alpha,
                                                         self.u0, self.v0, self.u1, self.v1,
                                                         self.blendweights1_x, self.blendweights1_y,
                                                        self.blendweights1_z, self.blendweights1_w)                                                
        return data
    

class CRF_joint(object):
    def __init__(self):
        self.joint_id = 0
        self.matrix = [ (0,0,0,0), (0,0,0,0), (0,0,0,0), (0,0,0,1) ]
        self.parent_id = 0xFFFFFFFF
        self.skeleton_index = 0
        self.i1 = 0
        self.i2 = 0        

    def __str__(self):
        string = ""
        string += "Joint id: %s\n" % self.joint_id
        string += "Matrix: \n%s\n%s\n%s\n%s\n" % (self.matrix[0],self.matrix[1],self.matrix[2],self.matrix[3])
        string += "Parent: %s\n" % self.parent_id
        string += "Skeleton index: %s\n" % self.skeleton_index        
        string += "Unknown: %s, %s\n" % (self.i1, self.i2)
        return string
    
class CRF_bone(object):
    def __init__(self):
        self.real_bone_id = 0
        self.bone_id = 0
        self.bone_name = b""
        self.child_list = []

    def __str__(self):
        string = ""
        string += "ID: %s, Name: %s, Children: %s, Unknown: %s, %s, %s, %s" % (self.bone_id, self.bone_name, self.child_list, self.i1, self.i2, self.i3, self.i4)
        return string
    
class CRF_jointmap(object):
    def __init__(self, file=None, file_offset=0):
        self.magick = 0x1
        self.joint_count = 0
        self.joint_list = []
        self.bone_count = 0
        self.i1 = 0
        self.bone_dict = {}
        
        if file != None:
            file.seek(file_offset)
            self.parse(file)
        
    def parse(self, file):
        self.magick = struct.unpack("<I", file.read(4)) #TODO can there be multiple jointmaps?
        self.joint_count, = struct.unpack("<I", file.read(4))
        #print("Joint count", self.joint_count)

        for i in range(0, self.joint_count):
            joint = CRF_joint()
            joint.joint_id = i
            #print(hex(file.tell()))            
            f11, f12, f13 = struct.unpack("<fff", file.read(12))
            joint.parent_id, = struct.unpack("<I", file.read(4))                
            f21, f22, f23 = struct.unpack("<fff", file.read(12))
            joint.skeleton_index, = struct.unpack("<I", file.read(4))                
            f31, f32, f33 = struct.unpack("<fff", file.read(12))
            joint.i1, = struct.unpack("<I", file.read(4))
            f41, f42, f43 = struct.unpack("<fff", file.read(12))
            joint.i2, = struct.unpack("<I", file.read(4))

            joint.matrix = []
            joint.matrix.append( (f11, f12, f13, 0) )
            joint.matrix.append( (f21, f22, f23, 0) )
            joint.matrix.append( (f31, f32, f33, 0) )
            joint.matrix.append( (f41, f42, f43, 1) )
            self.joint_list.append(joint)
            
        #dump_hex(file, "CRF_JOINTMAP", 2048)
        self.bone_count, = struct.unpack("<I", file.read(4))
        #print("Bone count", self.joint_count)        
        #self.i1, = struct.unpack("<I", file.read(4))
        
        for i in range(0, self.bone_count):
            bone = CRF_bone()
            
            # Read real_bone_id FIRST, alongside bone_id and length
            real_bone_id, bone_id, bone_name_length = struct.unpack("<III", file.read(12))
            bone_name, = struct.unpack("%is" % bone_name_length, file.read(bone_name_length))

            num_children, = struct.unpack("<I", file.read(4))
            
            bone.real_bone_id = real_bone_id
            bone.bone_id = bone_id
            bone.bone_name = bone_name
            
            for j in range(0, num_children): # (Changed from i to j to prevent variable shadowing)
                child, = struct.unpack("<I", file.read(4))
                bone.child_list.append(child)
                
            # REMOVED: bone.i1, bone.i2, bone.i3, bone.i4 = struct.unpack("BBBB", file.read(4))
    
            self.bone_dict[bone.bone_id] = bone
            #print(bone)
        #print(hex(file.tell()))
        #TODO followd by 61 bytes of unknown
            
class CRF_skeleton(object):
    def __init__(self, file=None, file_offset=0):
        self.skeleton_count = 0
        self.skeleton_list = [] # [ (bone, bone bone), (bone, bone) ... ]
        
        if file != None:
            file.seek(file_offset)
            self.parse(file)

    def parse(self, file):
        #dump_hex(file, "CRF_SKELETON", 512)
        self.skeleton_count, = struct.unpack("<I", file.read(4))
        for i in range(0, self.skeleton_count):
            bone_count, = struct.unpack("<I", file.read(4))
            bones = struct.unpack("<%sH" % bone_count, file.read(bone_count*2))
            self.skeleton_list.append(bones)

    def __str__(self):
        string = ""
        string += "Skeleton groups: %s, %s" % (self.skeleton_count, self.skeleton_list)
        return string


