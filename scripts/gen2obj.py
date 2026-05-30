#!/usr/bin/env python3
"""
Convert a Ravenswatch cooked .gen model to OBJ with skinning info.
Based on the oCTextSaver dump structure:
  header (16 bytes) -> class list -> sections (each a blob of data).
"""

import os
import struct
import sys
from pathlib import Path


class GENReader:
    def __init__(self, path):
        self.data = Path(path).read_bytes()
        self.pos = 0
        self.classes = []
        self.sections = []

    def read(self, fmt, size=None):
        if size is None:
            size = struct.calcsize(fmt)
        val = struct.unpack_from(fmt, self.data, self.pos)
        self.pos += size
        return val[0] if len(val)==1 else val

    def read_bytes(self, n):
        val = self.data[self.pos:self.pos+n]
        self.pos += n
        return val

    def read_str(self, length):
        raw = self.read_bytes(length)
        return raw.rstrip(b'\x00').decode('ascii', errors='ignore')

    def parse_header(self):
        # tag, flags, hdr_size
        self.tag = self.read_str(8)  # "stream\0\0"? just skip
        self.flags, self.hdr_size = self.read('<II')
        # skip rest of header
        self.pos = self.hdr_size

    def parse_classes(self):
        n = self.read('<I')[0]
        for i in range(n):
            # format: name[hash?](version)<[parent] ...
            line = self.read_str(128)  # rough; we'll just skip
            self.classes.append(line)

    def parse_sections(self):
        n = self.read('<I')[0]
        for i in range(n):
            # Section header: range_start, range_end, payload_len
            start, end = self.read('<II')
            plen = self.read('<I')[0]
            self.sections.append({
                'start': start,
                'end': end,
                'payload_len': plen,
                'data': self.data[start:start+plen]
            })

    def extract_vertex_array(self, sec, dtype='f', elem_count=3, skip=0):
        """Interpret a section's data as an array of floats/ints.
        Often the data starts with a short string header, then raw values.
        We'll skip `skip` bytes first, then read until end.
        """
        raw = sec['data'][skip:]
        if dtype == 'f':
            fmt = '<f'
            size = 4
        elif dtype == 'i':
            fmt = '<i'
            size = 4
        elif dtype == 'B':
            fmt = 'B'
            size = 1
        else:
            raise ValueError(dtype)
        count = len(raw) // (size * elem_count)
        arr = []
        off = 0
        for _ in range(count):
            vals = struct.unpack_from(f'<{elem_count}{fmt}', raw, off)
            arr.append(vals)
            off += size * elem_count
        return arr

    def find_section_by_string(self, needle):
        for sec in self.sections:
            # if the first 4 bytes are a length prefix? the dump shows @0004 str(...)
            # We'll look for the string inside the payload.
            try:
                s = sec['data'][4:].split(b'\x00')[0].decode('ascii')
            except:
                continue
            if s == needle:
                return sec
        return None

    def get_all_bone_names(self):
        """Scan section9 for bone name pairs (like 'DEF.BotLeg.L' etc.)"""
        sec9 = self.sections[9] if len(self.sections) > 9 else None
        if not sec9:
            return []
        data = sec9['data']
        # Bone names appear as two consecutive null-terminated strings.
        # We'll extract all strings and keep those starting with 'DEF.'
        names = set()
        i = 0
        while i < len(data):
            # look for 'DEF.'
            if data[i:i+4] == b'DEF.':
                end = data.index(b'\x00', i)
                name = data[i:end].decode('ascii')
                names.add(name)
                i = end
            else:
                i += 1
        # Return sorted list (order matters for skinning indices)
        return sorted(names)

def main():
    if len(sys.argv) < 2:
        print("Usage: python gen2obj.py input.gen")
        sys.exit(1)
    gen = GENReader(sys.argv[1])
    gen.parse_header()
    gen.parse_classes()
    gen.parse_sections()

    # 1. Find vertex attributes
    pos_sec = gen.find_section_by_string("position")
    if not pos_sec:
        print("Warning: no 'position' section found, trying first oCVec3VertexLayer")
        # fallback: any oCVec3VertexLayer that doesn't have "tangent"/"binormal"/"skinning"
        # For now we skip.
        sys.exit(1)
    norm_sec = gen.find_section_by_string("normal")
    tangent_sec = gen.find_section_by_string("tangent")
    binormal_sec = gen.find_section_by_string("binormal")
    uv_sec = gen.find_section_by_string("texcoord0")  # maybe named differently
    skin_sec = gen.find_section_by_string("skinning")

    positions = gen.extract_vertex_array(pos_sec, 'f', 3, skip=4+len("position")+1)
    tangents = gen.extract_vertex_array(tangent_sec, 'f', 3, skip=4+len("tangent")+1) if tangent_sec else []
    binormals = gen.extract_vertex_array(binormal_sec, 'f', 3, skip=4+len("binormal")+1) if binormal_sec else []

    # 2. Skinning data: typical format is 4 bytes bone index, 4 bytes weight (per vertex up to 8)
    skin_weights = []
    bone_indices = []
    if skin_sec:
        raw = skin_sec['data'][4+len("skinning")+1:]  # skip header
        # Each vertex: 8 * (uint8 weight, uint8 index?) or float?
        # From dump: skinning payload 121393 / (maybe 8*4*3036?) = ~4.99? unclear
        # We'll try to parse as 4 byte float weights and 4 byte int indices interleaved.
        # A safer way: assume 8 pairs of (bone_index[float?], weight[float]) per vertex.
        # You'll need to adjust based on actual binary.
        # Let's guess: 8 floats = 4 weights + 4 indices? No.
        # The class oCSkinning8VertexLayer suggests 8 bones per vertex.
        # Often engines store: 4 bytes index, 4 bytes weight (both float?), but indices are int.
        # We'll try to read 8 * (int, float) pairs.
        stride = 8 * (4 + 4)  # 64 bytes per vertex
        num_vertices = len(raw) // stride
        for v in range(num_vertices):
            vtx_weights = []
            vtx_indices = []
            off = v * stride
            for j in range(8):
                idx = struct.unpack_from('<i', raw, off)[0]
                wgt = struct.unpack_from('<f', raw, off+4)[0]
                if wgt > 0:
                    vtx_indices.append(idx)
                    vtx_weights.append(wgt)
                off += 8
            bone_indices.append(vtx_indices)
            skin_weights.append(vtx_weights)

    # 3. Get bone names (for ordering)
    bone_names = gen.get_all_bone_names()
    # Assuming skin indices refer to this sorted list.

    # 4. Write OBJ
    outname = os.path.splitext(sys.argv[1])[0] + ".obj"
    with open(outname, 'w') as f:
        f.write("# Converted from .gen\n")
        for pos in positions:
            f.write(f"v {pos[0]} {pos[1]} {pos[2]}\n")
        # ... write vertex normals (if any), texture coords, faces (from index buffer)
        # For now, just vertices.
    print(f"Wrote {outname} with {len(positions)} vertices.")

    # Optional: write skinning info
    if skin_weights:
        skin_path = os.path.splitext(sys.argv[1])[0] + "_skinning.txt"
        with open(skin_path, 'w') as f:
            for i, (indices, weights) in enumerate(zip(bone_indices, skin_weights)):
                f.write(f"v{i}: ")
                for idx, wgt in zip(indices, weights):
                    bone_name = bone_names[idx] if idx < len(bone_names) else f"bone{idx}"
                    f.write(f"{bone_name}({wgt:.4f}) ")
                f.write("\n")
        print(f"Skinning data written to {skin_path}")

if __name__ == "__main__":
    main()
